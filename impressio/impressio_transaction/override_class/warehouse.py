import frappe
import re
import qrcode
import base64
import json
from io import BytesIO

@frappe.whitelist()
def generate_warehouse_qr(qr_data):
    """Generate QR for Warehouse"""
    try:
        if isinstance(qr_data, str):
            qr_info = frappe._dict(json.loads(qr_data))
        else:
            qr_info = frappe._dict(qr_data)

        qr_content = f"""
            WAREHOUSE: {qr_info.warehouse_name}
            WAREHOUSE ID: {qr_info.warehouse_id}
            PARENT: {qr_info.parent_warehouse}
            TYPE: {qr_info.warehouse_type}
            TIME: {qr_info.timestamp}
            """

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return {'qr_image': img_str}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Warehouse QR Error")
        frappe.throw(f"Failed to generate warehouse QR: {str(e)}")
