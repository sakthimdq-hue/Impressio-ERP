"""
QR Code generation and validation utilities for Items and Packing Materials

Uses PyQRCode library (version 1.2.1)
"""

import frappe
from frappe import _
import json
import base64
import hashlib
from io import BytesIO

try:
    import pyqrcode
    HAS_PYQRCODE = True
except ImportError:
    HAS_PYQRCODE = False


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def is_packing_material(item_group):
    if not item_group:
        return False
    return "packing" in item_group.lower()


# --------------------------------------------------
# QR DATA GENERATION
# --------------------------------------------------

def generate_qr_data(doc):
    """Generate QR payload for any Item"""

    packing = is_packing_material(doc.item_group)

    qr_data = {
        "type": "packing_material" if packing else "item",
        "item_code": doc.name,
        "item_name": doc.item_name,
        "weight": float(doc.pm_weight or 0),
        "cbm": float(doc.pm_cbm or 0),
    }

    # Packing-only data
    if packing:
        qr_data["dimensions"] = {
            "l": float(doc.pm_length or 0),
            "w": float(doc.pm_width or 0),
            "h": float(doc.pm_height or 0),
        }

        checksum_base = f"{doc.name}:{doc.pm_length}:{doc.pm_width}:{doc.pm_height}"
    else:
        checksum_base = f"{doc.name}:{doc.item_name}"

    qr_data["checksum"] = hashlib.sha256(
        checksum_base.encode()
    ).hexdigest()[:12]

    return qr_data


# --------------------------------------------------
# QR IMAGE GENERATION
# --------------------------------------------------

def generate_qr_code_image(qr_data):
    """Generate base64 SVG QR image"""

    if not HAS_PYQRCODE:
        frappe.log_error(
            "PyQRCode not installed. Run: pip install pyqrcode",
            "QR Code Error"
        )
        return None

    try:
        data_str = json.dumps(qr_data, separators=(",", ":"))

        qr = pyqrcode.create(
            data_str,
            error="M",
            version=None,
            mode="binary"
        )

        buffer = BytesIO()
        qr.svg(
            buffer,
            scale=8,
            quiet_zone=4,
            module_color="#000000",
            background="#ffffff"
        )

        return base64.b64encode(buffer.getvalue()).decode()

    except Exception as e:
        frappe.log_error(
            f"QR generation failed: {str(e)}",
            "QR Code Error"
        )
        return None


# --------------------------------------------------
# DOC EVENT HOOK
# --------------------------------------------------

def generate_item_qr(doc, method=None):
    """
    Auto-generate QR for ALL items
    - Packing materials → require dimensions
    - Normal items → basic QR
    """

    # Packing materials require dimensions
    if is_packing_material(doc.item_group):
        if not doc.pm_length or not doc.pm_width or not doc.pm_height:
            return

    qr_data = generate_qr_data(doc)
    qr_image = generate_qr_code_image(qr_data)

    if not qr_image:
        return

    qr_data_json = json.dumps(qr_data)
    qr_data_uri = f"data:image/svg+xml;base64,{qr_image}"

    try:
        doc.db_set("pm_qr_code", qr_data_uri, update_modified=False)
        doc.db_set("pm_qr_data", qr_data_json, update_modified=False)

        # In-memory update
        doc.pm_qr_code = qr_data_uri
        doc.pm_qr_data = qr_data_json

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Failed saving QR for {doc.name}: {str(e)}",
            "QR Save Error"
        )


# --------------------------------------------------
# QR VALIDATION
# --------------------------------------------------

@frappe.whitelist()
def validate_qr_code(qr_data_str):
    """Validate scanned QR data"""

    try:
        qr_data = json.loads(qr_data_str)

        qr_type = qr_data.get("type")
        if qr_type not in ("packing_material", "item"):
            return {"valid": False, "error": "Invalid QR code type"}

        item_code = qr_data.get("item_code")
        if not item_code:
            return {"valid": False, "error": "Missing item code"}

        if not frappe.db.exists("Item", item_code):
            return {"valid": False, "error": f"Item {item_code} not found"}

        item = frappe.get_doc("Item", item_code)

        # Validate checksum
        if qr_type == "packing_material":
            checksum_base = f"{item.name}:{item.pm_length}:{item.pm_width}:{item.pm_height}"
        else:
            checksum_base = f"{item.name}:{item.item_name}"

        expected_checksum = hashlib.sha256(
            checksum_base.encode()
        ).hexdigest()[:12]

        if qr_data.get("checksum") != expected_checksum:
            return {
                "valid": False,
                "error": "QR data mismatch (item modified)",
                "item_code": item_code,
            }

        return {
            "valid": True,
            "type": qr_type,
            "item_code": item_code,
            "item_name": item.item_name,
            "dimensions": qr_data.get("dimensions"),
            "weight": qr_data.get("weight"),
            "cbm": qr_data.get("cbm"),
        }

    except json.JSONDecodeError:
        return {"valid": False, "error": "Invalid QR format"}

    except Exception as e:
        frappe.log_error(
            f"QR validation error: {str(e)}",
            "QR Validation Error"
        )
        return {"valid": False, "error": str(e)}


# --------------------------------------------------
# CONVENIENCE API
# --------------------------------------------------

def generate_packing_material_qr(doc, method=None):  # Add method=None parameter
    """
    Auto-generate QR for ALL items
    - Packing materials → require dimensions
    - Normal items → basic QR
    """
    item_code = doc.item_code
    doc.item_code= item_code.replace('-', '')
    # Packing materials require dimensions
    if is_packing_material(doc.item_group):
        if not doc.pm_length or not doc.pm_width or not doc.pm_height:
            return

    qr_data = generate_qr_data(doc)
    qr_image = generate_qr_code_image(qr_data)

    if not qr_image:
        return

    qr_data_json = json.dumps(qr_data)
    qr_data_uri = f"data:image/svg+xml;base64,{qr_image}"

    try:
        doc.db_set("pm_qr_code", qr_data_uri, update_modified=False)
        doc.db_set("pm_qr_data", qr_data_json, update_modified=False)

        # In-memory update
        doc.pm_qr_code = qr_data_uri
        doc.pm_qr_data = qr_data_json

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Failed saving QR for {doc.name}: {str(e)}",
            "QR Save Error"
        )