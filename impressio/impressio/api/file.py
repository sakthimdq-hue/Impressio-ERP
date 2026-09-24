import frappe
import uuid
from frappe.utils.file_manager import save_file

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@frappe.whitelist(allow_guest=True)
def custom_image_upload():
    try:
        file = frappe.request.files.get("file")
        is_private = frappe.form_dict.get("is_private", 1)

        # convert to int safely
        is_private = int(is_private) if str(is_private).isdigit() else 1

        if not file:
            frappe.throw("No file uploaded")

        filename = file.filename
        if not filename or "." not in filename:
            frappe.throw("Invalid file name")

        ext = filename.rsplit(".", 1)[1].lower()

        if ext not in ALLOWED_EXTENSIONS:
            frappe.throw(f"Only {', '.join(ALLOWED_EXTENSIONS)} files are allowed")

        content = file.read()

        if len(content) > MAX_FILE_SIZE:
            frappe.throw("File size must be less than 5MB")

        # 🔥 unique filename
        unique_name = f"{uuid.uuid4()}.{ext}"

        # ✅ save with ignore_permissions
        file_doc = save_file(
            fname=unique_name,
            content=content,
            dt=None,
            dn=None,
            is_private=is_private
        )

        # 🔥 IMPORTANT: bypass permission explicitly
        file_doc.flags.ignore_permissions = True
        file_doc.save()

        return {
            "status": "success",
            "message": "File uploaded successfully",
            "file_url": file_doc.file_url,
            "is_private": is_private
        }

    except frappe.ValidationError as ve:
        return {
            "status": "error",
            "message": str(ve)
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Custom Image Upload Error")
        return {
            "status": "error",
            "message": "Something went wrong"
        }