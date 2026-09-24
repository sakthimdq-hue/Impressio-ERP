import frappe
from frappe import _
from frappe.model.document import Document
import json


class DispatchOfOrders(Document):
    def validate(self):
        self.validate_dates()
        self.validate_packing_no()
        self.update_customer_details()
        self.validate_table_data()
        self.set_default_iawb_status()

        if not self.sales_invoice:
            frappe.throw("Sales Invoice is mandatory before Dispatch")

        # 2. Sales Invoice must be submitted
        si = frappe.get_doc("Sales Invoice", self.sales_invoice)
        if si.docstatus != 1:
            frappe.throw("Sales Invoice must be submitted before Dispatch")

    def validate_dates(self):
        """Validate that picking date is not before dispatch date"""
        if self.dispatch_date and self.picking_date:
            if self.picking_date < self.dispatch_date:
                frappe.throw(_("Picking Date cannot be before Dispatch Date"))

    def validate_packing_no(self):
        """Validate packing number is positive"""
        if self.packing_no and self.packing_no <= 0:
            frappe.throw(_("Packing Number must be greater than 0"))

    def validate_table_data(self):
        """Validate that table has data and required fields"""
        if not self.table_ytnc:
            frappe.throw(_("Please add items in the table before saving"))

        for i, row in enumerate(self.table_ytnc):
            if not row.item_code:
                frappe.throw(_("Row {0}: Item Code is required").format(i + 1))
            if not row.qty or row.qty <= 0:
                frappe.throw(_("Row {0}: Quantity must be greater than 0").format(i + 1))
            if row.rate is not None and row.rate < 0:
                frappe.throw(_("Row {0}: Rate must be greater than or equal to 0").format(i + 1))

    def set_default_iawb_status(self):
        """Set default IAWB status if not set"""
        if not self.iawb_status:
            self.iawb_status = "Pending"

    def update_customer_details(self):
        """Auto-update customer details if customer is selected"""
        if self.customer_name:
            try:
                customer = frappe.get_doc("Customer", self.customer_name)
                # Can auto-set other customer-related fields here
            except Exception:
                pass

    def on_submit(self):
        """Actions when document is submitted"""
        # Set status to IAWB Pending when dispatch is submitted
        self.db_set("iawb_status", "IAWB Pending")

        # Update linked packing order status
        if self.packing_order:
            frappe.db.set_value("Packing Of orders", self.packing_order, "packing_status", "Dispatched")

        # Create stock entry for dispatch
        stock_entry_name = self.create_stock_entry()

        frappe.msgprint(_("Dispatch {0} submitted. IAWB Status set to 'IAWB Pending'. {1}").format(
            self.name,
            f"Stock Entry {stock_entry_name} created." if stock_entry_name else ""
        ))

    def on_cancel(self):
        """Actions when document is cancelled"""
        self.revert_dispatch_status()
        self.db_set("iawb_status", "Pending")

        # Revert packing order status
        if self.packing_order:
            frappe.db.set_value("Packing Of orders", self.packing_order, "packing_status", "Completed")

    def create_stock_entry(self):
        """Create stock entry for dispatch items (Material Issue)"""
        if not self.table_ytnc or len(self.table_ytnc) == 0:
            return None

        try:
            # Get default source warehouse
            default_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
            if not default_warehouse:
                # Try to get first warehouse
                warehouses = frappe.get_all("Warehouse", filters={"is_group": 0}, limit=1)
                default_warehouse = warehouses[0].name if warehouses else None

            if not default_warehouse:
                frappe.log_error("No warehouse found for stock entry", "Dispatch Stock Entry Error")
                return None

            stock_entry = frappe.new_doc("Stock Entry")
            stock_entry.stock_entry_type = "Material Issue"
            stock_entry.posting_date = self.dispatch_date or frappe.utils.today()
            stock_entry.remarks = f"Dispatch from {self.name}"

            for item in self.table_ytnc:
                stock_entry.append("items", {
                    "item_code": item.item_code,
                    "qty": item.qty,
                    "s_warehouse": default_warehouse,
                    "basic_rate": item.rate or 0
                })

            stock_entry.insert(ignore_permissions=True)
            stock_entry.submit()

            return stock_entry.name

        except Exception as e:
            frappe.log_error(f"Error creating stock entry for dispatch {self.name}: {str(e)}",
                           "Dispatch Stock Entry Error")
            return None

    def revert_dispatch_status(self):
        """Revert status when document is cancelled"""
        frappe.msgprint(_("Dispatch {0} has been cancelled").format(self.name))

    @frappe.whitelist()
    def verify_item_by_scan(self, barcode_or_qr):
        """Verify an item by scanning its barcode/QR code"""
        if not barcode_or_qr:
            return {"success": False, "message": "No barcode/QR code provided"}

        # Try to parse as JSON (QR code data)
        try:
            qr_data = json.loads(barcode_or_qr)
            item_code = qr_data.get("item_code")
        except (json.JSONDecodeError, TypeError):
            # Not JSON, treat as barcode/item code
            item_code = barcode_or_qr

        # Find matching row in table
        for row in self.table_ytnc:
            if row.item_code == item_code:
                return {
                    "success": True,
                    "message": f"Item {item_code} verified",
                    "item_code": item_code,
                    "item_name": row.product_name,
                    "qty": row.qty
                }

        return {"success": False, "message": f"Item {barcode_or_qr} not found in dispatch list"}

# Additional server-side methods
@frappe.whitelist()
def get_customer_details(customer_name):
    """Get customer details for auto-filling"""
    if customer_name:
        customer = frappe.get_doc("Customer", customer_name)
        return {
            'customer_group': customer.customer_group,
            'territory': customer.territory,
            'customer_primary_address': customer.customer_primary_address
        }
    return {}

@frappe.whitelist()
def get_item_details(item_code):
    """Get item details for auto-filling in table"""
    if item_code:
        item = frappe.get_doc("Item", item_code)
        return {
            'product_name': item.item_name,
            'category': item.item_group,
            'rate': item.standard_rate or 0
        }
    return {}

@frappe.whitelist()
def create_multiple_dispatches(dispatch_data):
    """Create multiple dispatch records"""
    try:
        data = frappe.parse_json(dispatch_data)
        created_dispatches = []

        for dispatch in data:
            doc = frappe.new_doc("Dispatch Of Orders")
            doc.update(dispatch)
            doc.insert()
            created_dispatches.append(doc.name)

        return {
            'status': 'success',
            'message': f'Created {len(created_dispatches)} dispatch records',
            'dispatches': created_dispatches
        }
    except Exception as e:
        frappe.log_error(f"Error creating dispatches: {str(e)}")
        return {'status': 'error', 'message': str(e)}


@frappe.whitelist()
def get_iawb_pending_dispatches():
    """Get all dispatches with IAWB Pending status for logistics handover"""
    dispatches = frappe.get_all(
        "Dispatch Of Orders",
        filters={
            "iawb_status": "IAWB Pending",
            "docstatus": 1
        },
        fields=[
            "name", "customer_name", "dispatch_date", "packing_order",
            "packing_no", "iawb_status"
        ],
        order_by="dispatch_date desc"
    )

    # Enrich with item count
    for dispatch in dispatches:
        items = frappe.get_all(
            "Dispatch Of Orders Table",
            filters={"parent": dispatch.name},
            fields=["COUNT(*) as count"]
        )
        dispatch["item_count"] = items[0].count if items else 0

    return dispatches


@frappe.whitelist()
def update_iawb_status(dispatch_name, new_status, logistics_doc=None, tracking_number=None, logistics_partner=None):
    """Update IAWB status for a dispatch order

    Called from Handover To Logistics when shipment is created/updated
    """
    if not frappe.db.exists("Dispatch Of Orders", dispatch_name):
        return {"success": False, "message": f"Dispatch {dispatch_name} not found"}

    valid_statuses = ["Pending", "IAWB Pending", "IAWB Created", "Shipped", "Delivered"]
    if new_status not in valid_statuses:
        return {"success": False, "message": f"Invalid status: {new_status}"}

    update_fields = {"iawb_status": new_status}

    if logistics_doc:
        update_fields["handover_to_logistics"] = logistics_doc
    if tracking_number:
        update_fields["logistics_tracking_number"] = tracking_number
    if logistics_partner:
        update_fields["logistics_partner"] = logistics_partner

    frappe.db.set_value("Dispatch Of Orders", dispatch_name, update_fields)

    return {
        "success": True,
        "message": f"Dispatch {dispatch_name} status updated to {new_status}"
    }


@frappe.whitelist()
def verify_dispatch_item(dispatch_name, barcode_or_qr):
    """API method to verify dispatch item by scan"""
    doc = frappe.get_doc("Dispatch Of Orders", dispatch_name)
    return doc.verify_item_by_scan(barcode_or_qr)