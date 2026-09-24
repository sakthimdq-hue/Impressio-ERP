# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/doctype/ekart_settings/ekart_settings.py

import frappe
from frappe.model.document import Document
from frappe.utils import get_url

class EkartSettings(Document):
    def validate(self):
        """Validate and set default values"""
        # Generate webhook URL
        site_url = get_url()
        self.webhook_url = f"{site_url}/api/method/impressio.material_out.api.ekart.utils.handle_ekart_webhook"
        
        # Set API base URL
        if self.environment == "Sandbox":
            self.api_base_url = "https://api-sandbox.ekartlogistics.com"
        else:
            self.api_base_url = "https://api.ekartlogistics.com"
    
    def before_save(self):
        """Ensure single doctype saves properly"""
        # Ensure required fields have defaults
        if not self.warehouse_pincode:
            self.warehouse_pincode = "560001"
        if not hasattr(self, 'use_mock_api') or self.use_mock_api is None:
            self.use_mock_api = True