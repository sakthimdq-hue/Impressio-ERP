frappe.ui.form.on("Physical Inspection For Unloading", {
	refresh(frm) {
		if (!document.getElementById("vue-readings")) {
			const target = $('[data-fieldname="readings"]').closest(".form-section");
			target.append('<div id="vue-readings" class="mt-3" style="width:100%;"></div>');
		}

		frappe.require("/assets/impressio/js/vue_init.js", () => {
			window.createVueReadingsApp("vue-readings", frm);
		});
		set_gate_entry_filter(frm);
	},
	onload(frm) {
		set_gate_entry_filter(frm);
	},
});

function set_gate_entry_filter(frm) {
	frm.set_query('gate_entry', () => {
		return {
			query: 'impressio.impressio_transaction.doctype.physical_inspection_for_unloading.physical_inspection_for_unloading.get_available_gate_entries',
			filters: {
				current_doc: frm.doc.name || ''
			}
		};
	});
}
