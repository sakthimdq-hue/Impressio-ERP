# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/doctype/logistics_settings/logistics_settings.py
"""
Logistics Settings Controller
"""

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import get_url

class LogisticsSettings(Document):
    def validate(self):
        """Validate settings"""
        # Update webhook URL
        site_url = get_url()
        self.webhook_url = f"{site_url}/api/method/impressio.material_out.api.logistics.webhooks.handle_webhook"
        
        # Validate pincode
        if self.warehouse_pincode and len(str(self.warehouse_pincode)) != 6:
            frappe.throw(_("Warehouse pincode must be 6 digits"))
    
    def on_update(self):
        """After saving settings"""
        frappe.msgprint(_("Logistics Settings updated successfully"), alert=True)