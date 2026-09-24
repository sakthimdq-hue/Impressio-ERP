import frappe
import hashlib
from impressio.impressio.api.helper import ( BLOCK_GENERAL_USER, 
    BLOCK_GENERAL_USER_MESSAGE, sanitize_request,
    sync_guardian_students_after_register, check_otp, consume_otp, success, error, create_otp, get_website_notification
)
from frappe.utils.password import  check_password
from impressio.impressio.api.auth_token import (
    generate_token,
    revoke_token,
    revoke_all_tokens,
    validate_token,
    get_request_token
)
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def check_user_mobile(mobile=None):
    """
    Pre-registration validation:
    1. If mobile exists in User → already registered
    2. Else if exists in Guardians → allowed to register
    3. Else → not allowed (school has not added parent)
    """

    if not mobile:
        return error("Mobile number is required", 422)

    mobile = str(mobile).strip()

    # -------------------------------------
    # 1️⃣ Check if already registered (User)
    # -------------------------------------
    user_exists = frappe.db.exists(
        "User",
        {"mobile_no": mobile}
    )

    if user_exists:
        return success(
            "This mobile number is already registered. Kindly login instead.", {
                "allowed": False,
                "mobile": mobile
            }
        )

    # -------------------------------------
    # 2️⃣ Check Guardian (school parent database)
    # -------------------------------------
    guardian_exists = frappe.db.exists(
        "Guardians",
        {"mobile_number": mobile}
    )

    return success("Is Valid proceed for registration." if bool(guardian_exists) else BLOCK_GENERAL_USER_MESSAGE, {
        "allowed": bool(guardian_exists),
        "mobile": mobile
    })


@frappe.whitelist(allow_guest=True)
def send_register_otp(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile","email","password","confirm_password"]
    )

    if is_error:
        return error(payload, 422)
    
    email = payload.get("email")
    mobile = payload.get("mobile")
    password = payload.get("password")
    confirm_password = payload.get("confirm_password")

    guardian = frappe.db.exists("Guardians", {"mobile_number": mobile})
    if not guardian and BLOCK_GENERAL_USER:
        return error(BLOCK_GENERAL_USER_MESSAGE, 403)

    # ------------------------------------------------
    # Strong password validation (BEFORE DB insert)
    # ------------------------------------------------
    if password != confirm_password:
        return error("Passwords do not match", 422)

    if frappe.db.exists("User", {"email": email}):
        return error("Email already registered", 409)

    if frappe.db.exists("User", {"mobile_no": mobile}):
        return error("Mobile already registered", 409)
   

    mobile_sent, m_msg = create_otp(mobile=mobile, purpose="REGISTER_MOBILE")
    if not mobile_sent:
        return error(m_msg, 429)

    # email_sent, e_msg = create_otp(email=email, purpose="REGISTER_EMAIL")
    # if not email_sent:
    #     return error(e_msg, 429)

    return success("OTP sent to mobile and email")


@frappe.whitelist(allow_guest=True)
def register(**kwargs):


    is_error, payload = sanitize_request(
        kwargs,
        required=["parent_name","mobile","email","password","confirm_password","mobile_otp"]
    )
    if is_error:
        return error(payload, 422)

    parent_name = payload.get("parent_name")
    mobile = payload.get("mobile")
    email = payload.get("email")
    password = payload.get("password")
    confirm_password = payload.get("confirm_password")
    mobile_otp = payload.get("mobile_otp")
    # email_otp = payload.get("email_otp")

    if password != confirm_password:
        return error("Passwords do not match", 422)
    
    # ------------------------------------------------
    # Strong password validation (BEFORE DB insert)
    # ------------------------------------------------
    
    if frappe.db.exists("User", {"email": email}):
        return error("Email already registered", 409)

    if frappe.db.exists("User", {"mobile_no": mobile}):
        return error("Mobile already registered", 409)

    if not check_otp(mobile=mobile, otp=mobile_otp, purpose="REGISTER_MOBILE"):
        return error("Invalid mobile OTP", 401)

    # if not check_otp(email=email, otp=email_otp, purpose="REGISTER_EMAIL"):
    #     return error("Invalid email OTP", 401)

    try:
        frappe.db.begin()

        # Create Customer only when guardian does not exist
        guardian = frappe.db.exists("Guardians", {"mobile_number": mobile})

        if not guardian and BLOCK_GENERAL_USER:
            return error(BLOCK_GENERAL_USER_MESSAGE, 403)
        
        # Check if guardian has at least one student
        has_student = False

        if guardian:
            has_student = frappe.db.exists(
                "Student Guardians",
                {"guardian": guardian}
            )

        customer_doc = None

        # Create Customer only when NO student is linked
        if not has_student:
            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": parent_name,
                "customer_type": "Individual",
                "email_id": email,
                "mobile_no": mobile
            })
            customer.insert(ignore_permissions=True)
            customer_doc = customer.as_dict()


        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "mobile_no": mobile,
            "first_name": parent_name,
            "user_type": "Website User",
            "send_welcome_email": 0,
            "roles": [{"role": "Website Customer"}]
        })
        user.insert(ignore_permissions=True)
        user_doc = frappe.get_doc("User", email)
        user_doc.new_password = password
        user_doc.flags.ignore_permissions = True
        user_doc.flags.ignore_password_policy = True   # ⭐ THIS disables password validation
        user_doc.save()

        frappe.get_doc({
            "doctype": "Website Customer",
            "user": email,
            "customer": customer_doc.name if customer_doc else "",
        }).insert(ignore_permissions=True)

        # Consume OTP only after all business logic is successful
        consume_otp(mobile=mobile, purpose="REGISTER_MOBILE")
        # consume_otp(email=email, purpose="REGISTER_EMAIL")

        frappe.db.commit()
        # AFTER COMMIT — do NOT move above
        sync_guardian_students_after_register(mobile)

    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Register API Failed")
        return error("Registration failed", 500)

    response_data = {
        "has_student": bool(has_student)
    }

    if not guardian:
        response_data["customer"] = customer_doc.name

    return success("Registration successful", response_data)


@frappe.whitelist(allow_guest=True)
def send_login_otp(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile"]
    )
    if is_error:
        return error(payload, 422)
    
    mobile = payload.get("mobile")

    user = frappe.get_value("User", {"mobile_no":mobile})
    if not user:
        return error("Mobile not registered",404)
    
    guardian = frappe.db.exists("Guardians", {"mobile_number": mobile})
    if not guardian and BLOCK_GENERAL_USER:
        return error(BLOCK_GENERAL_USER_MESSAGE, 403)

    sent, message = create_otp(mobile=mobile, purpose="Login")

    if not sent:
        return error(message, 429)  # Too Many Requests

    return success(message)



@frappe.whitelist(allow_guest=True)
def login(**kwargs):


    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile"],
        optional=["password","otp"]
    )
    if is_error:
        return error(payload, 422)

    mobile = payload.get("mobile")
    password = payload.get("password")
    otp = payload.get("otp")

    if not mobile:
        return error("Mobile number is required", 422)

    if not password and not otp:
        return error("Password or OTP is required", 422)

    user = frappe.get_value("User", {"mobile_no": mobile, "enabled": 1})
    if not user:
        return error("Invalid login credentials", 401)

    guardian_name = frappe.db.exists("Guardians", {"mobile_number": mobile})
    customer_name = frappe.get_value("Customer", {"mobile_no": mobile})

    if not guardian_name and BLOCK_GENERAL_USER:
        return error(BLOCK_GENERAL_USER_MESSAGE, 403)
    

    # Check if guardian actually has linked students
    has_student = False

    if guardian_name:
        has_student = frappe.db.exists(
            "Student Guardians",
            {"guardian": guardian_name}
        )
        # --------------------------------------------------
        # STUDENT DASHBOARD COUNTS
        # --------------------------------------------------
        students_count = 0
        pending_count = 0

        if guardian_name:
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
            """, guardian_name, as_dict=True)

            if counts:
                students_count = counts[0].students_count or 0
                pending_count = counts[0].pending_count or 0



    response_data = {
        "has_student": bool(has_student),
        "customer": customer_name if not bool(has_student) else "",
        "students_count": students_count,
        "pending_count": pending_count
        }

   
     # load user to set last_login
    website_customer = frappe.get_value(
            "Website Customer",
            {"name": user},
            ["name", "customer", "student"],
            as_dict=True
        )

    # --------------------------------------------------
    # AUTO ATTACH / DETACH STUDENT
    # --------------------------------------------------
    if website_customer and response_data['has_student']:

        # CASE 1: Verified students exist → ATTACH
        if students_count > 0 :

            first_verified_student = frappe.db.sql("""
                SELECT s.name
                FROM `tabStudents` s
                INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
                INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
                WHERE
                    sg.guardian = %s
                    AND IFNULL(s.enabled, 0) = 1
                    AND IFNULL(s.is_verified, 0) = 1
                    AND IFNULL(s.customer, '') != ''
                    AND sch.status = 'Active'
                ORDER BY s.modified DESC
                LIMIT 1
            """, guardian_name)

            if first_verified_student:
                student_name = first_verified_student[0][0]

                frappe.db.set_value(
                    "Website Customer",
                    website_customer.name,
                    "student",
                    student_name
                )

                website_customer.student = student_name

        # CASE 2: No verified students → DETACH
        elif students_count == 0 and website_customer.student:

            frappe.db.set_value(
                "Website Customer",
                website_customer.name,
                "student",
                None
            )

            website_customer.student = None
    
    try:
        school = None

        if website_customer.student:
            school = frappe.db.sql("""
                    SELECT sch.name
                    FROM `tabStudents` s
                    INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
                    WHERE
                        IFNULL(s.enabled, 0) = 1
                        AND IFNULL(s.is_verified, 0) = 1
                        AND IFNULL(s.customer, '') != ''
                        AND sch.status = 'Active'
                        AND s.name = %s
                    ORDER BY s.modified DESC
                    LIMIT 1
                """, website_customer.student)

        response_data['notification'] = get_website_notification("Login", school)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "School Pop-up Lookup Error")
        

    # --------------------------------------------------
    # EXISTING CUSTOMER RESOLUTION (UNCHANGED)
    # --------------------------------------------------
    if response_data['has_student'] and website_customer and website_customer.student:
        student = frappe.get_value("Students",
                    {"name":  website_customer.student},
                    ["name", "customer"],
                    as_dict=True
                    )
        response_data['customer'] = student.customer
    else:
        response_data['customer'] = website_customer.customer if not response_data['has_student'] and website_customer else ""


    # ---------------- PASSWORD LOGIN ----------------
    if password:
        try:
            check_password(user, password)

            token = generate_token(user)
            response_data["token"] = token

            return success("Login Success, Incase you are logged out, kindly call the customer care (9059990804) to update your number. Team Invent're.", response_data)

        except frappe.AuthenticationError:
            return error("Invalid login credentials", 401)

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Password Login Failure")
            return error("Login service unavailable", 500)


    # ---------------- OTP LOGIN ----------------
    if otp:
        try:            

            if not check_otp(mobile=mobile, otp=otp, purpose="Login"):                
                return error("Invalid or expired OTP", 401)

            consume_otp(mobile=mobile, purpose="Login")

            token = generate_token(user)

            response_data["token"] = token

            return success("Login Success, Incase you are logged out, kindly call the customer care (9059990804) to update your number. Team Invent're.", response_data)

        except Exception:
            frappe.log_error(frappe.get_traceback(), "OTP Login Failure")
            return error("Login failed. Please try again.", 500)


@frappe.whitelist(allow_guest=True)
def send_forgot_password_otp(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile"]
    )
    if is_error:
        return error(payload, 422)

    mobile = payload.get("mobile")

    if not frappe.db.exists("User", {"mobile_no":mobile}):
        return error("Mobile not registered",404)

    sent, message = create_otp(mobile=mobile, purpose="ForgotPassword")
    
    if not sent:
        return error(message, 429)  # Too Many Requests

    return success(message)


@frappe.whitelist(allow_guest=True)
def verify_forgot_password_otp(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile","otp"]
    )
    if is_error:
        return error(payload, 422)

    mobile = payload.get("mobile")
    otp = payload.get("otp")

    if not check_otp(mobile=mobile, otp=otp, purpose="ForgotPassword"):
        return error("Invalid or expired OTP",401)

    return success("OTP verified successfully")



@frappe.whitelist(allow_guest=True)
def reset_password(**kwargs):


    is_error, payload = sanitize_request(
        kwargs,
        required=["mobile","otp","password","confirm_password"]
    )
    if is_error:
        return error(payload, 422)

    mobile = payload.get("mobile")
    otp = payload.get("otp")
    password = payload.get("password")
    confirm_password = payload.get("confirm_password")

    if password != confirm_password:
        return error("Passwords do not match",422)

    if not check_otp(mobile=mobile, otp=otp, purpose="ForgotPassword"):
        return error("Invalid or expired OTP",401)

    user_doc = frappe.get_doc("User", {"mobile_no": mobile})
    if not user_doc:
        return error("Mobile not registered",404)
    
    user_doc.new_password = password
    user_doc.flags.ignore_permissions = True
    user_doc.flags.ignore_password_policy = True   # ⭐ THIS disables password validation
    user_doc.save()

    consume_otp(mobile=mobile, purpose="ForgotPassword")

    return success("Password reset successful")



@frappe.whitelist(allow_guest=True)
def logout():
    try:
        token = get_request_token()
        user = validate_token(token)
        # frappe.log_error(title="Logout Event triggered", message=f"user token: {token}")

        # if not user:
        #     return error("Invalid or expired session", 401)

        revoke_token(token)

        return success("Logout successful")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Logout Failure")
        return error("Logout failed", 500)


@frappe.whitelist(allow_guest=True)
def logout_all_devices():
    try:
        token = get_request_token()
        user = validate_token(token)

        if not user:
            return error("Invalid or expired session", 401)

        # revoke every session
        revoke_all_tokens(user)

        return success("Logged out from all devices")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Logout All Devices Failure")
        return error("Logout all devices failed", 500)


def make_session_id(token: str):
    # safe identifier derived from token
    return hashlib.sha256(token.encode()).hexdigest()[:16]

@frappe.whitelist(allow_guest=True)
def my_logged_devices():
    try:
        # validate current session
        token = get_request_token()
        user = validate_token(token)

        if not user:
            return error("Invalid or expired session", 401)

        # fetch all active tokens
        sessions = frappe.get_all(
            "Website Auth Token",
            filters={
                "user": user,
                "expires_at": [">", now_datetime()]
            },
            fields=[
                "token",
                "device",
                "ip_address",
                "creation",
                "expires_at"
            ],
            order_by="creation desc"
        )

        result = []
        current_session_id = make_session_id(token)

        for s in sessions:
            session_id = make_session_id(s.token)

            result.append({
                "session_id": session_id,
                "device": s.device or "Unknown Device",
                "ip_address": s.ip_address,
                "login_time": s.creation,
                "expires_at": s.expires_at,
                "current": session_id == current_session_id
            })

        return success(result)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "List Logged Devices Failed")
        return error("Failed to fetch active sessions", 500)

@frappe.whitelist(allow_guest=True)
def logout_device(**kwargs):
    try:
        token = get_request_token()
        user = validate_token(token)

        is_error, payload = sanitize_request(kwargs,required="session_id")
        if is_error:
            return error(payload, 422)
        
        session_id = payload.get("session_id")

        if not user:
            return error("Invalid or expired session", 401)

        sessions = frappe.get_all(
            "Website Auth Token",
            filters={"user": user},
            fields=["name", "token"]
        )

        for s in sessions:
            if make_session_id(s.token) == session_id:
                frappe.delete_doc("Website Auth Token", s.name, ignore_permissions=True)
                frappe.db.commit()
                return success("Device logged out")

        return error("Session not found", 404)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Logout Specific Device Failed")
        return error("Unable to logout device", 500)