# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from erpnext.stock.doctype.batch.batch import get_batch_no
from frappe.utils import nowdate, nowtime



class PickslipGenerationAgainstSalesOrder(Document):
    def validate(self):
        self.validate_sales_order_status()
    
    def validate_sales_order_status(self):
        """Validate that the selected Sales Order is Submitted (docstatus = 1)"""
        if self.order_no:
            docstatus = frappe.db.get_value("Sales Order", self.order_no, "docstatus")
            if docstatus != 1:
                frappe.throw(_("Only Submitted Sales Orders are allowed. Selected order is not submitted."))
    
    def before_save(self):
        self.pick_slip_no = self.name


@frappe.whitelist()
def create_material_transfer_from_pickslips(
    pickslip_names,
    source_warehouse=None,
    target_warehouse=None,
    company=None,
    submit_stock_entry=False
):
    if isinstance(pickslip_names, str):
        pickslip_names = frappe.parse_json(pickslip_names)

    stock_entries = []

    for pickslip_name in pickslip_names:
        res = create_material_transfer_from_individual_pickslip(
            pickslip_name=pickslip_name,
            submit_stock_entry=submit_stock_entry
        )
        stock_entries.append(res["stock_entry"])

    return {
        "success": True,
        "stock_entries": stock_entries,
        "count": len(stock_entries)
    }



@frappe.whitelist()
def fetch_items(order_no):
    """Fetch items from the Sales Order and return them to the form"""
    if not order_no:
        frappe.throw("Please select an Order No first")

    # Validate docstatus here as well
    docstatus = frappe.db.get_value("Sales Order", order_no, "docstatus")
    if docstatus != 1:
        frappe.throw("Only Submitted Sales Orders are allowed")

    sales_order = frappe.get_doc("Sales Order", order_no)
    items = []
    for item in sales_order.items:
        items.append({
            "item_code": item.item_code,
            "product_name": item.item_name,
            "batch_no": "",
            "category": item.item_group,
            "qty": item.qty
        })

    return items






@frappe.whitelist()
def create_packing_from_pickslip(pickslip_name):
    """
    Create a Packing Of orders document from a submitted Pickslip.
    Items are pulled from the Pickslip, not directly from Sales Order.
    """
    if not pickslip_name:
        frappe.throw(_("Pickslip name is required"))

    # Get the pickslip document
    pickslip = frappe.get_doc("Pickslip Generation Against Sales Order", pickslip_name)

    # Validate pickslip is submitted
    if pickslip.docstatus != 1:
        frappe.throw(_("Only submitted Pickslips can be used to create Packing"))

    # Check if a packing already exists for this pickslip
    existing_packing = frappe.get_all(
        "Packing Of orders",
        filters={"pickslip_no": pickslip_name},
        limit=1
    )
    if existing_packing:
        frappe.throw(_("A Packing document already exists for this Pickslip: {0}").format(existing_packing[0].name))

    # Create new Packing document
    packing = frappe.new_doc("Packing Of orders")
    packing.pickslip_no = pickslip_name
    packing.sales_order = pickslip.order_no
    packing.customer_name = pickslip.customer_name
    packing.pickslip_date = frappe.utils.nowdate()
    packing.packing_status = "Pending"

    # Pull items from the Pickslip (table_kino)
    for item in pickslip.table_kino:
        packing.append("table", {
            "product": None,  # Product Bundle - may not apply
            "product_name": item.item_name or item.product_name,
            "barcode": item.item_code,  # Use item_code as barcode initially
            "qty": item.qty,
            "scan_status": "Pending"
        })

    # Calculate totals
    packing.total_items = len(packing.table)
    packing.items_confirmed = 0
    packing.packing_progress = 0

    # Insert the packing document
    packing.insert(ignore_permissions=True)

    # Add comment to pickslip
    pickslip.add_comment("Comment", _("Packing document created: {0}").format(packing.name))

    frappe.msgprint(_("Packing document {0} created successfully").format(packing.name))

    return packing.name


@frappe.whitelist()
def fetch_pickslip_items(pickslip_name):
    """
    Fetch items from a Pickslip document for populating Packing items.
    This is called when pickslip_no is selected in Packing Of orders.
    """
    if not pickslip_name:
        frappe.throw(_("Please select a Pickslip first"))

    pickslip = frappe.get_doc("Pickslip Generation Against Sales Order", pickslip_name)

    items = []
    for item in pickslip.table_kino:
        items.append({
            "product": None,
            "product_name": item.item_name or item.product_name,
            "barcode": item.item_code,
            "qty": item.qty,
            "scan_status": "Pending"
        })

    # Also return pickslip metadata
    return {
        "items": items,
        "sales_order": pickslip.order_no,
        "customer_name": pickslip.customer_name
    }


@frappe.whitelist()
def generate_bulk_slip_from_list(pickslip_names):
    """Generate combined bulk slip with same items grouped and quantities summed"""
    
    if not pickslip_names:
        frappe.throw("No pickslips selected")
    
    if isinstance(pickslip_names, str):
        pickslip_names = frappe.parse_json(pickslip_names)
    
    # Get all items from selected pickslips
    all_items = []
    for pickslip_name in pickslip_names:
        pickslip = frappe.get_doc("Pickslip Generation Against Sales Order", pickslip_name)
        for item in pickslip.table_kino:
            all_items.append({
                "item_code": item.item_code,
                "product_name": item.product_name or "None",
                "batch_no": item.batch_no or "None",
                "category": item.category or "Consumable",  # Default value
                "required_qty": item.qty,  # Using qty as required_qty
                "picked_qty": item.qty,    # Assuming picked_qty equals required_qty initially
                "uom": frappe.db.get_value("Item", item.item_code, "stock_uom") or "Nos",
                "rack_location": "",  # Add this field if you have it
                "pickslip": pickslip_name,
                "customer": pickslip.customer_name,
                "order_no": pickslip.order_no
            })
    
    # Group items by item_code, product_name, batch_no, category and sum quantities
    grouped_items = {}
    for item in all_items:
        key = (item["item_code"], item["product_name"], item["batch_no"], item["category"])
        if key in grouped_items:
            grouped_items[key]["required_qty"] += item["required_qty"]
            grouped_items[key]["picked_qty"] += item["picked_qty"]
            grouped_items[key]["pickslips"].append(item["pickslip"])
            grouped_items[key]["orders"].append(item["order_no"])
            grouped_items[key]["customers"].append(item["customer"])
        else:
            grouped_items[key] = {
                "item_code": item["item_code"],
                "product_name": item["product_name"],
                "batch_no": item["batch_no"],
                "category": item["category"],
                "required_qty": item["required_qty"],
                "picked_qty": item["picked_qty"],
                "uom": item["uom"],
                "rack_location": item["rack_location"],
                "pickslips": [item["pickslip"]],
                "orders": [item["order_no"]],
                "customers": [item["customer"]]
            }
    
    # Convert to list for template
    consolidated_items = list(grouped_items.values())
    
    # Calculate totals
    total_required_qty = sum(item["required_qty"] for item in consolidated_items)
    total_picked_qty = sum(item["picked_qty"] for item in consolidated_items)
    
    # Prepare context for template
    context = {
        "items": consolidated_items,
        "total_pickslips": len(pickslip_names),
        "total_unique_items": len(consolidated_items),
        "total_required_qty": total_required_qty,
        "total_picked_qty": total_picked_qty,
        "pickslip_names": pickslip_names,
        "generated_date": frappe.utils.nowdate()
    }
    
    # Render HTML template
    html = frappe.render_template("templates/emails/combined_bulk_slip.html", context)
    
    return html


def get_valuation_rate(item_code, warehouse, posting_date):
    """
    Returns (valuation_rate, allow_zero_valuation) for an item.
    Raises an error if valuation is missing for non-zero-valuation items.
    """
    # Check if item allows zero valuation
    allow_zero = frappe.db.get_value("Item", item_code, "allow_zero_valuation_rate") or 0

    # Try to get valuation rate from latest Stock Ledger Entry
    sle = frappe.db.sql("""
        SELECT valuation_rate
        FROM `tabStock Ledger Entry`
        WHERE item_code=%s AND warehouse=%s AND posting_date <= %s
        ORDER BY posting_date DESC, posting_time DESC, creation DESC
        LIMIT 1
    """, (item_code, warehouse, posting_date), as_dict=True)

    valuation_rate = sle[0].valuation_rate if sle else None

    # Fallback to item master valuation rate
    if valuation_rate is None or valuation_rate == 0:
        valuation_rate = frappe.db.get_value("Item", item_code, "valuation_rate") or 0

    # If still zero and item doesn't allow zero valuation, throw error
    if valuation_rate == 0 and not allow_zero:
        frappe.throw(f"Item {item_code} requires a valuation rate. "
                     "Please update the Item master or post incoming stock before transfer.")

    return valuation_rate, allow_zero

def get_company_from_pickslip(pickslip):
    if pickslip.order_no:
        return frappe.db.get_value("Sales Order", pickslip.order_no, "company")

    frappe.throw(_("Company not found for Pickslip {0}").format(pickslip.name))


def get_target_warehouse(row, pickslip):
    # 1️⃣ From Pickslip row
    if hasattr(row, "target_warehouse") and row.target_warehouse:
        return row.target_warehouse

    # 2️⃣ From Sales Order
    if pickslip.order_no:
        so_warehouse = frappe.db.get_value(
            "Sales Order",
            pickslip.order_no,
            "set_warehouse"
        )
        if so_warehouse:
            return so_warehouse

    # 3️⃣ From Item Default
    item_wh = frappe.db.get_value(
        "Item Default",
        {
            "parent": row.item_code,
            "company": get_company_from_pickslip(pickslip)
        },
        "default_warehouse"
    )
    if item_wh:
        return item_wh

    frappe.throw(
        _("Target warehouse not found for item {0}").format(row.item_code)
    )



def get_source_warehouse(item_code, qty, batch_no=None):
    """
    Returns warehouse where stock is available
    - Batch-aware
    - Safe & ERPNext compliant
    """

    # ---------------------------
    # BATCH ITEM
    # ---------------------------
    if batch_no:
        warehouse = frappe.db.sql("""
            SELECT sle.warehouse, SUM(sle.actual_qty) AS qty
            FROM `tabStock Ledger Entry` sle
            WHERE sle.item_code = %s
              AND sle.batch_no = %s
              AND sle.is_cancelled = 0
            GROUP BY sle.warehouse
            HAVING qty >= %s
            ORDER BY qty DESC
            LIMIT 1
        """, (item_code, batch_no, qty), as_dict=True)

        if warehouse:
            return warehouse[0].warehouse

        frappe.throw(
            _("No stock available for batch {0} of item {1}")
            .format(batch_no, item_code)
        )

    # ---------------------------
    # NON-BATCH ITEM
    # ---------------------------
    warehouse = frappe.db.sql("""
        SELECT warehouse
        FROM `tabBin`
        WHERE item_code = %s
          AND actual_qty >= %s
        ORDER BY actual_qty DESC
        LIMIT 1
    """, (item_code, qty), as_dict=True)

    if warehouse:
        return warehouse[0].warehouse

    frappe.throw(
        _("No stock available for item {0}").format(item_code)
    )



@frappe.whitelist()
def create_material_transfer_from_individual_pickslip(pickslip_name, submit_stock_entry=False):
    """
    Create Material Transfer Stock Entry from a single Pickslip
    """

    def validate_warehouse_company(warehouse, company):
        wh_company = frappe.db.get_value("Warehouse", warehouse, "company")
        if not wh_company:
            frappe.throw(_("Warehouse {0} does not exist").format(warehouse))
        if wh_company != company:
            frappe.throw(
                _("Warehouse {0} belongs to {1}, not {2}")
                .format(warehouse, wh_company, company)
            )

    try:
        # --------------------------------
        # LOAD PICKSLIP
        # --------------------------------
        pickslip = frappe.get_doc(
            "Pickslip Generation Against Sales Order",
            pickslip_name
        )

        if pickslip.docstatus != 1:
            frappe.throw(_("Pickslip must be submitted"))

        # --------------------------------
        # COMPANY (FROM SALES ORDER)
        # --------------------------------
        company = get_company_from_pickslip(pickslip)

        # --------------------------------
        # CREATE STOCK ENTRY
        # --------------------------------
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.stock_entry_type = "Material Transfer"
        stock_entry.purpose = "Material Transfer"
        stock_entry.company = company
        stock_entry.posting_date = nowdate()
        stock_entry.posting_time = nowtime()
        stock_entry.title = f"Material Transfer for Pickslip {pickslip.name}"

        # --------------------------------
        # ITEMS
        # --------------------------------
        for row in pickslip.table_kino:

            if not row.item_code or not row.qty or row.qty <= 0:
                continue

            item_doc = frappe.get_doc("Item", row.item_code)

            # SOURCE WAREHOUSE (STOCK-BASED)
            source_warehouse = get_source_warehouse(
                item_code=row.item_code,
                qty=row.qty,
                batch_no=row.batch_no
            )

            # TARGET WAREHOUSE
            target_warehouse = get_target_warehouse(row, pickslip)

            # VALIDATE WAREHOUSES
            validate_warehouse_company(source_warehouse, company)
            validate_warehouse_company(target_warehouse, company)

            # VALUATION
            valuation_rate, allow_zero, err = get_valuation_rate_for_individual(
                row.item_code,
                source_warehouse,
                stock_entry.posting_date
            )

            if err:
                frappe.throw(f"{row.item_code}: {err}")

            # APPEND ITEM
            stock_entry.append("items", {
                "item_code": row.item_code,
                "item_name": item_doc.item_name,
                "qty": row.qty,
                "uom": item_doc.stock_uom,
                "batch_no": row.batch_no,
                "s_warehouse": source_warehouse,
                "t_warehouse": target_warehouse,
                "valuation_rate": valuation_rate,
                "basic_rate": valuation_rate,
                # "allow_zero_valuation_rate": allow_zero,
                "allow_alternative_item": 0
            })

        if not stock_entry.items:
            frappe.throw(_("No valid items found to transfer"))

        # --------------------------------
        # SAVE & SUBMIT
        # --------------------------------
        stock_entry.insert(ignore_permissions=True)

        if submit_stock_entry:
            stock_entry.submit()

        pickslip.add_comment(
            "Comment",
            _("Stock Entry created: {0}").format(stock_entry.name)
        )

        return {
            "success": True,
            "stock_entry": stock_entry.name
        }

    # --------------------------------
    # SAFE ERROR LOGGING
    # --------------------------------
    except Exception as e:
        full_msg = f"Individual Stock Entry Error ({pickslip_name}): {str(e)}"
        title = full_msg[:137] + "..." if len(full_msg) > 140 else full_msg

        try:
            frappe.get_doc({
                "doctype": "Error Log",
                "title": title,
                "method": "create_material_transfer_from_individual_pickslip",
                "message": frappe.get_traceback()
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Pickslip Stock Entry Error")

        frappe.throw(str(e))




def get_available_batches(item_code, warehouse):
    """
    Get available batches with actual stock
    ERPNext v15 compatible (uses Stock Ledger Entry)
    """
    return frappe.db.sql(
        """
        SELECT
            sle.batch_no,
            SUM(sle.actual_qty) AS actual_qty
        FROM `tabStock Ledger Entry` sle
        WHERE
            sle.item_code = %s
            AND sle.warehouse = %s
            AND sle.batch_no IS NOT NULL
            AND sle.is_cancelled = 0
        GROUP BY sle.batch_no
        HAVING SUM(sle.actual_qty) > 0
        ORDER BY sle.posting_date ASC, sle.posting_time ASC
        """,
        (item_code, warehouse),
        as_dict=True
    )


@frappe.whitelist()
def create_bulk_stock_entry_from_pickslips(pickslip_names, auto_submit=False):
    """Create a single Stock Entry from multiple Pickslips with batch-safe handling"""

    DEFAULT_SOURCE_WAREHOUSE = "Stores - MQA"
    DEFAULT_TARGET_WAREHOUSE = "Finished Goods - MQA"

    if isinstance(pickslip_names, str):
        pickslip_names = frappe.parse_json(pickslip_names)

    if not pickslip_names:
        frappe.throw(_("No pickslips selected"))

    all_items = []

    # --------------------------------------------------
    # FETCH & PROCESS PICKSLIP ITEMS
    # --------------------------------------------------
    for pickslip_name in pickslip_names:
        pickslip = frappe.get_doc(
            "Pickslip Generation Against Sales Order",
            pickslip_name
        )

        if pickslip.docstatus != 1:
            frappe.throw(
                _("Pickslip {0} is not submitted").format(pickslip_name)
            )

        for row in pickslip.table_kino:
            item_doc = frappe.get_doc("Item", row.item_code)

            source_warehouse = DEFAULT_SOURCE_WAREHOUSE
            target_warehouse = DEFAULT_TARGET_WAREHOUSE
            qty_required = row.qty

            # --------------------------------------------------
            # BATCH HANDLING (CRITICAL FIX)
            # --------------------------------------------------
            if item_doc.has_batch_no:

                # If batch already provided → use directly
                if row.batch_no:
                    all_items.append({
                        "item_code": row.item_code,
                        "item_name": item_doc.item_name,
                        "batch_no": row.batch_no,
                        "qty": qty_required,
                        "uom": item_doc.stock_uom,
                        "s_warehouse": source_warehouse,
                        "t_warehouse": target_warehouse,
                        "pickslip": pickslip_name
                    })
                    continue

                # Auto-split across available batches
                batches = get_batches_for_item(
                    item_code=row.item_code,
                    warehouse=source_warehouse
                )

                remaining_qty = qty_required

                for b in batches:
                    if remaining_qty <= 0:
                        break

                    if b.actual_qty <= 0:
                        continue

                    use_qty = min(b.actual_qty, remaining_qty)

                    all_items.append({
                        "item_code": row.item_code,
                        "item_name": item_doc.item_name,
                        "batch_no": b.batch_no,
                        "qty": use_qty,
                        "uom": item_doc.stock_uom,
                        "s_warehouse": source_warehouse,
                        "t_warehouse": target_warehouse,
                        "pickslip": pickslip_name
                    })

                    remaining_qty -= use_qty

                if remaining_qty > 0:
                    frappe.throw(
                        _("Insufficient batch stock for item {0} in {1}")
                        .format(row.item_code, source_warehouse)
                    )

            # --------------------------------------------------
            # NON-BATCH ITEMS
            # --------------------------------------------------
            else:
                all_items.append({
                    "item_code": row.item_code,
                    "item_name": item_doc.item_name,
                    "batch_no": None,
                    "qty": qty_required,
                    "uom": item_doc.stock_uom,
                    "s_warehouse": source_warehouse,
                    "t_warehouse": target_warehouse,
                    "pickslip": pickslip_name
                })

    # --------------------------------------------------
    # GROUP ITEMS (Item + Batch + Warehouses)
    # --------------------------------------------------
    grouped_items = {}

    for item in all_items:
        key = (
            item["item_code"],
            item["batch_no"],
            item["s_warehouse"],
            item["t_warehouse"]
        )

        if key not in grouped_items:
            grouped_items[key] = item.copy()
        else:
            grouped_items[key]["qty"] += item["qty"]

    # --------------------------------------------------
    # CREATE STOCK ENTRY
    # --------------------------------------------------
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Material Transfer"
    stock_entry.purpose = "Material Transfer"
    stock_entry.company = "MD quality apps"
    stock_entry.posting_date = nowdate()
    stock_entry.posting_time = nowtime()

    stock_entry.title = (
        f"Stock Entry for Pickslip {pickslip_names[0]}"
        if len(pickslip_names) == 1
        else f"Bulk Stock Entry for {len(pickslip_names)} Pickslips"
    )

    for item in grouped_items.values():
        stock_entry.append("items", {
            "item_code": item["item_code"],
            "item_name": item["item_name"],
            "qty": item["qty"],
            "uom": item["uom"],
            "batch_no": item["batch_no"],
            "s_warehouse": item["s_warehouse"],
            "t_warehouse": item["t_warehouse"],
            "allow_alternative_item": 0
        })

    stock_entry.insert(ignore_permissions=True)

    if auto_submit:
        stock_entry.submit()

    frappe.db.commit()

    return {
        "stock_entry": stock_entry.name
    }



def get_valuation_rate_for_individual(item_code, warehouse, posting_date):
    """
    Returns (valuation_rate, allow_zero_valuation, error_message) for an item.
    Optimized for individual pickslip operations.
    """
    try:
        # Check if item exists
        if not frappe.db.exists("Item", item_code):
            return 0, False, f"Item {item_code} does not exist"

        # Check if item allows zero valuation
        item_doc = frappe.get_doc("Item", item_code)
        allow_zero = item_doc.get("allow_zero_valuation_rate", 0)
        
        # Try to get valuation rate from latest Stock Ledger Entry
        sle = frappe.db.sql("""
            SELECT valuation_rate, stock_value, qty_after_transaction
            FROM `tabStock Ledger Entry`
            WHERE item_code=%s AND warehouse=%s AND posting_date <= %s
            AND is_cancelled = 0
            ORDER BY posting_date DESC, posting_time DESC, creation DESC
            LIMIT 1
        """, (item_code, warehouse, posting_date), as_dict=True)

        valuation_rate = None
        
        if sle:
            # Use valuation rate from SLE if available
            if sle[0].valuation_rate and sle[0].valuation_rate > 0:
                valuation_rate = sle[0].valuation_rate
            # Calculate from stock value and quantity
            elif sle[0].stock_value and sle[0].qty_after_transaction and sle[0].qty_after_transaction > 0:
                valuation_rate = sle[0].stock_value / sle[0].qty_after_transaction

        # Fallback to item master valuation rate
        if not valuation_rate or valuation_rate == 0:
            valuation_rate = item_doc.get("valuation_rate") or 0

        # If still zero and item doesn't allow zero valuation, return error
        if (valuation_rate == 0 or valuation_rate is None) and not allow_zero:
            return 0, False, f"Valuation rate is required. Please update Item master or create incoming stock transaction."

        # Ensure valuation rate is not negative
        valuation_rate = abs(valuation_rate) if valuation_rate else 0

        return valuation_rate, allow_zero, None

    except Exception as e:
        frappe.log_error(f"Valuation Rate Error for {item_code}: {str(e)}")
        return 0, False, f"Error calculating valuation rate: {str(e)}"
