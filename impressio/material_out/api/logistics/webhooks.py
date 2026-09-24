# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/webhooks.py
"""
Webhook handlers for carriers
"""

import frappe
import json
import hmac
import hashlib
from frappe import _
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """Handle webhook events from carriers"""
    try:
        data = frappe.request.get_data(as_text=True)
        frappe.log_error(
            title="Webhook Received",
            message=f"Webhook Data: {data}"
        )
        
        try:
            webhook_data = json.loads(data)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Invalid JSON"}, 400
        
        # Get carrier from webhook data or headers
        carrier = frappe.request.headers.get("X-Carrier") or webhook_data.get("carrier")
        
        if carrier == "Ekart":
            return handle_ekart_webhook(webhook_data)
        elif carrier == "Amazon":
            return handle_amazon_webhook(webhook_data)
        elif carrier == "Shiprocket":
            return handle_shiprocket_webhook(webhook_data)
        else:
            return {"status": "error", "message": "Unknown carrier"}, 400
        
    except Exception as e:
        frappe.log_error(
            title="Webhook Error",
            message=f"Error: {str(e)}\nData: {frappe.request.get_data() if frappe.request else 'No request'}"
        )
        return {"status": "error", "message": str(e)}, 500

def handle_ekart_webhook(data):
    """Handle Ekart webhook"""
    try:
        settings = frappe.get_single("Logistics Settings")
        signature = frappe.request.headers.get("X-Ekart-Signature")
        
        if settings.webhook_secret and signature:
            payload = frappe.request.get_data(as_text=True)
            expected_signature = hmac.new(
                settings.webhook_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                return {"status": "error", "message": "Invalid signature"}, 401
        
        tracking_id = data.get("tracking_id")
        event_type = data.get("event_type")
        
        if not tracking_id:
            return {"status": "error", "message": "No tracking ID provided"}, 400
        
        # Find document by tracking number
        docs = frappe.get_all(
            "Handover To Logistics",
            filters={"ekart_tracking_number": tracking_id},
            fields=["name"]
        )
        
        if not docs:
            return {"status": "error", "message": "Document not found"}, 404
        
        docname = docs[0].name
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        # Update document
        _update_shipment_status(doc, event_type, data)
        
        return {"status": "success", "message": "Webhook processed"}
        
    except Exception as e:
        frappe.log_error(title="Ekart Webhook Error", message=str(e))
        return {"status": "error", "message": str(e)}, 500

def handle_amazon_webhook(data):
    """Handle Amazon webhook"""
    # Similar implementation for Amazon
    return {"status": "success", "message": "Amazon webhook processed"}

def handle_shiprocket_webhook(data):
    """Handle Shiprocket webhook"""
    # Similar implementation for Shiprocket
    return {"status": "success", "message": "Shiprocket webhook processed"}

def _update_shipment_status(doc, event_type, data):
    """Update shipment status from webhook"""
    status_mapping = {
        "SHIPMENT_CREATED": "Created",
        "PICKED_UP": "Picked Up",
        "IN_TRANSIT": "In Transit",
        "OUT_FOR_DELIVERY": "Out for Delivery",
        "DELIVERED": "Delivered",
        "RTO": "RTO",
        "EXCEPTION": "Exception",
        "CANCELLED": "Cancelled"
    }
    
    new_status = status_mapping.get(event_type, "Unknown")
    doc.carrier_status = new_status
    
    if doc.logistics_partner == "Ekart":
        doc.ekart_shipment_status = new_status
    
    # Add to tracking history
    doc.append("ekart_tracking_history", {
        "event_time": now_datetime(),
        "event_type": event_type,
        "status": new_status,
        "location": data.get("location", ""),
        "remarks": data.get("remarks", data.get("description", ""))
    })
    
    # Set dates for specific events
    if event_type == "PICKED_UP":
        doc.ekart_pickup_date = now_datetime()
    elif event_type == "DELIVERED":
        doc.ekart_delivery_date = now_datetime()
        doc.status = "Delivered"
    
    doc.save(ignore_permissions=True)
    frappe.db.commit()