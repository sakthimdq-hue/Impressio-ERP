# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt



import frappe
from frappe.model.document import Document
from frappe import _


class PickingForProductsagainstOrderFromracks(Document):
    def validate(self):
        self.validate_sales_order_status()
    
    def validate_sales_order_status(self):
        """Validate that the selected Sales Order is Submitted (docstatus = 1)"""
        if self.order_no:
            docstatus = frappe.db.get_value("Sales Order", self.order_no, "docstatus")
            if docstatus != 1:
                frappe.throw(_("Only Submitted Sales Orders are allowed. Selected order is not submitted."))

@frappe.whitelist()
def fetch_items(order_no):

    """Fetch items from the Sales Order and return them to the form"""
    if not order_no:
        frappe.throw("Please select an Order No first")

    # Validate docstatus
    docstatus = frappe.db.get_value("Sales Order", order_no, "docstatus")
    if docstatus != 1:
        frappe.throw("Only Submitted Sales Orders are allowed")

    sales_order = frappe.get_doc("Sales Order", order_no)
    items = []
    for item in sales_order.items:
        items.append({
            "item_code": item.item_code,
            "product_name": item.item_name,
            "batch_no": "",
            "date":item.transaction_date,
            "category": item.item_group,
            "qty": item.qty
        })

    return items


   