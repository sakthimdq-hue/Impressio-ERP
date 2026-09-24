import frappe
import math
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import sanitize_request, _clean_value, get_account_customers, SKIP_ITEM_GROUPS, resolve_school_grade, success, error, validate_fields, is_in_wishlist, get_item_group_flatten, is_book_item, get_group_tree_as_array, resolve_catalog_groups, get_customer_addresses, validate_customer_access, get_full_url, get_customer_shipping_address, get_raw_item_description, resolve_image_url, get_product_prices, is_new_student, get_item_group_ancestors
from frappe.utils import get_url




@frappe.whitelist(allow_guest=True)
def dashboard():

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
    
    if not user.get("customer_data",{}).get("name"):
        return error("not allowed", 401)
    
    # Initialize safe defaults
    student = user.student_data or {}
    customer = user.customer_data or {}

    response = {
        "student": None,
        "customer": None,
        "guardian": None,
        "students_count": 0,
        "pending_count": 0
    }

    # ------------------------------------------------
    # Total linked students count (ALL schools)
    # ------------------------------------------------
    if user.has_student:

        guardian = frappe.db.get_value(
            "Guardians",
            {"mobile_number": user.mobile},
            "name"
        )

        if guardian:
            counts = frappe.db.sql("""
            SELECT
                COUNT(
                    CASE 
                        WHEN IFNULL(s.enabled, 0) = 1
                            AND IFNULL(s.is_verified, 0) = 1
                            AND IFNULL(s.customer, '') != ''
                            AND sch.status = 'Active'
                        THEN 1
                    END
                ) AS students_count,

                COUNT(
                    CASE
                        WHEN IFNULL(s.enabled, 0) = 1
                            AND IFNULL(s.is_verified, 0) = 0
                            AND IFNULL(s.customer, '') = ''
                            AND sch.status = 'Active'
                        THEN 1
                    END
                ) AS pending_count

            FROM `tabStudents` s
            INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
            INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
            WHERE sg.guardian = %s
        """, guardian, as_dict=True)
        
        if counts:
            response["students_count"] = counts[0].students_count or 0
            response["pending_count"] = counts[0].pending_count or 0
                        

    # Case 1 – Student Flow
    if user.has_student and student:

        response["student"] = {
            "id": student.get("name"),
            "student_name": student.get("first_name"),
            "school_logo": student.get("school", {}).get("school_logo") if student.get("school") else None,
            "grade":  resolve_school_grade(student.get("grade"),student.get("school").get("name")),
            "section": student.get("section"),
            "school_code": student.get("school_code"),
            "enrollment_number": student.get("enrollment_number"),
            "medium": student.get("medium"),
            "curriculum": student.get("curriculum"),
            "profile_picture": student.get("profile_picture_attach")
        }

        response["guardian"] = {
            "name": user.full_name,
            "mobile": user.mobile
        }

        # Customer linked through student
        if customer:
            response["customer"] = {
                "id": customer.get("name"),
                "customer_name": customer.get("customer_name"),
                "email": customer.get("email_id"),
                "mobile": customer.get("mobile_no")
            }

    # Case 2 – Direct Customer Flow (No Student)
    elif not user.has_student and customer:

        response["customer"] = {
            "id": customer.get("name"),
            "customer_name": customer.get("customer_name"),
            "email": customer.get("email_id"),
            "mobile": customer.get("mobile_no")
        }

    else:
        return error("No valid user data found")

    return success(response)


def build_full_name(first_name, middle_name=None, last_name=None):
    return " ".join(
        part for part in [first_name, middle_name, last_name] if part
    )


@frappe.whitelist(allow_guest=True)
def get_user_profile():
    user = BaseAPI().user
    if not user:
        return error("Login required", 401)

    user_doc = frappe.get_doc("User", user.name)

    full_name = build_full_name(
        user_doc.first_name,
        user_doc.middle_name,
        user_doc.last_name
    )

    user_image = user_doc.user_image

    if user_image and user_image.startswith("/"):
        user_image = f"{frappe.utils.get_url()}{user_image}"

    return success("Success", {
        "first_name": user_doc.first_name,
        "middle_name": user_doc.middle_name,
        "last_name": user_doc.last_name,
        "full_name": full_name,
        "mobile": user_doc.mobile_no,
        "email": user_doc.name,
        "profile_image": user_image
    })


def is_valid_user_image(path):
    if not path:
        return False

    return (
        path.startswith("/files/")
        or path.startswith("/private/files/")
        or path.startswith("https://")
    )



@frappe.whitelist(allow_guest=True)
def update_user_profile(**kwargs):

    user = BaseAPI().user
    if not user:
        return error("Login required", 401)
    
    is_error, payload = sanitize_request(
        kwargs,
        required =  ["first_name", "last_name"],
        optional = ["middle_name", "mobile", "profile_image"]
    )
    if is_error:
        return error(payload, 422)

    first_name = payload.get("first_name")
    middle_name = payload.get("middle_name")
    last_name = payload.get("last_name")
    mobile = payload.get("mobile")
    profile_image = payload.get("profile_image")

    try:
        frappe.db.begin()

        user_doc = frappe.get_doc("User", user.name)

        # -----------------------------
        # Name update rules
        # -----------------------------
        name_update_requested = any(
            v is not None for v in [first_name, middle_name, last_name]
        )

        if name_update_requested:
            if not first_name or not last_name:
                frappe.db.rollback()
                return error(
                    "First name and last name are required to update name",
                    422
                )

            user_doc.first_name = first_name
            user_doc.middle_name = middle_name
            user_doc.last_name = last_name

            user_doc.full_name = build_full_name(
                first_name,
                middle_name,
                last_name
            )

        # -----------------------------
        # Mobile update
        # -----------------------------
        if mobile and mobile != user_doc.mobile_no:
            if frappe.db.exists(
                "User",
                {
                    "mobile_no": mobile,
                    "name": ["!=", user_doc.name]
                }
            ):
                frappe.db.rollback()
                return error("Mobile number already in use", 409)

            user_doc.mobile_no = mobile

        # -----------------------------
        # Profile image update (FIXED)
        # -----------------------------
        if profile_image is not None:
            if not is_valid_user_image(profile_image):
                frappe.db.rollback()
                return error("Invalid profile image", 422)

            user_doc.user_image = profile_image

        user_doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Update User Profile Failed")
        return error("Failed to update profile", 500)

    return success("Profile updated successfully", {
        "first_name": user_doc.first_name,
        "middle_name": user_doc.middle_name,
        "last_name": user_doc.last_name,
        "full_name": user_doc.full_name,
        "mobile": user_doc.mobile_no,
        "email": user_doc.name,
        "profile_image": user_doc.user_image
    })


@frappe.whitelist(allow_guest=True)
def customer_addresses(**kwargs):
    """
    Returns all addresses of logged-in customer
    grouped by address_type
    Primary address is matched using Customer.customer_primary_address
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required")
    
    is_error, payload = sanitize_request(
        kwargs,
        optional = ["customer"]
    )
    if is_error:
        return error(payload, 422)
    
    customer = payload.get("customer")
    customer = customer if customer is not None else user.get("customer_data", {}).get("name")
    

    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    # ------------------------------------------------
    # Fetch customer's primary address
    # ------------------------------------------------
    return get_customer_addresses(customer)


@frappe.whitelist(allow_guest=True)
def get_address(**kwargs):
    """
    Return a particular address of a customer
    (not necessarily default)
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
    
    is_error, payload = sanitize_request(
        kwargs,
        required=["address_id"],
        optional = ["customer"]
    )
    if is_error:
        return error(payload, 422)

    address_id = payload.get("address_id")
    customer = payload.get("customer")
    # Resolve customer
    customer = customer if customer else user.get("customer_data", {}).get("name")

    # -----------------------------
    # Validate customer access
    # -----------------------------
    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    # -----------------------------
    # Ownership check (VERY IMPORTANT)
    # -----------------------------
    exists = frappe.db.exists(
        "Dynamic Link",
        {
            "link_doctype": "Customer",
            "link_name": customer,
            "parent": address_id
        }
    )

    if not exists:
        return error("Address not found", 404)

    # -----------------------------
    # Fetch address
    # -----------------------------
    address = frappe.db.get_value(
        "Address",
        address_id,
        [
            "name",
            "address_title",
            "address_type",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "country",
            "pincode",
            "phone",
            "email_id"
        ],
        as_dict=True
    )

    if not address:
        return error("Address not found", 404)

    return success("Address fetched", address)


@frappe.whitelist(allow_guest=True)
def create_customer_shipping_address(**kwargs):

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    # ------------------------------------------------
    # 🔴 Instead of single customer → get all account customers
    # ------------------------------------------------
    customers = get_account_customers(user)

    if not customers:
        return error("No customer linked to this account", 403)

    # -----------------------------
    # Required Fields
    # -----------------------------  

    is_error, payload = sanitize_request(
        kwargs,
        required = [
        "address_title",
        "address_line1",
        "city",
        "state",
        "pincode",
        "country"
        ],
        optional=["address_line2", "phone", "email_id"]
    )
    if is_error:
        return error(payload, 422)
    
    address_title = payload.get("address_title")
    address_line1 = payload.get("address_line1")
    address_line2 = payload.get("address_line2")
    city = payload.get("city")
    state = payload.get("state")
    pincode = payload.get("pincode")
    country = payload.get("country")
    phone = payload.get("phone")
    email_id = payload.get("email_id")


    try:
        # -----------------------------
        # Create Address
        # -----------------------------
        address = frappe.get_doc({
            "doctype": "Address",
            "address_title": address_title,
            "address_type": "Shipping",
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "state": state,
            "pincode": pincode,
            "country": country,
            "phone": phone,
            "email_id": email_id,
        })

        # ------------------------------------------------
        # 🔴 Link address to ALL customers (FAMILY ADDRESS)
        # ------------------------------------------------
        for cust in customers:
            address.append("links", {
                "link_doctype": "Customer",
                "link_name": cust
            })

        address.insert(ignore_permissions=True)

        # ------------------------------------------------
        # 🔴 Set as default for ALL customers
        # ------------------------------------------------
        
        ok = set_family_default_address(customers, address.name)
        if not ok:
            frappe.log_error(
                f"Failed default switch for {customers}",
                "Family Address Default Sync Failed"
            )

        frappe.db.commit()

        return success("Address created and synced", {
            "address_id": address.name,
            "linked_customers": customers,
            "is_default": 1
        })

    except Exception:
        frappe.log_error(
            title="Create Family Address Error",
            message=frappe.get_traceback()
        )
        return error("Unable to create address", 500)



@frappe.whitelist(allow_guest=True)
def update_customer_shipping_address(**kwargs):
    """
    Updates an existing Shipping Address for logged-in customer
    Works exactly like create_customer_shipping_address
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    customers = get_account_customers(user)

    if not customers:
        return error("No customer linked to this account", 403)

    # ---------------------------------
    # Required Fields
    # ---------------------------------
    is_error, payload = sanitize_request(
        kwargs,
        required = [
        "address_id",
        "address_title",
        "address_line1",
        "city",
        "state",
        "pincode",
        "country"
        ],
        optional=["address_line2", "phone", "email_id"]
    )
    if is_error:
        return error(payload, 422)

    address_id = payload.get("address_id")
    address_title = payload.get("address_title")
    address_line1 = payload.get("address_line1")
    address_line2 = payload.get("address_line2")
    city = payload.get("city")
    state = payload.get("state")
    pincode = payload.get("pincode")
    country = payload.get("country")
    phone = payload.get("phone")
    email_id = payload.get("email_id")


    # Check if address belongs to ANY of account customers
    owned = frappe.db.exists(
        "Dynamic Link",
        {
            "parent": address_id,
            "link_doctype": "Customer",
            "link_name": ["in", customers]
        }
    )

    if not owned:
        return error("Address does not belong to this account", 403)

    try:
        # ---------------------------------
        # Load Address
        # ---------------------------------
        address = frappe.get_doc("Address", address_id)

        # ---------------------------------
        # Update fields (SAME AS CREATE)
        # ---------------------------------
        address.address_title = address_title
        address.address_type = "Shipping"
        address.address_line1 = address_line1
        address.address_line2 = address_line2
        address.city = city
        address.state = state
        address.pincode = pincode
        address.country = country
        address.phone = phone
        address.email_id = email_id
        address.save(ignore_permissions=True)       

        frappe.db.commit()

        return success("Shipping address updated successfully", {
            "address_id": address.name
        })

    except Exception:
        frappe.log_error(
            title="Update Shipping Address Error",
            message=frappe.get_traceback()
        )
        return error("Failed to update address", 500)   




@frappe.whitelist(allow_guest=True)
def switch_address(**kwargs):

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    is_error, payload = sanitize_request(
        kwargs,
        required = ["address_id"]
    )
    if is_error:
        return error(payload, 422)
    
    address_id = payload.get("address_id")
    customers = get_account_customers(user)

    if not customers:
        return error("No customers linked to this account", 403)

    # ------------------------------------------------
    # Step 1: Verify address belongs to this account
    # ------------------------------------------------
    owned = frappe.db.exists(
        "Dynamic Link",
        {
            "parent": address_id,
            "link_doctype": "Customer",
            "link_name": ["in", customers]
        }
    )

    if not owned:
        return error("Address does not belong to this account", 403)

    # ------------------------------------------------
    # Step 2: Link address to missing customers
    # ------------------------------------------------
    for cust in customers:

        already_linked = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": address_id,
                "link_doctype": "Customer",
                "link_name": cust
            }
        )

        if not already_linked:
            address_doc = frappe.get_doc("Address", address_id)
            address_doc.append("links", {
                "link_doctype": "Customer",
                "link_name": cust
            })
            address_doc.save(ignore_permissions=True)

    # ------------------------------------------------
    # Step 3: Apply default to ALL customers
    # ------------------------------------------------
    success_flag = set_family_default_address(customers, address_id)

    if not success_flag:
        return error("Unable to update address", 400)

    frappe.db.commit()

    return success("Default address updated.", {
        "address_id": address_id,
        "customers": customers
    })



def set_family_default_address(customers, address_id):

    try:
        # ------------------------------------
        # Reset address flags for ALL customers
        # ------------------------------------
        frappe.db.sql(
            """
            UPDATE `tabAddress`
            SET
                is_shipping_address = 0,
                is_primary_address = 0
            WHERE name IN (
                SELECT parent
                FROM `tabDynamic Link`
                WHERE link_doctype = 'Customer'
                AND link_name IN %s
            )
            """,
            (tuple(customers),)
        )

        # ------------------------------------
        # Enable selected address
        # ------------------------------------
        frappe.db.set_value("Address", address_id, {
            "is_shipping_address": 1,
            "is_primary_address": 1
        })

        # ------------------------------------
        # Update ALL customers primary pointer
        # ------------------------------------
        for cust in customers:
            frappe.db.set_value(
                "Customer",
                cust,
                "customer_primary_address",
                address_id
            )

        return True

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Family Switch Address Failed")
        return False
    

@frappe.whitelist(allow_guest=True)
def sync_family_primary_address():

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    customers = get_account_customers(user)

    if not customers:
        return error("No customers linked to this account", 403)

    # ------------------------------------------------
    # Step 1: Find first customer having primary address
    # ------------------------------------------------
    primary_address = None
    source_customer = None

    for cust in customers:
        addr = frappe.db.get_value(
            "Customer",
            cust,
            "customer_primary_address"
        )
        if addr:
            primary_address = addr
            source_customer = cust
            break

    if not primary_address:
        return success("No primary address found to sync", None)

    # ------------------------------------------------
    # Step 2: Attach address to all customers
    # ------------------------------------------------
    address_doc = frappe.get_doc("Address", primary_address)

    for cust in customers:

        linked = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": primary_address,
                "link_doctype": "Customer",
                "link_name": cust
            }
        )

        if not linked:
            address_doc.append("links", {
                "link_doctype": "Customer",
                "link_name": cust
            })

    address_doc.save(ignore_permissions=True)

    # ------------------------------------------------
    # Step 3: Apply as family default
    # ------------------------------------------------
    ok = set_family_default_address(customers, primary_address)

    if not ok:
        return error("Failed to sync family address", 500)

    frappe.db.commit()

    return success("Family address synchronized", {
        "address_id": primary_address,
        "source_customer": source_customer,
        "synced_customers": customers
    })


@frappe.whitelist(allow_guest=True)
def delete_customer_address(**kwargs):
    """
    Hybrid delete:
    - Hard delete if address is unused
    - Soft delete if address is referenced
    - Block delete if selected shipping / billing / primary
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    is_error, payload = sanitize_request(kwargs,required = ["address_id"],optional=["customer"])
    if is_error:
        return error(payload, 422)

    customer = payload.get("customer") or user.get("customer_data", {}).get("name")
    address_id = payload.get("address_id")

    # -----------------------------
    # Validate customer access
    # -----------------------------
    msg = validate_customer_access(user, customer)
    if msg:
        return error(msg, 403)

    # -----------------------------
    # Validate address ownership
    # -----------------------------
    if not frappe.db.exists(
        "Dynamic Link",
        {
            "link_doctype": "Customer",
            "link_name": customer,
            "parent": address_id
        }
    ):
        return error("Address does not belong to customer", 403)

    # -----------------------------
    # Fetch address flags
    # -----------------------------
    address = frappe.get_value(
        "Address",
        address_id,
        [
            "is_shipping_address",
            "is_primary_address",
            "disabled"
        ],
        as_dict=True
    )

    if not address:
        return error("Address not found", 404)

    # -----------------------------
    # Block deletion rules
    # -----------------------------
    if address.is_shipping_address:
        return error("Cannot delete selected shipping address", 422)

    if address.is_primary_address:
        return error("Cannot delete selected billing address", 422)

    customer_primary_address = frappe.get_value(
        "Customer",
        customer,
        "customer_primary_address"
    )

    if customer_primary_address == address_id:
        return error("Cannot delete customer's primary address", 422)

    # -----------------------------
    # Check if address is used
    # -----------------------------
    used_in_docs = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Address",
            "parent": address_id,
            "link_doctype": ["!=", "Customer"]
        },
        limit=1
    )

    try:
        # -----------------------------
        # Decide delete strategy
        # -----------------------------
        if used_in_docs:
            # SOFT DELETE
            if address.disabled:
                return error("Address already deleted", 422)

            frappe.db.set_value("Address", address_id, "disabled", 1)
            action = "soft_deleted"
        else:
            # HARD DELETE
            frappe.delete_doc(
                "Address",
                address_id,
                force=1,
                ignore_permissions=True
            )
            action = "hard_deleted"

        frappe.db.commit()

        return success("Address deleted successfully", {
            "customer": customer,
            "address_id": address_id,
            "mode": action
        })

    except Exception:
        frappe.log_error(
            title="Hybrid Delete Address Error",
            message=frappe.get_traceback()
        )
        return error("Failed to delete address", 500)




@frappe.whitelist(allow_guest=True)
def categories():
    roots = ["Uniform", "Books Bundle","General Merchandise"]

    data = []

    for root in roots:
        tree = get_group_tree_as_array(root)
        if tree:
            data.append(tree)

    return success("success", data)


@frappe.whitelist(allow_guest=True)
def get_notification_settings():

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    profile = frappe.get_value(
        "Website Customer",
        {"user": user.name},
        [
            "whatsapp_message",
            "sms_alert",
            "email_alert",
            "order_updates"
        ],
        as_dict=True
    )

    if not profile:
        return error("Website customer profile not found")

    return success("Success", profile)




@frappe.whitelist(allow_guest=True)
def update_notification_settings(**kwargs):

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    # Fetch Website Customer profile
    profile_name = frappe.get_value(
        "Website Customer",
        {"user": user.name},
        "name"
    )

    if not profile_name:
        return error("Website customer profile not found")

    allowed_fields = [
        "whatsapp_message",
        "sms_alert",
        "email_alert",
        "order_updates"
    ]

    update_data = {}

    for field in allowed_fields:
        if field in kwargs:
            update_data[field] = int(bool(kwargs.get(field)))

    if not update_data:
        return error("No valid fields to update", 422)

    try:
        frappe.db.set_value(
            "Website Customer",
            profile_name,
            update_data
        )

        frappe.db.commit()

        updated = frappe.get_value(
            "Website Customer",
            profile_name,
            allowed_fields,
            as_dict=True
        )

        return success("Notification settings updated successfully", updated) 

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Update Notification Settings Error")
        return error("Failed to update settings", 500)



def resolve_bom_tree(item_code):
    """
    Recursively resolve BOM tree for an item
    respecting custom_display and custom_bom_display
    and omit empty 'items' keys
    """

    bom_name = frappe.get_value(
        "BOM",
        {
            "item": item_code,
            "is_active": 1,
            "docstatus": ["!=", 2],
            "custom_display": 1
        },
        "name"
    )

    if not bom_name:
        return []

    bom_doc = frappe.get_doc("BOM", bom_name)

    # BOM visible but children should not be exposed
    if not bom_doc.custom_bom_display:
        return []

    bom_items = frappe.get_all(
        "BOM Item",
        filters={"parent": bom_name},
        fields=["item_code", "qty"],
        order_by="idx asc"
    )

    children = []

    for bi in bom_items:
        node = {
            "item_code": bi.item_code,
            "qty": bi.qty
        }

        # recursion
        sub_items = resolve_bom_tree(bi.item_code)

        # inject ONLY if exists
        if sub_items:
            node["items"] = sub_items

        children.append(node)

    return children


def get_item_filters(
    *,
    user,
    allowed_categories = None,
    apply_grade=True,
    exclude_item_codes=None
):
    """
    # 1. Base filters (disabled, is_sales_item, variant_of)
    # 2. School filter         ← existing
    # 3. Grade filter          ← existing (sets filters["name"])
    # 4. Gender filter         ← ADD HERE (intersects with grade result)
    # 5. Exclusions            ← existing
    """

    filters = {
        "disabled": 0,
        "is_sales_item": 1,
        "variant_of": ["is", "not set"],
    }

    if allowed_categories:
        filters["item_group"] = ["in", allowed_categories]

    # -------------------------
    # School filter
    # -------------------------
    if not user.has_student:
        filters["custom_school_name"] = ["in", [None, ""]]
    else:
        filters["custom_school_name"] = [
            "in",
            [None, "", user.student_data.get("school_name")]
        ]

    # -------------------------
    # Grade filter (child table)
    # -------------------------
    if apply_grade and user.has_student:

        # 1️⃣ Get all grade-restricted items (VERY FAST because small table)
        restricted_items = set(
            frappe.get_all(
                "Uniform Grade",
                pluck="parent",
                distinct=True
            )
        )

        # 2️⃣ Always include unrestricted items
        if restricted_items:
            unrestricted_items = set(
                frappe.get_all(
                    "Item",
                    filters={
                        "name": ["not in", list(restricted_items)],
                        "disabled": 0,
                        "is_sales_item": 1,
                        "variant_of": ["is", "not set"],
                    },
                    pluck="name"
                )
            )
        else:
            unrestricted_items = set()

        allowed_items = set(unrestricted_items)

        # 3️⃣ If student + grade → add matching uniforms
        if user.has_student:
            grade = user.student_data.get("grade")

            if grade:
                grade_items = set(
                    frappe.get_all(
                        "Uniform Grade",
                        filters={"grade": grade},
                        pluck="parent"
                    )
                )

                allowed_items |= grade_items

        # 4️⃣ Inject into filters
        if allowed_items:
            filters["name"] = ["in", list(allowed_items)]
        else:
            filters["name"] = ["in", ["__no_items__"]]

    # -------------------------
    # Gender filter
    # -------------------------
    if user.has_student:
        gender = user.student_data.get("gender")
        if gender:
            filters["custom_gender"] = ["in", [None, "", gender]]
        
    # -------------------------
    # Exclusions
    # -------------------------
    if exclude_item_codes:
        filters["item_code"] = ["not in", exclude_item_codes]

    return filters



@frappe.whitelist(allow_guest=True)
def all_items(page=1, page_size=10, categories=None):
    
    page = int(_clean_value(page) or 1)
    page_size = min(int(_clean_value(page_size) or 10), 25)
    offset = (page - 1) * page_size
    
    sanitized_categories = []

    if categories:
        for cat in categories:
            clv = _clean_value(cat)
            if clv:
                sanitized_categories.append(clv)

    user = BaseAPI().user
    if not user or not user.get("customer_data",{}).get("name"):
        return error("Login required", 401)
    
    if is_new_student(user):
        return get_magic_boxes_for_student(user, page, page_size)

    # 1. Fetch main items
    allowed_categories = resolve_catalog_groups(sanitized_categories)

    item_filters = get_item_filters(
        user=user,
        allowed_categories=allowed_categories,
        apply_grade=True
    )

    total = frappe.db.count("Item", filters=item_filters)
    total_pages = math.ceil(total / page_size)

    items = frappe.get_all(
        "Item",
        filters=item_filters,
        fields=["name","item_name","item_code","item_group","image","has_variants","custom_gender"],
        order_by="modified desc",
        start=offset,
        page_length=page_size
    )

    # 2. Resolve source item (variant(parent template) or self)
    price_source_map = {}
    for item in items:
        if item.has_variants:
            price_source_map[item.item_code] = frappe.get_value(
                "Item",
                {"variant_of": item.item_code, "disabled": 0},
                "item_code",
                order_by="creation asc"
            )
        else:
            price_source_map[item.item_code] = item.item_code


    source_codes = list(filter(None, price_source_map.values()))

    # 3. Prices
    price_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", source_codes],
                "price_list": "Standard Selling"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    mrp_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", source_codes],
                "price_list": "MRP"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    # 4. Attributes
    attrs = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", source_codes]},
        fields=["parent", "attribute", "attribute_value"]
    )

    attr_map = {}
    for a in attrs:
        attr_map.setdefault(a.parent, {})[
            a.attribute.lower()
        ] = a.attribute_value

    # 5. Build response
    data = []
    for item in items:
        source_code = price_source_map.get(item.item_code)

        price = price_map.get(source_code, 0)
        mrp = mrp_map.get(source_code, 0)
        image = resolve_image_url(item.image)

        data.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "item_group": item.item_group,
            "custom_uniform_grade" : "jk",
            "image": image,
            "type": "book" if is_book_item(item.item_code) else "product",
            "price": price,
            "mrp": mrp,
            "attributes": attr_map.get(source_code, {})
        })
    
    return success("Success", {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "data": data
    })



@frappe.whitelist(allow_guest=True)
def products_you_may_like(page=1, page_size=10, item_code=None):
    """
    Products You May Like API
    - Uses cart items first
    - Falls back to ordered items
    - Optional reference item_code
    """

    page = int(_clean_value(page) or 1)
    page_size = min(int(_clean_value(page_size) or 10), 25)
    offset = (page - 1) * page_size
    item_code = _clean_value(item_code) or None

    api = BaseAPI()
    user = api.user
    if not user or not user.get("customer_data",{}).get("name"):
        return error("Login required", 401)

    # New students → only magic box
    if is_new_student(user):
        return get_magic_boxes_for_student(user, page, page_size)

    # ------------------------------------------------
    # 1️⃣ Collect interest groups
    # ------------------------------------------------
    collected_groups = set()
    exclude_items = set()
    order_codes = []

    # -------------------------
    # A. Cart based groups
    # -------------------------
    cart_items = frappe.get_all(
        "Website Cart",
        filters={"website_user": user.name},
        fields=["item_code"]
    )

    cart_codes = [c.item_code for c in cart_items]
    exclude_items.update(cart_codes)


    if cart_codes:
        groups = frappe.get_all(
            "Item",
            filters={"item_code": ["in", cart_codes]},
            pluck="item_group"
        )
        collected_groups.update(groups)

    # -------------------------
    # B. Order history fallback
    # -------------------------

    if not collected_groups:
        ordered_items = frappe.get_all(
            "Sales Order Item",
            filters={"docstatus": 1},
            fields=["item_code"],
            distinct=True,
            limit=20
        )

        order_codes = [o.item_code for o in ordered_items]
        exclude_items.update(order_codes)

        if order_codes:
            groups = frappe.get_all(
                "Item",
                filters={"item_code": ["in", order_codes]},
                pluck="item_group"
            )
            collected_groups.update(groups)

    # -------------------------
    # C. Reference product
    # -------------------------

    if item_code:
        ref_group = frappe.get_value("Item", item_code, "item_group")
        if ref_group:
            collected_groups.add(ref_group)
        exclude_items.add(item_code)

    # -------------------------
    # D. Resolve catalog groups
    # -------------------------
    allowed_categories = resolve_catalog_groups(list(collected_groups))
    
    if not allowed_categories:
        allowed_categories = resolve_catalog_groups()

    if not allowed_categories:
        return success("Success", {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
            "data": []
        })

    # ------------------------------------------------
    # 2️⃣ Build item filters
    # ------------------------------------------------
    item_filters = get_item_filters(
        user=user,
        allowed_categories=allowed_categories,
        apply_grade=True,
        exclude_item_codes=list(exclude_items)
    )

    # ------------------------------------------------
    # 3️⃣ Total count (REAL pagination)
    # ------------------------------------------------
    total = frappe.db.count("Item", filters=item_filters)
    total_pages = math.ceil(total / page_size) if total else 0

    # ------------------------------------------------
    # 4️⃣ Fetch only page records
    # ------------------------------------------------
    items = frappe.get_all(
        "Item",
        filters=item_filters,
        fields=[
            "name", "item_name", "item_code",
            "item_group", "image",
            "has_variants", "modified", "custom_gender"
        ],
        order_by="creation desc",
        start=offset,
        page_length=page_size
    )

    if not items:
        return success("Success", {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "data": []
        })

    # ------------------------------------------------
    # 5️⃣ Resolve price source
    # ------------------------------------------------
    price_source_map = {}
    for item in items:
        if item.has_variants:
            price_source_map[item.item_code] = frappe.get_value(
                "Item",
                {"variant_of": item.item_code, "disabled": 0},
                "item_code",
                order_by="creation asc"
            )
        else:
            price_source_map[item.item_code] = item.item_code

    source_codes = list(filter(None, price_source_map.values()))

    # ------------------------------------------------
    # 6️⃣ Prices
    # ------------------------------------------------
    price_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", source_codes],
                "price_list": "Standard Selling"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    mrp_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", source_codes],
                "price_list": "MRP"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    # ------------------------------------------------
    # 7️⃣ Attributes
    # ------------------------------------------------
    attrs = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", source_codes]},
        fields=["parent", "attribute", "attribute_value"]
    )

    attr_map = {}
    for a in attrs:
        attr_map.setdefault(a.parent, {})[
            a.attribute.lower()
        ] = a.attribute_value

    # ------------------------------------------------
    # 8️⃣ Build response
    # ------------------------------------------------
    data = []

    for item in items:
        source_code = price_source_map.get(item.item_code)

        price = price_map.get(source_code, 0)
        mrp = mrp_map.get(source_code, 0)
        discount = round(((mrp - price) / mrp) * 100, 2) if mrp and price else 0

        image = resolve_image_url(item.image)

        data.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "item_group": item.item_group,
            "image": image,
            "type": "book" if is_book_item(item.item_code) else "product",
            "price": price,
            "mrp": mrp,
            "discount_percentage": discount,
            "attributes": attr_map.get(source_code, {}),
            "modified": item.modified
        })

    # ------------------------------------------------
    # 9️⃣ Final response (NO Python slicing!)
    # ------------------------------------------------
    return success("Success", {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "data": data
    })




def get_magic_boxes_for_student(user, page=1, page_size=10):

    page = int(page)
    page_size = min(int(page_size),50)
    offset = (page - 1) * page_size

    student = user.get("student_data")
    if not student:
        return success("Success", {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
            "data": []
        })
    
    customer = user.get("customer_data").name or None
    if not customer:
        return success("Success", {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
            "data": []
        })


    school = student.get("school_name")
    grade = student.get("grade")

    # --------------------------------------------------
    # 1️⃣ Base filters (Magic Box only)
    # --------------------------------------------------
    filters = {
        "item_group": "Magic Box",
        "disabled": 0,
        "is_sales_item": 1,
        "variant_of": ["is", "not set"]
    }

    # --------------------------------------------------
    # 🚫 Already Purchased Magic Boxes
    # --------------------------------------------------

    purchased_items = set(
        frappe.get_all(
            "Sales Order Item",
            filters={
                "docstatus": 1,
                "item_code": ["in",
                    frappe.get_all(
                        "Item",
                        filters={"item_group": "Magic Box"},
                        pluck="name"
                    )
                ],
                "parent": ["in",
                    frappe.get_all(
                        "Sales Order",
                        filters={
                            "customer": customer,
                            "docstatus": 1
                        },
                        pluck="name"
                    )
                ]
            },
            pluck="item_code",
            distinct=True
        )
    )
    # --------------------------------------------------
    # 2️⃣ School filter (same as catalog)
    # --------------------------------------------------
    filters["custom_school_name"] = [
        "in",
        [None, "", school]
    ]

    # --------------------------------------------------
    # 3️⃣ Grade restriction using Uniform Grade
    # --------------------------------------------------

    # All grade restricted magic boxes
    restricted_items = set(
        frappe.get_all(
            "Uniform Grade",
            filters={
                "parent": ["in",
                    frappe.get_all(
                        "Item",
                        filters={"item_group": "Magic Box"},
                        pluck="name"
                    )
                ]
            },
            pluck="parent",
            distinct=True
        )
    )

    # Unrestricted magic boxes
    unrestricted_items = set(
        frappe.get_all(
            "Item",
            filters={
                "item_group": "Magic Box",
                "name": ["not in", list(restricted_items)],
                "disabled": 0,
                "is_sales_item": 1,
                "variant_of": ["is", "not set"]
            },
            pluck="name"
        )
    )

    allowed_items = set(unrestricted_items)

    # Add grade matched magic boxes
    if grade:
        grade_items = set(
            frappe.get_all(
                "Uniform Grade",
                filters={"grade": grade},
                pluck="parent"
            )
        )
        allowed_items |= grade_items
    
    # remove already purchased
    allowed_items -= purchased_items

    # Inject into query
    if allowed_items:
        filters["name"] = ["in", list(allowed_items)]
    else:
        filters["name"] = ["in", ["__no_items__"]]

    st_gender = user.student_data.get("gender",None)
    if st_gender:
        filters["custom_gender"] = ["in", [None, "", st_gender]]

    # --------------------------------------------------
    # 4️⃣ Fetch items
    # --------------------------------------------------
    items = frappe.get_all(
        "Item",
        filters=filters,
        fields=[
            "item_code",
            "item_name",
            "item_group",
            "image",
            "custom_school_name",
            "modified",
            "custom_gender"
        ],
        order_by="modified desc",
        start=offset,
        page_length=page_size
    )


    if not items:
        return success("Success", {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
            "data": []
        })

    # --------------------------------------------
    # 2️⃣ Fetch Prices
    # --------------------------------------------
    item_codes = [i.item_code for i in items]

    price_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", item_codes],
                "price_list": "Standard Selling"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    mrp_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", item_codes],
                "price_list": "MRP"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    # --------------------------------------------
    # 3️⃣ Build response
    # --------------------------------------------
    data = []

    for item in items:
        price = price_map.get(item.item_code, 0)
        mrp = mrp_map.get(item.item_code, 0)
        discount = round(((mrp - price) / mrp) * 100, 2) if mrp and price else 0

        data.append({
            "type": "magicbox",
            "item_code": item.item_code,
            "item_name": item.item_name,
            "item_group": item.item_group,
            "image": resolve_image_url(item.image),
            "school": item.custom_school_name,
            "grade": item.custom_grade,
            "price": price,
            "mrp": mrp,
            "discount_percentage": discount
        })

    # --------------------------------------------
    # 4️⃣ Total Count
    # --------------------------------------------
    total = frappe.db.count("Item", filters)
    total_pages = math.ceil(total / page_size)

    return success("Success", {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "data": data
    })



@frappe.whitelist(allow_guest=True)
def get_item_by_id(
    item_code
):

    user = BaseAPI().user
    if not user or not user.get("customer_data",{}).get("name"):
        return error("Login required", 401)
    
    item_code = _clean_value(item_code)
    if not item_code:
        return error("item_code is required", 422)
    

    allowed_categories = resolve_catalog_groups()
    
    item_filters = get_item_filters(
        user=user,
        allowed_categories=allowed_categories,
        apply_grade=True
    )

    # Lock to requested item
    item_filters["item_code"] = item_code
    
    # 1. Fetch main item (template / book root)
    item = frappe.get_value(
        "Item",
        item_filters,
        ["*" ],
        as_dict=True
    )

    if not item:
        return success("Success", None,403)

    # Get Customer Primary Shipping address
    shipping_address = get_customer_shipping_address(user.customer_data.name)
    shipping_address = (
            {
                "id": shipping_address.get("id"),
                "pincode": shipping_address.get("pincode")
            }
            if shipping_address
            else None
    )

    # Get Customer Primary Shipping address
    size_chart = None
    if item.item_group:
        size_chart = get_full_url(item.custom_size_chart)

    res = {}
    # 2. Decide behavior
    if is_book_item(item.item_code):
        res =  get_book_detail(user,
            item
        )
    else:
        res =  get_product_selector_tree(item.get("item_code"),user=user)
        
    if not res:
        return success("not found",{})

    res["size_chart"] = size_chart
    res["shippin_address"] = shipping_address
    
    return success("success",res)


@frappe.whitelist(allow_guest=True)
def get_order_items_detail(**kwargs):
    """
    Returns product selector tree for items in a Sales Order.
    No catalog/grade/school filters — items are already purchased.
    Only validation: item_codes must belong to the given sales_order.
    """

    api = BaseAPI()
    user = api.user

    if not user or not user.get("customer_data", {}).get("name"):
        return error("Login required", 401)

    is_error, payload = sanitize_request(
        kwargs,
        required=["sales_order"]
    )
    if is_error:
        return error(payload, 422)

    sales_order = payload.get("sales_order")
    raw_codes   = kwargs.get("item_codes")

    if not isinstance(raw_codes, list):
        return error("item_codes must be a list", 422)

    item_codes = list({
        _clean_value(c)
        for c in raw_codes
        if _clean_value(c)
    })

    if not item_codes:
        return error("No valid item_codes provided", 422)

    # ------------------------------------------------
    # Step 1: Validate Sales Order belongs to customer
    # ------------------------------------------------
    customer = user.customer_data.name

    so_customer = frappe.db.get_value("Sales Order", sales_order, "customer")

    if not so_customer:
        return error("Sales Order not found", 404)

    if so_customer != customer:
        return error("Sales Order does not belong to this account", 403)

    # ------------------------------------------------
    # Step 2: Validate item_codes exist in that Sales Order
    # ------------------------------------------------
    so_item_codes = set(
        frappe.get_all(
            "Sale Order Sub Items",
            filters={"parent": sales_order},
            pluck="item_code"
        )
    )


    invalid_codes = [c for c in item_codes if c not in so_item_codes]

    if invalid_codes:
        return error(
            f"Item(s) not found in Sales Order: {', '.join(invalid_codes)}",
            422
        )

    # ------------------------------------------------
    # Step 3: Resolve variant → root template
    # ------------------------------------------------
    meta_rows = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "variant_of", "disabled"]
    )

    resolve_map = {}   # input_code → root_code
    not_found   = []

    for row in meta_rows:
        if row.disabled:
            not_found.append(row.name)
            continue
        resolve_map[row.name] = row.variant_of if row.variant_of else row.name

    for c in item_codes:
        if c not in {r.name for r in meta_rows}:
            not_found.append(c)

    # ------------------------------------------------
    # Step 4: Build product selector tree per root
    # ------------------------------------------------
    results   = {}   # input_code → detail
    processed = {}   # root_code  → detail  (dedup sibling variants)

    for input_code in item_codes:

        root_code = resolve_map.get(input_code)

        if not root_code:
            continue

        if root_code in processed:
            results[input_code] = processed[root_code]
            continue

        detail = get_product_selector_tree(root_code, user=user)

        if not detail:
            not_found.append(input_code)
            continue

        processed[root_code] = detail
        results[input_code]  = detail

    # ------------------------------------------------
    # Step 5: Return
    # ------------------------------------------------
    return success("Items fetched", {
        "count"    : len(results),
        ""
        "data"     : results,          # { "Uniform1": {...}, "Uniform218XA": {...} }
        "not_found": list(set(not_found))
    })



def get_book_detail(user,item):

    mrp = frappe.get_value(
        "Item Price",
        {"item_code": item.item_code, "price_list": "MRP"},
        "price_list_rate"
    ) or 0

    price = frappe.get_value(
        "Item Price",
        {"item_code": item.item_code, "price_list": "Standard Selling"},
        "price_list_rate"
    ) or 0


    has_wishlist = False
    
    if user:
        has_wishlist = frappe.db.exists(
            "Website Wishlist",
            {
                "website_user": user.name,
                "item_code": item.item_code
            }
        )

    item_group_ancestors = []
    
    if item.item_group:
        item_group_ancestors = get_item_group_ancestors(item.item_group)

    
    return success("Success", {
        "type": "book",
        "item_code": item.item_code,
        "item_name": item.item_name,
        "item_group_ancestors": item_group_ancestors,
        "image": resolve_image_url(item.image),
        "description": item.description,
        "school": item.custom_school_name,
        "grade": item.custom_grade,
        "mrp":mrp,
        "price": price,
        "has_wishlist": 1 if has_wishlist else 0,
        "items": resolve_bom_tree(item.item_code)
    })



@frappe.whitelist(allow_guest=True)
def magic_box_by_id(item_code):

    api = BaseAPI()
    user = api.user
    
    if not user or not user.get("customer_data",{}).get("name"):
        return error("Login required", 401)
    
    item_code = _clean_value(item_code)
    if not item_code:
        return error("item_code is required", 422)

    # ------------------------------------------------
    # 1️⃣ Fetch item
    # ------------------------------------------------
    item = frappe.get_value(
        "Item",
        item_code,
        ["name", "item_name", "item_group", "image", "description",
         "custom_school_name", "custom_grade", "disabled"],
        as_dict=True
    )

    if not item:
        return error("Magic Box not found", 404)

    # Must belong to Magic Box group
    if item.item_group != "Magic Box":
        return error("Invalid Magic Box", 422)

    if item.disabled:
        return error("Magic Box disabled", 403)

    # ------------------------------------------------
    # 2️⃣ Find default active BOM
    # ------------------------------------------------
    bom = frappe.get_value(
        "BOM",
        {
            "item": item_code,
            "item": item_code,
            "is_active": 1,
            "docstatus": ["!=", 2]
        },
        "name"
    )

    if not bom:
        return error("Magic Box is not configured (BOM missing)", 422)

    # ------------------------------------------------
    # 3️⃣ Fetch first-layer children
    # ------------------------------------------------
    bom_items = frappe.get_all(
        "BOM Item",
        filters={"parent": bom},
        fields=["item_code", "qty"]
    )



    if not bom_items:
        return success("Success", {
            "type": "magicbox",
            "item_code": item_code,
            "items": []
        })

    # ------------------------------------------------
    # 4️⃣ Resolve children
    # ------------------------------------------------
    children = []

    for row in bom_items:

        child_code = row.item_code
        qty = row.qty

        # Get minimal item info
        child_meta = frappe.get_value(
            "Item",
            child_code,
            ["item_group", "has_variants", "disabled","custom_size_chart"],
            as_dict=True
        )

        # Skip invalid
        if not child_meta or child_meta.disabled:
            continue

        # ❌ prevent nested magic box
        if child_meta.item_group == "Magic Box":
            frappe.log_error(
                f"Nested Magic Box detected: {child_code}",
                "Magic Box Configuration Error"
            )
            continue

        # Get Customer Primary Shipping address
        size_chart = get_full_url(child_meta.custom_size_chart)

        # ----------------------------
        # BOOK
        # ----------------------------
        if child_meta.item_group == "Books Bundle":
            book_item = frappe.get_doc("Item", child_code)

            book_res = get_book_detail(
                user,
                book_item
            )

            if book_res and book_res.get("data"):
                data = book_res["data"]
                data["qty"] = qty
                data["type"] = "book"
                data["size_chart"] = size_chart
                children.append(data)

        # ----------------------------
        # PRODUCT (simple OR template)
        # ----------------------------
        else:

            product_res = get_product_selector_tree(child_code, user=user)

            if not product_res:
                continue

            product_res["qty"] = qty
            product_res["type"] = "product"
            product_res["size_chart"] = size_chart

            children.append(product_res)
    # ------------------------------------------------
    # 5️⃣ Final Response
    # ------------------------------------------------
    pricese =  get_product_prices(item_code)

    item_group_ancestors = []
    
    if item.item_group:
        item_group_ancestors = get_item_group_ancestors(item.item_group)

    return success("Success", {
        "type": "magicbox",
        "item_code": item_code,
        "item_name": item.item_name,
        "item_group_ancestors": item_group_ancestors,
        "image": resolve_image_url(item.image),
        "description": item.description,
        "school": item.custom_school_name,
        "grade": item.custom_grade,
        "price":pricese.get("Standard Selling"),
        "mrp":pricese.get("MRP"),
        "items": children
    })


# @frappe.whitelist(allow_guest=True)
def get_product_selector_tree(item_code, user=None):

    # ------------------------------------------------
    # 1️⃣ Fetch Item
    # --------------------------------------------------
    item = frappe.get_value(
        "Item",
        item_code,
        ["name", "item_name","item_group", "has_variants", "disabled", "image", "description"],
        as_dict=True
    )

    if not item or item.disabled:
        return None

    prices = get_product_prices(item_code)

    item_group_ancestors = []
    
    if item.item_group:
        item_group_ancestors = get_item_group_ancestors(item.item_group)
        

    # --------------------------------------------------
    # 2️⃣ SIMPLE PRODUCT (no variants)
    # --------------------------------------------------
    wishlist_items = set(is_in_wishlist(user, [item_code]))

    if not item.has_variants:
        return {
            "type": "product",
            "item_code": item_code,
            "item_name": item.item_name,
            "has_wishlist": item_code in wishlist_items,
            "item_group": item.item_group,
            "item_group_ancestors": item_group_ancestors,
            "image": resolve_image_url(item.image),
            "description": item.description,
            "mrp": prices.get("MRP",0),
            "price": prices.get("Standard Selling",0),
            "options": []
        }

    # --------------------------------------------------
    # 3️⃣ GET ATTRIBUTE ORDER FROM TEMPLATE
    # (Preserve exact ERPNext attribute names)
    # --------------------------------------------------
    item_doc = frappe.get_doc("Item", item_code)

    attribute_order = []
    attribute_labels = {}

    for d in item_doc.attributes:
        key = d.attribute.lower()
        attribute_order.append(key)
        attribute_labels[key] = d.attribute  # original name

    if not attribute_order:
        return None


    # --------------------------------------------------
    # 4️⃣ FETCH VARIANTS
    # --------------------------------------------------
    variants = frappe.get_all(
        "Item",
        filters={
            "variant_of": item_code,
            "disabled": 0
        },
        fields=["item_code", "item_group", "item_name", "image"]
    )

    if not variants:
        return None

    variant_codes = [v.item_code for v in variants]

    wishlist_items = set()

    if user:
        wishlist_items = set(is_in_wishlist(user, variant_codes))

    # --------------------------------------------------
    # 5️⃣ VARIANT ATTRIBUTE VALUES
    # --------------------------------------------------
    attr_rows = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": ["in", variant_codes]},
        fields=["parent", "attribute", "attribute_value"]
    )


    # SKU -> {fabric:A, size:S, colour:Red}
    variant_attr_map = {}
    for r in attr_rows:
        variant_attr_map.setdefault(r.parent, {})[
            r.attribute.lower()
        ] = r.attribute_value

    # ensure all attributes exist (avoid broken branches)
    for v in variants:
        attrs = variant_attr_map.setdefault(v.item_code, {})
        for attr in attribute_order:
            attrs.setdefault(attr, None)

    # --------------------------------------------------
    # 6️⃣ PRICE MAP
    # --------------------------------------------------
    price_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", variant_codes],
                "price_list": "Standard Selling"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    mrp_map = {
        p.item_code: p.price_list_rate
        for p in frappe.get_all(
            "Item Price",
            filters={
                "item_code": ["in", variant_codes],
                "price_list": "MRP"
            },
            fields=["item_code", "price_list_rate"]
        )
    }

    # --------------------------------------------------
    # 7️⃣ STOCK
    # --------------------------------------------------
    bins = frappe.get_all(
        "Bin",
        filters={"item_code": ["in", variant_codes]},
        fields=["item_code", "actual_qty"]
    )

    stock_map = {b.item_code: b.actual_qty for b in bins}

    # --------------------------------------------------
    # 8️⃣ TREE BUILDER
    # --------------------------------------------------
    def insert_variant(tree, attrs, level, sku_data):

        if level >= len(attribute_order):
            return

        attr_key = attribute_order[level]
        value = attrs.get(attr_key)

        if not value:
            return

        # find existing node
        node = next((x for x in tree if x["value"] == value), None)

        if not node:
            node = {
                "attribute": attr_key,                   # machine key
                "label": attribute_labels[attr_key],     # display label
                "value": value
            }
            tree.append(node)

        # LAST LEVEL → attach SKU
        if level == len(attribute_order) - 1:

            node.update(sku_data)

            if "children" in node:
                node.pop("children", None)

        else:
            if "children" not in node:
                node["children"] = []

            insert_variant(node["children"], attrs, level + 1, sku_data)

    # --------------------------------------------------
    # 9️⃣ BUILD TREE
    # --------------------------------------------------
    options_tree = []

    for v in variants:

        attrs = variant_attr_map.get(v.item_code, {})

        sku_data = {
            "item_code": v.item_code,
            "item_name": v.item_name,
            "item_group": v.item_group,
            "image": resolve_image_url(v.image),
            "price": price_map.get(v.item_code, 0),
            "mrp": mrp_map.get(v.item_code, 0),
            "in_stock": stock_map.get(v.item_code, 0) > 0,
            "has_wishlist": v.item_code in wishlist_items
        }

        insert_variant(options_tree, attrs, 0, sku_data)

    # --------------------------------------------------
    # 🔟 CLEAN EMPTY CHILDREN
    # --------------------------------------------------
    def clean_tree(nodes):
        for n in nodes:
            if "children" in n:
                clean_tree(n["children"])
                if not n["children"]:
                    n.pop("children")

    clean_tree(options_tree)

    # --------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------
    return {
        "type": "product",
        "item_code": item_code,
        "item_group": item.item_group,
        "item_group_ancestors": item_group_ancestors,
        "item_name": item.item_name,
        "image": resolve_image_url(item.image),
        "description": item.description,
        "options": options_tree
    }