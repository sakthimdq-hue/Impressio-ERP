import frappe
from impressio.impressio.api.helper import check_otp, consume_otp, success, error, validate_fields, create_otp
from frappe.utils.password import update_password
from frappe.auth import LoginManager
from frappe.sessions import clear_sessions




@frappe.whitelist(allow_guest=True)
def send_register_otp(**kwargs):

    required = ["parent_name","mobile","email"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg, 422)

    email = kwargs.get("email")
    mobile = kwargs.get("mobile")

    if frappe.db.exists("User", {"email": email}):
        return error("Email already registered", 409)

    if frappe.db.exists("User", {"mobile_no": mobile}):
        return error("Mobile already registered", 409)

    mobile_sent, m_msg = create_otp(mobile=mobile, purpose="REGISTER_MOBILE")
    if not mobile_sent:
        return error(m_msg, 429)

    email_sent, e_msg = create_otp(email=email, purpose="REGISTER_EMAIL")
    if not email_sent:
        return error(e_msg, 429)

    return success("OTP sent to mobile and email")



@frappe.whitelist(allow_guest=True)
def register(**kwargs):

    required = ["parent_name","mobile","email","password","confirm_password","mobile_otp","email_otp"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg, 422)

    parent_name = kwargs.get("parent_name")
    mobile = kwargs.get("mobile")
    email = kwargs.get("email")
    password = kwargs.get("password")
    confirm_password = kwargs.get("confirm_password")
    mobile_otp = kwargs.get("mobile_otp")
    email_otp = kwargs.get("email_otp")

    if password != confirm_password:
        return error("Passwords do not match", 422)
    
    if frappe.db.exists("User", {"email": email}):
        return error("Email already registered", 409)

    if frappe.db.exists("User", {"mobile_no": mobile}):
        return error("Mobile already registered", 409)

    if not check_otp(mobile=mobile, otp=mobile_otp, purpose="REGISTER_MOBILE"):
        return error("Invalid mobile OTP", 401)

    if not check_otp(email=email, otp=email_otp, purpose="REGISTER_EMAIL"):
        return error("Invalid email OTP", 401)

    try:
        frappe.db.begin()

        # Create Customer only when guardian does not exist
        guardian = frappe.db.exists("Guardians", {"mobile_number": mobile})

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
        update_password(user=email, pwd=password)

        frappe.get_doc({
            "doctype": "Website Customer",
            "user": email,
            "customer": customer_doc.name if customer_doc else "",
        }).insert(ignore_permissions=True)

        # Consume OTP only after all business logic is successful
        consume_otp(mobile=mobile, purpose="REGISTER_MOBILE")
        consume_otp(email=email, purpose="REGISTER_EMAIL")


        frappe.db.commit()

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

    required = ["parent_name","mobile"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg,422)

    mobile = kwargs.get("mobile")

    user = frappe.get_value("User", {"mobile_no":mobile})
    if not user:
        return error("Mobile not registered",404)

    sent, message = create_otp(mobile=mobile, purpose="Login")

    if not sent:
        return error(message, 429)  # Too Many Requests

    return success(message)



@frappe.whitelist(allow_guest=True)
def login(**kwargs):

    mobile = kwargs.get("mobile")
    password = kwargs.get("password")
    otp = kwargs.get("otp")

    if not mobile:
        return error("Mobile number is required", 422)

    if not password and not otp:
        return error("Password or OTP is required", 422)

    user = frappe.get_value("User", {"mobile_no": mobile, "enabled": 1})
    if not user:
        return error("Invalid login credentials", 401)

    guardian_name = frappe.db.exists("Guardians", {"mobile_number": mobile})
    customer_name = frappe.get_value("Customer", {"mobile_no": mobile})
    

    # Check if guardian actually has linked students
    has_student = False

    if guardian_name:
        has_student = frappe.db.exists(
            "Student Guardians",
            {"guardian": guardian_name}
        )

    response_data = {
        "has_student": bool(has_student),
        "customer": customer_name if not bool(has_student) else ""
    }

   
     # load user to set last_login
    website_customer = frappe.get_value(
            "Website Customer",
            {"name": user},
            ["name", "customer", "student"],
            as_dict=True
        )


    if response_data['has_student'] and website_customer and website_customer.student:
        student = frappe.get_value("Students",
                                   {"name":  website_customer.student},
                                      ["name", "customer"],
                                     as_dict=True)
        response_data['customer'] = student.customer
    else:
        response_data['customer'] = website_customer.customer if not response_data['has_student'] and website_customer else ""


    # ---------------- PASSWORD LOGIN ----------------
    if password:
        lm = LoginManager()
        try:
            # 1️⃣ Authenticate credentials (no session yet)
            lm = LoginManager()
            lm.authenticate(user=user, pwd=password)

            # 2️⃣ Clear ALL previous sessions
            # clear_sessions(user)

            # 3️⃣ Create NEW session + set cookie
            lm.post_login()

            # lm.authenticate(user=user, pwd=password)
            # lm.post_login()
            return success("Login successful", response_data)

        except frappe.AuthenticationError:
            return error("Invalid login credentials", 401)

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Password Login Failure")
            return error("Login service unavailable", 500)

    # ---------------- OTP LOGIN ----------------
    if otp:
        frappe.db.begin()

        try:
            if not check_otp(mobile=mobile, otp=otp, purpose="Login"):
                frappe.db.rollback()
                return error("Invalid or expired OTP", 401)

            consume_otp(mobile=mobile, purpose="Login")

            clear_sessions(user)

            frappe.local.login_manager = LoginManager()
            frappe.local.login_manager.user = user
            frappe.local.login_manager.post_login()

            frappe.db.commit()
            return success("Login successful", response_data)

        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "OTP Login Failure")
            return error("Login failed. Please try again.", 500)



@frappe.whitelist(allow_guest=True)
def send_forgot_password_otp(**kwargs):

    required = ["email"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg,422)

    email = kwargs.get("email")

    if not frappe.db.exists("User", {"email":email}):
        return error("Email not registered",404)

    sent, message = create_otp(email=email, purpose="ForgotPassword")
    
    if not sent:
        return error(message, 429)  # Too Many Requests

    return success(message)


@frappe.whitelist(allow_guest=True)
def verify_forgot_password_otp(**kwargs):

    required = ["email","otp"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg,422)

    email = kwargs.get("email")
    otp = kwargs.get("otp")

    if not check_otp(email=email, otp=otp, purpose="ForgotPassword"):
        return error("Invalid or expired OTP",401)

    return success("OTP verified successfully")



@frappe.whitelist(allow_guest=True)
def reset_password(**kwargs):

    required = ["email","otp","password","confirm_password"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg,422)

    email = kwargs.get("email")
    otp = kwargs.get("otp")
    password = kwargs.get("password")
    confirm_password = kwargs.get("confirm_password")

    if password != confirm_password:
        return error("Passwords do not match",422)

    if not check_otp(email=email, otp=otp, purpose="ForgotPassword"):
     return error("Invalid or expired OTP",401)

    update_password(user=email, pwd=password)

    consume_otp(email=email, purpose="ForgotPassword")

    return success("Password reset successful")


# @frappe.whitelist()
# def logout():

#     try:
#         user = frappe.session.user

#         if user == "Guest":
#             return success("Already logged out")

#         # Clear all active sessions for this user
#         clear_sessions(user)

#         # Logout current session
#         frappe.local.login_manager.logout()

#         return success("Logout successful")

#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "Logout Failure")
#         return error("Logout failed", 500)


@frappe.whitelist(allow_guest=True)
def logout():
    try:
        user = frappe.session.user

        if user != "Guest":
            frappe.local.login_manager.logout()
            clear_sessions(user)

        # 🔥 Explicit cookie deletion (IMPORTANT)
        frappe.local.cookie_manager.delete_cookie("sid")
        frappe.local.cookie_manager.delete_cookie("user_id")
        frappe.local.cookie_manager.delete_cookie("full_name")

        frappe.local.response.http_status_code = 200
        return success("Logout successful")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Logout Failure")
        return error("Logout failed", 500)
