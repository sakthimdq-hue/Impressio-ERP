import frappe
from frappe.utils import today


def create_delivery_note_from_handover(handover_name):
    """Create Delivery Note from Handover To Logistics document"""
    """Create Delivery Note from Handover To Logistics document"""
    try:
        # Fetch handover document
        handover = frappe.get_doc("Handover To Logistics", handover_name)

        # FIX: Get Sales Invoice from multiple possible fields
        sales_invoice_name = None

        # Priority 1: Direct sales_invoice field
        if handover.sales_invoice:
            sales_invoice_name = handover.sales_invoice
        # Priority 2: order_no field (common in your case)
        elif handover.order_no and frappe.db.exists("Sales Invoice", handover.order_no):
            sales_invoice_name = handover.order_no
        # Priority 3: invoice_number field
        elif handover.invoice_number and frappe.db.exists("Sales Invoice", handover.invoice_number):
            sales_invoice_name = handover.invoice_number

        if not sales_invoice_name:
            frappe.log_error(
                title="Delivery Note Creation Skipped",
                message=f"No valid Sales Invoice found for Handover: {handover_name}"
            )
            return None

        si = frappe.get_doc("Sales Invoice", sales_invoice_name)

        # Avoid duplicate Delivery Notes
        if frappe.db.exists("Delivery Note", {
            "handover_to_logistics": handover.name
        }):
            return

        # Create Delivery Note
        # Create Delivery Note
        dn = frappe.new_doc("Delivery Note")

        dn.naming_series = "MAT-DN-.YYYY.-"
        dn.customer = si.customer
        dn.company = si.company
        dn.posting_date = today()
        dn.set_posting_time = 1

        # Transport info
        dn.transporter = handover.logistics_partner
        dn.lr_no = handover.logistics_tracking_number
        dn.lr_date = today()

        # Custom links (make sure fields exist)
        dn.sales_invoice = si.name
        dn.handover_to_logistics = handover.name
        dn.handover_to_logistics = handover.name

        # Copy items from Sales Invoice
        for item in si.items:
            dn.append("items", {
                "item_code": item.item_code,
                "qty": item.qty,
                "warehouse": item.warehouse,
                "rate": item.rate,
                "against_sales_order": None,   # explicitly None to avoid so_detail error
                "against_sales_invoice": si.name,
                "si_detail": item.name,
            })

        # Insert and submit
        dn.insert(ignore_permissions=True)
        dn.submit()

        # Link back to handover
        frappe.db.set_value(
            "Handover To Logistics", 
            handover.name, 
            "delivery_note", 
            dn.name
        )

        frappe.log_error(
            title="Delivery Note Created",
            message=f"Delivery Note {dn.name} created for Handover {handover_name}"
        )

        return dn

    except Exception as e:
        frappe.log_error(
            title="Delivery Note Creation Failed",
            message=f"Handover: {handover_name}\nError: {str(e)}"
        )
        # Don't throw error, just log it so shipment creation continues
        return None


def validate(doc, method=None):
    # REQUIRED for hook — do not remove
    pass
