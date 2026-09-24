# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/tasks.py
"""
Scheduled tasks for logistics
"""

import frappe
from frappe.utils import now_datetime, add_to_date

def auto_track_shipments():
    """Auto track shipments periodically"""
    try:
        settings = frappe.get_single("Logistics Settings")
        
        if not settings.auto_track_shipment:
            return
        
        # Get shipments that need tracking (not delivered or cancelled)
        shipments = frappe.get_all(
            "Handover To Logistics",
            filters={
                "logistics_tracking_number": ["!=", ""],
                "carrier_status": ["not in", ["Delivered", "Cancelled", "RTO"]]
            },
            fields=["name", "logistics_tracking_number", "logistics_partner"]
        )
        
        for shipment in shipments:
            try:
                frappe.enqueue(
                    "impressio.material_out.api.logistics.utils.track_shipment",
                    docname=shipment.name,
                    queue="short",
                    timeout=60
                )
            except:
                pass
        
        frappe.log_error(
            title="Auto Track Shipments",
            message=f"Auto-tracked {len(shipments)} shipments"
        )
        
    except Exception as e:
        frappe.log_error(title="Auto Track Failed", message=str(e))

def cleanup_old_data():
    """Cleanup old logistics data"""
    try:
        # Delete old error logs (older than 30 days)
        thirty_days_ago = add_to_date(now_datetime(), days=-30)
        
        frappe.db.sql("""
            DELETE FROM `tabError Log` 
            WHERE creation < %s 
            AND method LIKE '%%logistics%%'
        """, thirty_days_ago)
        
    except Exception as e:
        frappe.log_error(title="Cleanup Failed", message=str(e))