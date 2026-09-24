import frappe
from frappe.core.doctype.user import user
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import sanitize_request, resolve_school_grade, check_otp, consume_otp, success, error, validate_fields, create_otp, get_notification_for_user
from frappe.utils import now_datetime
from frappe.utils import validate_email_address


@frappe.whitelist(allow_guest=True)
def admission_dropdown():
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    if not user.has_student:
        return success([])

    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": user.mobile},
        "name"
    )

    if not guardian:
        return success([])

    students = frappe.db.sql("""
        SELECT parent AS student
        FROM `tabStudent Guardians`
        WHERE guardian = %s
    """, guardian, as_dict=True)

    if not students:
        return success([])

    rows = frappe.db.sql("""
            SELECT
                sch.name AS school,
                sch.school_name,
                s.name AS student_id,
                s.first_name AS student_name,
                s.enrollment_number
            FROM `tabStudent Guardians` sg
            INNER JOIN `tabStudents` s ON s.name = sg.parent
            INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
            WHERE sg.guardian = %s
                AND IFNULL(s.enabled, 0) = 1
                AND IFNULL(s.is_verified, 0) = 0
                AND sch.status = 'Active'
            ORDER BY sch.school_name, s.first_name
        """, guardian, as_dict=True)

    grouped = {}

    for r in rows:
        school_key = r["school"]

        if school_key not in grouped:
            grouped[school_key] = {
                "name": r["school"],
                "school_name": r["school_name"],
                "students": []
            }

        grouped[school_key]["students"].append({
            "id": r["student_id"],
            "student_name": r["student_name"],
            "enrollment_number": r["enrollment_number"]
        })

    result = list(grouped.values())

    return success("Success", result)




@frappe.whitelist(allow_guest=True)
def linked_students():
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    if not user.has_student:
        return error("Forbidden", 403)

    # ----------------------------------
    # Get guardian
    # ----------------------------------
    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": user.mobile},
        "name"
    )

    if not guardian:
        return success("Success", [])

    # ----------------------------------
    # Fetch ALL linked students
    # ----------------------------------
    rows = frappe.db.sql("""
        SELECT 
            sch.name AS school,
            sch.school_name,
            s.name,
            s.first_name,
            s.enrollment_number,
            s.profile_picture_attach,
            s.gender,
            s.customer,
            s.enabled
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE 
            sg.guardian = %s
            AND sch.status = 'Active'
            AND IFNULL(s.enabled, 0) = 1                 -- only enabled
            AND IFNULL(s.customer, '') != ''             -- must have customer (admitted)
            AND IFNULL(s.is_verified, 0) = 1             -- only verified ⭐
        ORDER BY sch.school_name, s.first_name
    """, guardian, as_dict=True)

    # ----------------------------------
    # Build full image path
    # ----------------------------------
    site_url = frappe.utils.get_url()
    for r in rows:
        if r.profile_picture_attach:
            r.profile_picture_attach = site_url + r.profile_picture_attach
        else:
            r.profile_picture_attach = None

    # ----------------------------------
    # GROUP BY SCHOOL  ⭐ IMPORTANT PART
    # ----------------------------------
    grouped = {}

    for r in rows:
        school_key = r["school"]

        if school_key not in grouped:
            grouped[school_key] = {
                "school": r["school"],
                "school_name": r["school_name"],
                "students": []
            }

        # remove school fields inside student object
        student_data = {
            "name": r["name"],
            "first_name": r["first_name"],
            "enrollment_number": r["enrollment_number"],
            "profile_picture_attach": r["profile_picture_attach"],
            "gender": r["gender"],
            "customer": r["customer"],
            "enabled": r["enabled"]
        }

        grouped[school_key]["students"].append(student_data)

    # convert dict → list
    result = list(grouped.values())

    return success("Success", result)


@frappe.whitelist(allow_guest=True)
def student_information(**kwargs):  

    is_error, payload = sanitize_request(
        kwargs,
        required = ["school", "enrollment_number"]
    )
    if is_error:
        return error(payload, 422)

    school = payload.get("school")
    enrollment_number = payload.get("enrollment_number")

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    if not user.has_student:
        return error("No student linked")

    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": user.mobile},
        "name"
    )
    if not guardian:
        return error("Guardian not found")

    # 1️⃣ Validate ownership + get student
    student = frappe.db.sql("""
        SELECT s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE sg.guardian=%s AND sch.name=%s AND s.enrollment_number=%s
            AND IFNULL(s.enabled, 0) = 1
            AND sch.status = 'Active'
    """, (guardian, school, enrollment_number), as_dict=True)

    if not student:
        return error("Student not found")

    student_doc = frappe.get_doc("Students", student[0].name)
    school_doc  = frappe.get_doc("School", school)

    site_url = frappe.utils.get_url()
    profile = student_doc.profile_picture_attach
    profile = site_url + profile if profile else None


    # -------------------------------------------------------
    # 2️⃣ Collect Existing Selected Products from Student
    # -------------------------------------------------------
    selected_map = {}

    for row in student_doc.subject_group:
        selected_map.setdefault(row.bundle_name, {}) \
            .setdefault(row.sub_bundle_name, []) \
            .append(row.product_name)


    # -------------------------------------------------------
    # 3️⃣ Build Subject Groups from Books Costing
    # -------------------------------------------------------
    subject_groups = {}

    for row in school_doc.books_details_costing:
        if row.grade != student_doc.grade:
            continue

        subject_groups.setdefault(row.bundle_name, {}) \
            .setdefault(row.sub_bundle_name, []) \
            .append(row.product_name)


    # -------------------------------------------------------
    # 4️⃣ Prepare Final Subject Group Response
    # -------------------------------------------------------
    subject_group_list = []

    for bundle, subs in subject_groups.items():
        subjects = []

        for sub, products in subs.items():

            available_products = list(set(products))

            # Already selected by student
            selected_products = selected_map.get(bundle, {}).get(sub, [])

            subjects.append({
                "sub_bundle_name": sub,
                "products": available_products,
                "selected_products": selected_products
            })

        subject_group_list.append({
            "bundle_name": bundle,
            "subjects": subjects
        })


    # -------------------------------------------------------
    # 5️⃣ Build Final Response
    # -------------------------------------------------------
    data = {
        "is_verified": bool(student_doc.is_verified),
        "basic_details": {
            "name": student_doc.name,
            "student_name": student_doc.first_name,
            "shoe_size" : student_doc.shoe_size,
            "customer": student_doc.customer or None,
            "class_section": f"{resolve_school_grade(student_doc.get('grade'), school_doc.get('name'))} {student_doc.section or ''}".strip(),
            "house_color": student_doc.house_color or None,
            "shirt_size": student_doc.shirt_size or None,
            "trouser_size": student_doc.trouser_size or None,
            "school_name": school_doc.school_name,
            "campus": school_doc.branch_name,
            "medium": student_doc.medium or None,
            "curriculum": student_doc.curriculum or None,
            "profile_picture": profile
        },
        "subject_group": subject_group_list
    }

    return success("Success", data)



@frappe.whitelist(allow_guest=True)
def send_student_update_otp(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required = ["school", "enrollment_number"]
    )
    if is_error:
        return error(payload, 422)

    school = payload.get("school")
    enrollment_number = payload.get("enrollment_number")

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    if not user.has_student:
        return error("No student linked")

    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": user.mobile},
        "name"
    )
    if not guardian:
        return error("Guardian not found")

    # Verify student ownership
    allowed = frappe.db.sql("""
        SELECT s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE sg.guardian=%s AND sch.name=%s AND s.enrollment_number=%s
        LIMIT 1
    """, (guardian, school, enrollment_number), as_dict=True)

    if not allowed:
        return error("Student not found")

    name = allowed[0].name 
    sent, msg = create_otp(mobile=user.mobile, purpose=f"STUDENT_UPDATE_{name}")
        
    if not sent:
        return error(msg, 429)

    return success("OTP sent to registered mobile number")



@frappe.whitelist(allow_guest=True)
def update_student_information(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required =  ["school", "enrollment_number", "mobile_otp"]
    )
    if is_error:
        return error(payload, 422)

    school = payload.get("school")
    enrollment_number = payload.get("enrollment_number")
    mobile_otp = payload.get("mobile_otp")

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    if not user.has_student:
        return error("No student linked")

    guardian = frappe.db.get_value(
        "Guardians",
        {"mobile_number": user.mobile},
        "name"
    )
    if not guardian:
        return error("Guardian not found")

   

    # Validate student ownership
    student = frappe.db.sql("""
        SELECT s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE sg.guardian=%s AND sch.name=%s AND s.enrollment_number=%s
    """, (guardian, school, enrollment_number), as_dict=True)

    if not student:
        return error("Student not found")

    purpose = f"STUDENT_UPDATE_{student[0].name}"
    # OTP Verification using dynamic purpose
    if not check_otp(mobile=user.mobile, otp=mobile_otp, purpose=purpose):
        return error("Invalid or expired OTP", 401)

    doc = frappe.get_doc("Students", student[0].name)

    # -----------------------
    # Update Basic Fields
    # -----------------------
    if kwargs.get("student_name"):
        doc.first_name = kwargs.get("student_name")

    if kwargs.get("shoe_size"):
        doc.shoe_size = kwargs.get("shoe_size")

    if kwargs.get("house_color"):
        doc.house_color = kwargs.get("house_color")

    if kwargs.get("trouser_size"):
        doc.trouser_size = kwargs.get("trouser_size")

    if kwargs.get("shirt_size"):
        doc.shirt_size = kwargs.get("shirt_size")
        
    if kwargs.get("medium"):
        doc.medium = kwargs.get("medium")

    if kwargs.get("curriculum"):
        doc.curriculum = kwargs.get("curriculum")


    # ----- NEW LOGIC -----
    if not doc.is_verified or not doc.customer:
        create_customer_from_student(doc)

    doc.is_verified = True;  # mark verification on update


    # -----------------------
    # Update Subject Group Child Table
    # subject_group format:
    # [
    #   {bundle_name:"Maths", subjects:[{sub_bundle_name:"Algebra", products:["Book1","Book2"]}]}
    # ]
    # -----------------------
           
    doc.set("subject_group", [])

    groups = frappe.parse_json(kwargs.get("subject_group"))

    for bundle in groups:
        bundle_name = bundle.get("bundle_name")

        for sub in bundle.get("subjects", []):
            sub_name = sub.get("sub_bundle_name")

            for product in sub.get("products", []):
                doc.append("subject_group", {
                    "bundle_name": bundle_name,
                    "sub_bundle_name": sub_name,
                    "product_name": product
                })


    doc.save(ignore_permissions=True)
    consume_otp(mobile=user.mobile, purpose=purpose)

    return success("Student information updated successfully")



def create_customer_from_student(student_doc):
    """
    Create Customer from Student details if not already exists.
    Also create Address and Contact from student data.
    """

    # If student already linked to a customer, return it
    if getattr(student_doc, "customer", None):
        return frappe.get_doc("Customer", student_doc.customer)


    email = student_doc.student_email_id
    mobile = student_doc.student_mobile_number
    student_name = student_doc.first_name


    final_email = None

    if email:
        # Split if multiple emails present
        first_email = email.split(";")[0].strip()

        try:
            validate_email_address(first_email, throw=True)
            final_email = first_email
        except Exception:
            final_email = None

    email = final_email

    # -----------------------------
    # Create Customer
    # -----------------------------

    customer = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": student_name,
        "customer_type": "Individual",
        "email_id": email or "",
        "mobile_no": mobile or "", 
        "gender": student_doc.gender or "",
        "custom_school_code": student_doc.school_code,
        "custom_enrollment_number": student_doc.enrollment_number
    })

    if student_doc.customer_group:
        customer.customer_group = student_doc.customer_group or "Student"

    customer.insert(ignore_permissions=True)

    customer_name = customer.name


    # -----------------------------
    # Link created customer to student
    # -----------------------------
    student_doc.customer = customer_name
    student_doc.student_email_id = email
    student_doc.save(ignore_permissions=True)


    # -----------------------------
    # Create Billing Addresses
    # -----------------------------
    for addr in student_doc.student_billing_addresses:
        try:
            if frappe.db.exists("Address", {
                "address_title": f"{student_name} - {addr.address_title}"
            }):
                continue
            if not addr.address_line_1 or not addr.city:
                continue
            
            address = frappe.get_doc({
                "doctype": "Address",
                "address_title": f"{student_name} - {addr.address_title}",
                "address_type": "Billing",
                "address_line1": addr.address_line_1,
                "address_line2": addr.address_line_2,
                "city": addr.city,
                "state": addr.state,
                "country": addr.country,
                "pincode": str(addr.pincode) if addr.pincode else "",
                "links": [
                    {
                        "link_doctype": "Customer",
                        "link_name": customer_name
                    }
                ]
            })

            address.insert(ignore_permissions=True)

            if addr.preferred:
                customer.customer_primary_address = address.name
            customer.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                title="Student Billing Address Creation Failed",
                message=frappe.as_json({
                    "student": student_doc.name,
                    "customer": customer_name,
                    "address_title": addr.address_title,
                    "error": str(e)
                })
            )
        continue

    # -----------------------------
    # Create Shipping Addresses
    # -----------------------------
    for addr in student_doc.student_shipping_addresses:
        try:
            if frappe.db.exists("Address", {
                "address_title": f"{student_name} - {addr.address_title}"
            }):
                continue
            if not addr.address_line_1 or not addr.city:
                continue

            address = frappe.get_doc({
                "doctype": "Address",
                "address_title": f"{student_name} - {addr.address_title}",
                "address_type": "Shipping",
                "address_line1": addr.address_line_1,
                "address_line2": addr.address_line_2,
                "city": addr.city,
                "state": addr.state,
                "country": addr.country,
                "pincode": str(addr.pincode) if addr.pincode else "",
                "links": [
                    {
                        "link_doctype": "Customer",
                        "link_name": customer_name
                    }
                ]
            })

            address.insert(ignore_permissions=True)

            if addr.preferred:
                customer.customer_primary_address = address.name
                customer.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                title="Student Shipping Address Creation Failed",
                message=frappe.as_json({
                    "student": student_doc.name,
                    "customer": customer_name,
                    "address_title": addr.address_title,
                    "error": str(e)
                })
            )
            continue

    # -----------------------------
    # Create Contact from Guardian
    # -----------------------------
    if student_doc.guardians:

        guardian = student_doc.guardians[0]

        if guardian.get('email') and not frappe.db.exists("Contact", {"email_id": guardian.email}):

            contact = frappe.get_doc({
                "doctype": "Contact",
                "first_name": guardian.guardian_name,
                "email_id": guardian.email,
                "phone": guardian.phone_no,
                "mobile_no": mobile,
                "links": [
                    {
                        "link_doctype": "Customer",
                        "link_name": customer_name
                    }
                ]
            })

            contact.insert(ignore_permissions=True)
            customer.customer_primary_contact = contact.name
        
        customer.save(ignore_permissions=True)

    return customer



@frappe.whitelist()
def create_customers_from_students(student_names):
    """
    student_names: list of Student docnames
    """

    if isinstance(student_names, str):
        import json
        student_names = json.loads(student_names)

    created = []
    skipped = []
    failed = []

    for student_name in student_names:
        try:
            # ✅ Check exists
            if not frappe.db.exists("Students", student_name):
                failed.append({
                    "student": student_name,
                    "error": "Student not found"
                })
                continue

            student_doc = frappe.get_doc("Students", student_name)

            # ✅ Already has customer
            if student_doc.customer:
                skipped.append({
                    "student": student_name,
                    "reason": f"Already linked to Customer {student_doc.customer}"
                })
                continue

            # ✅ Create customer
            customer = create_customer_from_student(student_doc)

            created.append({
                "student": student_name,
                "customer": customer.name
            })

        except Exception as e:
            frappe.log_error(
                title="Bulk Customer Creation Failed",
                message=f"{student_name}: {str(e)}"
            )

            failed.append({
                "student": student_name,
                "error": str(e)
            })

    return {
        "created": created,
        "skipped": skipped,
        "failed": failed
    }


@frappe.whitelist(allow_guest=True)
def switch_student(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required =  ["student"]
    )
    if is_error:
        return error(payload, 422)

    student_name = payload.get("student")

    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)


    # Must be a guardian with students
    if not user.has_student:
        return error("No students linked to this account", 403)

    guardian = user.guardian_name

    # Validate that student belongs to this guardian
    is_valid = frappe.db.exists(
        "Student Guardians",
        {
            "parent": student_name,
            "guardian": guardian
        }
    )

    if not is_valid:
        return error("Unauthorized student access", 403)

    # Fetch student document
    student_doc = frappe.get_doc("Students", student_name)
    school_code = student_doc.get("school_code", None)

    if not school_code:
        return error("Student must be linked with any school.", 401)
    
    # -----------------------------
    # NEW CHECK: Student must be verified
    # -----------------------------
    if not student_doc.enabled:
        return error("Student is not enabled", 403)

    if not student_doc.is_verified or not student_doc.customer:
        return error("Student is not verified yet", 403)
    
    school = frappe.get_doc("School",{"school_code": school_code})

    if not school:
        return error("School not found", 404)

    notification =  get_notification_for_user(user, 'Select Student Page')


    # Update Website Customer current student
    website_customer = frappe.get_value(
        "Website Customer",
        {"user": user.name},
        "name"
    )

    frappe.db.set_value(
        "Website Customer",
        website_customer,
        "student",
        student_name
    )
    student_full_name = f"{student_doc.first_name or ''} {student_doc.last_name or ''}"

    return success("Student switched successfully", {
        "current_student": student_name,
        "student_name": student_full_name.strip() ,
        "customer": student_doc.customer,
        "notification": notification
    })
