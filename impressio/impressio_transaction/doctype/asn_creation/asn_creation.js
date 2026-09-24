frappe.ui.form.on("ASN Creation", {
	onload(frm) {
		frm.set_query("po_no", function (doc) {
			return {
				query: "impressio.impressio_transaction.doctype.asn_creation.asn_creation.get_pending_po",
				filters: {
					supplier: doc.vendor_code,
				},
			};
		});
	},

	vendor_code(frm) {
		frm.set_value("po_no", "");
		frm.refresh_field("po_no");
	},

	po_no(frm) {
		if (frm.doc.po_no) {
			frappe.call({
				method: "impressio.impressio_transaction.doctype.asn_creation.asn_creation.get_po_details",
				args: {
					po_no: frm.doc.po_no,
				},
				callback: function (r) {
					if (r.message && Array.isArray(r.message)) {
						frm.clear_table("product_table");

						r.message.forEach(function (row) {
							let child = frm.add_child("product_table");
							child.product_code = row.product_code;
							child.product_name = row.product_name;
							child.po_quantity = row.po_quantity;
							child.po_no = row.po_no;
							child.po_date = row.po_date;
							child.delivered_qty = 0;
							child.pending_qty = row.pending_qty;
						});

						frm.refresh_field("product_table");
					}
				},
			});
		}
	},
});

frappe.ui.form.on("ASN Child Table", {
	delivered_qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		let delivered = parseFloat(row.delivered_qty || 0);
		let pending = parseFloat(row.pending_qty || 0);

		if (delivered > pending) {
			frappe.msgprint(
				__("Delivered Qty cannot be greater than Pending Qty ({0})", [pending])
			);
			frappe.model.set_value(cdt, cdn, "delivered_qty", pending);
		}
	},
});
