import frappe
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import sanitize_request,_clean_value, get_valid_coupon, validate_and_calculate_coupon , success, error, validate_fields, get_customer_shipping_address,is_book_item, get_full_image_url, validate_customer_access, get_product_prices, get_item_group_flatten, is_new_student, get_notification_for_user
from frappe.utils import get_url
from collections import defaultdict
from impressio.impressio.api.user import sync_family_primary_address

def get_restricted_item_codes(item_code):
    """
    Returns all item_codes that should be treated as the same purchase group.
    If variant -> return all variants of template
    If normal item -> return itself
    """

    variant_of = frappe.db.get_value("Item", item_code, "variant_of")

    # Not a variant
    if not variant_of:
        return [item_code]

    # Is variant → get all variants of template
    variants = frappe.get_all(
        "Item",
        filters={"variant_of": variant_of},
        pluck="name"
    )

    # Include template itself also (safety)
    variants.append(variant_of)

    return variants
    
def get_item_purchase_restriction(item_code, customer, website_user=None):
    """
    Returns:
        restricted (bool)
        status (str) -> OK / IN_CART / PURCHASED
    """

    # -------- Restriction check --------
    item_group = frappe.db.get_value("Item", item_code, "item_group")

    restricted = False

    if item_group == "Magic Box":
        restricted = True
    else:
        prices = get_product_prices(item_code)
        standard_price = prices.get("Standard Selling")

        if standard_price is None or float(standard_price) <= 0:
            restricted = True

    if not restricted:
        return False, "OK"

    # -------- Variant handling --------
    item_codes = get_restricted_item_codes(item_code)

    if not item_codes:
        return True, "OK"

    placeholders = ", ".join(["%s"] * len(item_codes))

    # -------- Live cart check --------
    if website_user:
        cart_query = f"""
            SELECT item_code
            FROM `tabWebsite Cart`
            WHERE
                website_user = %s
                AND customer = %s
                AND item_code IN ({placeholders})
            LIMIT 1
        """

        cart_values = [website_user, customer] + item_codes
        in_cart = frappe.db.sql(cart_query, cart_values, as_dict=True)

        if in_cart:
            # IMPORTANT: ignore same item update
            if in_cart[0]["item_code"] != item_code:
                return True, "IN_CART"

    # -------- Past purchase check --------
    query = f"""
        SELECT soi.item_code
        FROM `tabSales Order Item` soi
        INNER JOIN `tabSales Order` so
            ON so.name = soi.parent
        WHERE
            so.customer = %s
            AND so.docstatus = 1
            AND soi.item_code IN ({placeholders})
        LIMIT 1
    """

    values = [customer] + item_codes
    already_purchased = frappe.db.sql(query, values)

    if already_purchased:
        return True, "PURCHASED"

    return True, "OK"


@frappe.whitelist(allow_guest=True)
def add_to_cart(**kwargs):
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
    
    if  is_new_student(user):
        clear_cart(user.name)
        return error("not allowed", 403)
   

    is_error, payload = sanitize_request(
        kwargs,
        required = ["item_code", "qty"],
        optional=["customer"]
    )
    if is_error:
        return error(payload, 422)

    item_code = payload.get("item_code")
    qty = float(payload.get("qty"))

    customer = payload.get("customer", None)
    customer = customer if customer is not None else user.get("customer_data", {}).get("name")

    # Validate customer access
    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    if not frappe.db.exists("Item", item_code):
        return error("Invalid Item Code")

    restricted, status = get_item_purchase_restriction(
        item_code,
        customer,
        website_user=user.name
    )

    if status == "PURCHASED":
        return error("You have already purchased this item earlier", 403)

    if status == "IN_CART":
        return error(
            "Another variant of this item already exists in your cart. "
            "Please remove it first to add this one.",
            409
        )

    if restricted:
        qty = 1
 
    existing = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": customer,
            "item_code": item_code
        },
        fields=["name", "qty"]
    )

    if existing:
        cart_doc = frappe.get_doc("Website Cart", existing[0].name)
        
        # Single purchase item (Magic box OR price 0)
        if restricted:
            if float(cart_doc.qty) != 1:
                cart_doc.qty = 1
                cart_doc.save(ignore_permissions=True)
            return success("Item already in cart. Only one purchase is allowed.")

        cart_doc.qty = float(cart_doc.qty) + qty
        cart_doc.save(ignore_permissions=True)
        return success("Cart updated successfully")

    cart = frappe.new_doc("Website Cart")
    cart.website_user = user.name
    cart.customer = customer
    cart.item_code = item_code
    cart.qty = qty
    cart.added_on = frappe.utils.now()
    cart.insert(ignore_permissions=True)

    return success("Item added to cart")


@frappe.whitelist(allow_guest=True)
def add_magicbox_to_cart(**kwargs):

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    if not is_new_student(user):
        return error("not allowed", 403)

    item_codes = kwargs.get("item_codes")
    magic_box_id = _clean_value(kwargs.get("magic_box_id"))

    if not item_codes or not magic_box_id:
        return error("Missing required data", 422)

    # -------------------------------------------------
    # 1️⃣ Validate customer
    # -------------------------------------------------
    customer = user.get("customer_data", {}).get("name")
    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    # -------------------------------------------------
    # 2️⃣ Validate Magic Box
    # -------------------------------------------------
    if not frappe.db.exists("Item", magic_box_id):
        return error("Invalid Magic Box", 404)

    # -------------------------------------------------
    # 3️⃣ Clear existing cart
    # -------------------------------------------------
    old_cart_items = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": customer
        },
        pluck="name"
    )

    for name in old_cart_items:
        frappe.delete_doc("Website Cart", name, ignore_permissions=True)

    # -------------------------------------------------
    # 4️⃣ Create SINGLE parent cart row
    # -------------------------------------------------
    cart = frappe.new_doc("Website Cart")
    cart.website_user = user.name
    cart.customer = customer
    cart.item_code = magic_box_id
    cart.qty = 1
    cart.added_on = frappe.utils.now()
    cart.is_magicbox_item = 1

    # -------------------------------------------------
    # 5️⃣ Insert child items
    # -------------------------------------------------
    for row in item_codes:

        item_code = _clean_value(row.get("item_code"))
        qty = float(row.get("qty", 0))

        if not item_code or qty <= 0:
            continue

        if not frappe.db.exists("Item", item_code):
            continue

        cart.append("sub_items", {
            "item_code": item_code,
            "qty": qty
        })

    cart.insert(ignore_permissions=True)

    return success("Magic Box added to cart successfully")

@frappe.whitelist(allow_guest=True)
def update_cart_qty(**kwargs):
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
    
    if is_new_student(user):
        clear_cart(user.name)
        return error("not allowed", 403)   

    is_error, payload = sanitize_request(kwargs,
        required = ["item_code", "qty"],
        optional = ["customer"]
    )
    if is_error:
        return error(payload, 422)
        
    item_code = payload.get("item_code")

    # ---- qty validation ----
    try:
        qty = float(payload.get("qty"))
    except:
        return error("Invalid quantity", 422)

    if qty <= 0:
        return error("Quantity must be greater than 0", 422)

    # ---- customer ----
    customer = payload.get("customer", None)
    customer = customer if customer is not None else user.get("customer_data", {}).get("name")

    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    # ---- item validation ----
    if not frappe.db.exists("Item", item_code):
        return error("Invalid Item Code")

    # ---- restriction engine ----
    restricted, status = get_item_purchase_restriction(
        item_code,
        customer,
        website_user=user.name
    )

    # If customer already bought this in past → remove from cart immediately

    if status == "PURCHASED":
        frappe.db.delete("Website Cart", {
            "website_user": user.name,
            "customer": customer,
            "item_code": item_code
        })
        return error("You have already purchased this item earlier", 403)

    if status == "IN_CART":
        return error(
            "Another variant of this item already exists in your cart. "
            "Please remove it first.",
            409
        )
        
    # ---- find cart ----
    cart = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": customer,
            "item_code": item_code
        },
        fields=["name", "qty"]
    )

    if not cart:
        return error("Item not found in cart")

    cart_doc = frappe.get_doc("Website Cart", cart[0].name)

    # ---- enforce quantity rules ----
    if restricted:
        # Magic Box / Free item
        if float(cart_doc.qty) != 1:
            cart_doc.qty = 1
            cart_doc.save(ignore_permissions=True)

        return success("Only 1 quantity allowed for this item")

    # Normal item
    cart_doc.qty = qty
    cart_doc.save(ignore_permissions=True)

    return success("Cart quantity updated")



@frappe.whitelist(allow_guest=True)
def remove_from_cart(**kwargs):
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    is_error, payload = sanitize_request(kwargs,
        required = ["item_code"],
        optional = ["customer"]
    )
    if is_error:
        return error(payload, 422)

    item_code = payload.get("item_code")
    customer = payload.get("customer", None)
    customer = customer if customer is not None else user.get("customer_data", {}).get("name")

    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    cart = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": customer,
            "item_code": item_code
        },
        fields=["name"]
    )

    if not cart:
        return error("Item not found in cart")

    frappe.delete_doc("Website Cart", cart[0].name, ignore_permissions=True)

    return success("Item removed from cart")


@frappe.whitelist(allow_guest=True)
def get_all_cart_items(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        optional=["coupon_code"]
    )
    if is_error:
        return error(payload, 422)

    coupon_code = payload.get("coupon_code")

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
    
    delivery_fee = 0

    # ------------------------------------------------
    # 1️⃣ Resolve allowed customers
    # ------------------------------------------------
    allowed_customers = user.linked_customers or []

    if not allowed_customers:
        return success("success",{
            "cart_total_items": 0,
            "cart_sub_total_amount": 0,
            "cart_total_amount": 0,
            "users": []
        })

    try: 
        sync_family_primary_address()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Cart API - Sync Address Error")

    # ------------------------------------------------
    # 2️⃣ Fetch cart rows
    # ------------------------------------------------
    carts = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": ["in", allowed_customers]
        },
        fields=["name","customer","item_code","qty","is_magicbox_item"]
    )


    if not carts:
        return  success("success",  {
            "cart_total_items": 0,
            "cart_sub_total_amount":0,
            "cart_total_amount": 0,
            "users": []
        })

    # ------------------------------------------------
    # 3️⃣ Group by customer
    # ------------------------------------------------
    carts_by_customer = defaultdict(list)
    for row in carts:
        carts_by_customer[row.customer].append(row)

    # ------------------------------------------------
    # Coupon allowed only for single customer cart
    # ------------------------------------------------

    single_customer_cart = len(carts_by_customer) == 1

    # ------------------------------------------------
    # 4️⃣ Preload coupon (optional)
    # ------------------------------------------------
    coupon = None
    coupon_error = None

    if coupon_code and single_customer_cart:
        coupon, coupon_error = get_valid_coupon(coupon_code)
    else:
        # silently ignore coupon
        coupon = None
        coupon_error = None
   

    users_data = []
    cart_total_items = 0
    cart_sub_total_amount = 0
    cart_total_amount = 0     # before discount
    cart_discount_total = 0   # after discount
    
    # ------------------------------------------------
    # 5️⃣ Build response per customer
    # ------------------------------------------------
    for customer, rows in carts_by_customer.items():

        student = frappe.get_value(
            "Students",
            {"customer": customer},
            ["name", "first_name", "enrollment_number"],
            as_dict=True
        )

        if student:
            user_name = f"{student.first_name} ({student.enrollment_number})"
        else:
            user_name = frappe.get_value(
                "Customer", customer, "customer_name"
            )

        user_items = []
        user_total_items = 0
        user_total_amount = 0

        for row in rows:

            item = frappe.get_doc("Item", row.item_code)

            sub_items_data = None
            # -------------------------------
            # Attach Magic Box selections
            # -------------------------------
            if row.is_magicbox_item:

                cart_doc = frappe.get_doc("Website Cart", row.name)

                sub_items_data = []

                for sub in cart_doc.sub_items:

                    sub_item = frappe.get_doc("Item", sub.item_code)

                    # 🔥 Parent name for sub item
                    if sub_item.variant_of:
                        sub_parent_name = frappe.get_value(
                            "Item",
                            sub_item.variant_of,
                            "item_name"
                        )
                    else:
                        sub_parent_name = sub_item.item_name


                    # fetch attributes if variant
                    sub_attributes = {}
                    if sub_item.variant_of:
                        attrs = frappe.get_all(
                            "Item Variant Attribute",
                            filters={"parent": sub_item.name},
                            fields=["attribute", "attribute_value"]
                        )
                        sub_attributes = {
                            a.attribute: a.attribute_value for a in attrs
                        }
                    # -------------------------------
                    # Image fallback (variant -> template)
                    # -------------------------------
                    sub_image = sub_item.image

                    if not sub_image and sub_item.variant_of:
                        sub_image = frappe.get_value(
                            "Item",
                            sub_item.variant_of,
                            "image"
                        )
                        

                    sub_items_data.append({
                        "item_code": sub_item.name,
                        "parent_item_code": sub_item.variant_of or sub_item.name,
                        "item_name":sub_parent_name,
                        "qty": float(sub.qty),
                        "image": get_full_image_url(sub_image),
                        "attributes": sub_attributes,
                        "type": "book" if is_book_item(sub_item.name) else "product"
                    })

            # --------------------------------------------------
            #  Prices
            # --------------------------------------------------
            price_lists = get_product_prices(item.name)


            qty = float(row.qty)
            rate = float(price_lists.get("Standard Selling") or 0.0)
            mrp = float(price_lists.get("MRP") or 0.0)
            amount = qty * rate

            user_total_items += qty
            user_total_amount += amount

            parent_item_code = item.variant_of or item.name
            has_attributes = 1 if item.variant_of else 0

            # 🔥 Get parent item name instead of variant name
            if item.variant_of:
                parent_item_name = frappe.get_value(
                    "Item",
                    item.variant_of,
                    "item_name"
                )
            else:
                parent_item_name = item.item_name

            attributes = {}
            if has_attributes:
                attrs = frappe.get_all(
                    "Item Variant Attribute",
                    filters={"parent": item.name},
                    fields=["attribute", "attribute_value"]
                )
                attributes = {
                    a.attribute: a.attribute_value for a in attrs
                }

            item_type = "book" if is_book_item(item.name) else "product"
            # -------------------------------
            # Image fallback (variant -> template)
            # -------------------------------
            variant_image = item.image

            if not variant_image and item.variant_of:
                variant_image = frappe.get_value(
                    "Item",
                    item.variant_of,
                    "image"
                )

            user_items.append({
                "item_code": item.name,
                "parent_item_code": parent_item_code,
                "item_name": parent_item_name,
                "item_group": item.item_group,
                "qty": qty,
                "mrp": mrp,
                "rate": rate,
                "amount": amount,
                "uom": item.stock_uom,
                "image": get_full_image_url(variant_image),
                "has_attributes": has_attributes,
                "attributes": attributes,
                "type": "magicbox" if row.is_magicbox_item else item_type,
                "sub_items": sub_items_data if row.is_magicbox_item else None
            })

        # ------------------------------------------------
        # 6️⃣ Apply coupon (per customer)
        # ------------------------------------------------

        discount_amount = 0
        applied_coupon = None
        original_user_amount = user_total_amount

        if coupon:
            valid, discount_amount, msg = validate_and_calculate_coupon(
                coupon, customer, user_total_amount
            )

            if valid:
                user_total_amount -= discount_amount
                applied_coupon = coupon_code
                coupon_error = None
            else:
                # silently ignore coupon (no error for UI)
                discount_amount = 0
                applied_coupon = None
                coupon_error = msg


        cart_total_items += user_total_items

        # subtotal = before discount
        cart_sub_total_amount += original_user_amount

        # total discount
        cart_discount_total += discount_amount

        # total payable
        cart_total_amount += user_total_amount

        users_data.append({
            "user_name": user_name,
            "customer": customer,
            "total_items": user_total_items,
            "total_amount": user_total_amount,
            "discount_amount": discount_amount,
            "coupon_applied": applied_coupon,
            "primary_address": get_customer_shipping_address(customer),
            "items": user_items
        })

    # ------------------------------------------------
    # 7️⃣ Final response
    # ------------------------------------------------
    

    delivery_fee =  extra_fee(carts, cart_total_amount)
    grand_total = cart_total_amount + delivery_fee

    return success("success", {
        "cart_total_items": cart_total_items,
        "cart_sub_total_amount": cart_sub_total_amount,
        "cart_discount_amount": cart_discount_total,
        "delivery_fee": delivery_fee,
        "cart_total_amount": grand_total,
        "coupon_error": coupon_error,
        "users": users_data,
        "notification": get_notification_for_user(user, "Cart Page")
    })



def get_top_level_item_group(item_group):
    """Walk up until direct child of 'All Item Groups'."""
    try:
        if not item_group:
            return None

        current = item_group
        while True:
            parent = frappe.get_value("Item Group", current, "parent_item_group")
            if not parent or parent == "All Item Groups":
                return current
            current = parent

    except Exception:
        return None


def extra_fee(carts, cart_sub_total=0):

    try:
        if not carts:
            return 0

        # ── Step 1: Collect item_codes and customers from cart ─────────────
        item_codes = list({row.item_code for row in carts if row.item_code})
        customers  = list({row.customer  for row in carts if row.customer})

        if not item_codes or not customers:
            return 0

        # ── Step 2: Collect school.name ────────────────────────────────────
        schools = set()

        school_codes = frappe.get_all(
            "Students",
            filters={"customer": ["in", customers]},
            pluck="school_code"
        )
        school_codes = [s for s in school_codes if s]  # remove nulls

        if school_codes:
            school_names = frappe.get_all(
                "School",
                filters={"school_code": ["in", school_codes]},
                pluck="name"
            )
            schools = set(school_names or [])

        if not schools:
            return 0

        # ── Step 3: Collect top-level item groups ──────────────────────────
        raw_groups = frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            pluck="item_group"
        )

        top_groups = set()
        for ig in (raw_groups or []):
            if not ig:
                continue
            top = get_top_level_item_group(ig)
            if top:
                top_groups.add(top)

        # ── Fetch matching active rules ────────────────────────────────────
        rules = frappe.get_all(
            "Delivery Fee Rule",
            filters={
                "is_active": 1,
                "school": ["in", list(schools)]
            },
            fields=["name", "delivery_fee", "min_amount", "max_amount"]
        )

        if not rules:
            return 0

        sub_total = float(cart_sub_total or 0)
        max_fee   = 0

        for rule in (rules or []):
            if not rule:
                continue

            # ── Amount check ───────────────────────────────────────────────
            min_amount = float(rule.get("min_amount") or 0)
            max_amount = float(rule.get("max_amount") or 0)

            # min_amount mandatory — cart must be >= min
            if sub_total < min_amount:
                continue

            # max_amount optional — if set, cart must be <= max
            if max_amount and sub_total > max_amount:
                continue

            # ── Item group check (optional) ────────────────────────────────
            applicable_groups = frappe.get_all(
                "Applicable Item Group",
                filters={"parent": rule.name},
                pluck="item_group"
            )

            if applicable_groups:
                if not top_groups.intersection(set(applicable_groups)):
                    continue

            # ── Rule matches → track highest fee ──────────────────────────
            fee = float(rule.get("delivery_fee") or 0)
            if fee > max_fee:
                max_fee = fee

        return max_fee

    except Exception:
        frappe.log_error(frappe.get_traceback(), "extra_fee - Delivery Fee Calculation Error")
        return 100  # fallback delivery fee



def clear_cart(userName):

    if not userName:
        return error("Login required", 401)

    # Fetch all cart rows for this website user
    cart_rows = frappe.get_all(
        "Website Cart",
        filters={"website_user": userName},
        pluck="name"
    )

    if not cart_rows:
        return success("Cart is already empty")

    # Bulk delete (fast & safe)
    frappe.db.delete(
        "Website Cart",
        {"name": ["in", cart_rows]}
    )

    frappe.db.commit()

    return success("Cart cleared successfully")
