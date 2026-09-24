import frappe
import re
import uuid
from frappe.utils import now
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import (
    _clean_value, sanitize_request, sanitize_array,
    success, error, validate_fields, get_full_image_url,
    extract_pin_code, get_product_prices, get_payment_provider_details
)
from impressio.impressio.api.sales_helper import get_bundle_items
from impressio.impressio.api.payments import handle_payment, send_checkout_notification, finalize_checkout_and_build_redirect


# ─────────────────────────────────────────────────────────────────────────────
# SHARED INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_dn_items_for_so(order_id, extra_fields=None):
    """
    Fetches Delivery Note Items linked to a Sales Order via EITHER
    against_sales_order OR custom_custom_against_sales_order,
    deduplicates by row name (normal wins), and returns two clean lists.

    Args:
        order_id     (str):  Sales Order name
        extra_fields (list): Additional DN Item fields to fetch

    Returns:
        dn_normal (list): Rows linked via against_sales_order
        dn_sub    (list): Rows linked ONLY via custom_custom_against_sales_order
    """
    base_fields = [
        "name", "item_code", "qty", "parent",
        "against_sales_order", "custom_custom_against_sales_order"
    ]
    fields = list(set(base_fields + (extra_fields or [])))

    dn_normal_rows = frappe.get_all(
        "Delivery Note Item",
        filters={"against_sales_order": order_id, "docstatus": 1},
        fields=fields
    )
    dn_sub_rows = frappe.get_all(
        "Delivery Note Item",
        filters={"custom_custom_against_sales_order": order_id, "docstatus": 1},
        fields=fields
    )

    # Deduplicate by row name — normal wins if both fields set on same row
    seen_names = set()
    dn_normal  = []
    dn_sub     = []

    for row in dn_normal_rows:
        if row.name not in seen_names:
            seen_names.add(row.name)
            dn_normal.append(row)

    for row in dn_sub_rows:
        if row.name not in seen_names:
            seen_names.add(row.name)
            dn_sub.append(row)

    return dn_normal, dn_sub


def _build_dn_net_qty_map(sales_order, delivery_note):
    """
    Returns net available qty per item scoped to a single delivery note,
    after subtracting any return DNs raised against it.

    Used by:
        - create_return_exchange_request (step 8)
        - checkout_return_exchange_request (step 6)

    Returns:
        net_qty_map    (dict): { item_code: available_float_qty }
        dn_item_codes  (set):  item codes present in this DN
    """
    # Reuse get_dn_items_for_so, then filter down to this DN
    all_normal, all_sub = get_dn_items_for_so(order_id=sales_order)

    this_dn_normal = [r for r in all_normal if r.parent == delivery_note]
    this_dn_sub    = [r for r in all_sub    if r.parent == delivery_note]

    net_qty_map = {}
    for row in (this_dn_normal + this_dn_sub):
        if float(row.qty or 0) > 0:
            net_qty_map[row.item_code] = (
                net_qty_map.get(row.item_code, 0) + float(row.qty)
            )

    # Subtract quantities already returned against this DN
    return_dn_names = frappe.get_all(
        "Delivery Note",
        filters={"return_against": delivery_note, "is_return": 1, "docstatus": 1},
        pluck="name"
    )

    if return_dn_names:
        # Return DNs are already tied to this DN via return_against —
        # no need to re-filter by SO; fetch all items from them directly
        ret_rows = frappe.get_all(
            "Delivery Note Item",
            filters={"parent": ["in", return_dn_names], "docstatus": 1},
            fields=["item_code", "qty"]
        )
        for row in ret_rows:
            if row.item_code in net_qty_map:
                # qty on return DNs is stored as negative
                net_qty_map[row.item_code] = max(
                    net_qty_map[row.item_code] + float(row.qty or 0), 0
                )

    return net_qty_map, set(net_qty_map.keys())

def _calculate_exchange_prices(so, items_list, action_type="Exchange"):
    """
    items_list: list of dicts with keys old_item_code, new_item_code, qty
                (works with both plain dicts and frappe document rows)

    action_type: "Exchange" | "Missing"
                 Missing → all lines are no_charge regardless of item/price

    Returns:
        line_items       – per-item breakdown
        total_old_amount – sum of (so_rate × qty) for all items
        total_new_amount – sum of (new live price × qty) for charged items only
        total_discount   – credit given for returned items (charged items only)
        net_payable      – total_new_amount − total_discount
                           positive  → customer pays more
                           negative  → refund owed
                           zero      → straight swap
    """
    so_item_rate_map = {
        item.item_code: float(item.rate or 0)
        for item in so.items
    }

    sub_item_parent_map = {
        sub.item_code: sub.parent_item_code
        for sub in (so.custom_sub_items or [])
    }

    is_missing = (action_type == "Missing")

    line_items       = []
    total_old_amount = 0
    total_new_amount = 0
    total_discount   = 0

    for item in items_list:
        old_item_code = item.get("old_item_code") if isinstance(item, dict) else item.old_item_code
        new_item_code = item.get("new_item_code") if isinstance(item, dict) else item.new_item_code
        qty           = int((item.get("qty") if isinstance(item, dict) else item.qty) or 1)

        # Rule 1: Missing action → always free, no price calculation needed
        # Rule 2: same item → no charge
        # Rule 3: old item is a bundle sub-item → no charge
        is_same_item  = (old_item_code == new_item_code)
        parent_of_old = sub_item_parent_map.get(old_item_code)
        is_sub_item   = (parent_of_old is not None) and (parent_of_old != old_item_code)

        no_charge = is_missing or is_same_item or is_sub_item

        old_rate   = so_item_rate_map.get(old_item_code, 0)
        new_prices = get_product_prices(new_item_code)
        new_rate   = float(new_prices.get("Standard Selling") or 0)

        if no_charge:
            line_old_amount = 0
            line_new_amount = 0
            line_discount   = 0
            amount_to_pay   = 0
            if is_missing:
                reason = "missing_item"
            elif is_same_item:
                reason = "same_item"
            else:
                reason = "sub_item_no_charge"
        else:
            line_old_amount = old_rate * qty
            line_new_amount = new_rate * qty
            line_discount   = line_old_amount
            amount_to_pay   = line_new_amount - line_old_amount
            reason          = "price_difference"

        total_old_amount += old_rate * qty
        total_new_amount += line_new_amount
        total_discount   += line_discount

        line_items.append({
            "old_item_code":   old_item_code,
            "new_item_code":   new_item_code,
            "qty":             qty,
            "old_rate":        round(old_rate, 2),
            "new_rate":        round(new_rate, 2),
            "line_old_amount": round(line_old_amount, 2),
            "line_new_amount": round(line_new_amount, 2),
            "line_discount":   round(line_discount, 2),
            "amount_to_pay":   round(amount_to_pay, 2),
            "no_charge":       no_charge,
            "reason":          reason
        })

    net_payable = round(total_new_amount - total_discount, 2)

    return (
        line_items,
        round(total_old_amount, 2),
        round(total_new_amount, 2),
        round(total_discount, 2),
        net_payable
    )


# ─────────────────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def my_orders(page=1, page_size=10):
    """
    List all orders created via checkout for logged-in customer
    """
    page      = int(_clean_value(page) or 1)
    page_size = int(_clean_value(page_size) or 10)
    offset    = (page - 1) * page_size

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    customer = user.get("customer_data", {}).get("name")
    if not customer:
        return error("Customer not found")

    orders = frappe.get_all(
        "Sales Order",
        filters={"customer": customer, "order_type": "Shopping Cart"},
        fields=[
            "docstatus", "name", "transaction_date", "grand_total",
            "currency", "status", "custom_payment_status",
            "custom_payment_mode", "custom_payment_flow",
            "custom_gateway_provider", "custom_cart_coupon_code"
        ],
        order_by="creation desc",
        limit_start=offset,
        limit_page_length=page_size
    )

    if not orders:
        return success("No orders found", {"orders": [], "page": page})

    order_names = [o.name for o in orders]
    items = frappe.get_all(
        "Sales Order Item",
        filters={"parent": ["in", order_names]},
        fields=["parent", "item_code", "item_name", "qty", "rate", "amount"]
    )

    items_map = {}
    for item in items:
        items_map.setdefault(item.parent, []).append(item)

    for order in orders:
        order["items"] = items_map.get(order.name, [])

    return success("Orders fetched", {
        "orders":    orders,
        "page":      page,
        "page_size": page_size
    })


@frappe.whitelist(allow_guest=True)
def order_detail(**kwargs):

    # 1️⃣ Validate user
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    # 2️⃣ Resolve customers
    allowed_customers = user.get("linked_customers") or []
    if not allowed_customers:
        return error("Customer not found", 403)

    # 3️⃣ Validate input
    is_error, payload = sanitize_request(kwargs, required=["order_id"])
    if is_error:
        return error(payload, 422)

    order_id = payload.get("order_id")

    # 4️⃣ Validate order ownership
    if not frappe.db.exists("Sales Order", {
        "name": order_id,
        "customer": ["in", allowed_customers],
        "order_type": "Shopping Cart"
    }):
        return error("Order not found or access denied", 403)

    # 5️⃣ Fetch order header
    order = frappe.get_all(
        "Sales Order",
        filters={"name": order_id},
        fields=[
            "name", "transaction_date", "grand_total", "currency",
            "status", "custom_payment_status", "custom_payment_mode",
            "custom_payment_flow", "custom_gateway_provider",
            "custom_parent_sales_order", "shipping_address_name"
        ],
        limit=1
    )[0]

    # 6️⃣ Fetch sub items
    sub_items = frappe.get_all(
        "Sale Order Sub Items",
        filters={"parent": order_id},
        fields=["parent_item_code", "item_code", "qty", "idx"]
    )

    # 7️⃣ Bulk fetch item meta
    def build_item_meta_map(item_codes):
        if not item_codes:
            return {}

        item_docs = frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "item_name", "image", "variant_of"]
        )

        variant_of_codes = list({i.variant_of for i in item_docs if i.variant_of})
        parent_image_map = {}
        if variant_of_codes:
            parent_docs = frappe.get_all(
                "Item",
                filters={"name": ["in", variant_of_codes]},
                fields=["name", "image"]
            )
            parent_image_map = {p.name: p.image for p in parent_docs}

        variant_item_codes = [i.name for i in item_docs if i.variant_of]
        attributes_map = {}
        if variant_item_codes:
            all_attrs = frappe.get_all(
                "Item Variant Attribute",
                filters={"parent": ["in", variant_item_codes]},
                fields=["parent", "attribute", "attribute_value"]
            )
            for attr in all_attrs:
                if attr.parent not in attributes_map:
                    attributes_map[attr.parent] = {}
                attributes_map[attr.parent][attr.attribute] = attr.attribute_value

        meta_map = {}
        for item in item_docs:
            image = item.image
            if not image and item.variant_of:
                image = parent_image_map.get(item.variant_of)
            meta_map[item.name] = {
                "item_name":  item.item_name,
                "image":      get_full_image_url(image) if image else None,
                "attributes": attributes_map.get(item.name, {})
            }

        return meta_map

    all_item_codes = list({row.item_code for row in sub_items})
    item_meta_map  = build_item_meta_map(all_item_codes)

    # 8️⃣ Preload ALL delivery note items for this SO
    dn_normal, dn_sub = get_dn_items_for_so(order_id)

    normal_delivered = {}
    for row in dn_normal:
        normal_delivered[row.item_code] = (
            normal_delivered.get(row.item_code, 0) + row.qty
        )

    sub_delivered = {}
    for row in dn_sub:
        sub_delivered[row.item_code] = (
            sub_delivered.get(row.item_code, 0) + row.qty
        )

    # 9️⃣ Build items list sorted by idx
    items_data = []
    for row in sorted(sub_items, key=lambda r: r.idx):
        is_normal     = (row.parent_item_code == row.item_code)
        delivered_qty = float(
            normal_delivered.get(row.item_code, 0)
            if is_normal else
            sub_delivered.get(row.item_code, 0)
        )
        ordered_qty = float(row.qty or 0)
        meta        = item_meta_map.get(row.item_code, {})

        items_data.append({
            "idx":              row.idx,
            "parent_item_code": row.parent_item_code,
            "item_code":        row.item_code,
            "item_name":        meta.get("item_name") or row.item_code,
            "image":            meta.get("image"),
            "attributes":       meta.get("attributes", {}),
            "qty":              ordered_qty,
            "delivered_qty":    delivered_qty,
            "pending_qty":      max(ordered_qty - delivered_qty, 0)
        })

    order["items"] = items_data

    # 🔟 Fetch return/exchange requests
    oreqs = frappe.get_all(
        "Return Exchange Request",
        filters={"sales_order": order_id},
        fields=[
            "name", "action_type", "delivery_note", "status",
            "reviewed_by", "reviewed_on", "notes",
            "return_delivery_note", "replacement_sales_order"
        ],
        order_by="creation asc"
    )

    oreq_raw_items  = {}
    all_oreq_names  = [o["name"] for o in oreqs]

    if all_oreq_names:
        all_oreq_item_rows = frappe.get_all(
            "Return Exchange Request Item",
            filters={"parent": ["in", all_oreq_names]},
            fields=["parent", "old_item_code", "new_item_code",
                    "qty", "notes", "first_image", "second_image"]
        )

        oreq_item_codes = list({
            code
            for row in all_oreq_item_rows
            for code in [row.old_item_code, row.new_item_code]
            if code
        })

        missing_codes = [c for c in oreq_item_codes if c not in item_meta_map]
        if missing_codes:
            item_meta_map.update(build_item_meta_map(missing_codes))

        for row in all_oreq_item_rows:
            if row.parent not in oreq_raw_items:
                oreq_raw_items[row.parent] = []

            old_meta = item_meta_map.get(row.old_item_code, {})
            new_meta = item_meta_map.get(row.new_item_code, {})

            oreq_raw_items[row.parent].append({
                "old_item_code":  row.old_item_code,
                "old_item_name":  old_meta.get("item_name") or row.old_item_code,
                "old_item_image": old_meta.get("image"),
                "old_attributes": old_meta.get("attributes", {}),
                "new_item_code":  row.new_item_code,
                "new_item_name":  new_meta.get("item_name") or row.new_item_code,
                "new_item_image": new_meta.get("image"),
                "new_attributes": new_meta.get("attributes", {}),
                "qty":            row.qty,
                "notes":          row.notes,
                "first_image":    get_full_image_url(row.first_image) if row.first_image else None,
                "second_image":   get_full_image_url(row.second_image) if row.second_image else None
            })

    for oreq in oreqs:
        oreq["items"] = oreq_raw_items.get(oreq["name"], [])

    order["requests"] = oreqs

    # Build delivered notes list
    all_dn_names = list({
        row.parent for row in (dn_normal + dn_sub) if row.parent
    })
    order["delivered"] = []

    if all_dn_names:
        dn_docs = frappe.get_all(
            "Delivery Note",
            filters={"name": ["in", all_dn_names]},
            fields=[
                "name", "posting_date", "status", "is_return",
                "return_against", "custom_is_delivered",
                "custom_delivered_date", "custom_status_tracking"
            ]
        )

        normal_dn_map = {}
        return_dn_map = {}

        for d in dn_docs:
            try:
                raw = frappe.parse_json(d.custom_status_tracking) if d.custom_status_tracking else None
                tracking_data = {
                    "status":           raw.get("status"),
                    "dn_name":          raw.get("dn_name"),
                    "hjjk":             raw.get("hjjk"),
                    "tracking_history": raw.get("tracking_history"),
                } if isinstance(raw, dict) else None
            except Exception:
                tracking_data = None

            info = {
                "name":                  d.name,
                "posting_date":          str(d.posting_date),
                "status":                tracking_data.get("status") if tracking_data else d.status,
                "is_return":             d.is_return,
                "return_against":        d.return_against,
                "custom_is_delivered":   d.custom_is_delivered,
                "custom_delivered_date": d.custom_delivered_date,
                "tracking_data":         tracking_data
            }

            if d.is_return:
                return_dn_map.setdefault(d.return_against, []).append(info)
            else:
                normal_dn_map[d.name] = info

        dn_items_map = {}
        for row in (dn_normal + dn_sub):
            dn_items_map.setdefault(row.parent, []).append({
                "item_code": row.item_code,
                "qty":       float(row.qty or 0)
            })

        all_dn_item_codes = list({
            row.item_code for row in (dn_normal + dn_sub) if row.item_code
        })
        missing_codes = [c for c in all_dn_item_codes if c not in item_meta_map]
        if missing_codes:
            item_meta_map.update(build_item_meta_map(missing_codes))

        def build_dn_items(dn_name):
            merged = {}
            for entry in dn_items_map.get(dn_name, []):
                merged[entry["item_code"]] = merged.get(entry["item_code"], 0) + entry["qty"]
            return [
                {
                    "item_code":  code,
                    "item_name":  item_meta_map.get(code, {}).get("item_name") or code,
                    "image":      item_meta_map.get(code, {}).get("image"),
                    "attributes": item_meta_map.get(code, {}).get("attributes", {}),
                    "qty":        qty
                }
                for code, qty in merged.items()
            ]

        delivered_notes = []
        for dn_name, info in normal_dn_map.items():
            nested_returns = sorted([
                {
                    "delivery_note": ret["name"],
                    "posting_date":  ret["posting_date"],
                    "status":        ret["status"],
                    "items":         build_dn_items(ret["name"])
                }
                for ret in return_dn_map.get(dn_name, [])
            ], key=lambda x: x["posting_date"])

            delivered_notes.append({
                "delivery_note":         dn_name,
                "posting_date":          info["posting_date"],
                "custom_is_delivered":   bool(info["custom_is_delivered"]),
                "custom_delivered_date": info["custom_delivered_date"],
                "status":                info["status"],
                "tracking_data":         info["tracking_data"],
                "items":                 build_dn_items(dn_name),
                "returns":               nested_returns
            })

        delivered_notes.sort(key=lambda x: x["posting_date"], reverse=True)
        order["delivered"] = delivered_notes

    return success("Order details fetched", order)


@frappe.whitelist(allow_guest=True)
def cancel_order(**kwargs):
    """
    Cancel order (only Draft allowed)
    """
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    customer = user.get("customer_data", {}).get("name")
    if not customer:
        return error("Customer not found")

    is_error, payload = sanitize_request(kwargs, required=["order_id"])
    if is_error:
        return error(payload, 422)

    order_id = payload.get("order_id")

    if not frappe.db.exists("Sales Order", order_id):
        return error("Order not found", 404)

    doc = frappe.get_doc("Sales Order", order_id)

    if doc.customer != customer:
        return error("Access denied", 403)

    if doc.order_type != "Shopping Cart":
        return error("Invalid order", 403)

    if doc.docstatus != 0:
        return error("Only draft orders can be cancelled")

    doc.flags.ignore_permissions = True
    doc.submit()
    doc.cancel()

    return success("Order cancelled successfully")


@frappe.whitelist()
def reset_sales_orders_to_draft(sales_orders):

    if isinstance(sales_orders, str):
        sales_orders = frappe.parse_json(sales_orders)

    results = []

    for so_name in sales_orders:
        so_name = _clean_value(so_name)

        try:
            so = frappe.get_doc("Sales Order", so_name)
        except Exception:
            results.append({"sales_order": so_name, "result": "error", "message": "Sales Order not found"})
            continue

        if so.docstatus != 2:
            results.append({
                "sales_order": so_name, "result": "skipped",
                "message": "Sales Order is not cancelled", "current_docstatus": so.docstatus
            })
            continue

        dn = frappe.db.get_value("Delivery Note Item", {"against_sales_order": so_name}, "parent")
        if dn:
            results.append({
                "sales_order": so_name, "result": "blocked",
                "message": "Delivery Note already created",
                "reference_doctype": "Delivery Note", "reference_name": dn
            })
            continue

        inv = frappe.db.get_value("Sales Invoice Item", {"sales_order": so_name}, "parent")
        if inv:
            results.append({
                "sales_order": so_name, "result": "blocked",
                "message": "Sales Invoice already created",
                "reference_doctype": "Sales Invoice", "reference_name": inv
            })
            continue

        pay = frappe.db.get_value(
            "Payment Entry Reference",
            {"reference_doctype": "Sales Order", "reference_name": so_name},
            "parent"
        )
        if pay:
            results.append({
                "sales_order": so_name, "result": "blocked",
                "message": "Payment Entry exists",
                "reference_doctype": "Payment Entry", "reference_name": pay
            })
            continue

        frappe.db.set_value("Sales Order", so_name, {"docstatus": 0, "status": "Draft"})
        results.append({"sales_order": so_name, "result": "success", "message": "Sales Order moved back to Draft"})

    frappe.db.commit()

    return {"total": len(sales_orders), "processed": len(results), "results": results}


def extract_pin_code(address):
    if not address:
        return None
    match = re.search(r"PIN\s*Code:\s*(\d+)", address)
    return match.group(1) if match else None


@frappe.whitelist(allow_guest=True)
def rebuild_sales_order_sub_items(
    sales_orders,
    update_pincode=False,
    update_subitems=False,
    update_school=False
):
    if isinstance(sales_orders, str):
        sales_orders = frappe.parse_json(sales_orders)

    update_pincode  = frappe.utils.cint(update_pincode)
    update_subitems = frappe.utils.cint(update_subitems)
    update_school   = frappe.utils.cint(update_school)

    if not sales_orders:
        return {"status": "error", "message": "No Sales Orders provided"}

    insert_rows  = []
    response     = []
    current_time = now()
    current_user = frappe.session.user

    for so_name in sales_orders:
        try:
            so = frappe.get_doc("Sales Order", so_name)

            school = grade = pin_code = None

            if update_school:
                student = frappe.db.get_value(
                    "Students", {"customer": so.customer},
                    ["school_code", "grade"], as_dict=True
                )
                if student:
                    if student.get("school_code"):
                        school = frappe.db.get_value(
                            "School", {"school_code": student["school_code"]}, "name"
                        )
                    grade = student.get("grade")

            if update_pincode:
                pin_code = extract_pin_code(so.shipping_address)

            update_fields = {}
            set_parts     = []

            if update_school and school is not None:
                set_parts.append("custom_student_school = %(school)s")
                update_fields["school"] = school

            if update_school and grade is not None:
                set_parts.append("custom_student_grade = %(grade)s")
                update_fields["grade"] = grade

            if update_pincode and pin_code is not None:
                set_parts.append("custom_pin_code = %(pin)s")
                update_fields["pin"] = pin_code

            if set_parts:
                update_fields["so"] = so_name
                frappe.db.sql(
                    f"UPDATE `tabSales Order` SET {', '.join(set_parts)} WHERE name = %(so)s",
                    update_fields
                )

            if update_subitems:

                # if so.custom_magic_box:
                #     response.append({"sales_order": so_name, "status": "magic box skipped", "rows_prepared": 0})
                #     continue
                                
                # Fetch existing sub items
                existing_sub_items = frappe.get_all(
                    "Sale Order Sub Items",
                    filters={"parent": so_name},
                    fields=["parent_item_code", "item_code", "qty", "idx"]
                )

                if existing_sub_items:
                    frappe.get_doc({
                        "doctype": "Sales Order Sub Item Log",
                        "sales_order": so_name,
                        "data": frappe.as_json(existing_sub_items),
                        "created_by": current_user,
                        "created_on": current_time
                    }).insert(ignore_permissions=True)

                frappe.db.delete("Sale Order Sub Items", {"parent": so_name})




                if so.custom_magic_box:
                    idx = row_count = 0

                    for sub_item in so.custom_sub_items:
                        item_group = frappe.get_cached_value("Item", sub_item.item_code, "item_group")

                        if item_group == "Books Template" or item_group == "Books Bundle":
                            for bi in get_bundle_items(sub_item.item_code, sub_item.qty):
                                idx += 1
                                row_count += 1
                                insert_rows.append({
                                    "name": str(uuid.uuid4()), "creation": current_time,
                                    "modified": current_time, "modified_by": current_user,
                                    "owner": current_user, "parent": so_name,
                                    "parenttype": "Sales Order", "parentfield": "custom_sub_items",
                                    "parent_item_code": sub_item.item_code,   # BOM parent
                                    "item_code": bi["item_code"], "qty": bi["qty"], "idx": idx
                                })
                        else:
                            idx += 1
                            row_count += 1
                            insert_rows.append({
                                "name": str(uuid.uuid4()), "creation": current_time,
                                "modified": current_time, "modified_by": current_user,
                                "owner": current_user, "parent": so_name,
                                "parenttype": "Sales Order", "parentfield": "custom_sub_items",
                                "parent_item_code": sub_item.parent_item_code,  # keep original
                                "item_code": sub_item.item_code, "qty": sub_item.qty, "idx": idx
                            })

                    response.append({"sales_order": so_name, "status": "magic box success", "rows_prepared": row_count})
                    continue


                idx = row_count = 0  # reset per SO

                for item in so.items:
                    item_group = frappe.get_cached_value("Item", item.item_code, "item_group")

                    if item_group == "Books Template" or item_group == "Books Bundle":
                        for bi in get_bundle_items(item.item_code, item.qty):
                            idx += 1
                            row_count += 1
                            insert_rows.append({
                                "name": str(uuid.uuid4()), "creation": current_time,
                                "modified": current_time, "modified_by": current_user,
                                "owner": current_user, "parent": so_name,
                                "parenttype": "Sales Order", "parentfield": "custom_sub_items",
                                "parent_item_code": item.item_code,
                                "item_code": bi["item_code"], "qty": bi["qty"], "idx": idx
                            })
                    else:
                        idx += 1
                        row_count += 1
                        insert_rows.append({
                            "name": str(uuid.uuid4()), "creation": current_time,
                            "modified": current_time, "modified_by": current_user,
                            "owner": current_user, "parent": so_name,
                            "parenttype": "Sales Order", "parentfield": "custom_sub_items",
                            "parent_item_code": item.item_code,
                            "item_code": item.item_code, "qty": item.qty, "idx": idx
                        })

                response.append({"sales_order": so_name, "status": "success", "rows_prepared": row_count})

            else:
                response.append({"sales_order": so_name, "status": "skipped", "message": "subitems rebuild disabled"})

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"Rebuild failed for {so_name}")
            response.append({"sales_order": so_name, "status": "error", "message": str(e)})

    if insert_rows and update_subitems and frappe.db.table_exists("Sale Order Sub Items"):
        query = """
            INSERT INTO `tabSale Order Sub Items`
            (name, creation, modified, modified_by, owner, parent, parenttype,
             parentfield, parent_item_code, item_code, qty, idx)
            VALUES
            (%(name)s, %(creation)s, %(modified)s, %(modified_by)s, %(owner)s,
             %(parent)s, %(parenttype)s, %(parentfield)s, %(parent_item_code)s,
             %(item_code)s, %(qty)s, %(idx)s)
        """
        frappe.db._cursor.executemany(query, insert_rows)
        frappe.db.commit()

    return {"status": "completed", "inserted_rows": len(insert_rows), "details": response}



@frappe.whitelist(allow_guest=True)
def get_exchange_price_details(**kwargs):
    """
    Pre-checkout price calculator without DN scope.
    Use when you only have a Sales Order and items list
    (e.g. before the user picks a specific delivery note).
    """
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    allowed_customers = user.get("linked_customers") or []
    if not allowed_customers:
        return error("Customer not found", 403)

    is_error, payload = sanitize_request(kwargs, required=["sales_order", "action_type"])
    items = sanitize_array(kwargs.get("items", []))

    if is_error or not items:
        return error(payload if is_error else "'items' must be a non-empty list", 422)

    sales_order = payload.get("sales_order")
    action_type = payload.get("action_type")

    so = frappe.get_doc("Sales Order", sales_order)
    if not so:
        return error("Sales Order not found", 404)
    if so.customer not in allowed_customers:
        return error("Access denied", 403)

    for idx, item in enumerate(items):
        if not item.get("old_item_code") or not item.get("new_item_code"):
            return error(f"Item at index {idx} is missing 'old_item_code' or 'new_item_code'", 422)

    line_items, total_old_amount, total_new_amount, total_discount, net_payable = \
        _calculate_exchange_prices(so, items,  action_type=action_type)

    return success("Exchange price details calculated", {
        "sales_order":      sales_order,
        "action_type":      action_type,
        "items":            line_items,
        "total_old_amount": total_old_amount,
        "total_new_amount": total_new_amount,
        "total_discount":   total_discount,
        "net_payable":      net_payable,
        "payment_required": net_payable > 0,
        "refund_owed":      net_payable < 0,
    })



@frappe.whitelist(allow_guest=True)
def create_return_exchange_request(**kwargs):

    # 1️⃣ Validate user
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    allowed_customers = user.get("linked_customers") or []
    if not allowed_customers:
        return error("Customer not found", 403)

    # 2️⃣ Validate payload
    is_error, payload = sanitize_request(
        kwargs,
        required=["sales_order", "delivery_note", "action_type"]
    )
    if is_error:
        return error(payload, 422)

    sales_order   = payload.get("sales_order")
    delivery_note = payload.get("delivery_note")
    action_type   = payload.get("action_type")
    items         = sanitize_array(kwargs.get("items", []))

    # 3️⃣ Validate action_type
    if action_type not in ["Exchange", "Missing"]:
        return error(f"Invalid action_type '{action_type}'", 422)

    # 4️⃣ Validate items
    if not items:
        return error("items must be a non-empty list", 422)

    # 5️⃣ Validate SO ownership
    so = frappe.db.get_value(
        "Sales Order",
        {"name": sales_order, "customer": ["in", allowed_customers], "order_type": "Shopping Cart"},
        ["name", "customer"],
        as_dict=True
    )
    if not so:
        return error("Order not found or access denied", 403)

    # 6️⃣ Validate DN — submitted, not a return, belongs to SO, confirmed delivered
    dn_doc = frappe.db.get_value(
        "Delivery Note",
        {"name": delivery_note, "docstatus": 1, "is_return": 0},
        ["name", "posting_date", "custom_is_delivered", "custom_delivered_date"],
        as_dict=True
    )
    if not dn_doc:
        return error("Delivery note not found or not valid", 404)

    if not dn_doc.custom_is_delivered or not dn_doc.custom_delivered_date:
        return error("Delivery note has not been confirmed as delivered yet", 422)

    dn_so_normal = frappe.db.exists("Delivery Note Item", {
        "parent": delivery_note, "against_sales_order": sales_order, "docstatus": 1
    })
    dn_so_sub = frappe.db.exists("Delivery Note Item", {
        "parent": delivery_note, "custom_custom_against_sales_order": sales_order, "docstatus": 1
    })
    if not dn_so_normal and not dn_so_sub:
        return error("Delivery note does not belong to this sales order", 403)

    # 7️⃣ 7-day window — counted from confirmed delivery date
    days_since_delivery = frappe.utils.date_diff(
        frappe.utils.today(), dn_doc.custom_delivered_date
    )
    if days_since_delivery > 7:
        return error(
            f"Requests must be raised within 7 days of delivery. "
            f"Delivered on {dn_doc.custom_delivered_date} ({days_since_delivery} days ago).",
            422
        )

    # 8️⃣ Build net qty map scoped to this DN
    net_qty_map, this_dn_item_codes = _build_dn_net_qty_map(sales_order, delivery_note)

    # 9️⃣ Build active requested qty map
    active_rer_names = frappe.get_all(
        "Return Exchange Request",
        filters={
            "sales_order": sales_order,
            "status": ["in", ["Under Review", "Approved", "In Progress", "Completed"]]
        },
        pluck="name"
    )
    active_requested_map = {}
    if active_rer_names:
        for row in frappe.get_all(
            "Return Exchange Request Item",
            filters={"parent": ["in", active_rer_names]},
            fields=["old_item_code", "qty"]
        ):
            active_requested_map[row.old_item_code] = (
                active_requested_map.get(row.old_item_code, 0) + float(row.qty or 0)
            )

    # 🔟 Validate SO item codes
    valid_item_codes = set(
        frappe.get_all("Sale Order Sub Items", filters={"parent": sales_order}, pluck="item_code")
    )
    if not valid_item_codes:
        return error("No items found for this order", 422)

    # Validate each item row
    seen_item_codes = set()

    for idx, row in enumerate(items):
        label         = f"Item row {idx + 1}"
        old_item_code = row.get("old_item_code")
        new_item_code = row.get("new_item_code")
        qty           = row.get("qty")
        first_image   = row.get("first_image")

        if not old_item_code:
            return error(f"{label}: old_item_code is required", 422)
        if not new_item_code:
            return error(f"{label}: new_item_code is required", 422)
        if not qty or int(qty) <= 0:
            return error(f"{label}: qty must be greater than 0", 422)
        if not first_image:
            return error(f"{label}: first_image is required", 422)
        if old_item_code not in valid_item_codes:
            return error(f"{label}: '{old_item_code}' does not belong to this order", 422)
        if old_item_code not in this_dn_item_codes:
            return error(f"{label}: '{old_item_code}' was not delivered in {delivery_note}", 422)
        if not frappe.db.exists("Item", new_item_code):
            return error(f"{label}: new_item_code '{new_item_code}' does not exist", 422)
        if old_item_code in seen_item_codes:
            return error(f"{label}: duplicate old_item_code '{old_item_code}'", 422)
        seen_item_codes.add(old_item_code)

        net_qty     = float(net_qty_map.get(old_item_code, 0))
        active_req  = float(active_requested_map.get(old_item_code, 0))
        requested   = float(qty)
        max_allowed = net_qty - active_req

        if net_qty <= 0:
            return error(f"{label}: '{old_item_code}' has no delivered qty available (fully returned)", 422)
        if max_allowed <= 0:
            return error(
                f"{label}: '{old_item_code}' already has active requests "
                f"covering all available qty ({int(net_qty)})",
                409
            )
        if requested > max_allowed:
            return error(
                f"{label}: requested qty {int(requested)} exceeds available qty {int(max_allowed)} "
                f"(net delivered: {int(net_qty)}, already requested: {int(active_req)})",
                422
            )

    # Create Return Exchange Request
    try:
        rer = frappe.new_doc("Return Exchange Request")
        rer.sales_order   = sales_order
        rer.delivery_note = delivery_note
        rer.action_type   = action_type
        rer.customer      = so.customer
        rer.status        = "Under Review"

        for row in items:
            rer.append("return_exchange_request_item", {
                "old_item_code": row.get("old_item_code"),
                "new_item_code": row.get("new_item_code"),
                "qty":           int(row.get("qty")),
                "notes":         row.get("notes") or "",
                "first_image":   row.get("first_image"),
                "second_image":  row.get("second_image")
            })

        rer.insert(ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        frappe.log_error(frappe.get_traceback(), "create_return_exchange_request - Insert Failed")
        return error("Failed to create request. Please try again.", 500)

    return success("Request submitted successfully", {
        "name":          rer.name,
        "status":        rer.status,
        "action_type":   rer.action_type,
        "sales_order":   rer.sales_order,
        "delivery_note": rer.delivery_note
    })

@frappe.whitelist(allow_guest=True)
def get_rer_exchange_price_details(**kwargs):

    # 1️⃣ Validate user
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    allowed_customers = user.get("linked_customers") or []
    if not allowed_customers:
        return error("Customer not found", 403)

    # 2️⃣ Validate payload
    is_error, payload = sanitize_request(kwargs, required=["rer_id"])
    if is_error:
        return error(payload, 422)

    rer_id = payload.get("rer_id")

    # 3️⃣ Fetch RER + ownership
    rer = frappe.get_doc("Return Exchange Request", rer_id)
    if not rer:
        return error("Return Exchange Request not found", 404)
    if rer.customer not in allowed_customers:
        return error("Access denied", 403)

    # 4️⃣ Status check
    if rer.status != "Approved":
        return error(f"Request is not approved (current status: {rer.status})", 409)

    # 5️⃣ Validate items
    if not rer.return_exchange_request_item:
        return error("No items found in this request", 422)

    # 6️⃣ Build response directly from RERI — prices stored at approval time
    line_items       = []
    total_old_amount = 0
    total_new_amount = 0
    total_discount   = 0

    for r in rer.return_exchange_request_item:
        qty      = int(r.qty or 1)
        old_rate = float(r.old_item_price or 0)
        new_rate = float(r.new_item_price or 0)

        line_old_amount = old_rate * qty
        line_new_amount = new_rate * qty
        line_discount   = line_old_amount
        amount_to_pay   = line_new_amount - line_old_amount

        total_old_amount += line_old_amount
        total_new_amount += line_new_amount
        total_discount   += line_discount

        line_items.append({
            "old_item_code":   r.old_item_code,
            "new_item_code":   r.new_item_code,
            "qty":             qty,
            "old_rate":        round(old_rate, 2),
            "new_rate":        round(new_rate, 2),
            "line_old_amount": round(line_old_amount, 2),
            "line_new_amount": round(line_new_amount, 2),
            "line_discount":   round(line_discount, 2),
            "amount_to_pay":   round(amount_to_pay, 2),
        })

    net_payable = round(rer.grand_total or 0, 2)

    return success("Exchange price details fetched", {
        "rer_id":           rer_id,
        "action_type":      rer.action_type,
        "sales_order":      rer.sales_order,
        "delivery_note":    rer.delivery_note,
        "items":            line_items,
        "total_old_amount": round(total_old_amount, 2),
        "total_new_amount": round(total_new_amount, 2),
        "total_discount":   round(total_discount, 2),
        "net_payable":      net_payable,
        "payment_required": net_payable > 0,
        "refund_owed":      net_payable < 0,
    })




@frappe.whitelist(allow_guest=True)
def checkout_return_exchange_request(**kwargs):

    # 1️⃣ Validate user
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    allowed_customers = user.get("linked_customers") or []
    if not allowed_customers:
        return error("Customer not found", 403)

    # 2️⃣ Validate payload
    is_error, payload = sanitize_request(
        kwargs,
        required=["rer_id", "payment_gateway"],
        optional=["refund_mode", "upi_id", "bank_name",
                  "bank_account_number", "ifsc_code", "holder_name"]
    )
    if is_error:
        return error(payload, 422)

    rer_id          = payload.get("rer_id")
    payment_gateway = payload.get("payment_gateway")

    # 3️⃣ Fetch RER + ownership + status check
    frappe.flags.ignore_permissions = True
    rer = frappe.get_doc("Return Exchange Request", rer_id)
    frappe.flags.ignore_permissions = False

    if not rer:
        return error("Return Exchange Request not found", 404)
    if rer.customer not in allowed_customers:
        return error("Access denied", 403)
    if rer.status != "Approved":
        return error(f"Request is not eligible for checkout (current status: {rer.status})", 409)

    # 4️⃣ Validate Return DN
    if not rer.return_delivery_note:
        return error("Return Delivery Note not found. Please contact support.", 422)

    if frappe.db.get_value("Delivery Note", rer.return_delivery_note, "docstatus") != 1:
        return error(
            f"Return Delivery Note {rer.return_delivery_note} is not submitted. "
            "Please contact support.", 422
        )

    # 5️⃣ Validate Replacement SO exists as Draft
    if not rer.replacement_sales_order:
        return error("Replacement Sales Order not found. Please contact support.", 422)

    so_docstatus = frappe.db.get_value("Sales Order", rer.replacement_sales_order, "docstatus")
    if so_docstatus != 0:
        return error(
            "Replacement Sales Order is not in Draft state. Please contact support.", 409
        )

    new_so      = frappe.get_doc("Sales Order", rer.replacement_sales_order)
    net_payable = float(rer.grand_total or 0)

    # 6️⃣ Only two scenarios reach here — Exchange with refund or payment

    # ── Scenario A: Refund owed (net_payable < 0) ────────────────────────
    if net_payable < 0:
        if not payload.get("refund_mode"):
            return error("refund_mode is required to process refund.", 422)

        has_upi  = bool(payload.get("upi_id"))
        has_bank = all([
            payload.get("bank_name"),
            payload.get("bank_account_number"),
            payload.get("ifsc_code"),
            payload.get("holder_name"),
        ])
        if not has_upi and not has_bank:
            return error(
                "Provide either UPI ID or complete bank account details "
                "(bank name, account number, IFSC, holder name).",
                422
            )

        try:
            new_so.custom_payment_status    = "SUCCESS"
            new_so.flags.ignore_permissions = True
            new_so.submit()

            rer.reload()
            rer.status              = "In Progress"
            rer.refund_mode         = payload.get("refund_mode")
            rer.upi_id              = payload.get("upi_id")
            rer.bank_name           = payload.get("bank_name")
            rer.bank_account_number = payload.get("bank_account_number")
            rer.ifsc_code           = payload.get("ifsc_code")
            rer.holder_name         = payload.get("holder_name")
            rer.flags.ignore_permissions = True
            rer.save(ignore_permissions=True)
            frappe.db.commit()

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"checkout_return_exchange_request - Refund Submit Failed for {rer_id}"
            )
            return error("Failed to confirm refund order. Please try again.", 500)

        redirect_url = finalize_checkout_and_build_redirect([new_so.name])
        return success("Refund order confirmed", {
            "orders":           [new_so.name],
            "payment_flow":     "REDIRECT",
            "payment_provider": "Exchange",
            "redirect":         {"url": redirect_url, "method": "GET"},
            "form":             None
        })

    # ── Scenario B: Payment required (net_payable > 0) ───────────────────
    # RER stays "Approved" — payment webhook submits SO and marks "In Progress"
    payment_ctx = get_payment_provider_details(payment_gateway)
    if not payment_ctx:
        return error("Invalid or unavailable payment provider", 409)

    provider = payment_ctx["provider"]
    gateway  = payment_ctx.get("gateway")

    if provider["payment_flow"] == "ONLINE" and not gateway:
        return error("Payment gateway configuration missing", 409)

    return handle_payment(
        sales_order_names=[new_so.name],
        provider=provider,
        gateway=gateway,
        delivery_cost=0,
        user=user,
        use_existing_reference=True
    )