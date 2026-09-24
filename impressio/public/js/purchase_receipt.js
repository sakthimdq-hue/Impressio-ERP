frappe.provide("erpnext.stock");

cur_frm.cscript.tax_table = "Purchase Taxes and Charges";

erpnext.accounts.taxes.setup_tax_filters("Purchase Taxes and Charges");
erpnext.accounts.taxes.setup_tax_validations("Purchase Receipt");
erpnext.buying.setup_buying_controller();

frappe.ui.form.on("Purchase Receipt", {
	setup: (frm) => {
		$.each(["items"], function (i, table_fieldname) {
			frm.get_field(table_fieldname).grid.editable_fields = [
				{ fieldname: "item_code", columns: 2 },
				{ fieldname: "qty", columns: 2 },
				{ fieldname: "rejected_qty", columns: 2 },
				{ fieldname: "custom_actual_grn_quantity", columns: 1 },
				{ fieldname: "custom_excess_grn_quantity", columns: 1 },
				{ fieldname: "custom_print", columns: 1 },
				{ fieldname: "custom_re_print", columns: 1 },
			];
		});

		frm.custom_make_buttons = {
			"Stock Entry": "Return",
			"Purchase Invoice": "Purchase Invoice",
			"Landed Cost Voucher": "Landed Cost Voucher",
		};

		frm.set_query("expense_account", "items", function () {
			return {
				query: "erpnext.controllers.queries.get_expense_account",
				filters: { company: frm.doc.company },
			};
		});

		frm.set_query("wip_composite_asset", "items", function () {
			return {
				filters: { is_composite_asset: 1, docstatus: 0 },
			};
		});

		frm.set_query("taxes_and_charges", function () {
			return {
				filters: { company: frm.doc.company },
			};
		});

		frm.set_query("subcontracting_receipt", function () {
			return {
				filters: {
					docstatus: 1,
					supplier: frm.doc.supplier,
				},
			};
		});
	},
	onload: function (frm) {
		erpnext.queries.setup_queries(frm, "Warehouse", function () {
			return erpnext.queries.warehouse(frm.doc);
		});
	},

	refresh: function (frm) {
		if (frm.doc.company) {
			frm.trigger("toggle_display_account_head");
		}

		if (frm.doc.docstatus === 1 && frm.doc.is_return === 1 && frm.doc.per_billed !== 100) {
			frm.add_custom_button(
				__("Debit Note"),
				function () {
					frappe.model.open_mapped_doc({
						method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
						frm: cur_frm,
					});
				},
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}

		if (
			frm.doc.docstatus === 1 &&
			frm.doc.is_internal_supplier &&
			!frm.doc.inter_company_reference
		) {
			frm.add_custom_button(
				__("Delivery Note"),
				function () {
					frappe.model.open_mapped_doc({
						method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_inter_company_delivery_note",
						frm: cur_frm,
					});
				},
				__("Create")
			);
		}

		if (frm.doc.docstatus === 0) {
			if (!frm.doc.is_return) {
				frappe.db
					.get_single_value("Buying Settings", "maintain_same_rate")
					.then((value) => {
						if (value) {
							frm.doc.items.forEach((item) => {
								frm.fields_dict.items.grid.update_docfield_property(
									"rate",
									"read_only",
									item.purchase_order && item.purchase_order_item
								);
							});
						}
					});
			}
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Landed Cost Voucher"),
				() => {
					frm.events.make_lcv(frm);
				},
				__("Create")
			);
		}

		frm.events.add_custom_buttons(frm);
	},

	make_lcv(frm) {
		frappe.call({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_lcv",
			args: {
				doctype: frm.doc.doctype,
				docname: frm.doc.name,
			},
			callback: (r) => {
				if (r.message) {
					var doc = frappe.model.sync(r.message);
					frappe.set_route("Form", doc[0].doctype, doc[0].name);
				}
			},
		});
	},

	add_custom_buttons: function (frm) {
		if (frm.doc.docstatus == 0) {
			frm.add_custom_button(
				__("Purchase Invoice"),
				function () {
					if (!frm.doc.supplier) {
						frappe.throw({
							title: __("Mandatory"),
							message: __("Please Select a Supplier"),
						});
					}
					erpnext.utils.map_current_doc({
						method: "erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_purchase_receipt",
						source_doctype: "Purchase Invoice",
						target: frm,
						setters: {
							supplier: frm.doc.supplier,
						},
						get_query_filters: {
							docstatus: 1,
							per_received: ["<", 100],
							company: frm.doc.company,
						},
					});
				},
				__("Get Items From")
			);
		}
	},

	company: function (frm) {
		frm.trigger("toggle_display_account_head");
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	subcontracting_receipt: (frm) => {
		if (
			frm.doc.is_subcontracted === 1 &&
			frm.doc.is_old_subcontracting_flow === 0 &&
			frm.doc.subcontracting_receipt
		) {
			frm.set_value("items", null);

			erpnext.utils.map_current_doc({
				method: "erpnext.subcontracting.doctype.subcontracting_receipt.subcontracting_receipt.make_purchase_receipt",
				source_name: frm.doc.subcontracting_receipt,
				target_doc: frm,
				freeze: true,
				freeze_message: __("Mapping Purchase Receipt ..."),
			});
		}
	},

	toggle_display_account_head: function (frm) {
		var enabled = erpnext.is_perpetual_inventory_enabled(frm.doc.company);
		frm.fields_dict["items"].grid.set_column_disp(["cost_center"], enabled);
	},
});

erpnext.stock.PurchaseReceiptController = class PurchaseReceiptController extends (
	erpnext.buying.BuyingController
) {
	setup(doc) {
		this.setup_posting_date_time_check();
		super.setup(doc);
	}

	refresh() {
		var me = this;
		super.refresh();

		erpnext.accounts.ledger_preview.show_accounting_ledger_preview(this.frm);
		erpnext.accounts.ledger_preview.show_stock_ledger_preview(this.frm);

		if (this.frm.doc.docstatus > 0) {
			this.show_stock_ledger();
			//removed for temporary
			this.show_general_ledger();

			this.frm.add_custom_button(
				__("Asset"),
				function () {
					frappe.route_options = {
						purchase_receipt: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset");
				},
				__("View")
			);

			this.frm.add_custom_button(
				__("Asset Movement"),
				function () {
					frappe.route_options = {
						reference_name: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset Movement");
				},
				__("View")
			);
		}

		if (!this.frm.doc.is_return && this.frm.doc.status != "Closed") {
			if (this.frm.doc.docstatus == 0) {
				this.frm.add_custom_button(
					__("Purchase Order"),
					function () {
						if (!me.frm.doc.supplier) {
							frappe.throw({
								title: __("Mandatory"),
								message: __("Please Select a Supplier"),
							});
						}
						erpnext.utils.map_current_doc({
							method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
							source_doctype: "Purchase Order",
							target: me.frm,
							setters: {
								supplier: me.frm.doc.supplier,
								schedule_date: undefined,
							},
							get_query_filters: {
								docstatus: 1,
								status: ["not in", ["Closed", "On Hold"]],
								per_received: ["<", 99.99],
								company: me.frm.doc.company,
							},
						});
					},
					__("Get Items From")
				);
			}

			if (this.frm.doc.docstatus == 1 && this.frm.doc.status != "Closed") {
				if (this.frm.has_perm("submit")) {
					cur_frm.add_custom_button(
						__("Close"),
						this.close_purchase_receipt,
						__("Status")
					);
				}

				cur_frm.add_custom_button(
					__("Purchase Return"),
					this.make_purchase_return,
					__("Create")
				);

				cur_frm.add_custom_button(
					__("Make Stock Entry"),
					cur_frm.cscript["Make Stock Entry"],
					__("Create")
				);

				if (flt(this.frm.doc.per_billed) < 100) {
					cur_frm.add_custom_button(
						__("Purchase Invoice"),
						this.make_purchase_invoice,
						__("Create")
					);
				}
				cur_frm.add_custom_button(
					__("Retention Stock Entry"),
					this.make_retention_stock_entry,
					__("Create")
				);

				cur_frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		}

		if (
			this.frm.doc.docstatus == 1 &&
			this.frm.doc.status === "Closed" &&
			this.frm.has_perm("submit")
		) {
			cur_frm.add_custom_button(__("Reopen"), this.reopen_purchase_receipt, __("Status"));
		}

		this.frm.toggle_reqd("supplier_warehouse", this.frm.doc.is_old_subcontracting_flow);
	}

	make_purchase_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			frm: cur_frm,
		});
	}

	make_purchase_return() {
		let me = this;

		let has_rejected_items = cur_frm.doc.items.filter((item) => {
			if (item.rejected_qty > 0) {
				return true;
			}
		});

		if (has_rejected_items && has_rejected_items.length > 0) {
			frappe.prompt(
				[
					{
						label: __("Return Qty from Rejected Warehouse"),
						fieldtype: "Check",
						fieldname: "return_for_rejected_warehouse",
						default: 1,
					},
				],
				function (values) {
					if (values.return_for_rejected_warehouse) {
						frappe.call({
							method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return_against_rejected_warehouse",
							args: {
								source_name: cur_frm.doc.name,
							},
							callback: function (r) {
								if (r.message) {
									frappe.model.sync(r.message);
									frappe.set_route("Form", r.message.doctype, r.message.name);
								}
							},
						});
					} else {
						cur_frm.cscript._make_purchase_return();
					}
				},
				__("Return Qty"),
				__("Make Return Entry")
			);
		} else {
			cur_frm.cscript._make_purchase_return();
		}
	}

	close_purchase_receipt() {
		cur_frm.cscript.update_status("Closed");
	}

	reopen_purchase_receipt() {
		cur_frm.cscript.update_status("Submitted");
	}

	make_retention_stock_entry() {
		frappe.call({
			method: "erpnext.stock.doctype.stock_entry.stock_entry.move_sample_to_retention_warehouse",
			args: {
				company: cur_frm.doc.company,
				items: cur_frm.doc.items,
			},
			callback: function (r) {
				if (r.message) {
					var doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				} else {
					frappe.msgprint(
						__(
							"Purchase Receipt doesn't have any Item for which Retain Sample is enabled."
						)
					);
				}
			},
		});
	}

	apply_putaway_rule() {
		if (this.frm.doc.apply_putaway_rule) erpnext.apply_putaway_rule(this.frm);
	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new erpnext.stock.PurchaseReceiptController({ frm: cur_frm }));

cur_frm.cscript.update_status = function (status) {
	frappe.ui.form.is_saving = true;
	frappe.call({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.update_purchase_receipt_status",
		args: { docname: cur_frm.doc.name, status: status },
		callback: function (r) {
			if (!r.exc) cur_frm.reload_doc();
		},
		always: function () {
			frappe.ui.form.is_saving = false;
		},
	});
};

cur_frm.fields_dict["items"].grid.get_field("project").get_query = function (doc, cdt, cdn) {
	return {
		filters: [["Project", "status", "not in", "Completed, Cancelled"]],
	};
};

cur_frm.fields_dict["select_print_heading"].get_query = function (doc, cdt, cdn) {
	return {
		filters: [["Print Heading", "docstatus", "!=", "2"]],
	};
};

cur_frm.fields_dict["items"].grid.get_field("bom").get_query = function (doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	return {
		filters: [
			["BOM", "item", "=", d.item_code],
			["BOM", "is_active", "=", "1"],
			["BOM", "docstatus", "=", "1"],
		],
	};
};

frappe.provide("erpnext.buying");

frappe.ui.form.on("Purchase Receipt", "is_subcontracted", function (frm) {
	if (frm.doc.is_old_subcontracting_flow) {
		erpnext.buying.get_default_bom(frm);
	}

	frm.toggle_reqd("supplier_warehouse", frm.doc.is_old_subcontracting_flow);
});

frappe.ui.form.on("Purchase Receipt Item", {
	item_code: function (frm, cdt, cdn) {
		var d = locals[cdt][cdn];
		frappe.db.get_value("Item", { name: d.item_code }, "sample_quantity", (r) => {
			frappe.model.set_value(cdt, cdn, "sample_quantity", r.sample_quantity);
			validate_sample_quantity(frm, cdt, cdn);
		});
	},
	qty: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	sample_quantity: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	batch_no: function (frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	custom_print: function (frm, cdt, cdn, fieldname) {
		// Print QR and update actual_qty/excess_qty fields
		print_qr_with_quantity_update(frm, cdt, cdn, "initial");
	},
	custom_re_print: function (frm, cdt, cdn, fieldname) {
		// Reprint QR without updating quantities
		print_qr_code(frm, cdt, cdn, "reprint");
	},
});

cur_frm.cscript._make_purchase_return = function () {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
		frm: cur_frm,
	});
};

cur_frm.cscript["Make Stock Entry"] = function () {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_stock_entry",
		frm: cur_frm,
	});
};

var validate_sample_quantity = function (frm, cdt, cdn) {
	var d = locals[cdt][cdn];
	if (d.sample_quantity && d.qty) {
		frappe.call({
			method: "erpnext.stock.doctype.stock_entry.stock_entry.validate_sample_quantity",
			args: {
				batch_no: d.batch_no,
				item_code: d.item_code,
				sample_quantity: d.sample_quantity,
				qty: d.qty,
			},
			callback: (r) => {
				frappe.model.set_value(cdt, cdn, "sample_quantity", r.message);
			},
		});
	}
};

function print_qr_with_quantity_update(frm, cdt, cdn, print_type) {
	var d = locals[cdt][cdn];

	// Get current values
	var current_actual = d.custom_actual_grn_quantity || 0;
	var current_excess = d.custom_excess_grn_quantity || 0;
	var accepted_qty = d.accepted_qty || d.qty || 0;

	// Calculate remaining quantities
	var remaining_actual = accepted_qty - current_actual;
	var total_printed = current_actual + current_excess;

	if (remaining_actual > 0) {
		// Still have actual quantity to print
		frappe.prompt(
			{
				fieldname: "print_qty",
				label: __("Quantity to Print"),
				fieldtype: "Int",
				default: 1,
				reqd: 1,
				description: __("Remaining Actual Quantity: {0}", [remaining_actual]),
			},
			(values) => {
				if (values.print_qty > 0) {
					if (values.print_qty <= remaining_actual) {
						// Update actual quantity in child table
						var new_actual_qty = current_actual + values.print_qty;
						frappe.model.set_value(
							cdt,
							cdn,
							"custom_actual_grn_quantity",
							new_actual_qty
						);

						// Generate QR codes
						generateQRCode(frm, d, values.print_qty, "actual", current_actual + 1);
					} else {
						frappe.msgprint(
							__("Cannot print more than remaining actual quantity: {0}", [
								remaining_actual,
							])
						);
					}
				}
			},
			__("Enter Print Quantity"),
			__("Print")
		);
	} else if (remaining_actual <= 0) {
		// All actual quantity printed, now print excess
		frappe.prompt(
			{
				fieldname: "print_qty",
				label: __("Excess Quantity to Print"),
				fieldtype: "Int",
				default: 1,
				reqd: 1,
				description: __("All actual quantity printed. Printing excess labels."),
			},
			(values) => {
				if (values.print_qty > 0) {
					// Update excess quantity in child table
					var new_excess_qty = current_excess + values.print_qty;
					frappe.model.set_value(cdt, cdn, "custom_excess_grn_quantity", new_excess_qty);

					// Generate QR codes for excess
					generateQRCode(
						frm,
						d,
						values.print_qty,
						"excess",
						accepted_qty + current_excess + 1
					);
				}
			},
			__("Enter Excess Quantity"),
			__("Print")
		);
	}
}

function print_qr_code(frm, cdt, cdn, print_type) {
	var d = locals[cdt][cdn];

	if (print_type === "reprint") {
		// For reprint, ask only for quantity without updating counters
		frappe.prompt(
			{
				fieldname: "reprint_qty",
				label: __("Reprint Quantity"),
				fieldtype: "Int",
				default: 1,
				reqd: 1,
				description: __("Enter the number of QR codes to reprint."),
			},
			(values) => {
				if (values.reprint_qty > 0) {
					var reprint_count = d.custom_reprint_count || 0;
					reprint_count += values.reprint_qty;
					frappe.model.set_value(cdt, cdn, "custom_reprint_count", reprint_count);
					generateQRCode(frm, d, values.reprint_qty, "reprint", 1, "reprint");
				}
			},
			__("Enter Reprint Quantity"),
			__("Reprint")
		);
	}
}

function generateQRCode(frm, item, quantity, quantity_type, start_number, print_type = "initial") {
	// Prepare QR data
	let qr_data = {
		item_code: item.item_code,
		item_name: item.item_name,
		purchase_receipt: frm.doc.name,
		quantity: quantity,
		quantity_type: quantity_type,
		batch_no: item.batch_no || "",
		serial_no: item.serial_no || "",
		print_type: print_type,
		timestamp: frappe.datetime.now_datetime(),
		start_number: start_number,
	};

	// Call server method to generate QR
	frappe.call({
		method: "impressio.impressio_transaction.override_class.purchase_receipt.generate_qr_code",
		args: {
			qr_data: qr_data,
			quantity: quantity,
		},
		callback: function (r) {
			if (r.message) {
				// Open print dialog or preview
				print_qr_document(r.message, frm, item, quantity, quantity_type, start_number);
			}
		},
		error: function (err) {
			frappe.msgprint(__("Error generating QR code: {0}", [err.message]));
		},
	});
}

function print_qr_document(qr_data, frm, item, quantity, quantity_type, start_number) {
	// Create print format HTML
	let print_html = `<!DOCTYPE html>
    <html>
    <head>
        <title>QR Code - ${qr_data.item_code}</title>
        <style>
		  
		  @page {
			size: auto;
			margin: 0;
		}

		body {
			margin: 0;
			padding: 0;
		}
			.qr-container {
			display: grid;
			grid-template-columns: repeat(2, 50mm); /* 2 columns */
			gap: 2mm;
			justify-content: start;
		}

		.qr-item {
			width: 50mm;
			height: 25mm;
			border: 1px solid #000;
			padding: 2mm;
			box-sizing: border-box;
			display: flex;
			flex-direction: row;
			align-items: center;
			gap: 2mm;
		}

	.qr-image img {
		width: 18mm;
		height: 18mm;
	}

	.qr-right {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		height: 100%;
	}

	.item-code {
		font-size: 9px;
		font-weight: bold;
	}

	.item-name {
		font-size: 7px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.quantity-badge {
		font-size: 7px;
		font-weight: bold;
	}

	.small-details {
		font-size: 6px;
		line-height: 1.2;
	}

	.timestamp {
		font-size: 6px;
		font-weight: bold;
	}

			</style>

    </head>
    <body>
        <div class="qr-container">`;

	let current_number = parseInt(start_number);

	for (let i = 0; i < quantity; i++) {
		let badge_class = quantity_type + "-badge";
		let display_type = quantity_type.charAt(0).toUpperCase() + quantity_type.slice(1);

		if (qr_data.print_type === "reprint") {
			badge_class = "reprint-badge";
			display_type = "Reprint";
		}

		print_html += `
			<div class="qr-item">

				<!-- LEFT : QR -->
				<div class="qr-image">
					<img src="data:image/png;base64,${qr_data.qr_image}">
				</div>

				<!-- RIGHT : DETAILS -->
				<div class="qr-right">

					<div class="item-code">
							${item.item_code}
					</div>

					<div class="item-name">
							${item.item_name || ""}
					</div>

					<div class="quantity-badge ${badge_class}">
							${display_type} - #${current_number + i}
					</div>

					<div class="small-details">
							PR: ${frm.doc.name}<br>
							Batch: ${item.batch_no || "N/A"}<br>
							Date: ${frm.doc.posting_date}
					</div>

					<div class="timestamp">
							${qr_data.print_type === "reprint" ? "REPRINT" : "ORIGINAL"}
					</div>

				</div>

			</div>`;
		// Add page break every 6 items
		// if ((i + 1) % 6 === 0) {
		// 	print_html += '<div style="page-break-after: always;"></div>';
		// }
	}

	print_html += `</div>
        <script>
            window.onload = function() {
                window.print();
            };
        </script>
    </body>
    </html>`;

	// Open print window
	let print_window = window.open("", "_blank");
	print_window.document.write(print_html);
	print_window.document.close();
}
