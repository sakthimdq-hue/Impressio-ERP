import frappe
import math
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import check_otp, consume_otp, success, error, validate_fields, create_otp
from frappe.utils import get_url



SKIP_ITEM_GROUPS = ["Raw Material", "Finished Products"]
BOOK_ITEM_GROUPS = ["Books", "Book Bundle"]  # future use


@frappe.whitelist()
def school_profile(**kwargs):

    required = ["school"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg, 422)

    school = kwargs.get("school")

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

    # Verify guardian has at least one student in this school
    allowed = frappe.db.sql("""
        SELECT s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE 
            sg.guardian = %s
            AND sch.name = %s
        LIMIT 1
    """, (guardian, school), as_dict=True)

    if not allowed:
        return error("Unauthorized school access")

    # Fetch full school document
    doc = frappe.get_doc("School", school).as_dict()

    return success("Success", doc)



@frappe.whitelist()
def student_profile(**kwargs):

    required = ["school", "enrollment_number"]
    msg = validate_fields(kwargs, required)
    if msg:
        return error(msg, 422)

    school = kwargs.get("school")
    enrollment_number = kwargs.get("enrollment_number")

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

    student = frappe.db.sql("""
        SELECT 
            s.name
        FROM `tabStudents` s
        INNER JOIN `tabStudent Guardians` sg ON sg.parent = s.name
        INNER JOIN `tabSchool` sch ON sch.school_code = s.school_code
        WHERE 
            sg.guardian = %s
            AND sch.name = %s
            AND s.enrollment_number = %s
    """, (guardian, school, enrollment_number), as_dict=True)

    if not student:
        return error("Student not found")

    doc = frappe.get_doc("Students", student[0].name).as_dict()

    # Build full profile image path
    site_url = frappe.utils.get_url()
    if doc.get("profile_picture_attach"):
        doc["profile_picture_attach"] = site_url + doc["profile_picture_attach"]
    else:
        doc["profile_picture_attach"] = None

    return success("Success", doc)


@frappe.whitelist()
def get_customer_doctype_structure():

    meta = frappe.get_meta("Customer")

    structure = {
        "doctype": meta.name,
        "fields": [],
        "child_tables": [],
        "links": []
    }

    # All fields
    for field in meta.fields:
        structure["fields"].append({
            "fieldname": field.fieldname,
            "label": field.label,
            "fieldtype": field.fieldtype,
            "options": field.options
        })

        # Detect child tables
        if field.fieldtype == "Table":
            structure["child_tables"].append({
                "fieldname": field.fieldname,
                "child_doctype": field.options
            })

        # Detect direct links
        if field.fieldtype == "Link":
            structure["links"].append({
                "fieldname": field.fieldname,
                "linked_doctype": field.options
            })

    return success("Customer Doctype Structure", structure)



@frappe.whitelist()
def items():
    """
    Temporary testing API to fetch all Item records with related data
    """

    # Optional authentication (if you want)
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    # Fetch all Items
    items = frappe.get_all(
        "Item",
          filters={
            "disabled": 0,
            "is_sales_item": 1,
            "item_group": ["in", SKIP_ITEM_GROUPS],
            "variant_of": ["is", "not set"]
        },
        fields=["*"]
    )

    result = []

    for item in items:
        item_doc = frappe.get_doc("Item", item.name)

        item_data = item_doc.as_dict()

        # Example: Fetch related tables if they exist
        item_data["item_prices"] = frappe.get_all(
            "Item Price",
            filters={"item_code": item.name},
            fields=["price_list", "price_list_rate"]
        )

        item_data["item_defaults"] = frappe.get_all(
            "Item Default",
            filters={"parent": item.name},
            fields=["company", "default_warehouse"]
        )

        # If you have custom child tables, you can add here
        # Example:
        # item_data["custom_table"] = item_doc.custom_child_table

        result.append(item_data)

    return {
        "user": user.name if user else "Guest",
        "total_items": len(result),
        "data": result
    }





@frappe.whitelist()
def payment_modes():
    """
    Temporary testing API
    Fetch all Mode of Payment records with ALL fields
    and ALL child tables (as stored in DocType)
    """

    # Optional authentication (same pattern as your items API)
    api = BaseAPI()
    user = api.user
    if not user:
        return error("Login required", 401)

    # Fetch all Mode of Payment names
    modes = frappe.get_all("Mode of Payment", fields=["name"])

    result = []

    for m in modes:
        # get_doc automatically pulls:
        # - all parent fields
        # - all child tables (Mode of Payment Account)
        mode_doc = frappe.get_doc("Mode of Payment", m.name)
        result.append(mode_doc.as_dict())

    return {
        "user": user.name if user else "Guest",
        "total_payment_modes": len(result),
        "data": result
    }


@frappe.whitelist()
def get_sales_order_all_fields():
    """
    Test API
    Returns Sales Order parent fields AND all child table fields
    with ONLY minimal keys:
    fieldname, label, fieldtype, options, reqd
    """

    meta = frappe.get_meta("Sales Order")

    result = {
        "doctype": "Sales Order",
        "parent_fields": [],
        "child_tables": {}
    }

    # ------------------------------------------------
    # Parent fields (Sales Order)
    # ------------------------------------------------
    for df in meta.fields:
        result["parent_fields"].append({
            "fieldname": df.fieldname,
            "label": df.label,
            "fieldtype": df.fieldtype,
            "options": df.options,
            "reqd": df.reqd
        })

    # ------------------------------------------------
    # Child tables (linked DocTypes)
    # ------------------------------------------------
    for df in meta.fields:
        if df.fieldtype == "Table" and df.options:
            child_meta = frappe.get_meta(df.options)

            result["child_tables"][df.options] = {
                "parent_field": df.fieldname,
                "fields": []
            }

            for cdf in child_meta.fields:
                result["child_tables"][df.options]["fields"].append({
                    "fieldname": cdf.fieldname,
                    "label": cdf.label,
                    "fieldtype": cdf.fieldtype,
                    "options": cdf.options,
                    "reqd": cdf.reqd
                })

    return result
