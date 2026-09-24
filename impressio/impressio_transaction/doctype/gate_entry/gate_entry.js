// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Entry", {
	refresh(frm) {},
	onload: function (frm) {
		frm.set_query("asn_no", function (doc) {
			return {
				filters: {
					docstatus: 1,
				},
			};
		});
	},
});
