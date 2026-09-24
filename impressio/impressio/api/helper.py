import frappe
import random
import re
import html
from frappe.utils import today, add_to_date, now_datetime, get_datetime
from frappe.utils import get_url
import requests
from urllib.parse import quote_plus
from impressio.impressio.api.sms_service import SMSService
from functools import lru_cache
from frappe.utils.html_utils import clean_html

BLOCK_GENERAL_USER = True
BLOCK_GENERAL_USER_MESSAGE = "This mobile number is not registered with us. Kindly enter the registered mobile number or contact customer care (9059990804) /school and get your number updated. Team Invent're."

SKIP_ITEM_GROUPS = ["Finished Goods","Raw Material","Books","Magic Box","POS ITEM","POS ITEMS","Sub Bundle"]
MAX_OTP_ATTEMPTS = 10
MAX_OTP_SEND_PER_DAY = 10
OTP_RESEND_INTERVAL_MIN = 1  # 1 minute cooldown
ENVIRONMENT = frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()

# pre-resolve frontend checkout URL to avoid repeated config lookups
FRONTEND_CHECKOUT_URL = frappe.conf.get(
            "FRONTEND_CHECKOUT_URL",
            "https://invweb.mdqapps.tech/checkout/order"
        )

# final human-text allow list
ALLOWED_TEXT = re.compile(r"[^A-Za-z0-9 @#&()$-.,:'/_+\-\n]")

def force_plain_text(value: str) -> str:
    """
    Convert any input into harmless human-readable text.
    Removes all HTML meaning permanently.
    """

    # decode ALL entities repeatedly
    for _ in range(3):
        value = html.unescape(value)

    # remove any remaining tags
    value = re.sub(r'<[^>]+>', '', value)

    # remove entity leftovers like &gt &lt &#62
    value = re.sub(r'&[#A-Za-z0-9]+;', '', value)

    # allow only safe business characters
    value = ALLOWED_TEXT.sub('', value)

    return value

def _clean_value(value):

    if value is None:
        return None

    # ---------- TYPE AWARE HANDLING ----------
    # true integers/floats should not go through HTML sanitizer
    if isinstance(value, (int, float)):
        return value

    value = str(value)

    # remove control chars
    value = re.sub(r'[\x00-\x1f\x7f]', '', value)

    # normalize spaces
    value = " ".join(value.strip().split())

    previous = None
    rounds = 0

    while value != previous and rounds < 5:
        previous = value
        value = html.unescape(value)
        value = clean_html(value)
        value = re.sub(r'<[^>]*>', '', value)
        rounds += 1

    # remove javascript protocols & handlers
    value = re.sub(r'(?i)javascript\s*:', '', value)
    value = re.sub(r'(?i)on\w+\s*=', '', value)

    # normalize again
    value = " ".join(value.split())

    # force into plain text mode (CRITICAL STEP)
    value = force_plain_text(value)

    # limit length
    value = value[:300]

    return value.strip() if value else None

def sanitize_request(kwargs: dict, required=None, optional=None):
    """
    required  -> string or list
    optional  -> string or list
    returns sanitized dict
    throws frappe.ValidationError if required missing
    """

    sanitized = {}

    # allow single string
    if isinstance(required, str):
        required = [required]

    if isinstance(optional, str):
        optional = [optional]

    required = required or []
    optional = optional or []

    try:

        # ---------------- REQUIRED ----------------
        for key in required:

            value = kwargs.get(key)

            if value is None or str(value).strip() == "":
                label = key.replace("_", " ").title()
                raise ValueError(f"{label} should not be empty")

            sanitized[key] = _clean_value(value)

        # ---------------- OPTIONAL ----------------
        for key in optional:

            if key in kwargs and kwargs.get(key) is not None:
                sanitized[key] = _clean_value(kwargs.get(key))
            else:
                sanitized[key] = None
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Request Sanitization Failed")
        return True, str(e) if str(e) else "Invalid input"

    return False, sanitized


def sanitize_array(data):
    """
    Recursively sanitize any array/dict structure.
    Preserves structure, cleans values.
    """

    # ---------------- LIST ----------------
    if isinstance(data, list):
        return [sanitize_array(item) for item in data]

    # ---------------- DICT ----------------
    elif isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned[key] = sanitize_array(value)
        return cleaned

    # ---------------- PRIMITIVES ----------------
    else:
        return _clean_value(data)



def force_guest_user():
    """
    Force execution context to Guest.
    Does NOT restore previous user.
    Use ONLY for read-only website APIs.
    """
    frappe.set_user("Guest")


def success(message, data=None, status=200):
    frappe.local.response["http_status_code"] = status
    return {
        "message": message,
        "data": data
    }

def error(message, status=400):
    frappe.local.response["http_status_code"] = status
    return {
        "message": message,
        "data": None
    }


def validate_fields(data, fields):
    for f in fields:
        if not data.get(f):
            return f"{f.replace('_',' ').title()} is required"
    return None



def random_numbers(digits=6):
    # Calculate the range based on number of digits
    # For 6 digits: start is 10^5 (100,000) and end is (10^6) - 1 (999,999)
    start = 10**(digits - 1)
    end = (10**digits) - 1 
    
    otp = random.randint(start, end)
    return str(otp) if ENVIRONMENT == "PRODUCTION" else "123456"





def can_send_otp(email=None, mobile=None, purpose="Login"):

    filters = {
        "purpose": purpose,
        "creation": [">=", today()]
    }

    if email:
        filters["email"] = email
    if mobile:
        filters["mobile"] = mobile

    sent_today = frappe.db.count("OTP Log", filters)

    if sent_today >= MAX_OTP_SEND_PER_DAY:
        return False, f"OTP send limit exceeded. Try again tomorrow."

    # Check resend cooldown
    last_otp = frappe.get_all("OTP Log",
        filters=filters,
        order_by="creation desc",
        limit=1
    )

    if last_otp:
        last_time = frappe.get_value("OTP Log", last_otp[0].name, "creation")
        if last_time and add_to_date(last_time, minutes=OTP_RESEND_INTERVAL_MIN) > now_datetime():
            return False, "Please wait before requesting another OTP."

    return True, None

def resolve_otp_sms_purpose(purpose: str) -> str:
    """
    Maps OTP purpose to SMS template intent
    (case-insensitive, whitespace-safe)
    """

    if not purpose:
        return None

    p = purpose.strip().upper()

    if p.startswith("STUDENT_UPDATE_"):
        return "STUDENT_UPDATE"   # intentional mapping

    return p




def create_otp(email=None, mobile=None, purpose="Login", digits=6, extra_data=None, user=None):

    allowed, msg = can_send_otp(email=email, mobile=mobile, purpose=purpose)
    if not allowed:
        return False, msg

    otp = random_numbers(digits)

    frappe.get_doc({
        "doctype":"OTP Log",
        "email":email,
        "mobile":mobile,
        "otp":otp,
        "purpose":purpose,
        "extra_data":frappe.as_json(extra_data) if extra_data else None,
        "user":user,
        "expiry":add_to_date(now_datetime(), minutes=10),
        "is_used":0,
        "attempts":0
    }).insert(ignore_permissions=True)

    # if email:
    #     send_otp_email(email, otp, purpose)
    
    if ENVIRONMENT != "PRODUCTION":
        return True, "OTP sent successfully"

    # Send OTP
    if mobile:
        sms_purpose = resolve_otp_sms_purpose(purpose)

        if sms_purpose == "LOGIN":
            success, res = SMSService.send_login_otp(
                mobile=mobile,
                otp=otp
            )

        elif sms_purpose == "REGISTER_MOBILE":
            success, res = SMSService.send_register_otp(
                mobile=mobile,
                otp=str(otp)
            )

        elif sms_purpose == "FORGOT_PASSWORD":
            success, res = SMSService.send_forgot_password_otp(
                mobile=mobile,
                otp=str(otp)
            )

        elif sms_purpose == "STUDENT_UPDATE":
            success, res = SMSService.send_student_update_otp(               
                mobile=mobile,
                otp=otp
            )  

        elif sms_purpose == "ZERO_ORDER":
            success, res = SMSService.send_zero_order_otp(
                mobile=mobile,
                otp=str(otp)
            )          

        else:
            return False, "Invalid OTP purpose"

        if not success:
            return False, res

    return True, "OTP sent successfully"



def send_otp_email(email, otp, purpose):
    try:
        frappe.sendmail(recipients=[email], subject=f"{purpose} OTP", message=f"Your OTP is {otp}")
    except Exception:
        frappe.log_error("Email not configured", "OTP Email Failed")

def send_otp_sms(mobile, otp):
    var1 = "Initial Registration"   # 🔥 MUST match Template Label exactly
    var2 = otp
    var3 = 10

    message = (
        f"Your OTP for {var1} is {var2}. "
        f"Please do not share this OTP with anyone. "
        f"It is valid for {var3} minutes. - INVENTRE EDUSERVICES PVT. LTD"
    )

    return SMSService.send(
        mobile=f"91{mobile}",
        message=message,
        template_id="380462",
        dlt_content_id="1107173978479110904",
        purpose="OTP"
    )





def check_otp(email=None, mobile=None, otp=None, purpose="Login"):

    log = frappe.get_all("OTP Log",
        filters={
            "email": email,
            "mobile": mobile,
            "purpose": purpose,
            "is_used": 0
        },
        order_by="creation desc",
        limit=1
    )

    if not log:
        return False

    otp_doc = frappe.get_doc("OTP Log", log[0].name)

    if otp_doc.expiry < now_datetime():
        frappe.delete_doc("OTP Log", otp_doc.name, force=True,ignore_permissions=True)
        frappe.db.commit()
        return False

    if str(otp_doc.otp) != str(otp):
        otp_doc.attempts = (otp_doc.attempts or 0) + 1

        if otp_doc.attempts >= MAX_OTP_ATTEMPTS:
            frappe.delete_doc("OTP Log", otp_doc.name, force=True, ignore_permissions=True)
        else:
            otp_doc.save(ignore_permissions=True)

        frappe.db.commit()
        return False

    return True



def consume_otp(email=None, mobile=None, purpose="Login"):
    try:
        frappe.db.delete("OTP Log", {
            "email": email,
            "mobile": mobile,
            "purpose": purpose
        })
    except Exception:
        return  # best effort, no big deal if it fails


def unwrap_response(res):
    # Convert JSON string to dict
    if isinstance(res, str):
        res = frappe.parse_json(res)

    if not isinstance(res, dict):
        return {
            "message": "",
            "data": None
        }

    # Case 1: Frappe RPC wrapper
    # { "message": { "message": "...", "data": ... } }
    if isinstance(res.get("message"), dict):
        return res["message"]

    # Case 2: Direct success()/error() return
    # { "message": "...", "data": ... }
    if "message" in res and "data" in res:
        return res

    # Fallback
    return {
        "message": "",
        "data": None
    }


def sync_guardian_students_after_register(mobile: str):
    """
    After a parent registers and proves mobile ownership,
    automatically activate (verify) all eligible students linked to the guardian
    and create customers for them.

    Safe to run multiple times (idempotent).
    """

    if not mobile:
        return

    # ---------------------------------------------------
    # 1️⃣ Find Guardian
    # ---------------------------------------------------
    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": mobile},
        "name"
    )


    if not guardian:
        # No guardian linked to this mobile → nothing to do
        return

    # ---------------------------------------------------
    # 2️⃣ Fetch ELIGIBLE students
    # ---------------------------------------------------
    # Conditions:
    # - linked to guardian
    # - enabled
    # - school active
    # - not already verified OR customer missing
    # ---------------------------------------------------
    students = frappe.db.sql("""
        SELECT s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE
            sg.guardian = %s
            AND IFNULL(s.enabled, 0) = 1
            AND sch.status = 'Active'
            AND (
                IFNULL(s.is_verified, 0) = 0
                OR IFNULL(s.customer, '') = ''
            )
    """, guardian, as_dict=True)

    if not students:
        return
    

    # Import locally to avoid circular import
    from impressio.impressio.api.student import create_customer_from_student

    # ---------------------------------------------------
    # 3️⃣ Activate each student
    # ---------------------------------------------------
    for row in students:
        try:
            student_doc = frappe.get_doc("Students", row.name)

            # Already completed admission
            if student_doc.is_verified and student_doc.customer:
                continue

            # Create customer if missing
            if not student_doc.customer:
                create_customer_from_student(student_doc)

            # Mark verified
            if not student_doc.is_verified:
                student_doc.is_verified = 1
                student_doc.flags.ignore_permissions = True
                student_doc.save(ignore_permissions=True)

            frappe.db.commit()

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Guardian Student Auto Sync Failed for {row.name}"
            )
            frappe.db.rollback()
            continue


def resolve_school_grade(grade, school):
    """
    Resolve school-specific grade name from student + school data
    """
    try:
        # if not student:
        #     return ""
    
        # grade = student.get("grade")
        # school = student.get("school")

        if not grade or not school:
            return grade
        
        school = frappe.get_doc("School",school)
        for row in school.get("grades_details", []):
            if row.get("grade") == grade:
                return row.get("school_given_grade_name") or grade

        return grade
    except Exception:
        return ""


def validate_customer_access(user, customer):
    if not customer:
        return "Customer is required"

    if not user.linked_customers:
        return "No linked customers found"

    if customer not in user.linked_customers:
        return "Unauthorized customer access"

    return None


def get_item_group_size_chart_url(item_group):
    """
    Returns full URL of custom_size_chart
    from the given Item Group only, or None.
    """

    if not item_group:
        return None

    size_chart = frappe.db.get_value(
        "Item Group",
        item_group,
        "custom_size_chart"
    )

    if not size_chart:
        return None

    if size_chart.startswith("/"):
        return f"{frappe.utils.get_url()}{size_chart}"

    return size_chart



def get_full_url(path):
    """
    Returns full URL of given image path or None.
    """

    # handle null / empty
    if not path:
        return None

    # ERPNext stored file
    if path.startswith("/"):
        return f"{get_url()}{path}"

    # already full URL (CDN/S3)
    return path


def get_item_group_flatten(groups):
    """
    Accepts a group name OR list of group names
    Returns unique list of groups including all descendants
    """
    if not groups:
        return []

    # Normalize input to list
    if isinstance(groups, str):
        groups = [groups]

    result = set()

    for group in groups:
        parent = frappe.get_value(
            "Item Group",
            group,
            ["lft", "rgt"],
            as_dict=True
        )

        if not parent:
            continue

        children = frappe.get_all(
            "Item Group",
            filters={
                "lft": [">=", parent.lft],
                "rgt": ["<=", parent.rgt]
            },
            pluck="name"
        )

        result.update(children)

    return list(result)


def get_group_tree_as_array(root_group):
    parent = frappe.get_value(
        "Item Group",
        root_group,
        ["lft", "rgt", "parent_item_group"],
        as_dict=True
    )

    if not parent:
        return None

    rows = frappe.get_all(
        "Item Group",
        filters={
            "lft": [">=", parent.lft],
            "rgt": ["<=", parent.rgt]
        },
        fields=["name", "parent_item_group"]
    )

    return build_tree_array(rows, root_group)


def build_tree_array(groups, root_name):
    node_map = {}

    # Initialize nodes
    for g in groups:
        node_map[g["name"]] = {
            "name": g["name"],
            "parent": g["parent_item_group"],
            "children": []
        }

    root_node = None

    # Attach children
    for g in groups:
        node = node_map[g["name"]]
        parent = g["parent_item_group"]

        if parent in node_map:
            node_map[parent]["children"].append(node)
        elif g["name"] == root_name:
            root_node = node

    return root_node



def get_item_group_ancestors(item_group):
    """
    Returns full parent hierarchy path of an Item Group
    Example:
    T-Shirt -> Casuals -> Uniform -> All Item Groups
    (returned as root → child order)
    """

    if not item_group:
        return []

    path = []
    current = item_group

    # climb upward until root
    while current:
        path.append(current)

        parent = frappe.db.get_value(
            "Item Group",
            current,
            "parent_item_group"
        )

        # stop at system root
        if not parent or parent == current:
            break

        current = parent

    # reverse so it becomes root → leaf
    path.reverse()

    return path

def get_item_group_trees(root_groups):
    """
    Takes array of root Item Groups and returns tree-view data
    """
    result = {}

    for root in root_groups:
        parent = frappe.get_value(
            "Item Group",
            root,
            ["lft", "rgt"],
            as_dict=True
        )

        if not parent:
            continue

        rows = frappe.get_all(
            "Item Group",
            filters={
                "lft": [">=", parent.lft],
                "rgt": ["<=", parent.rgt]
            },
            fields=["name", "parent_item_group"]
        )

        result[root] = build_group_tree(rows, root)

    return result


def build_group_tree(groups, root_name=None):
    """
    Convert flat Item Group rows into tree structure
    """
    group_map = {}
    tree = {}

    # Initialize nodes
    for g in groups:
        g["children"] = {}
        group_map[g["name"]] = g

    # Build hierarchy
    for g in groups:
        parent = g.get("parent_item_group")

        if parent and parent in group_map:
            group_map[parent]["children"][g["name"]] = g
        else:
            # Only attach the requested root at top level
            if not root_name or g["name"] == root_name:
                tree[g["name"]] = g

    return tree



def resolve_catalog_groups(frontend_groups=None):
    """
    Returns final Item Groups usable for catalog queries.
    Guarantees blocked trees never appear.
    """

    # 1. Expand blocked trees (absolute rule)
    blocked = set(get_item_group_flatten(SKIP_ITEM_GROUPS))

    # 2. Resolve requested groups
    if frontend_groups:
        requested = set(get_item_group_flatten(frontend_groups))
    else:
        # No filter → everything
        requested = set(frappe.get_all("Item Group", pluck="name"))

    # 3. HARD subtract blocked trees
    final_groups = list(requested - blocked)

    return final_groups


from functools import lru_cache

# @lru_cache(maxsize=1)
def get_books_groups():
    return set(get_item_group_flatten("Books Bundle"))


def is_book_item(item_code):

    # 1️⃣ must have active BOM
    has_bom = frappe.db.exists(
        "BOM",
        {
            "item": item_code,
            "is_active": 1,            
            "docstatus": ["!=", 2]
        }
    )

    if not has_bom:
        return False
    
    # 2️⃣ get item group
    item_group = frappe.db.get_value("Item", item_code, "item_group")
    if not item_group:
        return False
    # 3️⃣ check if group belongs to Books Bundle tree
    return item_group in get_books_groups()


def get_full_image_url(image):
    if not image:
        return None

    if image.startswith("http"):
        return image

    return frappe.utils.get_url(image)


def get_product_prices(item_code):
    price_lists =  frappe.get_all(
                    "Item Price",
                    filters={
                        "item_code":  item_code
                    },
                    fields=["price_list", "price_list_rate"]
                )

    price_lists = {pl['price_list']:pl['price_list_rate'] for pl in price_lists}

    return price_lists


def extract_pin_code(address):
    if not address:
        return None

    match = re.search(r"PIN\s*Code:\s*(\d+)", address)
    return match.group(1) if match else None



def validate_payment_mode(payment_mode, user):
    """
    Validates Mode of Payment and resolves provider + gateway
    using provider PRIORITY.

    Behaviour:
    - Invalid / not allowed mode -> THROW
    - COD -> return mode, gateway=None
    - ONLINE + provider+gateway exists -> return mode + gateway
    - ONLINE + no provider/gateway -> return mode, gateway=None
    """

    # ------------------------------------------------
    # 1️⃣ Fetch Mode of Payment
    # ------------------------------------------------
    mode = frappe.get_value(
        "Mode of Payment",
        {
            "name": payment_mode,
            "enabled": 1,
            "custom_enabled_for_website": 1
        },
        [
            "name",
            "custom_payment_flow",
            "custom_payment_category",
            "custom_allowed_for_student",
            "custom_allowed_for_direct_customer"
        ],
        as_dict=True
    )

    if not mode:
        frappe.throw("Invalid or disabled payment mode")

    # ------------------------------------------------
    # 2️⃣ User type validation
    # ------------------------------------------------
    is_student_flow = bool(user.has_student)

    if is_student_flow and not mode.custom_allowed_for_student:
        frappe.throw("Payment mode not allowed for student")

    if not is_student_flow and not mode.custom_allowed_for_direct_customer:
        frappe.throw("Payment mode not allowed for customer")

    payment_flow = mode.custom_payment_flow

    # ------------------------------------------------
    # 3️⃣ COD → no gateway needed
    # ------------------------------------------------
    if payment_flow == "COD":
        return {
            "mode": mode,
            "gateway": None
        }

    # ------------------------------------------------
    # 4️⃣ ONLINE → resolve provider by PRIORITY
    # ------------------------------------------------
    if payment_flow == "ONLINE":

        # 🔑 Fetch active providers ordered by priority
        providers = frappe.get_all(
            "Payment Provider",
            filters={"is_active": 1},
            fields=["name", "priority","provider_code"],
            order_by="priority asc"
        )

        for provider in providers:

            # Check provider supports this payment mode
            supports_mode = frappe.db.exists(
                "Payment Provider Supported Payment Mode",
                {
                    "parent": provider.name,
                    "mode_of_payment": mode.name,
                    "is_active": 1
                }
            )

            if not supports_mode:
                continue

            # Fetch active gateway config for environment
            gateway = frappe.get_value(
                "Payment Gateway Configuration",
                {
                    "gateway_provider": provider.name,
                    "environment": ENVIRONMENT,
                    "is_active": 1
                },
                ["*" ],
                as_dict=True
            )

            

            if gateway:
                return {
                    "mode": mode,
                    "gateway": gateway,
                    "provider": provider.provider_code  # optional but useful
                }

        # ONLINE but no provider/gateway found
        return {
            "mode": mode,
            "gateway": None
        }

    frappe.throw("Unsupported payment flow")

    
def get_payment_provider_details(provider_name=None, provider_code=None, server_side = False):
    """
    Helper (NOT API)
    Returns payment provider + active gateway configuration
    for current PAYMENT_ENV

    Raises:
        frappe.ValidationError
    """

    if not provider_code and not provider_name:
        return None


    # ------------------------------------------------
    # 1️⃣ Fetch Payment Provider
    # ------------------------------------------------
    provider_filters = {"is_active": 1}

    if provider_code:
        provider_filters["provider_code"] = provider_code.upper()

    if provider_name:
        provider_filters["name"] = provider_name

    provider = frappe.get_all(
        "Payment Provider",
        filters=provider_filters,
        fields=["*" ],
        limit=1
    )

    if not provider:
        return None

    provider = provider[0]

    # ------------------------------------------------
    # 2️⃣ Load active gateway configuration (ONLINE only)
    # ------------------------------------------------
    gateway_config = None

    if provider.payment_flow == "ONLINE":
        gateway = frappe.get_all(
            "Payment Gateway Configuration",
            filters={
                "gateway_provider": provider.name,
                "environment": f"SERVER_{ENVIRONMENT}" if server_side else ENVIRONMENT,
                "is_active": 1
            },
            fields=["*"],
            limit=1
        )

        if not gateway:
            return None

        gateway_config = gateway[0]

    # ------------------------------------------------
    # 3️⃣ Supported payment modes
    # ------------------------------------------------
    supported_modes = frappe.get_all(
        "Payment Provider Supported Payment Mode",
        filters={
            "parent": provider.name,
            "is_active": 1
        },
        pluck="mode_of_payment"
    )

    # ------------------------------------------------
    # 4️⃣ Return plain python data
    # ------------------------------------------------
    return {
        "provider":provider,
        "gateway": gateway_config,
        "supported_modes": supported_modes,
        "environment": ENVIRONMENT
    }




def get_customer_addresses(customer):
    """
    Returns all addresses of logged-in customer
    grouped by address_type
    Primary address is matched using Customer.customer_primary_address
    """ 

    if not customer:
        return error("Customer not found")

    # ------------------------------------------------
    # Fetch customer's primary address
    # ------------------------------------------------
    customer_primary_address = frappe.get_value(
        "Customer",
        customer,
        "customer_primary_address"
    )

    # ------------------------------------------------
    # Fetch Address linked via Dynamic Link
    # ------------------------------------------------
    addresses = frappe.get_all(
        "Address",
        filters=[
            ["Dynamic Link", "link_doctype", "=", "Customer"],
            ["Dynamic Link", "link_name", "=", customer],
            ["disabled", "=", 0]
        ],
        fields=[
            "name",
            "address_title",
            "address_type",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "phone",
            "email_id",
            "is_shipping_address",
            "is_primary_address",
            "disabled"
        ],
        order_by="address_type asc"
    )

    grouped = {}

    for addr in addresses:
        addr_type = addr.address_type or "Other"

        grouped.setdefault(addr_type, []).append({
            "id": addr.name,
            "title": addr.address_title,
            "line1": addr.address_line1,
            "line2": addr.address_line2,
            "city": addr.city,
            "state": addr.state,
            "pincode": addr.pincode,
            "country": addr.country,
            "phone" : addr.phone,
            "email_id" : addr.email_id,

            # ✅ Correct primary logic
            "is_primary": 1 if addr.name == customer_primary_address else 0,
            "is_shipping": addr.is_shipping_address,
            "is_billing": addr.is_primary_address,
            "disabled": addr.disabled
        })

    return {
        "customer": customer,
        "primary_address": customer_primary_address,
        "addresses": grouped
    }

def get_customer_shipping_address(customer):
    """
    Returns customer's PRIMARY address only.
    (ERPNext source of truth: Customer.customer_primary_address)
    """

    if not customer:
        return None

    # ------------------------------------
    # Step 1: Get primary address pointer
    # ------------------------------------
    address_id = frappe.db.get_value(
        "Customer",
        customer,
        "customer_primary_address"
    )

    if not address_id:
        return None

    # ------------------------------------
    # Step 2: Fetch address document
    # ------------------------------------
    addr = frappe.db.get_value(
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
            "pincode",
            "country",
            "phone",
            "email_id",
            "disabled"
        ],
        as_dict=True
    )

    if not addr or addr.disabled:
        return None

    # ------------------------------------
    # Step 3: Return formatted response
    # ------------------------------------
    return {
        "id": addr.name,
        "title": addr.address_title,
        "line1": addr.address_line1,
        "line2": addr.address_line2,
        "city": addr.city,
        "state": addr.state,
        "pincode": addr.pincode,
        "country": addr.country,
        "phone": addr.phone,
        "email_id": addr.email_id,
        "is_shipping": 1,
        "is_billing": 1
    }



def is_in_wishlist(user, item_codes):
    """
    Returns a set of item_codes present in wishlist for the user
    """
    if not user or not item_codes:
        return set()

    rows = frappe.get_all(
        "Website Wishlist",
        filters={
            "website_user": user.name,
            "item_code": ["in", item_codes]
        },
        pluck="item_code"
    )

    return set(rows)



def get_valid_coupon(coupon_code):
    coupon = frappe.get_value(
        "Website Cart Coupon",
        {
            "coupon_code": coupon_code,
            "is_active": 1
        },
        [
            "name",
            "school",
            "student",
            "discount_type",
            "discount",
            "maximum_discount_amount",
            "can_use_multiple_times",
            "one_time_use",
            "start_datetime",
            "end_datetime"
        ],
        as_dict=True
    )

    if not coupon:
        return None, "Invalid coupon"

    now = get_datetime()

    if coupon.start_datetime and now < coupon.start_datetime:
        return None, "Coupon not started"

    if coupon.end_datetime and now > coupon.end_datetime:
        return None, "Coupon expired"

    return coupon, None




def validate_and_calculate_coupon(coupon, customer, amount):
    """
    Returns:
        (is_valid, discount_amount, message)
    """

    # ------------------------------------------------
    # 0️⃣ Global one-time coupon (system wide)
    # ------------------------------------------------
    if coupon.one_time_use:

        globally_used = frappe.db.exists(
            "Sales Order",
            {
                "custom_cart_coupon_code": coupon.name,
                "docstatus": ["<", 2],  # draft or submitted
                "custom_payment_status": ["in", ["INITIATED","PENDING","PROCESSING", "SUCCESS"]]
            }
        )

        if globally_used:
            return False, 0, "Coupon already used"

    # ------------------------------------------------
    # 1️⃣ Per-customer single-use restriction
    # ------------------------------------------------
    if not coupon.can_use_multiple_times and not coupon.one_time_use:

        already_used = frappe.db.exists(
            "Sales Order",
            {
                "customer": customer,
                "custom_cart_coupon_code": coupon.name,
                "docstatus": ["<", 2],  # draft or submitted
                "custom_payment_status": ["in", ["INITIATED","PENDING","PROCESSING", "SUCCESS"]]
            }
        )

        if already_used:
            return False, 0, "Coupon already used by this customer"


    # ------------------------------------------------
    # 2️⃣ Resolve student
    # ------------------------------------------------
    student = frappe.get_value(
        "Students",
        {"customer": customer},
        ["name", "school_code"],
        as_dict=True
    )

    # ------------------------------------------------
    # 3️⃣ Common coupon (no school/student restriction)
    # ------------------------------------------------
    if coupon.school or coupon.student:

        if not student:
            return False, 0, "Coupon not applicable"

        school_name = None
        if student.school_code:
            school_name = frappe.get_value(
                "School",
                {"school_code": student.school_code},
                "name"
            )

        # Student coupon
        if coupon.student and coupon.student != student.name:
            return False, 0, "Coupon not applicable for this student"

        # School coupon
        if coupon.school and coupon.school != school_name:
            return False, 0, "Coupon not applicable for this school"

    # ------------------------------------------------
    # 4️⃣ Calculate discount
    # ------------------------------------------------
    if coupon.discount_type == "Fixed":
        discount = coupon.discount

    elif coupon.discount_type == "Percentage":
        discount = amount * (coupon.discount / 100)

    else:
        return False, 0, "Invalid coupon configuration"

    # ------------------------------------------------
    # 5️⃣ Apply max discount cap
    # ------------------------------------------------
    if coupon.maximum_discount_amount and coupon.maximum_discount_amount > 0:
        discount = min(discount, coupon.maximum_discount_amount)

    # Never exceed order total
    discount = min(discount, amount)

    return True, discount, None




# ======================= SALE ORDER =======================

def map_pinelabs_status(status: str):
    status = (status or "").upper()

    if status in ("PROCESSED", "CAPTURED"):
        return "SUCCESS"

    if status in ("FAILED", "DECLINED", "ERROR"):
        return "FAILED"

    if status in ("CANCELLED", "ABANDONED"):
        return "CANCELLED"

    return "PENDING"

def map_ccavenue_status(gateway_status: str) -> str:
    """
    Map CC Avenue order status to ERPNext payment state.
    Accounting-safe mapping (chargeback & reversal aware)
    """

    status = (gateway_status or "").strip().upper()

    # ------------------------------------------------
    # 1️⃣ FINANCIAL SUCCESS (money captured)
    # ------------------------------------------------
    SUCCESS_STATES = {
        "SUCCESS",
        "SUCCESSFUL",
        "SHIPPED",            # Auto-confirm merchants
    }

    # ------------------------------------------------
    # 2️⃣ DEFINITE FAILURE (money never received)
    # ------------------------------------------------
    FAILURE_STATES = {
        "FAILURE",
        "FAILED",
        "UNSUCCESSFUL",
        "ABORTED",
        "CANCELLED",
        "INVALID",
        "FRAUD",
        "AUTO-REVERSED",      # Bank rolled back
        "AUTO REVERSED",
        "TIMEDOUT",
        "TIMEOUT",
    }

    # ------------------------------------------------
    # 3️⃣ REVERSALS / POST-PAYMENT (CRITICAL)
    # ------------------------------------------------
    REVERSAL_STATES = {
        "CHARGEBACK",
        "REFUNDED",
    }

    # ------------------------------------------------
    # 4️⃣ INTERMEDIATE (bank processing)
    # ------------------------------------------------
    PENDING_STATES = {
        "INITIATED",
        "AWAITED",
        "AWAIT",
        "PENDING",
        "VERIFYING",
    }

    # ---------------- Decision ----------------

    if status in SUCCESS_STATES:
        return "SUCCESS"

    if status in FAILURE_STATES:
        return "FAILED"

    if status in REVERSAL_STATES:
        # IMPORTANT:
        # Do NOT auto-cancel order here.
        # Requires finance workflow.
        return "REVERSAL"

    if status in PENDING_STATES:
        return "PENDING"

    # ------------------------------------------------
    # Unknown future state (VERY IMPORTANT)
    # ------------------------------------------------
    frappe.log_error(
        title="CCAVENUE UNKNOWN STATUS",
        message=f"Received unmapped CC Avenue status: {status}"
    )

    # safest assumption: bank undecided
    return "PENDING"

def get_billing_address_from_sale_order(sales_order_name):
    """
    Returns a PAYMENT-SAFE billing address dict
    with guaranteed values for CC Avenue
    """

    if not sales_order_name:
        frappe.throw("Sales Order name is required")

    so = frappe.get_doc("Sales Order", sales_order_name)

    address = None
    if so.customer_address:
        address = frappe.get_doc("Address", so.customer_address)

    # -----------------------------
    # SAFE FALLBACKS
    # -----------------------------
    billing_name = (
        address.address_title if address else None
    ) or so.customer_name or "Customer"

    billing_address = ", ".join(filter(None, [
        getattr(address, "address_line1", None),
        getattr(address, "address_line2", None),
    ])) or "NA"

    billing_city = getattr(address, "city", None) or "NA"
    billing_state = getattr(address, "state", None) or "NA"
    billing_zip = getattr(address, "pincode", None) or "000000"
    billing_country = getattr(address, "country", None) or "India"

    billing_email = (
        getattr(address, "email_id", None)
        or so.contact_email
        or ""
    )

    billing_tel = (
        getattr(address, "phone", None)
        or so.contact_mobile
        or ""
    )

    # -----------------------------
    # RETURN PAYMENT-READY OBJECT
    # -----------------------------
    return {
        "billing_name": billing_name,
        "billing_address": billing_address,
        "billing_city": billing_city,
        "billing_state": billing_state,
        "billing_zip": billing_zip,
        "billing_country": billing_country,
        "billing_email": billing_email if billing_email else "",
        "billing_tel":  billing_tel if billing_tel else "",
    }



def get_raw_item_description(item_code):
    if not item_code:
        return ""

    item_doc = frappe.get_doc("Item", item_code)
    if not item_doc or not item_doc.description:
        return ""

    return item_doc.get_formatted("description")


def resolve_image_url(image: str | None) -> str | None:
    if not image:
        return None

    image = image.strip()

    # Already a full URL (http, https)
    if image.startswith(("http://", "https://")):
        return image

    # Frappe-managed file paths
    # /files/..., /private/files/..., files/...
    if image.startswith(("/", "files/", "private/files/")):
        return get_url(image)

    # Fallback: return as-is (for unknown external sources)
    return image


def is_new_student(user):
    try:
        student = user.get("student_data")
        if student and student.is_new_student:
            return True
        return False
    except Exception as e:
        return False


def get_customer_name_from_mobile(mobile: str) -> str:
    """
    Resolve the best possible human name from a phone number.
    Priority:
    1) User
    2) Contact
    3) Fallback None
    """

    if not mobile:
        return None

    mobile = mobile.strip().replace("+91", "").replace(" ", "")

    # ---------------- USER ----------------
    user = frappe.db.get_value(
        "User",
        {"mobile_no": mobile, "enabled": 1},
        ["full_name"],
        as_dict=True
    )
    if user and user.full_name:
        return user.full_name

    # ---------------- CONTACT ----------------
    contact = frappe.db.get_value(
        "Contact",
        {"mobile_no": mobile},
        ["first_name", "last_name"],
        as_dict=True
    )

    if contact:
        name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        if name:
            return name

    return None



#  For website pop-up
def get_website_notification(show_on="Select Student Page", school_name=None, ):
    """
    Fetch latest applicable Website Notification.

    Rules:
    - Active only
    - Within date range
    - Correct page (show_on)
    - If notification has schools → filter by school
    - If notification has NO schools → global (visible to all)
    """

    now = now_datetime()

    notification = frappe.db.sql("""
        SELECT
            wn.name,
            wn.title,
            wn.message,
            wn.start_date,
            wn.end_date
        FROM `tabWebsite Notification` wn
        WHERE
            wn.is_active = 1
            AND wn.show_on = %(show_on)s
            AND (wn.start_date IS NULL OR wn.start_date <= %(now)s)
            AND (wn.end_date IS NULL OR wn.end_date >= %(now)s)

            AND (
                (%(school)s IS NOT NULL AND EXISTS (
                    SELECT 1
                    FROM `tabWebsite Notification School` wns
                    WHERE wns.parent = wn.name
                    AND wns.school = %(school)s
                ))

                OR

                (%(school)s IS NULL AND NOT EXISTS (
                    SELECT 1
                    FROM `tabWebsite Notification School` wns
                    WHERE wns.parent = wn.name
                ))
            )

        ORDER BY wn.creation DESC
        LIMIT 1
        """, {
        "school": school_name,
        "show_on": show_on,
        "now": now
    }, as_dict=True)

    return notification[0] if notification else None


def get_notification_for_user(user, show_on="Select Student Page"):
    """
    Decide applicable notification based on logged in user.

    Flow:
    - Find Website Customer
    - Find selected student
    - Find student's school
    - If school exists → school specific notification
    - Else → global notification
    """


    if not user:
        return None

    # Get Website Customer
    website_customer = frappe.db.get_value(
        "Website Customer",
        {"user": user.name},
        ["name", "student"],
        as_dict=True
    )

    if not website_customer:
        return get_website_notification(show_on)

    student_name = website_customer.student

    if not student_name:
        return get_website_notification(show_on)

    # Get student school code
    school_code = frappe.db.get_value("Students", student_name, "school_code")

    if not school_code:
        return get_website_notification(show_on)

    # Get school name
    school_name = frappe.db.get_value(
        "School",
        {"school_code": school_code},
        "name"
    )


    # If still not found → fallback global
    return get_website_notification(show_on, school_name)


def get_account_customers(user):
    """
    Returns all customers controlled by this login account.
    Works for both guardian and single customer users.
    """

    customers = []

    # Guardian → multiple customers (students)
    linked = user.get("linked_customers") or []
    if linked:
        customers = linked

    # Non-guardian fallback
    elif user.get("customer_data"):
        customers = [user.get("customer_data").get("name")]

    return list(set(customers))


# For RER Status Update

def finalize_rer_on_replacement_so_payment(sales_order_name):
    """
    Called after a replacement Sales Order is confirmed paid.

    Responsibilities:
        1) Guard: only runs for replacement SOs with a parent SO
        2) Find the linked Return Exchange Request
        3) Update RER financial fields
        4) Move RER status to "In Progress"

    Args:
        sales_order_name (str): Name of the replacement Sales Order
    """

    # ─────────────────────────────────────────────────────────
    # 1️⃣ Load SO + guard checks
    # ─────────────────────────────────────────────────────────
    so = frappe.get_doc("Sales Order", sales_order_name)

    if not so.custom_is_replacement_so:
        return

    parent_so_name = so.custom_parent_sales_order
    if not parent_so_name:
        frappe.log_error(
            title="FINALIZE RER | MISSING PARENT SO",
            message=f"Replacement SO {sales_order_name} has no custom_parent_sales_order set"
        )
        return

    # ─────────────────────────────────────────────────────────
    # 2️⃣ Find the linked RER
    # ─────────────────────────────────────────────────────────
    rer_name = frappe.db.get_value(
        "Return Exchange Request",
        {
            "replacement_sales_order": sales_order_name,
            "status": "Approved"                          # only act on Approved RERs
        },
        "name"
    )

    if not rer_name:
        frappe.log_error(
            title="FINALIZE RER | RER NOT FOUND",
            message=(
                f"No Approved RER found with replacement_sales_order = {sales_order_name}. "
                f"Either already processed or mismatch."
            )
        )
        return

    # ─────────────────────────────────────────────────────────
    # 3️⃣ Load parent SO for old_sales_order_grand_total
    # ─────────────────────────────────────────────────────────
    parent_grand_total = frappe.db.get_value(
        "Sales Order", parent_so_name, "grand_total"
    )

    if parent_grand_total is None:
        frappe.log_error(
            title="FINALIZE RER | PARENT SO NOT FOUND",
            message=f"Parent SO {parent_so_name} not found for replacement SO {sales_order_name}"
        )
        return

    # ─────────────────────────────────────────────────────────
    # 4️⃣ Update RER
    # ─────────────────────────────────────────────────────────
    try:
        rer = frappe.get_doc("Return Exchange Request", rer_name)

        # Idempotency guard — already moved on
        if rer.status not in ("Approved",):
            frappe.log_error(
                title="FINALIZE RER | ALREADY PROCESSED",
                message=f"RER {rer_name} is already in status '{rer.status}', skipping."
            )
            return

        rer.old_sales_order_grant_total = float(parent_grand_total or 0)
        rer.new_sales_order_grant_total = float(parent_grand_total + so.grand_total or 0)
        rer.grand_total                 = float(so.grand_total or 0)
        rer.status                      = "In Progress"

        rer.flags.ignore_permissions = True
        rer.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.log_error(
            title="FINALIZE RER | SUCCESS",
            message=f"RER {rer_name} moved to In Progress for replacement SO {sales_order_name}"
        )

    except Exception:
        frappe.log_error(
            title="FINALIZE RER | SAVE FAILED",
            message=frappe.get_traceback()
        )