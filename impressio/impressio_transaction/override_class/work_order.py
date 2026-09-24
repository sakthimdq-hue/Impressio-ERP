import frappe

@frappe.whitelist()
def generate_work_order_qr(qr_data):
    import qrcode
    import base64
    from io import BytesIO
    import json

    data = json.loads(qr_data)

    # Only production_item stored
    qr_payload = {
        "work_order": data.get("work_order"),
    }

    qr = qrcode.make(json.dumps(qr_payload))
    buffer = BytesIO()
    qr.save(buffer, format="PNG")

    return {
        "qr_image": base64.b64encode(buffer.getvalue()).decode("utf-8"),
        "production_item": data.get("production_item")
    }
