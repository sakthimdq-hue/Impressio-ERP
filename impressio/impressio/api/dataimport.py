import frappe
import openpyxl
from frappe.utils import get_site_path


@frappe.whitelist(allow_guest=True)
def import_grades_details(file_url, school_name):
    """
    Import School Grade Details child table from Excel
    Deletes old data and creates fresh rows
    """

    # ------------------------------------------------
    # 0️⃣ Validation
    # ------------------------------------------------
    if not frappe.db.exists("School", school_name):
        frappe.throw(f"School not found: {school_name}")

    # ------------------------------------------------
    # 1️⃣ Load School
    # ------------------------------------------------
    school = frappe.get_doc("School", school_name)

    # ------------------------------------------------
    # 2️⃣ Resolve file path
    # ------------------------------------------------
    file_path = get_site_path("public", file_url.lstrip("/"))

    if not frappe.utils.os.path.exists(file_path):
        frappe.throw("Excel file not found on server")

    # ------------------------------------------------
    # 3️⃣ Load Excel
    # ------------------------------------------------
    wb = openpyxl.load_workbook(file_path)
    sheet = wb.active

    headers = [
        cell.value.strip() if cell.value else ""
        for cell in sheet[1]
    ]

    # ------------------------------------------------
    # 4️⃣ Header → Field mapping
    # ------------------------------------------------
    SCHOOL_GRADE_FIELDS = {
        "Grade": "grade",
        "School Given Grade Name": "school_given_grade_name",
        "Sections": "sections"
    }

    col_map = {}
    for idx, header in enumerate(headers):
        if header in SCHOOL_GRADE_FIELDS:
            col_map[idx] = SCHOOL_GRADE_FIELDS[header]

    if "grade" not in col_map.values():
        frappe.throw("Missing required column: Grade")

    # ------------------------------------------------
    # 🔥 5️⃣ DELETE OLD DATA
    # ------------------------------------------------
    school.set("grades_details", [])

    created = 0

    # ------------------------------------------------
    # 6️⃣ Iterate rows (CREATE ONLY)
    # ------------------------------------------------
    for row_idx, row in enumerate(
        sheet.iter_rows(min_row=2, values_only=True),
        start=2
    ):
        payload = {}

        for col_idx, fieldname in col_map.items():
            value = row[col_idx] if col_idx < len(row) else None
            if value not in ("", None):
                payload[fieldname] = str(value).strip()

        grade = payload.get("grade")
        if not grade:
            continue

        # Validate Grade
        if not frappe.db.exists("Grade", grade):
            frappe.throw(f"Invalid Grade '{grade}' at row {row_idx}")

        school.append("grades_details", payload)
        created += 1

    # ------------------------------------------------
    # 7️⃣ Save School
    # ------------------------------------------------
    school.save(ignore_permissions=True)

    return {
        "status": "success",
        "school": school_name,
        "created": created,
        "deleted_old_rows": True
    }
