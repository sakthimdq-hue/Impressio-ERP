# inventre/overrides/sales_invoice/sales_invoice.py

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
import frappe
from frappe.utils.background_jobs import enqueue
from frappe import _
from frappe.utils import flt, nowdate


class CustomSalesInvoice(SalesInvoice):

    def validate(self):
        super().validate()
        # Only validate if packing_reference is set
        if not getattr(self, "packing_reference", None):
            return

        # Link packing quantities
        packing = frappe.get_doc("Packing Of orders", self.packing_reference)
        packed_map = {}
        for p in packing.table:
            item_code = p.product or p.barcode or "UNKNOWN"
            packed_map[item_code] = packed_map.get(item_code, 0) + (p.qty or 0)

        for si in self.items:
            if si.qty > packed_map.get(si.item_code, 0):
                frappe.throw(f"Qty for {si.item_code} exceeds packed quantity")

    def on_submit(self):
        # Link Packing to this Sales Invoice
        if getattr(self, "packing_reference", None):
            packing = frappe.get_doc("Packing Of orders", self.packing_reference)
            packing.sales_invoice = self.name
            packing.save(ignore_permissions=True)

@frappe.whitelist()
def create_handover_from_si(sales_invoice):
    """Create Handover from Sales Invoice - FIXED with correct field names"""
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)

        # Check if already exists
        existing = frappe.db.exists("Handover To Logistics", {"sales_invoice": sales_invoice})
        if existing:
            frappe.throw(f"Handover already exists: {existing}")

        # Get logistics settings
        settings = frappe.get_single("Logistics Settings")

        handover = frappe.new_doc("Handover To Logistics")

        # === CRITICAL: Status MUST be Draft ===
        handover.status = "Draft"


        if not settings.default_carrier:
         frappe.throw(_("Default Logistics Partner is not set in Logistics Settings"))

        handover.logistics_partner = settings.default_carrier

        # Set default carrier from settings
        # if settings.default_carrier:
        #     handover.logistics_partner = settings.default_carrier

        # Carrier status
        handover.carrier_status = "Pending"

        # === BASIC INFORMATION ===
        # CRITICAL FIX: Set ALL invoice reference fields consistently
        handover.sales_invoice = sales_invoice  # PRIMARY field for linking
        handover.order_no = sales_invoice        # For compatibility/UI display
        handover.invoice_number = sales_invoice  # For reports/filtering

        handover.customer_name = si.customer_name or si.customer

        # Phone number - Use correct field names
        # Try common phone field names in Sales Invoice
        phone_fields = [
            'contact_phone', 'contact_mobile', 'mobile_no', 
            'phone', 'customer_phone', 'customer_mobile'
        ]

        customer_phone = None
        for field in phone_fields:
            if hasattr(si, field) and getattr(si, field):
                customer_phone = getattr(si, field)
                break

        if customer_phone:
            handover.customer_phone = customer_phone

        # === ADDRESS FROM SALES INVOICE ===
        address_name = si.shipping_address_name or si.customer_address
        if address_name:
            try:
                address = frappe.get_doc("Address", address_name)
                # Build address lines
                address_lines = []
                if address.address_line1:
                    address_lines.append(address.address_line1)
                if address.address_line2:
                    address_lines.append(address.address_line2)

                handover.address = "\n".join(address_lines)
                handover.pincode = address.pincode or settings.warehouse_pincode or "560001"
                handover.city = address.city or ""
                handover.state = address.state or ""
                handover.location = address.city or ""

                # Also try to get phone from address
                if not customer_phone and address.phone:
                    handover.customer_phone = address.phone
            except:
                # Fallback to warehouse address from settings
                handover.address = settings.warehouse_address or "Default Warehouse Address"
                handover.pincode = settings.warehouse_pincode or "560001"
        else:
            # Use warehouse address from settings
            handover.address = settings.warehouse_address or "Default Warehouse Address"
            handover.pincode = settings.warehouse_pincode or "560001"

        # === PACKING MATERIALS FROM SALES INVOICE ITEMS ===
        for item in si.items:
            handover.append("packing_materials", {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": item.qty,
                "uom": item.uom,
                "pm_weight": item.weight_per_unit or 0.5,
                # Dimensions will be filled by user
                "pm_length": 0,
                "pm_width": 0,
                "pm_height": 0
            })

        # === FINANCIAL VALUES ===
        handover.declared_value = si.grand_total or 0
        handover.invoice_value = si.grand_total or 0

        # Payment type
        if si.is_return or (si.outstanding_amount and si.outstanding_amount > 0):
            handover.payment_type = "COD"
            handover.cod_amount = si.outstanding_amount or 0
        else:
            handover.payment_type = "Prepaid"
            handover.cod_amount = 0

        # Dates
        handover.handover_date = frappe.utils.today()
        handover.handover_time = frappe.utils.nowtime()

        # Save the document
        handover.insert(ignore_permissions=True)

        # Mark Sales Invoice
        frappe.db.set_value("Sales Invoice", sales_invoice, "custom_handover_created", 1)
        frappe.db.commit()

        # Return success with redirect to EDIT mode
        return {
            "success": True,
            "handover": handover.name,
            "redirect": f"/app/handover-to-logistics/{handover.name}/edit",
            "message": f"Handover created: {handover.name}"
        }

    except Exception as e:
        import traceback
        frappe.log_error(
            title="Create Handover from SI Failed",
            message=f"SI: {sales_invoice}\nError: {str(e)}\n{traceback.format_exc()}"
        )
        frappe.throw(_("Failed to create handover: {0}").format(str(e)))


def enqueue_submit_dispatch(dispatch_name, sales_invoice):
    """Enqueue dispatch submission in background"""
    try:
        enqueue(
            method=submit_dispatch_background,
            queue='default',
            timeout=300,
            is_async=True,
            at_front=False,  # Don't put at front of queue
            job_name=f"submit_dispatch_{dispatch_name}",
            dispatch_name=dispatch_name,
            sales_invoice=sales_invoice
        )
    except Exception as e:
        frappe.log_error(
            message=f"Failed to enqueue dispatch submission for {dispatch_name}: {str(e)}",
            title="Dispatch Enqueue Failed"
        )


def submit_dispatch_background(dispatch_name, sales_invoice):
    """Submit Dispatch in background job"""
    try:
        # Start a new transaction for background job
        frappe.db.begin()

        # Reload the document in background context
        dispatch = frappe.get_doc("Dispatch Of Orders", dispatch_name)

        # Check if dispatch still exists and is draft
        if dispatch and dispatch.docstatus == 0:
            # Submit the dispatch
            dispatch.submit()

            # Update status
            frappe.db.set_value("Sales Invoice", sales_invoice, 
                "dispatch_status", "Submitted")

            frappe.db.commit()

            # Log success
            frappe.publish_realtime(
                event='msgprint',
                message=f'Dispatch {dispatch_name} submitted successfully!',
                user=frappe.session.user
            )

            frappe.logger().info(f"Dispatch {dispatch_name} submitted successfully for SI {sales_invoice}")

        else:
            frappe.logger().warning(f"Dispatch {dispatch_name} not found or already submitted")

    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Failed to submit dispatch {dispatch_name}: {str(e)}"
        frappe.log_error(
            message=error_msg,
            title="Dispatch Submission Failed"
        )

        # Update status to failed
        frappe.db.set_value("Sales Invoice", sales_invoice, 
            "dispatch_status", "Failed")
        frappe.db.commit()

        # Notify user
        frappe.publish_realtime(
            event='msgprint',
            message=f'Failed to submit Dispatch {dispatch_name}: {str(e)}',
            user=frappe.session.user
        )


def get_default_warehouse(company):
    """Get default warehouse for company"""
    try:
        # Try to get default warehouse from company
        warehouse = frappe.db.get_value("Warehouse", {
            "company": company,
            "is_group": 0
        }, "name", order_by="creation")

        if not warehouse:
            # Get any warehouse
            warehouse = frappe.db.get_value("Warehouse", 
                {"is_group": 0}, "name", order_by="creation")

        return warehouse or "Stores - Default"
    except:
        return "Stores - Default"