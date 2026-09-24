import frappe
import json
from frappe.model.document import Document


class PickSlip(Document):
    pass


@frappe.whitelist()
def get_items_from_sales_orders(po_numbers):
    import json

    if not po_numbers:
        return []

    if isinstance(po_numbers, str):
        try:
            po_numbers = json.loads(po_numbers)
        except Exception:
            po_numbers = [po_numbers]

    po_numbers = list({p for p in po_numbers if p})
    if not po_numbers:
        return []

    valid_pos = frappe.get_all(
        "Sales Order", filters={"name": ["in", po_numbers]}, pluck="name"
    )

    if not valid_pos:
        frappe.log_error(
            f"Invalid PO Numbers: {po_numbers}", "Pick Slip: Invalid Sales Orders"
        )
        return []

    items = frappe.get_all(
        "Sales Order Item",
        filters={"parent": ["in", valid_pos]},
        fields=[
            "name",
            "parent",
            "idx",
            "item_code",
            "item_name",
            "qty",
            "uom",
            "warehouse",
            "transaction_date",
        ],
        order_by="parent asc, idx asc",
    )

    return items or []
