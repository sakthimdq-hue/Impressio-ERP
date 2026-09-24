// Impressio Live Orders/Pricing Importer for ERPNext Sales Order Form View

frappe.provide("impressio");

frappe.ui.form.on("Sales Order", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("API"),
				function () {
					impressio.show_sales_order_api_dialog(frm);
				},
				__("Get Items From")
			);
		}
	}
});

impressio.show_sales_order_api_dialog = function (frm) {
	let raw_api_items = [];
	const DEFAULT_API_URL = "https://impressiodemouat.mdqapps.online/api/external/orders?api_key=gde76gg34g347g34g6643g6734g6643";

	const d = new frappe.ui.Dialog({
		title: __("Import Items from Orders API"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "header_html",
				options: `
					<div class="text-muted small" style="margin-bottom: 12px;">
						${__("Fetch items from the live Orders API, select items, adjust quantities, and add them to this Sales Order.")}
					</div>
					<div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px;">
						<div style="flex: 1;">
							<input type="text" id="sales-order-api-url-input" class="form-control input-sm" 
								style="font-family: monospace; font-size: 12px; height: 34px; padding-left: 10px;" 
								value="${DEFAULT_API_URL}" 
								placeholder="https://api.example.com/orders" />
						</div>
						<button type="button" id="btn-fetch-so-api" class="btn btn-sm btn-default" style="height: 34px; font-weight: 600; white-space: nowrap;">
							🔄 Fetch Live Data
						</button>
					</div>

					<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; background: #f8fafc; padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
						<div style="flex: 2; min-width: 160px;">
							<input type="text" id="so-item-search" class="form-control input-xs" placeholder="🔍 Search item code or name..." style="font-size: 12px; height: 28px;" />
						</div>
						<div style="flex: 1; min-width: 130px;">
							<select id="so-group-filter" class="form-control input-xs" style="font-size: 12px; height: 28px;">
								<option value="">All Categories</option>
							</select>
						</div>
						<div style="flex: 1; min-width: 110px;">
							<select id="so-tier-filter" class="form-control input-xs" style="font-size: 12px; height: 28px;">
								<option value="">All Types</option>
								<option value="bundle">Bundles Only</option>
								<option value="single">Single Items Only</option>
							</select>
						</div>
						<div style="display: flex; gap: 4px;">
							<button type="button" class="btn btn-xs btn-default" id="so-btn-select-all">Select All</button>
							<button type="button" class="btn btn-xs btn-default" id="so-btn-deselect-all">Deselect All</button>
						</div>
					</div>
				`
			},
			{
				fieldtype: "HTML",
				fieldname: "preview_html",
				options: `
					<div id="so-preview-container" style="min-height: 180px;">
						<div style="text-align: center; padding: 40px 20px; color: #64748b;">
							<div class="spinner-border spinner-border-sm text-primary" role="status" style="width: 2rem; height: 2rem; margin-bottom: 10px;"></div>
							<div style="font-size: 13px; font-weight: 500;">Connecting to API endpoint...</div>
						</div>
					</div>
				`
			},
			{
				fieldtype: "HTML",
				fieldname: "footer_options_html",
				options: `
					<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; padding: 10px 14px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0; flex-wrap: wrap; gap: 8px;">
						<div id="so-summary-stats" style="font-size: 12.5px; font-weight: 600; color: #065f46;">
							✅ 0 items selected (₹0.00 total)
						</div>
						<div style="display: flex; gap: 15px; align-items: center; font-size: 12px;">
							<label style="margin-bottom: 0; font-weight: normal; cursor: pointer; display: flex; align-items: center; gap: 5px;">
								<input type="radio" name="so-import-mode" value="append" checked />
								<span>Append to current items</span>
							</label>
							<label style="margin-bottom: 0; font-weight: normal; cursor: pointer; display: flex; align-items: center; gap: 5px;">
								<input type="radio" name="so-import-mode" value="replace" />
								<span>Replace existing items</span>
							</label>
						</div>
					</div>
				`
			}
		],
		primary_action_label: __("Add Selected Items to Sales Order"),
		primary_action: function () {
			const selected_items = get_selected_items_with_qty();

			if (!selected_items || selected_items.length === 0) {
				frappe.msgprint({
					title: __("No Items Selected"),
					indicator: "orange",
					message: __("Please select at least one item to add to the Sales Order.")
				});
				return;
			}

			const primary_btn = d.get_primary_btn();
			primary_btn.prop("disabled", true).text(__("Adding {0} Items...", [selected_items.length]));

			const import_mode = d.$wrapper.find("input[name='so-import-mode']:checked").val() || "append";

			// First, ensure all selected items exist in Item Master in ERPNext
			frappe.call({
				method: "impressio.api.import_pricing_items",
				args: {
					items_data: selected_items
				},
				freeze: true,
				freeze_message: __("Preparing item records in ERPNext..."),
				callback: function (r) {
					primary_btn.prop("disabled", false);

					if (import_mode === "replace") {
						frm.clear_table("items");
						if (frm.doc.custom_sub_items) {
							frm.clear_table("custom_sub_items");
						}
					}

					selected_items.forEach(it => {
						const row = frm.add_child("items");
						row.item_code = it.item_code;
						row.item_name = it.item_name || it.item_code;
						row.qty = it.qty || 1;
						row.rate = it.rate || 0;
						row.price_list_rate = it.rate || 0;
						row.amount = (it.qty || 1) * (it.rate || 0);
						row.uom = it.stock_uom || "Nos";
						row.stock_uom = it.stock_uom || "Nos";
						row.description = it.description || it.item_name || it.item_code;
						if (frm.doc.set_warehouse) {
							row.warehouse = frm.doc.set_warehouse;
						}

						// Handle sub items for bundles
						if (it.is_bundle && it.bundle_items && it.bundle_items.length) {
							it.bundle_items.forEach(sub => {
								const sub_code = sub.item_code || sub.code || (sub.product_id ? `PROD-${sub.product_id}` : sub.website_display_name);
								const sub_row = frm.add_child("custom_sub_items");
								sub_row.parent_item_code = it.item_code;
								sub_row.item_code = sub_code;
								sub_row.qty = (sub.quantity || 1) * (it.qty || 1);
							});
						} else {
							const sub_row = frm.add_child("custom_sub_items");
							sub_row.parent_item_code = it.item_code;
							sub_row.item_code = it.item_code;
							sub_row.qty = it.qty || 1;
						}
					});

					frm.refresh_field("items");
					frm.refresh_field("custom_sub_items");

					// Recalculate totals
					if (frm.cscript && typeof frm.cscript.calculate_taxes_and_totals === "function") {
						frm.cscript.calculate_taxes_and_totals();
					} else if (frm.events && typeof frm.events.calculate_taxes_and_totals === "function") {
						frm.events.calculate_taxes_and_totals(frm);
					}

					frm.dirty();
					d.hide();

					frappe.show_alert({
						message: __("Added {0} items to Sales Order successfully!", [selected_items.length]),
						indicator: "green"
					}, 6);
				},
				error: function (err) {
					primary_btn.prop("disabled", false).text(__("Add Selected Items to Sales Order"));
					let msg = (err && err.message) ? err.message : __("Error preparing items in ERPNext.");
					frappe.msgprint({
						title: __("Item Preparation Error"),
						indicator: "red",
						message: msg
					});
				}
			});
		}
	});

	function get_selected_items_with_qty() {
		const selected = [];
		d.$wrapper.find(".so-item-checkbox:checked").each(function () {
			const idx = parseInt($(this).data("index"), 10);
			const it = raw_api_items[idx];
			if (it) {
				const qty_input = d.$wrapper.find(`.so-qty-input[data-index="${idx}"]`);
				const qty = parseFloat(qty_input.val()) || 1;
				const rate = it.standard_rate != null ? it.standard_rate : (it.calc_msp != null ? parseFloat(it.calc_msp) : (it.rate || 0));

				selected.push({
					...it,
					item_code: it.item_code || it.code || (it.product_id ? `PROD-${it.product_id}` : ""),
					item_name: it.item_name || it.website_display_name || it.product_name || it.item_code,
					qty: qty,
					rate: rate,
					stock_uom: it.stock_uom || it.uom || "Nos",
					description: it.description || it.website_display_name || it.item_name
				});
			}
		});
		return selected;
	}

	function update_summary_stats() {
		const selected = get_selected_items_with_qty();
		let total_val = 0;
		selected.forEach(s => {
			total_val += (s.qty * s.rate);
		});

		d.$wrapper.find("#so-summary-stats").html(
			`✅ <b>${selected.length}</b> items selected (Total: <b>₹${total_val.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b>)`
		);

		const btn = d.get_primary_btn();
		if (selected.length === 0) {
			btn.prop("disabled", true).text(__("Add Selected Items"));
		} else {
			btn.prop("disabled", false).text(__("➕ Add {0} Items (₹{1})", [selected.length, Math.round(total_val)]));
		}
	}

	function render_items_table() {
		const search = (d.$wrapper.find("#so-item-search").val() || "").toLowerCase().trim();
		const group_filter = d.$wrapper.find("#so-group-filter").val() || "";
		const tier_filter = d.$wrapper.find("#so-tier-filter").val() || "";

		let filtered = raw_api_items.map((it, idx) => ({ ...it, _idx: idx })).filter(it => {
			const code = (it.item_code || it.code || "").toLowerCase();
			const name = (it.website_display_name || it.item_name || it.product_name || "").toLowerCase();
			const group = it.item_group || it.category_name || it.category || "Garments";
			const is_bundle = !!it.is_bundle;

			const match_search = !search || code.includes(search) || name.includes(search);
			const match_group = !group_filter || group === group_filter;
			let match_tier = true;
			if (tier_filter === "bundle") match_tier = is_bundle;
			if (tier_filter === "single") match_tier = !is_bundle;

			return match_search && match_group && match_tier;
		});

		if (filtered.length === 0) {
			d.$wrapper.find("#so-preview-container").html(`
				<div style="text-align: center; padding: 30px; border: 1px dashed #cbd5e1; border-radius: 8px; background: #fafbfc;">
					<div style="font-size: 24px; margin-bottom: 4px;">🔍</div>
					<div style="font-weight: 600; color: #475569; font-size: 13px;">No items match your filter criteria</div>
					<div style="font-size: 11.5px; color: #94a3b8; margin-top: 3px;">Try clearing the search or category filters.</div>
				</div>
			`);
			update_summary_stats();
			return;
		}

		let rows = "";
		filtered.forEach(it => {
			const idx = it._idx;
			const code = it.item_code || it.code || (it.product_id ? `PROD-${it.product_id}` : "ITEM");
			const name = it.website_display_name || it.item_name || it.product_name || code;
			const group = it.item_group || it.category_name || it.category || "Garments";
			const rate = it.standard_rate != null ? it.standard_rate : (it.calc_msp != null ? parseFloat(it.calc_msp) : 0);
			const is_bundle = it.is_bundle ? `<span class="badge badge-warning" style="font-size:10px; margin-left: 5px;">Bundle</span>` : "";
			const img_src = it.image_url || (it.image_urls && it.image_urls.length ? it.image_urls[0] : "");
			const img_html = img_src
				? `<img src="${img_src}" style="width: 32px; height: 32px; object-fit: cover; border-radius: 4px; border: 1px solid #e2e8f0; margin-right: 8px;" />`
				: `<div style="width: 32px; height: 32px; background: #f1f5f9; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font-size: 14px; margin-right: 8px; color: #94a3b8;">📦</div>`;

			rows += `
				<tr style="border-bottom: 1px solid #f1f5f9; vertical-align: middle;">
					<td style="width: 40px; text-align: center; padding: 8px 4px;">
						<input type="checkbox" class="so-item-checkbox" data-index="${idx}" checked />
					</td>
					<td style="padding: 8px 6px;">
						<div style="display: flex; align-items: center;">
							${img_html}
							<div>
								<div style="font-weight: 600; font-size: 12.5px; color: #1e293b;">${frappe.utils.escape_html(name)} ${is_bundle}</div>
								<div style="font-size: 11px; color: #64748b; font-family: monospace;">${frappe.utils.escape_html(code)} • <span class="badge badge-light">${frappe.utils.escape_html(group)}</span></div>
							</div>
						</div>
					</td>
					<td style="width: 90px; text-align: right; padding: 8px 6px; font-weight: 600; font-size: 12.5px; color: #0f172a;">
						₹${rate.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
					</td>
					<td style="width: 90px; padding: 8px 6px; text-align: center;">
						<input type="number" class="form-control input-xs so-qty-input" data-index="${idx}" value="${it.quantity || 1}" min="1" style="text-align: center; width: 70px; margin: 0 auto;" />
					</td>
				</tr>
			`;
		});

		const table_html = `
			<div style="max-height: 380px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px;">
				<table class="table table-hover" style="margin-bottom: 0; font-size: 12px; width: 100%;">
					<thead style="background: #f8fafc; position: sticky; top: 0; z-index: 2; border-bottom: 1px solid #cbd5e1;">
						<tr>
							<th style="width: 40px; text-align: center; padding: 8px 4px;">
								<input type="checkbox" id="so-header-select-all" checked />
							</th>
							<th style="padding: 8px 6px;">Item</th>
							<th style="width: 90px; text-align: right; padding: 8px 6px;">Rate</th>
							<th style="width: 90px; text-align: center; padding: 8px 6px;">Qty</th>
						</tr>
					</thead>
					<tbody>
						${rows}
					</tbody>
				</table>
			</div>
		`;

		d.$wrapper.find("#so-preview-container").html(table_html);
		update_summary_stats();
	}

	function populate_group_filters() {
		const groups = new Set();
		raw_api_items.forEach(it => {
			const g = it.item_group || it.category_name || it.category || "Garments";
			if (g) groups.add(g);
		});

		let options = `<option value="">All Categories</option>`;
		Array.from(groups).sort().forEach(g => {
			options += `<option value="${frappe.utils.escape_html(g)}">${frappe.utils.escape_html(g)}</option>`;
		});

		d.$wrapper.find("#so-group-filter").html(options);
	}

	function fetch_data_from_api() {
		const url = (d.$wrapper.find("#sales-order-api-url-input").val() || "").trim() || DEFAULT_API_URL;
		d.$wrapper.find("#so-preview-container").html(`
			<div style="text-align: center; padding: 40px 20px; color: #047857; background: #fafafa; border-radius: 8px; border: 1px dashed #cbd5e1;">
				<div style="font-size: 24px; margin-bottom: 8px; animation: spin 1s linear infinite;">⏳</div>
				<div style="font-size: 13.5px; font-weight: 600; color: #1e293b;">Fetching live items from API...</div>
			</div>
		`);

		frappe.call({
			method: "impressio.api.fetch_pricing_from_api",
			args: { api_url: url },
			callback: function (r) {
				if (r && r.message && r.message.success) {
					raw_api_items = r.message.items || [];
					populate_group_filters();
					render_items_table();
				} else {
					d.$wrapper.find("#so-preview-container").html(`
						<div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 18px; text-align: center;">
							<div style="font-weight: 600; color: #991b1b; font-size: 13.5px;">Failed to Fetch API Data</div>
						</div>
					`);
				}
			},
			error: function (err) {
				let err_msg = (err && err.message) ? err.message : "Network or API format error";
				d.$wrapper.find("#so-preview-container").html(`
					<div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 18px; text-align: center;">
						<div style="font-weight: 600; color: #991b1b; font-size: 13.5px;">Error: ${frappe.utils.escape_html(err_msg)}</div>
						<div style="font-size: 11.5px; color: #b91c1c; margin-top: 4px;">Please check the API key, network connection, or endpoint parameters.</div>
					</div>
				`);
			}
		});
	}

	d.show();

	// Event Handlers
	d.$wrapper.find("#btn-fetch-so-api").on("click", function () {
		fetch_data_from_api();
	});

	d.$wrapper.find("#sales-order-api-url-input").on("keypress", function (e) {
		if (e.which === 13) {
			e.preventDefault();
			fetch_data_from_api();
		}
	});

	d.$wrapper.on("input", "#so-item-search", function () {
		render_items_table();
	});

	d.$wrapper.on("change", "#so-group-filter, #so-tier-filter", function () {
		render_items_table();
	});

	d.$wrapper.on("change", "#so-header-select-all", function () {
		const is_checked = $(this).is(":checked");
		d.$wrapper.find(".so-item-checkbox").prop("checked", is_checked);
		update_summary_stats();
	});

	d.$wrapper.on("change", ".so-item-checkbox, .so-qty-input", function () {
		update_summary_stats();
	});

	d.$wrapper.find("#so-btn-select-all").on("click", function () {
		d.$wrapper.find(".so-item-checkbox").prop("checked", true);
		d.$wrapper.find("#so-header-select-all").prop("checked", true);
		update_summary_stats();
	});

	d.$wrapper.find("#so-btn-deselect-all").on("click", function () {
		d.$wrapper.find(".so-item-checkbox").prop("checked", false);
		d.$wrapper.find("#so-header-select-all").prop("checked", false);
		update_summary_stats();
	});

	// Auto-fetch on open
	fetch_data_from_api();
};
