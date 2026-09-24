# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ASNCreation(Document):
	def validate(self):
		for d in self.get("product_table") or []:
			po_qty = flt(d.po_quantity or 0)
			delivered = flt(d.delivered_qty or 0)
			if delivered > po_qty:
				frappe.throw(
					f"Delivered Qty for Item {d.product_code} cannot be greater than PO Qty ({po_qty})."
				)


@frappe.whitelist()
def get_po_details(po_no):
	"""
	Fetch items from the selected Purchase Order that still have balance quantities to deliver.
	"""
	if not po_no:
		frappe.throw("Purchase Order is required.")

	po_doc = frappe.get_doc("Purchase Order", po_no)

	asn_items = frappe.db.sql("""
		SELECT child.product_code, SUM(child.delivered_qty) AS total_delivered
		FROM `tabASN Creation` parent
		INNER JOIN `tabASN Child Table` child ON child.parent = parent.name
		WHERE parent.docstatus < 2 AND child.po_no = %s
		GROUP BY child.product_code
	""", (po_no,), as_dict=True)

	delivered_map = {d.product_code: flt(d.total_delivered) for d in asn_items}

	valid_po_details = []

	for row in po_doc.items:
		total_delivered = delivered_map.get(row.item_code, 0)
		remaining_qty = flt(row.qty) - total_delivered

		if remaining_qty > 0:
			valid_po_details.append({
				"product_code": row.item_code,
				"product_name": row.item_name,
				"po_quantity": row.qty,
				"po_no": po_doc.name,
				"po_date": po_doc.transaction_date,
				"delivered_qty": 0,
				"pending_qty": remaining_qty
			})

	if not valid_po_details:
		frappe.throw(f"All items in PO {po_no} are fully delivered.")

	return valid_po_details


@frappe.whitelist()
def get_pending_po(doctype, txt, searchfield, start, page_len, filters):
	"""
	Return only POs for the given supplier where at least one item is still pending delivery.
	"""
	supplier = filters.get("supplier")
	if not supplier:
		return []

	po_names = frappe.db.sql("""
		SELECT po.name
		FROM `tabPurchase Order` po
		WHERE po.supplier = %s AND po.docstatus = 1
		AND EXISTS (
			SELECT 1
			FROM `tabPurchase Order Item` poi
			LEFT JOIN (
				SELECT child.po_no, child.product_code, SUM(child.delivered_qty) AS delivered
				FROM `tabASN Creation` parent
				INNER JOIN `tabASN Child Table` child ON child.parent = parent.name
				WHERE parent.docstatus < 2
				GROUP BY child.po_no, child.product_code
			) a ON a.po_no = poi.parent AND a.product_code = poi.item_code
			WHERE poi.parent = po.name AND (COALESCE(a.delivered, 0) < poi.qty)
		)
	""", (supplier,))

	return po_names

@frappe.whitelist()
def get_asn_events(start, end, filters=None):
    asn_list = frappe.get_all(
        "ASN Creation",
        fields=[
            "name",
            "vendor_name",
            "po_no",
            "vendor_code",
            "departure_date_time",
            "arrival_date_time"
        ],
        filters=filters
    )

    events = []

    for a in asn_list:

        # --- Event for Departure Day ---
        events.append({
            "name": a.name,
            "asn_id": a.name,
            "title": a.name + " (Departure)",
            "vendor_name": a.vendor_name,
            "po_no": a.po_no,
            "type": "Departure",
            "start": a.departure_date_time,
            "end": a.departure_date_time,
            "doctype": "ASN Creation"
        })

        # --- Event for Arrival Day ---
        events.append({
            "name": a.name,
            "asn_id": a.name,
            "title": a.name + " (Arrival)",
            "vendor_name": a.vendor_name,
            "po_no": a.po_no,
            "type": "Arrival",
            "start": a.arrival_date_time,
            "end": a.arrival_date_time,
            "doctype": "ASN Creation"
        })

    return events

