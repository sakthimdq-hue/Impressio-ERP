import frappe
from frappe.model.document import Document

class DispatchOfOrdersTable(Document):
    def validate(self):
        self.validate_quantity()
        self.validate_rate()
        self.calculate_amount()
    
    def validate_quantity(self):
        if self.qty and self.qty <= 0:
            frappe.throw("Quantity must be greater than 0")
    
    def validate_rate(self):
        if self.rate and self.rate < 0:
            frappe.throw("Rate cannot be negative")
    
    def calculate_amount(self):
        if self.qty and self.rate:
            self.amount = self.qty * self.rate
        else:
            self.amount = 0