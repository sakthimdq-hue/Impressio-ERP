# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import json
from frappe.utils import getdate, add_days, today

class PackingOforders(Document):
    # -----------------------------
    # Core lifecycle
    # -----------------------------
    def validate(self):
        self.validate_required_fields()
        self.validate_table_data()
        self.calculate_packing_progress()
        self.update_packing_status()
    
    def before_submit(self):
        # Do not allow submit unless packing is 100%
        if self.packing_progress < 100:
            frappe.throw(_("All items must be scanned and confirmed before submission"))

        # Create Sales Invoice BEFORE submit
        self.create_sales_invoice_from_packing()

    

    def before_save(self):
    # Allow internal/system updates
        if getattr(self.flags, "ignore_validate", False):
            return

    # Allow system saves after submit
        if self.docstatus == 1:
            return

        if self.is_new():
            return

        existing = frappe.get_doc(self.doctype, self.name)
        if existing.sales_invoice:
            frappe.throw(
                _("Cannot modify packing after Sales Invoice {0} has been created")
                .format(existing.sales_invoice)
            )


    # def before_save(self):
    #     if self.is_new():
    #         return
    #     # prevent edits once SI exists (DB check)
    #     existing = frappe.get_doc(self.doctype, self.name)
    #     if existing.sales_invoice:
    #         frappe.throw(_("Cannot modify packing after Sales Invoice {0} has been created").format(existing.sales_invoice))

    # def on_submit(self):
    #     if self.packing_progress < 100:
    #         frappe.throw(_("All items must be scanned and confirmed before submission"))

    #     self.packing_status = "Completed"

    #     # auto-create SI (non-blocking)
    #     try:
    #         self.create_sales_invoice_from_packing()
    #     except Exception as e:
    #         frappe.log_error(str(e), "Packing → SI")
    #         frappe.msgprint(_("Packing completed but Sales Invoice creation failed: {0}").format(str(e)))

    #     # update pickslip
    #     if self.pickslip_no:
    #         frappe.db.set_value(
    #             "Pickslip Generation Against Sales Order",
    #             self.pickslip_no,
    #             "pickslip_status",
    #             "Packed",
    #         )

    #     frappe.msgprint(_("Packing completed successfully"))

    # -----------------------------
    # Scan & progress
    # -----------------------------
    def confirm_item_by_scan(self, barcode_or_qr):
        if not barcode_or_qr:
            frappe.throw(_("Invalid scan data"))

        raw = barcode_or_qr.strip()
        extracted = set()

        # Try JSON QR payload
        try:
            data = frappe.parse_json(raw)
            if isinstance(data, dict):
                for key in ("item_code", "barcode", "product", "code", "checksum"):
                    if data.get(key):
                        extracted.add(str(data[key]).strip().upper())
        except Exception:
            pass

        # Plain text fallback
        scan = raw.replace("\n", "|").replace("\r", "").strip().upper()
        extracted.add(scan)

        for key in ("ITEM:", "ITEM=", "CODE:", "PRODUCT:", "BARCODE:"):
            if key in scan:
                extracted.add(scan.split(key)[-1].split("|")[0].strip())

        # Debug log
        frappe.log_error(
            title="Packing Scan Debug",
            message=json.dumps(
                {"raw": raw, "extracted": list(extracted), "packing": self.name}
            ),
        )

        matched = None

        for row in self.get("table"):
            product = (row.product or "").upper()
            barcode = (row.barcode or "").upper()

            for code in extracted:
                if (
                    code == product
                    or code == barcode
                    or code in product
                    or code in barcode
                ):
                    matched = row
                    break

            if matched:
                break

        if not matched:
            frappe.log_error(
                title="Packing Scan Mismatch",
                message=json.dumps(
                    {"scan": raw, "codes": list(extracted), "packing": self.name}
                ),
            )
            return {
                "success": False,
                "message": _("Scanned item not found in packing list"),
            }

        if matched.scan_status == "Confirmed":
            return {
                "success": False,
                "message": _("Item already confirmed"),
            }

        matched.scan_status = "Confirmed"
        self.calculate_packing_progress()
        self.update_packing_status()

        self.flags.ignore_validate = True
        self.save(ignore_permissions=True)

        return {
            "success": True,
            "message": _("Item confirmed successfully"),
            "progress": self.packing_progress,
        }

    
    def calculate_packing_progress(self):
        if not self.table:
            self.total_items = self.items_confirmed = self.packing_progress = 0
            return
        self.total_items = len(self.table)
        self.items_confirmed = sum(1 for r in self.table if getattr(r, "scan_status", None) == "Confirmed")
        self.packing_progress = round((self.items_confirmed / self.total_items) * 100, 2) if self.total_items else 0

    def update_packing_status(self):
        if self.packing_progress == 0:
            self.packing_status = "Pending"
        elif self.packing_progress < 100:
            self.packing_status = "In Progress"
        else:
            self.packing_status = "Completed"

    # -----------------------------
    # Validations
    # -----------------------------
    def validate_required_fields(self):
        if not self.customer_name and not self.sales_order:
            frappe.throw(_("Please select a Customer or Sales Order"))

    def validate_table_data(self):
        if not self.table:
            frappe.throw(_("Please add items to pack"))
        for i, r in enumerate(self.table, start=1):
            if not r.product and not r.barcode:
                frappe.throw(_("Row {0}: Product or Barcode is required").format(i))
            if not r.qty or r.qty <= 0:
                frappe.throw(_("Row {0}: Quantity must be greater than 0").format(i))

    # -----------------------------
    # Sales Invoice
    # -----------------------------
    def create_sales_invoice_from_packing(self):
        if not self.sales_order:
            return None
        if self.sales_invoice:
            return self.sales_invoice

        so = frappe.get_doc("Sales Order", self.sales_order)

        si = frappe.new_doc("Sales Invoice")
        si.customer = self.customer_name
        si.company = so.company or frappe.defaults.get_user_default("company")
        si.posting_date = getdate(self.pickslip_date or today())

        if so.payment_schedule:
            due = getdate(so.payment_schedule[0].due_date)
        else:
            due = add_days(si.posting_date, 30)
        if due < si.posting_date:
            due = add_days(si.posting_date, 30)
        si.due_date = due

        si.payment_terms_template = so.payment_terms_template
        si.sales_order = self.sales_order
        si.packing_reference = self.name

        for p in self.table:
            code = p.product or p.barcode
            if not code:
                continue

            rate = 0.0
            uom = "Nos"
            try:
                it = frappe.get_doc("Item", code)
                rate = float(it.standard_rate or 0)
                uom = it.stock_uom or uom
            except Exception:
                pass

            for soi in so.items:
                if soi.item_code == code:
                    rate = float(soi.rate or rate)
                    uom = soi.uom or uom
                    break

            qty = float(p.qty or 1)
            si.append("items", {
                "item_code": code,
                "item_name": p.product_name or code,
                "qty": qty,
                "uom": uom,
                "rate": rate,
                "amount": rate * qty,
                "sales_order": self.sales_order,
            })

        if not si.items:
            frappe.throw(_("No valid items found to create Sales Invoice"))

        si.run_method("set_missing_values")
        si.calculate_taxes_and_totals()
        si.insert()
        si.submit()

        self.sales_invoice = si.name
        return si.name


# -----------------------------
# Whitelisted APIs
# -----------------------------
@frappe.whitelist()
def confirm_packing_item(docname, barcode_or_qr):
    doc = frappe.get_doc("Packing Of orders", docname)
    return doc.confirm_item_by_scan(barcode_or_qr)


@frappe.whitelist()
def get_packing_orders_for_dispatch():
    orders = frappe.get_all(
        "Packing Of orders",
        filters={"packing_status": "Completed", "docstatus": 1},
        fields=["name", "customer_name", "sales_order", "pickslip_date", "total_items"],
    )
    result = []
    for o in orders:
        if not frappe.get_all("Dispatch Of Orders", filters={"packing_order": o.name}, limit=1):
            result.append(o)
    return result


@frappe.whitelist()
def create_dispatch_from_packing(packing_name):
    packing = frappe.get_doc("Packing Of orders", packing_name)
    if packing.packing_status != "Completed":
        frappe.throw(_("Packing order must be completed before dispatch"))

    if frappe.get_all("Dispatch Of Orders", filters={"packing_order": packing_name}, limit=1):
        frappe.throw(_("A dispatch order already exists for this packing"))

    d = frappe.new_doc("Dispatch Of Orders")
    d.packing_order = packing.name
    d.customer_name = packing.customer_name
    d.dispatch_date = today()
    d.iawb_status = "Pending"

    for p in packing.table:
        code = p.product or p.barcode
        rate = 0
        try:
            rate = frappe.get_doc("Item", code).standard_rate or 0
        except Exception:
            pass
        d.append("table_ytnc", {
            "item_code": code,
            "product_name": p.product_name,
            "qty": p.qty,
            "rate": rate,
            "amount": rate * (p.qty or 0),
            "date": today(),
        })

    d.insert()
    packing.db_set("packing_status", "Dispatched")
    return d.name


@frappe.whitelist()
def create_handover_from_si(sales_invoice):
    """Create Handover To Logistics from Sales Invoice - SIMPLIFIED VERSION"""
    try:
        # Get Sales Invoice
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        
        # Check if already exists
        existing = frappe.db.exists("Handover To Logistics", {"sales_invoice": sales_invoice})
        if existing:
            frappe.throw(f"Handover already exists: {existing}")
        
        # Get logistics settings
        settings = frappe.get_single("Logistics Settings")
        
        # Create new document
        handover = frappe.new_doc("Handover To Logistics")
        
        # === CRITICAL: SET STATUS TO DRAFT ===
        handover.status = "Draft"
        
        # Set default carrier from settings
        if settings.default_carrier:
            handover.logistics_partner = settings.default_carrier
        
        # === BASIC INFORMATION ===
        handover.sales_invoice = sales_invoice
        handover.order_no = si.name
        handover.customer_name = si.customer_name or si.customer
        
        # Phone number
        if si.contact_mobile:
            handover.customer_phone = si.contact_mobile
        elif si.contact_phone:
            handover.customer_phone = si.contact_phone
        elif si.mobile_no:
            handover.customer_phone = si.mobile_no
        
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
            except:
                # Fallback if address not found
                handover.address = settings.warehouse_address or "Default Warehouse Address"
                handover.pincode = settings.warehouse_pincode or "560001"
        else:
            # Use settings warehouse address
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
        handover.invoice_number = si.name
        
        # Payment type
        if si.is_return or (si.outstanding_amount and si.outstanding_amount > 0):
            handover.payment_type = "COD"
            handover.cod_amount = si.outstanding_amount or 0
        else:
            handover.payment_type = "Prepaid"
            handover.cod_amount = 0
        
        # Dates
        handover.handover_date = frappe.utils.today()
        
        # Save the document
        handover.insert(ignore_permissions=True)
        
        # Mark Sales Invoice
        frappe.db.set_value("Sales Invoice", sales_invoice, "handover_created", 1)
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

@frappe.whitelist()
def add_item_to_packing_list(docname, item_data):
    doc = frappe.get_doc("Packing Of orders", docname)
    if isinstance(item_data, str):
        item_data = json.loads(item_data)

    row = doc.append("table", {})
    if isinstance(item_data, dict):
        row.product = item_data.get("item_code") or item_data.get("product")
        row.product_name = item_data.get("item_name") or item_data.get("product_name")
        row.barcode = item_data.get("barcode") or item_data.get("checksum")
        row.qty = item_data.get("qty", 1)
    else:
        row.product = str(item_data)
        row.qty = 1

    row.scan_status = "Pending"
    doc.save()
    return {"success": True, "message": _("Item added to packing list")}


@frappe.whitelist()
def create_sales_invoice_for_packing(packing_name):
    packing = frappe.get_doc("Packing Of orders", packing_name)
    if packing.packing_status != "Completed":
        frappe.throw(_("Packing must be completed before creating Sales Invoice"))
    return packing.sales_invoice or packing.create_sales_invoice_from_packing()


@frappe.whitelist()
def update_packing_table(docname, table_data):

    doc = frappe.get_doc("Packing Of orders", docname)

    if isinstance(table_data, str):
        table_data = json.loads(table_data)

    # Clear table
    doc.set("table", [])

    for row in table_data:
        doc.append("table", {
            "product": row.get("product"),
            "product_name": row.get("product_name"),
            "barcode": row.get("barcode"),
            "qty": row.get("qty") or 1,
            "scan_status": "Confirmed"   # 🔥 FORCE CONFIRMED
        })

    # 🔥 ALWAYS RECALCULATE FROM TABLE
    doc.calculate_packing_progress()
    doc.update_packing_status()

    doc.flags.ignore_validate = True
    doc.flags.ignore_mandatory = True

    doc.save(ignore_permissions=True)

    frappe.db.commit()

    return {"success": True}