import frappe
from impressio.impressio.api.helper import  BLOCK_GENERAL_USER, BLOCK_GENERAL_USER_MESSAGE, error, success, force_guest_user
from impressio.impressio.api.auth_token import validate_token, get_request_token

class BaseAPI:

    def __init__(self):
        self.allowed = [
            "impressio.api.auth.send_register_otp",
            "impressio.api.auth.register",
            "impressio.api.auth.send_login_otp",
            "impressio.api.auth.login",
            "impressio.api.auth.send_forgot_otp",
            "impressio.api.auth.verify_forgot_otp",
            "impressio.api.auth.reset_password",
            "impressio.api.auth.logout",
            "impressio.api.auth.my_logged_devices",
            "impressio.api.auth.logout_all_devices",
        ]

        cmd = frappe.form_dict.cmd
        force_guest_user()
        if cmd not in self.allowed:
            self.user = self.validate_user()
        else:
            self.user = None


    def validate_user(self):

         # 1️⃣ Resolve token
        token = get_request_token()
        user = validate_token(token)

        if not user:
            frappe.local.cookie_manager.delete_cookie("auth_token")
            frappe.local.response.http_status_code = 401
            return None
        


        # Get Website Customer Profile
        profile = frappe.get_value(
            "Website Customer",
            {"user": user},
            [
                "name",
                "user",
                "customer",
                "student",
                "whatsapp_message",
                "sms_alert",
                "email_alert",
                "order_updates"
            ],
            as_dict=True
        )

        if not profile:
            return None

        # Get core user details
        user_doc = frappe.get_value(
            "User",
            user,
            ["mobile_no", "first_name","full_name", "email"],
            as_dict=True
        )

        # Find guardian by mobile number
        guardian_name = frappe.db.exists(
            "Guardians",
            {"mobile_number": user_doc.mobile_no}
        )

        

        # Check if guardian actually has linked students
        has_student = False

        if guardian_name:
            has_student = frappe.db.exists(
                "Student Guardians",
                {"guardian": guardian_name}
            )

        # -------------------------------------------
        # Customer Handling When No Student Exists
        # -------------------------------------------

        # if BLOCK_GENERAL_USER and (not guardian_name or not has_student):
        if BLOCK_GENERAL_USER and not guardian_name:
            return None

        customer_name = None

        # if not has_student:

        #     # Always clear student field when no student exists
        #     frappe.db.set_value(
        #         "Website Customer",
        #         profile.name,
        #         "student",
        #         None
        #     )

        #     # First check if Website Customer already has a linked customer
        #     if profile.customer:
        #         customer_name = profile.customer

        #     else:                
        #         customer = frappe.get_doc({
        #             "doctype": "Customer",
        #             "customer_name": user_doc.first_name,
        #             "customer_type": "Individual",
        #             "email_id": user_doc.email,
        #             "mobile_no": user_doc.mobile_no
        #         })

        #         customer.insert(ignore_permissions=True)
        #         customer_name = customer.name

        #     # Update Website Customer with this customer
        #     frappe.db.set_value(
        #         "Website Customer",
        #         profile.name,
        #         "customer",
        #         customer_name
        #     )

        #     profile.customer = customer_name


        # -------------------------------------------
        # Build final profile object
        # -------------------------------------------

        profile.mobile = user_doc.mobile_no
        profile.first_name = user_doc.first_name
        profile.full_name = user_doc.full_name

        # TRUE only when at least one student exists
        profile.has_student = bool(has_student)

        # Guardian is relevant only if student exists
        profile.guardian_name = guardian_name if has_student else None

        # -------------------------------------------
        # Linked Students (NEW – guardian-based)
        # -------------------------------------------

        linked_students = []

        # if profile.has_student and guardian_name:
        #     linked_students = frappe.get_all(
        #         "Student Guardians",
        #         filters={"guardian": guardian_name},
        #         pluck="parent"   # parent = Students.name
        #     )

        linked_students = []

        if profile.has_student and guardian_name:

            # Step 1: Get all students mapped to guardian
            guardian_students = frappe.get_all(
                "Student Guardians",
                filters={"guardian": guardian_name},
                pluck="parent"
            )

            # Step 2: From those, allow only enabled students
            if guardian_students:
                linked_students = frappe.get_all(
                    "Students",
                    filters={
                        "name": ["in", guardian_students],
                        "enabled": 1
                    },
                    pluck="name"
                )


        # Always return array
        profile.linked_students = linked_students or []

        
        # Customer should be used only when user is not a guardian/student
        profile.customer = customer_name if not has_student else None


        # -------------------------------------------
        # Additional Student and Customer Details
        # (NEW LOGIC - ADDED AS REQUESTED)
        # -------------------------------------------

        # Case 1: User has student and student field is present
        # Case 1: User has student and student field is present
        if profile.has_student and profile.student:

            student_doc = frappe.get_doc("Students", profile.student)
            student_data = student_doc.as_dict()

            # -------------------------------------------
            # School Code → School Name (CORRECT PLACE)
            # -------------------------------------------
            # if student_doc.school_code:
            #     school_name = frappe.db.get_value(
            #         "School",
            #         {"school_code": student_doc.school_code},
            #         "name"
            #     )

            #     student_data["school_name"] = school_name
            # else:
            #     student_data["school_name"] = None

            if student_doc.school_code:
                school_doc = frappe.get_doc(
                    "School",
                    {"school_code": student_doc.school_code}
                )
                
                school_data = school_doc.as_dict()

                if not school_data:
                    student_data["school"] = None
                    student_data["school_name"] = None
                else:
                    # normalize logo URL
                    logo = school_data.get("school_logo")
                    if logo and logo.startswith("/"):
                        school_data["school_logo"] = (
                            f"{frappe.utils.get_url()}{logo}"
                        )

                    student_data["school"] = school_data
                    student_data["school_name"] = school_data.get("name")

            else:
                student_data["school"] = None
                student_data["school_name"] = None


            # Normalize profile picture
            picture = student_data.get("profile_picture_attach")
            if picture:
                if picture.startswith("/"):
                    student_data["profile_picture_attach"] = (
                        f"{frappe.utils.get_url()}{picture}"
                    )
            else:
                student_data["profile_picture_attach"] = (
                    f"{frappe.utils.get_url()}/private/files/images.jpeg"
                )

            profile.student_data = student_data

            # Fetch linked customer
            if student_doc.customer:
                customer_doc = frappe.get_doc("Customer", student_doc.customer)
                profile.customer_data = customer_doc.as_dict()


        # Case 2: No student exists – use Website Customer linked customer
        elif not profile.has_student and profile.customer:

            customer_doc = frappe.get_doc("Customer", profile.customer)

            profile.customer_data = customer_doc.as_dict()

        # -------------------------------------------
        # Active Linked Customers (NEW)
        # -------------------------------------------

        linked_customers = []

        # Case 1: Direct customer (no students)
        if not profile.has_student and profile.customer_data:
            linked_customers = [profile.customer_data.get("name")]

        # Case 2: Guardian with students
        elif profile.has_student and profile.linked_students:
            student_customers = frappe.get_all(
                "Students",
                filters={
                    "name": ["in", profile.linked_students],
                    "customer": ["is", "set"]
                },
                pluck="customer"
            )

            # ensure uniqueness + remove nulls
            linked_customers = list(set(student_customers))

        # Always return array
        profile.linked_customers = linked_customers

       
        return profile
