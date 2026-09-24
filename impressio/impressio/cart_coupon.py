import frappe
import pandas as pd
from datetime import datetime

@frappe.whitelist()
def download_coupon_template():

    columns = [
        "Coupon Code",
        "Is Active",
        "School",
        "Student",
        "One Time Use",
        "Customer can use multiple times",
        "Discount Type",
        "Discount",
        "Maximum Discount Amount",
        "Start Datetime",
        "End Datetime"
    ]

    df = pd.DataFrame(columns=columns)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Coupon_Import_Template_{now}.xlsx"
    file_path = frappe.get_site_path("public", "files", file_name)

    df.to_excel(file_path, index=False, engine="openpyxl")

    return f"/files/{file_name}"



@frappe.whitelist()
def upload_coupon_excel(file_url):

    import pandas as pd
    from frappe.utils import now_datetime, get_datetime, flt

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = frappe.get_site_path(
        "private" if file_doc.is_private else "public",
        "files",
        file_doc.file_name
    )

    df = pd.read_excel(file_path).fillna("")

    required_fields = ["Coupon Code", "Discount Type", "Discount"]

    summary = {
        "total": len(df),
        "success": 0,
        "failed": 0
    }

    errors = []
    success_rows = []

    # ---------------- PROCESS EACH ROW ----------------
    for idx, row in df.iterrows():
        row_no = idx + 2
        row_errors = []

        # ----- Mandatory -----
        for field in required_fields:
            if not str(row.get(field)).strip():
                row_errors.append(f"Missing mandatory field '{field}'")

        coupon_code = str(row.get("Coupon Code")).strip()

        # ----- Duplicate -----
        if coupon_code and frappe.db.exists("Website Cart Coupon", coupon_code):
            row_errors.append(f"Coupon already exists ({coupon_code})")
            

        # ----- Discount Type (case insensitive) -----
        discount_type = str(row.get("Discount Type")).strip().lower()

        if discount_type == "fixed":
            discount_type = "Fixed"
        elif discount_type == "percentage":
            discount_type = "Percentage"
        else:
            row_errors.append("Discount Type must be Fixed or Percentage")

        # ----- Discount -----
        discount = flt(row.get("Discount"))

        if discount <= 0:
            row_errors.append("Discount must be greater than 0")

        if discount_type == "Percentage" and discount > 100:
            row_errors.append("Percentage discount cannot exceed 100")

        # ----- Checkbox Rule -----
        one_time = str(row.get("One Time Use")).strip().upper() in ("1","YES","TRUE")
        multi_use = str(row.get("Customer can use multiple times")).strip().upper() in ("1","YES","TRUE")

        if one_time and multi_use:
            row_errors.append("Cannot enable both One Time Use and Multiple Use")

        # ----- Dates (Optional) -----
        start_dt = None
        end_dt = None

        start = row.get("Start Datetime")
        end = row.get("End Datetime")

        try:
            if str(start).strip():
                start_dt = get_datetime(start)

            if str(end).strip():
                end_dt = get_datetime(end)

            # validate only if both exist
            if start_dt and end_dt and end_dt < start_dt:
                row_errors.append("End Datetime must be after Start Datetime")

        except Exception:
            row_errors.append("Invalid date format (use: YYYY-MM-DD HH:MM:SS)")


        # ----- If Errors → collect -----
        if row_errors:
            summary["failed"] += 1
            for err in row_errors:
                errors.append({
                    "row": row_no,
                    "error": err
                })
            continue

        # ----- INSERT -----
        try:
            doc = frappe.new_doc("Website Cart Coupon")

            doc.coupon_code = coupon_code
            doc.discount_type = discount_type
            doc.discount = discount

            doc.is_active = 1

            doc.school = row.get("School") or None
            doc.student = row.get("Student") or None

            doc.one_time_use = 1 if one_time else 0
            doc.can_use_multiple_times = 1 if multi_use else 0

            doc.start_datetime = start_dt
            doc.end_datetime = end_dt

            max_amt = row.get("Maximum Discount Amount")
            doc.maximum_discount_amount = flt(max_amt) if max_amt else None

            doc.insert(ignore_permissions=True)

            summary["success"] += 1
            success_rows.append(row_no)

        except Exception as e:
            summary["failed"] += 1
            errors.append({
                "row": row_no,
                "error": str(e)
            })

    return {
        "summary": summary,
        "errors": errors,
        "inserted_rows": success_rows
    }
