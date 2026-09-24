import frappe
from frappe.model.document import Document

class OrderProcessingAgainstWebsiteOrdersTable(Document):
    def validate(self):
        """Validate child table fields"""
        if self.item_code:
            # Ensure item exists
            if not frappe.db.exists('Item', self.item_code):
                frappe.throw(f"Item {self.item_code} does not exist")
            
            # Auto-populate fields if empty
            if not self.item_name:
                self.item_name = frappe.db.get_value('Item', self.item_code, 'item_name')
            
            if not self.category:
                self.category = frappe.db.get_value('Item', self.item_code, 'item_group')
            
            if not self.batch_no:
                batch_series = frappe.db.get_value('Item', self.item_code, 'batch_number_series')
                if batch_series:
                    self.batch_no = batch_series