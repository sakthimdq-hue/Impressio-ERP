# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/setup.py
"""
Setup script for logistics module
"""

import frappe
from frappe import _

def after_install():
    """Setup after module installation"""
    create_logistics_settings()
    update_handover_doctype_fields()
    frappe.db.commit()
    frappe.msgprint(_("Logistics module installed successfully!"))

def create_logistics_settings():
    """Create Logistics Settings if not exists"""
    if not frappe.db.exists("DocType", "Logistics Settings"):
        frappe.msgprint(_("Please create Logistics Settings doctype first"))
        return
    
    if not frappe.db.exists("Logistics Settings", "Logistics Settings"):
        settings = frappe.new_doc("Logistics Settings")
        settings.enable_ekart = True
        settings.use_mock_api = True
        settings.warehouse_pincode = "560001"
        settings.save()
        frappe.msgprint(_("Created default Logistics Settings"))

def update_handover_doctype_fields():
    """Add carrier fields to Handover To Logistics via custom fields"""
    custom_fields = [
        {
            "dt": "Handover To Logistics",
            "fieldname": "logistics_section",
            "fieldtype": "Section Break",
            "label": "Logistics",
            "insert_after": "status",
            "collapsible": 1
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "logistics_partner",
            "fieldtype": "Select",
            "label": "Logistics Partner",
            "options": "\nEkart\nAmazon Shipping\nShiprocket",
            "default": "Ekart",
            "reqd": 1,
            "insert_after": "logistics_section"
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "service_type",
            "fieldtype": "Select",
            "label": "Service Type",
            "options": "",
            "depends_on": "logistics_partner",
            "insert_after": "logistics_partner"
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "logistics_tracking_number",
            "fieldtype": "Data",
            "label": "Tracking Number",
            "read_only": 1,
            "insert_after": "service_type"
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "carrier_name",
            "fieldtype": "Data",
            "label": "Carrier",
            "read_only": 1,
            "insert_after": "logistics_tracking_number"
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "carrier_status",
            "fieldtype": "Select",
            "label": "Carrier Status",
            "options": "\nPending\nCreated\nPicked Up\nIn Transit\nOut for Delivery\nDelivered\nRTO\nException\nCancelled",
            "default": "Pending",
            "read_only": 1,
            "insert_after": "carrier_name"
        },
        {
            "dt": "Handover To Logistics",
            "fieldname": "carrier_response",
            "fieldtype": "Code",
            "label": "Carrier Response",
            "options": "JSON",
            "read_only": 1,
            "insert_after": "carrier_status"
        }
    ]
    
    for field_data in custom_fields:
        if not frappe.db.exists("Custom Field", {"dt": field_data["dt"], "fieldname": field_data["fieldname"]}):
            cf = frappe.new_doc("Custom Field")
            for key, value in field_data.items():
                setattr(cf, key, value)
            cf.insert()
    
    frappe.msgprint(_("Added logistics fields to Handover To Logistics"))

@frappe.whitelist()
def setup_logistics_module():
    """Setup logistics module manually"""
    try:
        after_install()
        return {"status": "success", "message": "Logistics module setup completed"}
    except Exception as e:
        frappe.log_error(title="Logistics Setup Failed", message=str(e))
        return {"status": "error", "message": str(e)}