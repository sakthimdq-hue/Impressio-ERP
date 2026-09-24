import frappe
import json
import hmac
import hashlib
from frappe import _
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def handle_ekart_webhook():
    """Handle Ekart webhook events"""
    try:
        # Verify webhook signature
        settings = frappe.get_single("Ekart Settings")
        signature = frappe.request.headers.get("X-Ekart-Signature")
        
        if settings.webhook_secret and signature:
            payload = frappe.request.get_data(as_text=True)
            expected_signature = hmac.new(
                settings.webhook_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                frappe.throw("Invalid webhook signature")
        
        # Parse payload
        data = json.loads(frappe.request.get_data())
        
        # Process webhook event
        event_type = data.get("event_type")
        shipment_data = data.get("shipment", {})
        tracking_id = shipment_data.get("tracking_id")
        
        if not tracking_id:
            return {"status": "error", "message": "No tracking ID provided"}
        
        # Find document by tracking ID
        docs = frappe.get_all(
            "Handover To Logistics",
            filters={"ekart_tracking_number": tracking_id},
            fields=["name"]
        )
        
        if not docs:
            return {"status": "error", "message": "Document not found"}
        
        docname = docs[0].name
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        # Update document based on event type
        self._process_webhook_event(doc, event_type, shipment_data)
        
        return {"status": "success", "message": "Webhook processed"}
        
    except Exception as e:
        frappe.log_error(
            title="Ekart Webhook Error",
            message=f"Error: {str(e)}\nData: {frappe.request.get_data()}"
        )
        return {"status": "error", "message": str(e)}

def _process_webhook_event(self, doc, event_type, data):
    """Process different webhook events"""
    
    event_handlers = {
        "SHIPMENT_CREATED": self._handle_shipment_created,
        "PICKED_UP": self._handle_picked_up,
        "IN_TRANSIT": self._handle_in_transit,
        "OUT_FOR_DELIVERY": self._handle_out_for_delivery,
        "DELIVERED": self._handle_delivered,
        "RTO": self._handle_rto,
        "EXCEPTION": self._handle_exception,
        "CANCELLED": self._handle_cancelled
    }
    
    handler = event_handlers.get(event_type)
    if handler:
        handler(doc, data)
    
    # Always update tracking history
    self._update_tracking_from_webhook(doc, event_type, data)

def _update_tracking_from_webhook(self, doc, event_type, data):
    """Update tracking history from webhook"""
    doc.append("ekart_tracking_history", {
        "event_time": now_datetime(),
        "event_type": event_type,
        "status": data.get("status", event_type),
        "location": data.get("location", ""),
        "remarks": data.get("remarks", data.get("description", ""))
    })
    
    # Update main status
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
    
    doc.ekart_shipment_status = status_mapping.get(event_type, "Unknown")
    
    # Set dates for specific events
    if event_type == "PICKED_UP":
        doc.ekart_pickup_date = now_datetime()
    elif event_type == "DELIVERED":
        doc.ekart_delivery_date = now_datetime()
        doc.status = "Delivered"
    
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    # Create system notification
    frappe.publish_realtime(
        event="msgprint",
        message=f"Ekart Shipment Update: {doc.ekart_tracking_number} - {event_type}",
        user=doc.owner
    )