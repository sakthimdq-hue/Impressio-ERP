frappe.ui.form.on("Pick Slip", {
	onload: function (frm) {
		// Set initial visibility based on the field value when form loads
		frm.events._update_po_mode_visibility(frm);
	},

	refresh: function (frm) {
		// Also ensure visibility on refresh (useful after saves/loads)
		frm.events._update_po_mode_visibility(frm);
	},

	// field that decides single or multi mode
	single_op_or_multi_po: function (frm) {
		// Update visibility immediately when user changes this select
		frm.events._update_po_mode_visibility(frm);

		// When switching mode, clear the other PO field(s) and the child table
		// So there's no accidental mixing of items from different modes.
		if (frm.doc.single_op_or_multi_po === "Single Po") {
			// clear multi table and its values
			if (frm.doc.po_number && frm.doc.po_number.length) {
				frm.set_value("po_number", []);
			}
		} else if (frm.doc.single_op_or_multi_po === "Multi Po") {
			// clear single link
			if (frm.doc.po_number_single) {
				frm.set_value("po_number_single", "");
			}
		}

		// Always clear the child items when switching mode
		frm.clear_table("pick_slip_item_child_table");
		frm.refresh_field("pick_slip_item_child_table");
	},

	// existing multi-select/table field handler
	po_number: function (frm) {
		// Only act if currently in Multi mode
		if (frm.doc.single_op_or_multi_po === "Multi Po") {
			frm.trigger("load_items_from_po");
		}
	},

	// new single Link field handler
	po_number_single: function (frm) {
		// Only act if currently in Single mode
		if (frm.doc.single_op_or_multi_po === "Single Po") {
			frm.trigger("load_items_from_po_single");
		}
	},

	// load for the multi-select/table field (keeps previous behaviour)
	load_items_from_po: function (frm) {
		// If nothing selected, clear the child table
		if (!frm.doc.po_number || frm.doc.po_number.length === 0) {
			frm.clear_table("pick_slip_item_child_table");
			frm.refresh_field("pick_slip_item_child_table");
			return;
		}

		// Extract actual Sales Order IDs from "pick_slip_sales_order" column
		const po_list = (frm.doc.po_number || [])
			.map((row) => row.pick_slip_sales_order)
			.filter(Boolean);

		if (po_list.length === 0) {
			frappe.msgprint(__("No valid Sales Orders selected."));
			return;
		}

		// Use the common loader
		frm.events._fetch_and_add_items(frm, po_list);
	},

	// load for the single Link field
	load_items_from_po_single: function (frm) {
		const po = frm.doc.po_number_single;
		if (!po) {
			// clear table if user cleared the field
			frm.clear_table("pick_slip_item_child_table");
			frm.refresh_field("pick_slip_item_child_table");
			return;
		}

		// Call same loader with a single-element array
		frm.events._fetch_and_add_items(frm, [po]);
	},

	// common helper: calls server and adds items to the child table
	_fetch_and_add_items: function (frm, po_list) {
		console.log("Selected Sales Orders:", po_list);

		frappe.call({
			method: "impressio.impressio.doctype.pick_slip.pick_slip.get_items_from_sales_orders",
			args: { po_numbers: po_list },
			freeze: true,
			freeze_message: __("Fetching items from selected Sales Orders..."),
			callback: function (r) {
				frm.clear_table("pick_slip_item_child_table");

				const items = r.message || [];
				if (items.length === 0) {
					frappe.msgprint(__("No items found for the selected Sales Orders."));
					frm.refresh_field("pick_slip_item_child_table");
					return;
				}

				// Add items to the child table
				items.forEach((d) => {
					frm.add_child("pick_slip_item_child_table", {
						item_code: d.item_code,
						item_name: d.item_name,
						qty: d.qty,
						uom: d.uom,
						warehouse: d.warehouse,
						po_number: d.parent,
						po_date: d.transaction_date,
						so_item_row: d.name,
						line_no: d.idx,
					});
				});

				frm.refresh_field("pick_slip_item_child_table");
				frappe.show_alert({
					message: __("{0} items loaded from selected Sales Orders.", [items.length]),
					indicator: "green",
				});
			},
			error: function (err) {
				console.error("Error fetching Sales Order items:", err);
				frappe.msgprint(__("An error occurred while fetching Sales Order items."));
			},
		});
	},

	// helper: show/hide fields according to single_op_or_multi_po value
	_update_po_mode_visibility: function (frm) {
		const mode = frm.doc.single_op_or_multi_po;

		// default to Single if not set (optional)
		// const effective_mode = mode || "Single Po";

		const showSingle = mode === "Single Po";
		const showMulti = mode === "Multi Po";

		// toggle display (this hides the field from the form view)
		frm.toggle_display("po_number_single", showSingle);
		frm.toggle_display("po_number", showMulti);

		// optionally toggle required property so validation fits the selected mode
		frm.toggle_reqd("po_number_single", showSingle);
		frm.toggle_reqd("po_number", showMulti);
	},
});
