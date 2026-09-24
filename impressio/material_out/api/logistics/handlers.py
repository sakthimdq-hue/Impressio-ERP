# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/handlers.py
"""
Document event handlers for logistics
"""

import frappe
from frappe import _

def on_submit(doc, method):
    """When Handover To Logistics is submitted"""
    try:
        settings = frappe.get_single("Logistics Settings")
        
        # Auto create shipment if enabled
        if settings.auto_create_shipment and not doc.logistics_tracking_number:
            frappe.enqueue(
                "impressio.material_out.api.logistics.utils.create_shipment",
                docname=doc.name,
                queue="short",
                timeout=300
            )
            
            frappe.msgprint(
                _("Shipment creation queued for {0}").format(doc.logistics_partner),
                alert=True
            )
            
    except Exception as e:
        frappe.log_error(title="Submit Handler Failed", message=str(e))

def validate(doc, method):
    """Validate logistics document"""
    # Validate pincode
    if doc.pincode and len(str(doc.pincode)) != 6:
        frappe.throw(_("Pincode must be 6 digits"))
    
    # Validate weight
    if doc.weight and doc.weight <= 0:
        frappe.throw(_("Weight must be greater than 0"))
    
    # Validate dimensions
    for field in ['length', 'width', 'height']:
        if doc.get(field) and doc.get(field) < 0:
            frappe.throw(_("{0} cannot be negative").format(frappe.unscrub(field)))