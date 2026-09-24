// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Pass", {
	setup: function (frm) {
		$.each(["gate_pass_table"], function (i, table_fieldname) {
			frm.get_field(table_fieldname).grid.editable_fields = [
				{ fieldname: "item_code", columns: 2 },
				{ fieldname: "from_warehouse", columns: 2 },
				{ fieldname: "warehouse", columns: 2 },
				{ fieldname: "qty", columns: 2 },
				{ fieldname: "rate", columns: 2 },
			];
		});
	},
	refresh: function (frm) {
		frm.fields_dict["gate_pass_table"].grid.get_field("warehouse").get_query = function (
			doc,
			cdt,
			cdn
		) {
			var r = locals[cdt][cdn];
			console.log(r);
			return {
				filters: [["Warehouse", "name", "!=", r.from_warehouse]],
			};
		};
		frm.fields_dict["gate_pass_table"].grid.get_field("from_warehouse").get_query = function (
			doc,
			cdt,
			cdn
		) {
			var r = locals[cdt][cdn];
			// console.log(r);
			return {
				filters: [["Warehouse", "name", "!=", r.warehouse]],
			};
		};
	},
});

frappe.ui.form.on("Gate Pass Item", {
	rate(frm, doctype, name) {
		const item = locals[doctype][name];
		item.amount = flt(item.qty) * flt(item.rate);

		frappe.model.set_value(doctype, name, "amount", item.amount);
		refresh_field("amount", item.name, item.parentfield);
	},

	qty(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);

		row.amount = flt(row.qty) * flt(row.rate);
		frappe.model.set_value(cdt, cdn, "amount", row.amount);
		refresh_field("amount", row.name, row.parentfield);

		if (!row.item_code || !row.from_warehouse || !row.qty) return;

		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Bin",
				filters: {
					item_code: row.item_code,
					warehouse: row.from_warehouse,
				},
				fieldname: ["actual_qty"],
			},
			callback: function (r) {
				let stock = r.message?.actual_qty || 0;

				if (flt(row.qty) > flt(stock)) {
					frappe.msgprint({
						title: "Insufficient Stock",
						message: `The requested quantity (<b>${row.qty}</b>) exceeds the available stock (<b>${stock}</b>) in <b>${row.from_warehouse}</b>. Please adjust the quantity.`,
						indicator: "red",
					});

					frappe.model.set_value(cdt, cdn, "qty", 0);
				}
			},
		});
	},

	from_warehouse(frm, cdt, cdn) {
		if (frm.doc.gate_entry_type != "OUTWARD") return;
		let row = locals[cdt][cdn];

		if (!row.item_code || !row.from_warehouse) return;

		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Bin",
				filters: {
					item_code: row.item_code,
					warehouse: row.from_warehouse,
				},
				fieldname: ["actual_qty"],
			},
			callback: function (r) {
				let stock = r.message?.actual_qty || 0;

				if (stock <= 0) {
					frappe.msgprint({
						title: "Stock Not Available",
						message: `No stock is available for item <b>${row.item_code}</b> in <b>${row.from_warehouse}</b>. Please choose another warehouse.`,
						indicator: "red",
					});

					frappe.model.set_value(cdt, cdn, "from_warehouse", "");
				} else {
					frappe.msgprint({
						title: "Stock Availability",
						message: `Available stock for item <b>${row.item_code}</b> in <b>${row.from_warehouse}</b> is <b>${stock}</b>.`,
						indicator: "green",
					});

					frappe.model.set_value(cdt, cdn, "available_qty", stock);
				}
			},
		});
	},
});
