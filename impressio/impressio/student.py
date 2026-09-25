
import frappe
import json
import re
from frappe import _
from frappe.utils import cstr, flt, getdate
import pandas as pd
from openpyxl import load_workbook
from datetime import datetime



# ========================================================
# DOWNLOAD TEMPLATE
# ========================================================

@frappe.whitelist()
def download_student_template():

    columns = [
        # ---------------- STUDENT ----------------
        "Enabled",
        "New Student",
        "School Code",
        "Enrollment Number",
        "First Name",
        "Middle Name",
        "Last Name",
        "Grade",
        "Section",
        "Joining Date",
        "Student Email Address",
        "Date of Birth",
        "Blood Group",
        "Student Mobile Number",
        "Gender",
        "Nationality",
        "Customer Group",

        # ---------------- SHIPPING ADDRESS ----------------
        "Shipping Address Title",
        "Shipping Address Type",
        "Shipping Address Line 1",
        "Shipping Address Line 2",
        "Shipping City",
        "Shipping State",
        "Shipping Country",
        "Shipping Postal Code",
        "Shipping Preferred",
        "Shipping Disabled",

        # ---------------- BILLING ADDRESS ----------------
        "Billing Address Title",
        "Billing Address Type",
        "Billing Address Line 1",
        "Billing Address Line 2",
        "Billing City",
        "Billing State",
        "Billing Country",
        "Billing Postal Code",
        "Billing Preferred",
        "Billing Disabled",

        # ---------------- GUARDIAN ----------------
        "Guardian Name",
        "Guardian Relation",
        "Guardian Email",
        "Guardian Phone No",
        "Guardian Alternate No",

        # ---------------- SIBLING ----------------
        "Sibling Studying in Same Institute",
        "Sibling Full Name",
        "Sibling Gender",
        "Sibling Grade",
        "Sibling Section",
        "Sibling Institution",
        "Sibling Date of Birth"
    ]

    df = pd.DataFrame(columns=columns)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Student_Import_Template_{now}.xlsx"
    file_path = frappe.get_site_path("public", "files", file_name)

    df.to_excel(file_path, index=False, engine="openpyxl")

    wb = load_workbook(file_path)
    ws = wb.active
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22

    wb.save(file_path)
    return f"/files/{file_name}"



# --------------------------------------------------------
# MASTER VALIDATION HELPERS
# --------------------------------------------------------

def get_grade(grade_name):
    if not grade_name:
        frappe.throw(_("Grade is mandatory"))
    grade_name = str(grade_name).strip()
    if not frappe.db.exists("Grade", grade_name):
        frappe.throw(_("Grade '{0}' does not exist").format(grade_name))
    return frappe.get_doc("Grade", grade_name)


def get_gender(gender_name):
    if not gender_name:
        frappe.throw(_("Gender is mandatory"))
    gender_name = str(gender_name).strip()
    if not frappe.db.exists("Gender", gender_name):
        frappe.throw(_("Gender '{0}' does not exist").format(gender_name))
    return frappe.get_doc("Gender", gender_name)


def get_customer_group(customer_group_name="Student"):
    if not customer_group_name:
        customer_group_name = "Student"
    customer_group_name = str(customer_group_name).strip()
    if not frappe.db.exists("Customer Group", customer_group_name):
        frappe.throw(
            _("Customer Group '{0}' does not exist").format(customer_group_name)
        )
    return frappe.get_doc("Customer Group", customer_group_name)



def student_exists(school_code, enrollment_number):
    return frappe.db.exists(
        "Students",
        {
            "school_code": school_code,
            "enrollment_number": enrollment_number
        }
    )


def validate_school(school_code):
    school_code = str(school_code).strip()
    if not frappe.db.exists("School", {"school_code": school_code}):
        matched_code = frappe.db.get_value("School", {"school_name": school_code}, "school_code")
        if not matched_code and frappe.db.exists("School", school_code):
            matched_code = frappe.db.get_value("School", school_code, "school_code")
        if not matched_code:
            frappe.throw(
                _("School with School Code '{0}' does not exist").format(school_code)
            )




# --------------------------------------------------------
# GUARDIAN HELPERS
# --------------------------------------------------------

def validate_mobile(number):
    """
    Remove non-digits.
    Accept:
      - 10 digit number
      - OR 12 digit starting with 91 → convert to 10 digit
    """
    number = re.sub(r"\D", "", str(number or ""))

    # handle +91 / 91 prefix
    if len(number) == 12 and number.startswith("91"):
        number = number[2:]

    if len(number) == 10:
        return number

    return None

def get_guardian_by_mobile(mobile_number):
    if not mobile_number:
        return None
    guardian_name = frappe.db.get_value("Guardians", {"mobile_number": mobile_number}, "name")
    return frappe.get_doc("Guardians", guardian_name) if guardian_name else None


def create_guardian(guardian_data):
    """
    DB INSERTION ALLOWED HERE
    Unique key = mobile_number
    """
    guardian = frappe.new_doc("Guardians")
    guardian.guardian_name = guardian_data.get("guardian_name")
    guardian.email_address = guardian_data.get("email")
    guardian.mobile_number = guardian_data.get("phone_no")
    guardian.alternate_mobile_number = guardian_data.get("alternate_no")
    guardian.relation = guardian_data.get("relation")
    guardian.insert(ignore_permissions=True)
    return guardian


# --------------------------------------------------------
# MAIN STUDENT IMPORT
# --------------------------------------------------------
@frappe.whitelist()
def upload_student_excel(file_url):
    """
    Construct + INSERT Students with Guardian, Sibling, and Child Table Addresses
    Atomic transaction:
    - Invalid School → FULL rollback
    - Duplicate (school_code + enrollment) → skip row
    """

    import pandas as pd
    from frappe import _

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = frappe.get_site_path(
        "private" if file_doc.is_private else "public",
        "files",
        file_doc.file_name
    )

    df = pd.read_excel(file_path).fillna("")

    summary = {
        "success_count": 0,
        "failed_count": 0,
        "total_count": len(df)
    }

    students_map = {}
    response = []

    # --------------------------------------------------------
    # FIELD MAPPINGS
    # --------------------------------------------------------

    STUDENT_FIELDS = {
        "Enabled": "enabled",
        "New Student": "is_new_student",
        "School Code": "school_code",
        "Enrollment Number": "enrollment_number",
        "First Name": "first_name",
        "Middle Name": "middle_name",
        "Last Name": "last_name",
        "Grade": "grade",
        "Section": "section",
        "Joining Date": "joining_date",
        "Student Email Address": "student_email_id",
        "Date of Birth": "date_of_birth",
        "Blood Group": "blood_group",
        "Student Mobile Number": "student_mobile_number",
        "Nationality": "nationality",
        "Gender": "gender",
        "Customer Group": "customer_group",
    }

    BILLING_ADDRESS_FIELDS = {
        "Billing Address Title": "address_title",
        "Billing Address Type": "address_type",
        "Billing Address Line 1": "address_line_1",
        "Billing Address Line 2": "address_line_2",
        "Billing City": "city",
        "Billing Country": "country",
        "Billing State": "state",
        "Billing Postal Code": "pincode",
        "Billing Preferred": "preferred",
        "Billing Disabled": "disabled"
    }

    SHIPPING_ADDRESS_FIELDS = {
        "Shipping Address Title": "address_title",
        "Shipping Address Type": "address_type",
        "Shipping Address Line 1": "address_line_1",
        "Shipping Address Line 2": "address_line_2",
        "Shipping City": "city",
        "Shipping Country": "country",
        "Shipping State": "state",
        "Shipping Postal Code": "pincode",
        "Shipping Preferred": "preferred",
        "Shipping Disabled": "disabled"
    }

    GUARDIAN_FIELDS = {
        "Guardian Name": "guardian_name",
        "Guardian Email": "email",
        "Guardian Phone No": "phone_no",
        "Guardian Alternate No": "alternate_no",
        "Guardian Relation": "relation"
    }

    SIBLING_FIELDS = {
        "Sibling Full Name": "full_name",
        "Sibling Gender": "gender",
        "Sibling Grade": "grade",
        "Sibling Section": "section",
        "Sibling Institution": "institution",
        "Sibling Date of Birth": "date_of_birth",
        "Sibling Studying in Same Institute": "studying_in_same_institute"
    }

    # --------------------------------------------------------
    # PRE-VALIDATION
    # --------------------------------------------------------

    missing_refs = set()

    for idx, row in df.iterrows():
        grade = row.get("Grade")
        gender = row.get("Gender")
        customer_group = row.get("Customer Group")
        school_code = str(row.get("School Code")).strip()

        if school_code:
            validate_school(school_code)

        if grade:
            get_grade(grade)

        if gender:
            get_gender(gender)

        if customer_group:
            get_customer_group(customer_group)


    if missing_refs:
        frappe.throw(_("Reference data missing: {0}").format(", ".join(sorted(missing_refs))))

    # --------------------------------------------------------
    # PROCESS WITH TRANSACTION
    # --------------------------------------------------------

    try:
        frappe.db.begin()

        for idx, row in df.iterrows():
            enrollment = str(row.get("Enrollment Number")).strip()
            school_code = str(row.get("School Code")).strip()

            if not enrollment:
                frappe.throw(_("Enrollment Number missing at row {0}").format(idx + 2))

            if not school_code:
                frappe.throw(_("School Code missing at row {0}").format(idx + 2))

            # ❌ Duplicate → Skip only this row
            if student_exists(school_code, enrollment):
                summary["failed_count"] += 1
                response.append({
                    "enrollment_number": enrollment,
                    "school_code": school_code,
                    "rows": [idx + 2],
                    "status": "Skipped",
                    "reason": "Student already exists for this School Code"
                })
                continue

            if enrollment not in students_map:
                students_map[enrollment] = {
                    "row_numbers": [idx + 2],
                    "student": {},
                    "guardians": [],
                    "siblings": [],
                    "billing_addresses": [],
                    "shipping_addresses": []
                }

                student = students_map[enrollment]["student"]

                for col, field in STUDENT_FIELDS.items():
                    if col in row and row[col] != "":
                        student[field] = row[col]

                grade_doc = get_grade(row.get("Grade"))
                gender_doc = get_gender(row.get("Gender"))
                customer_group_doc = get_customer_group(row.get("Customer Group"))

                student["grade"] = grade_doc.name if grade_doc else None
                student["gender"] = gender_doc.name if gender_doc else None
                student["customer_group"] = customer_group_doc.name if customer_group_doc else None

            else:
                students_map[enrollment]["row_numbers"].append(idx + 2)

            guardian_payload = {
                field: row[col]
                for col, field in GUARDIAN_FIELDS.items()
                if col in row and row[col] != ""
            }

            # if guardian_payload:
            #     mobile = guardian_payload.get("phone_no")
            #     guardian_doc = get_guardian_by_mobile(mobile)
            #     if not guardian_doc:
            #         guardian_doc = create_guardian(guardian_payload)

            #     students_map[enrollment]["guardians"].append({
            #         "guardian": guardian_doc.name,
            #         "relation": guardian_payload.get("relation")
            #     })
            if guardian_payload:

                guardian_name = guardian_payload.get("guardian_name")
                mobile = validate_mobile(guardian_payload.get("phone_no"))

                if not guardian_name:
                    frappe.throw(_("Guardian Name missing at row {0}").format(idx + 2))

                if not mobile:
                    frappe.throw(_("Guardian Phone No missing at row {0}").format(idx + 2))

                guardian_doc = get_guardian_by_mobile(mobile)

                if not guardian_doc:
                    guardian_doc = create_guardian(guardian_payload)

                students_map[enrollment]["guardians"].append({
                    "guardian": guardian_doc.name,
                    "relation": guardian_payload.get("relation")
                })

            sibling_payload = {}
            for col, field in SIBLING_FIELDS.items():
                if col in row and row[col] != "":
                    value = row[col]
                    if field == "studying_in_same_institute":
                        value = str(value).strip().upper()
                        if value not in ("YES", "NO"):
                            frappe.throw(
                                _("Invalid value '{0}' for Studying in Same Institute at row {1}")
                                .format(row[col], idx + 2)
                            )
                    sibling_payload[field] = value

            if sibling_payload and len(sibling_payload) > 1:
                students_map[enrollment]["siblings"].append(sibling_payload)

            billing_payload = {
                field: row[col]
                for col, field in BILLING_ADDRESS_FIELDS.items()
                if col in row and row[col] != ""
            }

            if billing_payload:
                students_map[enrollment]["billing_addresses"].append(billing_payload)

            shipping_payload = {
                field: row[col]
                for col, field in SHIPPING_ADDRESS_FIELDS.items()
                if col in row and row[col] != ""
            }

            if shipping_payload:
                students_map[enrollment]["shipping_addresses"].append(shipping_payload)

        # --------------------------------------------------------
        # INSERT STUDENTS
        # --------------------------------------------------------

        for enrollment, data in students_map.items():
            student_doc = frappe.new_doc("Students")
            student_doc.update(data["student"])

            for g in data["guardians"]:
                student_doc.append("guardians", g)

            for s in data["siblings"]:
                student_doc.append("siblings", s)

            billing_preferred_set = False
            for b in data["billing_addresses"]:
                b["preferred"] = 1 if not billing_preferred_set else 0
                billing_preferred_set = True
                student_doc.append("student_billing_addresses", b)

            shipping_preferred_set = False
            for sh in data["shipping_addresses"]:
                sh["preferred"] = 1 if not shipping_preferred_set else 0
                shipping_preferred_set = True
                student_doc.append("student_shipping_addresses", sh)

            student_doc.insert(ignore_permissions=True)

            summary["success_count"] += 1
            response.append({
                "enrollment_number": enrollment,
                "rows": data["row_numbers"],
                "status": "Inserted",
                "student": student_doc.name
            })

        frappe.db.commit()

    except Exception as e:
        frappe.db.rollback()
        frappe.throw(_("Import failed: {0}").format(str(e)))

    return {
        "message": f"Imported {summary['success_count']} students successfully",
        "summary": summary,
        "result": response
    }


@frappe.whitelist()
def preview_student_excel(file_url):
    """
    Preview the student Excel import structure before actual insertion.
    Returns parsed student data with guardians, siblings, and addresses.
    """

    import pandas as pd
    from frappe import _

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = frappe.get_site_path(
        "private" if file_doc.is_private else "public",
        "files",
        file_doc.file_name
    )

    df = pd.read_excel(file_path).fillna("")

    students_map = {}

    # --------------------------------------------------------
    # FIELD MAPPINGS
    # --------------------------------------------------------
    STUDENT_FIELDS = {
        "Enabled": "enabled",
        "New Student": "is_new_student",
        "School Code": "school_code",
        "Enrollment Number": "enrollment_number",
        "First Name": "first_name",
        "Middle Name": "middle_name",
        "Last Name": "last_name",
        "Grade": "grade",
        "Section": "section", 
        "Joining Date": "joining_date",
        "Student Email Address": "student_email_id",
        "Date of Birth": "date_of_birth",
        "Blood Group": "blood_group",
        "Student Mobile Number": "student_mobile_number",
        "Nationality": "nationality",
        "Gender": "gender",
        "Customer Group": "customer_group"
    }

    BILLING_ADDRESS_FIELDS = {
        "Billing Address Title": "address_title",
        "Billing Address Type": "address_type",
        "Billing Address Line 1": "address_line_1",
        "Billing Address Line 2": "address_line_2",
        "Billing City": "city",
        "Billing Country": "country",
        "Billing State": "state",
        "Billing Postal Code": "postal_code",
        "Billing Preferred": "preferred",
        "Billing Disabled": "disabled"
    }

    SHIPPING_ADDRESS_FIELDS = {
        "Shipping Address Title": "address_title",
        "Shipping Address Type": "address_type",
        "Shipping Address Line 1": "address_line_1",
        "Shipping Address Line 2": "address_line_2",
        "Shipping City": "city",
        "Shipping Country": "country",
        "Shipping State": "state",
        "Shipping Postal Code": "postal_code",
        "Shipping Preferred": "preferred",
        "Shipping Disabled": "disabled"
    }

    GUARDIAN_FIELDS = {
        "Guardian Name": "guardian_name",
        "Guardian Email": "email",
        "Guardian Phone No": "phone_no",
        "Guardian Alternate No": "alternate_no",
        "Guardian Relation": "relation"
    }

    SIBLING_FIELDS = {
        "Sibling Full Name": "full_name",
        "Sibling Gender": "gender",
        "Sibling Grade": "grade",
        "Sibling Section": "section",
        "Sibling Institution": "institution",
        "Sibling Date of Birth": "date_of_birth",
        "Sibling Studying in Same Institute": "studying_in_same_institute"
    }

    # --------------------------------------------------------
    # PARSE EXCEL
    # --------------------------------------------------------
    for idx, row in df.iterrows():
        enrollment = str(row.get("Enrollment Number")).strip()
        if not enrollment:
            continue  # skip empty enrollment

        if enrollment not in students_map:
            students_map[enrollment] = {
                "row_numbers": [idx + 2],
                "student": {},
                "guardians": [],
                "siblings": [],
                "billing_addresses": [],
                "shipping_addresses": []
            }

            student = students_map[enrollment]["student"]

            # Student fields
            for col, field in STUDENT_FIELDS.items():
                if col in row and row[col] != "":
                    student[field] = row[col]

            # Attach references if exists
            grade_doc = get_grade(row.get("Grade"))
            gender_doc = get_gender(row.get("Gender"))
            customer_group_doc = get_customer_group(row.get("Customer Group"))

            student["grade"] = grade_doc.name if grade_doc else None
            student["gender"] = gender_doc.name if gender_doc else None
            student["customer_group"] = customer_group_doc.name if customer_group_doc else None

        else:
            students_map[enrollment]["row_numbers"].append(idx + 2)

        # Guardians
        guardian_payload = {field: row[col] for col, field in GUARDIAN_FIELDS.items() if col in row and row[col] != ""}
        if guardian_payload:
            students_map[enrollment]["guardians"].append(guardian_payload)

        # Siblings
        sibling_payload = {}
        for col, field in SIBLING_FIELDS.items():
            if col in row and row[col] != "":
                value = row[col]
                if field == "studying_in_same_institute":
                    value = str(value).strip().upper()
                    if value not in ("YES", "NO"):
                        value = None
                sibling_payload[field] = value
        if sibling_payload and len(sibling_payload) > 1:
            students_map[enrollment]["siblings"].append(sibling_payload)

        # Billing Addresses
        billing_payload = {field: row[col] for col, field in BILLING_ADDRESS_FIELDS.items() if col in row and row[col] != ""}
        if billing_payload:
            students_map[enrollment]["billing_addresses"].append(billing_payload)

        # Shipping Addresses
        shipping_payload = {field: row[col] for col, field in SHIPPING_ADDRESS_FIELDS.items() if col in row and row[col] != ""}
        if shipping_payload:
            students_map[enrollment]["shipping_addresses"].append(shipping_payload)

    # --------------------------------------------------------
    # RETURN STRUCTURE
    # --------------------------------------------------------
    return students_map



@frappe.whitelist()
def get_student_doctype_keys():
    """
    Return fieldnames for Student and its child tables
    """

    result = {}

    # -------------------------
    # Student (Parent)
    # -------------------------
    student_meta = frappe.get_meta("Students")

    result["student"] = [
        {
            "label": df.label,
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "reqd": df.reqd
        }
        for df in student_meta.fields
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
    ]

    # -------------------------
    # Guardians (Child Table)
    # -------------------------
    guardian_meta = frappe.get_meta("Student Guardians")

    result["guardians"] = [
        {
            "label": df.label,
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "reqd": df.reqd
        }
        for df in guardian_meta.fields
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
    ]

    # -------------------------
    # Siblings (Child Table)
    # -------------------------
    sibling_meta = frappe.get_meta("Students Siblings")

    result["siblings"] = [
        {
            "label": df.label,
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "reqd": df.reqd
        }
        for df in sibling_meta.fields
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
    ]

    # -------------------------
    # Siblings (Child Table)
    # -------------------------
    sibling_meta = frappe.get_meta("Student Billing Address")

    result["student_billing_addresses"] = [
        {
            "label": df.label,
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "reqd": df.reqd
        }
        for df in sibling_meta.fields
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
    ]

    # -------------------------
    # Siblings (Child Table)
    # -------------------------
    sibling_meta = frappe.get_meta("Student Shipping Address")

    result["student_shipping_addresses"] = [
        {
            "label": df.label,
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "reqd": df.reqd
        }
        for df in sibling_meta.fields
        if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
    ]

    return result

    