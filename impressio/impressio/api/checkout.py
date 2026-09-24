import frappe
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import FRONTEND_CHECKOUT_URL,sanitize_request,  get_valid_coupon, validate_and_calculate_coupon, get_payment_provider_details, check_otp, consume_otp, success, error, validate_fields,extract_pin_code, create_otp,is_book_item, get_full_image_url
from impressio.impressio.api.payments import handle_payment, send_checkout_notification
from frappe.utils import get_url, now_datetime
from impressio.impressio.api.cart import extra_fee, clear_cart, get_product_prices
from impressio.impressio.api.sales_helper import append_bundle_items_to_so, get_bundle_items




def create_sales_order_from_cart_rows(customer, rows,user, extra=None):
    """
    Create ONE Sales Order for ONE customer
    using provided cart rows
    """

    if not rows:
        return error("Cart is empty")

    company = frappe.defaults.get_user_default("Company")
    selling_price_list = frappe.db.get_single_value(
        "Selling Settings", "selling_price_list"
    )

    currency = frappe.get_cached_value(
        "Company", company, "default_currency"
    )

    so = frappe.new_doc("Sales Order")
    so.customer = customer
    so.company = company
    so.order_type = "Shopping Cart"
    so.currency = currency
    so.set_warehouse = "Stores - IESPL"
    so.selling_price_list = selling_price_list

    # ------------------------------------------------
    # FETCH STUDENT DATA
    # ------------------------------------------------
    school = None
    grade = None

    if customer:
        student = frappe.db.get_value(
                "Students",
                {"customer": so.customer},
                ["school_code", "grade"],
                as_dict=True
            )

        if student:
            school_code = student.get("school_code")
            grade = student.get("grade")

            if school_code:
                school = frappe.db.get_value(
                    "School",
                    {"school_code": school_code},
                    "name"
                )

    

    so.custom_student_school = school
    so.custom_student_grade = grade

    # ------------------------------------------------
    # ✅ Set contact details from logged-in user
    # ------------------------------------------------
    if user:
        so.contact_mobile = (
            user.get("mobile")
            or (user.get("customer_data").get("mobile_no") if user.get("customer_data") else None)
        )
        so.contact_email = user.get("email")


    if extra:
        for k, v in extra.items():
            so.set(k, v)

    has_magic_box = False

    for row in rows:

        cart_doc = frappe.get_doc("Website Cart", row.name)
        is_magic_box = getattr(cart_doc, "is_magicbox_item", 0)

        # if any row is magic box → whole SO becomes magic box order
        if is_magic_box:
            has_magic_box = True

        # -----------------------------
        # Add Sales Order Item
        # -----------------------------
        so.append("items", {
            "item_code": row.item_code,
            "qty": row.qty
        })
        
        frappe.log("item group for " + row.item_code + " is " + str(frappe.get_value("Item", row.item_code, "item_group")))
        
        item_group = frappe.get_value("Item", row.item_code, "item_group")

        if item_group == "Books Bundle":

            append_bundle_items_to_so(
                so,
                row.item_code,
                row.qty
            )
            
        elif item_group == "Books Template":

            append_bundle_items_to_so(
                so,
                row.item_code,
                row.qty
            )

        # -----------------------------
        # Attach configuration
        # -----------------------------
        elif is_magic_box and cart_doc.sub_items:

            for sub in cart_doc.sub_items:

                sub_item_group = frappe.get_value("Item", sub.item_code, "item_group")

                if sub_item_group in ["Books Bundle", "Books Template"]:
                    
                    bundle_items = get_bundle_items(sub.item_code, sub.qty)

                    for bi in bundle_items:
                        so.append("custom_sub_items", {
                            "parent_item_code": sub.item_code,  # 🔥 selected variant
                            "item_code": bi["item_code"],
                            "qty": bi["qty"]
                        })

                else:
                    so.append("custom_sub_items", {
                        "parent_item_code": row.item_code,
                        "item_code": sub.item_code,
                        "qty": sub.qty
                    })


        else:
            so.append("custom_sub_items", {
                    "parent_item_code": row.item_code,
                    "item_code": row.item_code,
                    "qty": row.qty
                })

        
    # mark order as magic box order
    if has_magic_box:
        so.custom_magic_box = 1

    so.insert(ignore_permissions=True)

    return so



@frappe.whitelist(allow_guest=True)
def checkout(**kwargs):
    """
    Checkout API
    - Single payment
    - Multiple Sales Orders (guardian flow)
    """

    # ------------------------------------------------
    # 1️⃣ Validate user
    # ------------------------------------------------
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    # ------------------------------------------------
    # 1️⃣.1️⃣ Validate inputs
    # ------------------------------------------------
    is_error, payload = sanitize_request(
        kwargs,
        required=["payment_gateway"],
        optional=["coupon_code"]
    )
    if is_error:
        return error(payload, 422)

    payment_gateway = payload.get("payment_gateway")
    coupon_code = payload.get("coupon_code")  # optional


    # ------------------------------------------------
    # 2️⃣ Resolve payment provider (HELPER)
    # ------------------------------------------------
    payment_ctx = get_payment_provider_details(payment_gateway)

    if not payment_ctx:
        return error("Invalid or unavailable payment provider", 409)

    provider = payment_ctx["provider"]        # dict
    gateway = payment_ctx.get("gateway")      # dict | None

    # ONLINE payments MUST have gateway
    if provider["payment_flow"] == "ONLINE" and not gateway:
        return error("Payment gateway configuration missing", 409)

    # ------------------------------------------------
    # 3️⃣ Fetch ALL carts for logged-in user
    # ------------------------------------------------
    carts = frappe.get_all(
        "Website Cart",
        filters={
            "website_user": user.name,
            "customer": ["in", user.get("linked_customers", [])]
        },
        fields=["name","customer","item_code","qty"]
    )


    # ── Compute subtotal from cart rows (needed for delivery fee rule) ──
    cart_sub_total = 0
    for row in carts:
        prices = get_product_prices(row.item_code)
        rate = float(prices.get("Standard Selling") or 0)
        cart_sub_total += rate * float(row.qty or 0)

    delivery_cost = extra_fee(carts, cart_sub_total)

    if not carts:
        return error("Cart is empty", 409)

    # ------------------------------------------------
    # 4️⃣ Group cart rows by CUSTOMER
    # ------------------------------------------------
    from collections import defaultdict

    carts_by_customer = defaultdict(list)
    for row in carts:
        carts_by_customer[row.customer].append(row)
    # ------------------------------------------------
    # Coupon allowed only for single-customer checkout
    # ------------------------------------------------
    single_customer_checkout = len(carts_by_customer) == 1

    # ------------------------------------------------
    # Coupon validation (checkout level)
    # ------------------------------------------------
    
    coupon = None
    coupon_customer = None
    coupon_discount_map = {}

    # Only attempt coupon if single customer order
    if coupon_code and single_customer_checkout:

        coupon, msg = get_valid_coupon(coupon_code)

        if coupon:
            customer = list(carts_by_customer.keys())[0]
            rows = carts_by_customer[customer]

            total_amount = 0
            for row in rows:
                prices = get_product_prices(row.item_code)
                rate = float(prices.get("Standard Selling") or 0)
                total_amount += rate * float(row.qty)

            valid, discount, msg = validate_and_calculate_coupon(
                coupon, customer, total_amount
            )

            if valid and discount > 0:
                coupon_customer = customer
                coupon_discount_map[customer] = discount
            else:
                coupon = None

    # If multiple customers → coupon silently ignored
    else:
        coupon = None


    # ------------------------------------------------
    # 5️⃣ Create Sales Orders (one per customer)
    # ------------------------------------------------
    sales_orders = []

    payment_meta = {
        "custom_payment_flow": provider["payment_flow"],
        "custom_payment_mode": (
            "UNKNOWN" if provider["payment_flow"] == "ONLINE" else "COD"
        ),
        "custom_gateway_provider": provider["provider_code"]
    }

    for customer, rows in carts_by_customer.items():
        so = create_sales_order_from_cart_rows(
            customer=customer,
            rows=rows,
            user=user,
            extra=payment_meta
        )
       

        # Safety (in case helper changes later)
        if not so or not hasattr(so, "name"):
            return error("Failed to create sales order")


        # ------------------------------------------------
        # Apply coupon to this SO
        # ------------------------------------------------
        if coupon and customer == coupon_customer:
            so.custom_cart_coupon_code = coupon.name
            so.discount_amount = coupon_discount_map.get(customer, 0)
            so.apply_discount_on = "Grand Total"
            so.flags.ignore_permissions = True
            so.save()
        
        #  reload fresh doc (safe)
        so = frappe.get_doc("Sales Order", so.name)

        if so.shipping_address_name:
            so.custom_pin_code = frappe.db.get_value(
                "Address",
                so.shipping_address_name,
                "pincode"
            )
            so.flags.ignore_permissions = True
            so.save()
    

        sales_orders.append(so.name)


    # ------------------------------------------------
    # 6️⃣ Route to payment handler (SINGLE PAYMENT)
    # ------------------------------------------------

    # clear_cart(user.name)  # 🔥 CART CLEARED ONLY AFTER SALES ORDER CREATION

    return handle_payment(
        sales_order_names=sales_orders,
        provider=provider,
        gateway=gateway,
        delivery_cost = delivery_cost,
        user=user
    )


@frappe.whitelist(allow_guest=True)
def verify_zero_order( otp):

    # ------------------------------------------------
    # 1️⃣ Validate user
    # ------------------------------------------------
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
        
    mobile = user.get("mobile")

    log = frappe.get_all(
        "OTP Log",
        filters={
            "mobile": mobile,
            "otp": otp,
            "purpose": "ZERO_ORDER",
            "is_used": 0
        },
        fields=["name","extra_data","expiry","user"],
        order_by="creation desc",
        limit=1
    )

    if not log:
        return error("Invalid OTP")

    log = log[0]

    if now_datetime() > log.expiry:
        return error("OTP expired")

    # security: same logged-in user
    if log.user != user.name:
        return error("Unauthorized")

    # 🔥 read orders from OTP (NOT FROM FRONTEND)
    reference = frappe.parse_json(log.extra_data or "{}")
    sales_orders = reference.get("names", [])

    submitted = []

    for so_name in sales_orders:
        so = frappe.get_doc("Sales Order", so_name)

        if so.docstatus != 0:
            continue

        so.custom_payment_flow = "OFFLINE"
        so.payment_status = "PREPAID"
        so.custom_gateway_provider = "ZERO_ORDER"
        so.custom_payment_status = "SUCCESS"
        so.custom_payment_mode = "OTP_CONFIRMED"
        
        payment_ref = f"ZERO-{log.name}"
        so.custom_internal_payment_reference = payment_ref
        so.custom_gateway_order_id = payment_ref
        so.save(ignore_permissions=True)
        so.submit()

        submitted.append(so.name)

    # consume OTP
    consume_otp(email=None, mobile=mobile, purpose="ZERO_ORDER")

    # ------------------------------------------------
    # 1️⃣ Send Order Placed SMS (NON-BLOCKING)
    # ------------------------------------------------
    try:
        send_checkout_notification(sales_orders)
    except Exception:
        frappe.log_error(
            title="ZERO_ORDER | ORDER PLACED SMS FAILED",
            message=frappe.get_traceback()
        )


    redirect_url = (
        f"{FRONTEND_CHECKOUT_URL}"
        f"?orders={','.join(sales_orders)}"
        f"&status=success"
        f"&payment_flow=OFFLINE"
    )

    return success("Order confirmed", {
        "orders": sales_orders,
        "payment_flow": "OFFLINE",
        "payment_provider": "ZERO_ORDER",
        "redirect": {
            "url": redirect_url,
            "method": "GET"
        },
        "form": None
    })