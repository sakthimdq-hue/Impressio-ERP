// Impressio Live Pricing Importer for ERPNext Quotation Form View

frappe.provide("impressio");

frappe.ui.form.on("Quotation", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("API"),
				function () {
					impressio.show_quotation_api_dialog(frm);
				},
				__("Get Items From")
			);
		}
	}
});

impressio.show_quotation_api_dialog = function (frm) {
	let raw_api_items = [];
	const DEFAULT_API_URL = "https://impressiouat.mdqapps.online/api/external/products?api_key=ed4e1357e99a5b4a76151409d56744f8d9a03a5ac3d8f5b14285ea088b8971c9";

	const d = new frappe.ui.Dialog({
		title: __("Import Items from API"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "header_html",
				options: `
					<div class="text-muted small" style="margin-bottom: 12px;">
						${__("Fetch items from the external API, select items, adjust quantities, and add them to this Quotation.")}
					</div>
				`
			},

					<div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px;">
						<div style="flex: 1;">
							<input type="text" id="quotation-api-url-input" class="form-control input-sm" 
								style="font-family: monospace; font-size: 12px; height: 34px; padding-left: 10px;" 
								value="${DEFAULT_API_URL}" 
								placeholder="https://api.example.com/pricing-items" />
						</div>
						<button type="button" id="btn-fetch-quotation-api" class="btn btn-sm btn-default" style="height: 34px; font-weight: 600; white-space: nowrap;">
							🔄 Fetch Live Data
						</button>
					</div>

					<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; background: #f8fafc; padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
						<div style="flex: 2; min-width: 160px;">
							<input type="text" id="quotation-item-search" class="form-control input-xs" placeholder="🔍 Search item code or name..." style="font-size: 12px; height: 28px;" />
						</div>
						<div style="flex: 1; min-width: 130px;">
							<select id="quotation-group-filter" class="form-control input-xs" style="font-size: 12px; height: 28px;">
								<option value="">All Groups</option>
							</select>
						</div>
						<div style="flex: 1; min-width: 110px;">
							<select id="quotation-tier-filter" class="form-control input-xs" style="font-size: 12px; height: 28px;">
								<option value="">All Tiers</option>
								<option value="Silver">Silver</option>
								<option value="Gold">Gold</option>
								<option value="Platinum">Platinum</option>
							</select>
						</div>
						<div style="display: flex; gap: 4px;">
							<button type="button" class="btn btn-xs btn-default" id="btn-select-all">Select All</button>
							<button type="button" class="btn btn-xs btn-default" id="btn-deselect-all">Deselect All</button>
						</div>
					</div>
				`
			},
			{
				fieldtype: "HTML",
				fieldname: "preview_html",
				options: `
					<div id="quotation-preview-container" style="min-height: 180px;">
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
						<div id="quotation-summary-stats" style="font-size: 12.5px; font-weight: 600; color: #065f46;">
							✅ 0 items selected (₹0.00 total)
						</div>
						<div style="display: flex; gap: 15px; align-items: center; font-size: 12px;">
							<label style="margin-bottom: 0; font-weight: normal; cursor: pointer; display: flex; align-items: center; gap: 5px;">
								<input type="radio" name="quotation-import-mode" value="append" checked />
								<span>Append to current items</span>
							</label>
							<label style="margin-bottom: 0; font-weight: normal; cursor: pointer; display: flex; align-items: center; gap: 5px;">
								<input type="radio" name="quotation-import-mode" value="replace" />
								<span>Replace existing items</span>
							</label>
						</div>
					</div>
				`
			}
		],
		primary_action_label: __("Add Selected Items to Quotation"),
		primary_action: function () {
			const selected_items = get_selected_items_with_qty();

			if (!selected_items || selected_items.length === 0) {
				frappe.msgprint({
					title: __("No Items Selected"),
					indicator: "orange",
					message: __("Please select at least one item to add to the Quotation.")
				});
				return;
			}

			const primary_btn = d.get_primary_btn();
			primary_btn.prop("disabled", true).text(__("Adding {0} Items...", [selected_items.length]));

			const import_mode = d.$wrapper.find("input[name='quotation-import-mode']:checked").val() || "append";

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
					});

					frm.refresh_field("items");

					// Recalculate totals
					if (frm.cscript && typeof frm.cscript.calculate_taxes_and_totals === "function") {
						frm.cscript.calculate_taxes_and_totals();
					} else if (frm.events && typeof frm.events.calculate_taxes_and_totals === "function") {
						frm.events.calculate_taxes_and_totals(frm);
					}

					frm.dirty();
					d.hide();

					frappe.show_alert({
						message: __("Added {0} items to Quotation successfully!", [selected_items.length]),
						indicator: "green"
					}, 6);
				},
				error: function () {
					primary_btn.prop("disabled", false).text(__("Add Selected Items to Quotation"));
				}
			});
		}
	});

	function get_selected_items_with_qty() {
		const selected = [];
		d.$wrapper.find(".quotation-item-checkbox:checked").each(function () {
			const idx = parseInt($(this).data("index"), 10);
			const it = raw_api_items[idx];
			if (it) {
				const qty_input = d.$wrapper.find(`.quotation-qty-input[data-index="${idx}"]`);
				const qty = parseFloat(qty_input.val()) || 1;
				const rate = it.standard_rate != null ? it.standard_rate : (it.msp != null ? it.msp : (it.calc_msp != null ? it.calc_msp : (it.price_incl_gst || 0)));

				selected.push({
					...it,
					item_code: it.item_code || it.code || it.sku,
					item_name: it.item_name || it.product_name || it.item_code,
					qty: qty,
					rate: rate,
					stock_uom: it.stock_uom || it.uom || "Nos",
					description: it.description || it.item_name
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

		d.$wrapper.find("#quotation-summary-stats").html(
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
		const search = (d.$wrapper.find("#quotation-item-search").val() || "").toLowerCase().trim();
		const group_filter = d.$wrapper.find("#quotation-group-filter").val() || "";
		const tier_filter = d.$wrapper.find("#quotation-tier-filter").val() || "";

		let filtered = raw_api_items.map((it, idx) => ({ ...it, _idx: idx })).filter(it => {
			const code = (it.item_code || it.code || "").toLowerCase();
			const name = (it.item_name || it.product_name || "").toLowerCase();
			const group = it.item_group || it.group || it.category || "Garments";
			const tier = it.tier || "";

			const match_search = !search || code.includes(search) || name.includes(search);
			const match_group = !group_filter || group === group_filter;
			const match_tier = !tier_filter || tier === tier_filter;

			return match_search && match_group && match_tier;
		});

		if (filtered.length === 0) {
			d.$wrapper.find("#quotation-preview-container").html(`
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
			const item_code = it.item_code || it.code || it.sku || "—";
			const item_name = it.item_name || it.product_name || item_code;
			const item_group = it.item_group || it.group || it.category || "Garments";
			const tier = it.tier || "";
			const standard_rate = it.standard_rate != null ? it.standard_rate : (it.msp != null ? it.msp : (it.calc_msp != null ? it.calc_msp : 0));
			const gst = it.gst_rate != null ? it.gst_rate + "%" : "—";
			const tierBadgeClass = tier === "Platinum" ? "badge-warning" : (tier === "Gold" ? "badge-info" : (tier === "Silver" ? "badge-secondary" : ""));

			rows += `
				<tr data-index="${idx}">
					<td style="text-align: center; vertical-align: middle;">
						<input type="checkbox" class="quotation-item-checkbox" data-index="${idx}" checked />
					</td>
					<td style="font-family: monospace; font-size: 11.5px; font-weight: 600; color: #1e293b; vertical-align: middle;">
						${frappe.utils.escape_html(item_code)}
					</td>
					<td style="font-size: 12px; vertical-align: middle;">
						${frappe.utils.escape_html(item_name)}
					</td>
					<td style="vertical-align: middle;">
						<span class="badge badge-light" style="font-size: 10px; border: 1px solid #e2e8f0;">${frappe.utils.escape_html(item_group)}</span>
					</td>
					<td style="vertical-align: middle;">
						${tier ? `<span class="badge ${tierBadgeClass}" style="font-size: 10px;">${frappe.utils.escape_html(tier)}</span>` : '<span class="text-muted">—</span>'}
					</td>
					<td style="width: 80px; vertical-align: middle;">
						<input type="number" min="1" step="1" value="1" class="form-control input-xs quotation-qty-input" data-index="${idx}" style="text-align: right; height: 26px; font-size: 11.5px;" />
					</td>
					<td class="text-right" style="font-family: monospace; font-size: 12px; font-weight: 700; color: #059669; vertical-align: middle;">
						₹${standard_rate}
					</td>
					<td class="text-right" style="font-size: 11px; color: #64748b; vertical-align: middle;">
						${gst}
					</td>
				</tr>
			`;
		});

		d.$wrapper.find("#quotation-preview-container").html(`
			<div style="max-height: 280px; overflow-y: auto; border: 1px solid #cbd5e1; border-radius: 6px;">
				<table class="table table-bordered table-condensed table-hover" style="margin-bottom: 0; font-size: 12px;">
					<thead style="background: #f8fafc; position: sticky; top: 0; z-index: 1;">
						<tr>
							<th style="width: 36px; text-align: center;">
								<input type="checkbox" id="header-select-all" checked />
							</th>
							<th>Item Code</th>
							<th>Item Name</th>
							<th>Group</th>
							<th>Tier</th>
							<th style="width: 80px; text-align: right;">Qty</th>
							<th class="text-right">MSP Rate ₹</th>
							<th class="text-right">GST %</th>
						</tr>
					</thead>
					<tbody>
						${rows}
					</tbody>
				</table>
			</div>
		`);

		update_summary_stats();
	}

	function populate_group_filters() {
		const groups = new Set();
		raw_api_items.forEach(it => {
			const g = it.item_group || it.group || it.category;
			if (g) groups.add(g);
		});

		const select = d.$wrapper.find("#quotation-group-filter");
		select.html('<option value="">All Groups</option>');
		Array.from(groups).sort().forEach(g => {
			select.append(`<option value="${frappe.utils.escape_html(g)}">${frappe.utils.escape_html(g)}</option>`);
		});
	}

	function fetch_data_from_api() {
		const url = (d.$wrapper.find("#quotation-api-url-input").val() || "").trim() || DEFAULT_API_URL;
		d.$wrapper.find("#quotation-preview-container").html(`
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
					d.$wrapper.find("#quotation-preview-container").html(`
						<div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 18px; text-align: center;">
							<div style="font-weight: 600; color: #991b1b; font-size: 13.5px;">Failed to Fetch API Data</div>
						</div>
					`);
				}
			},
			error: function (err) {
				d.$wrapper.find("#quotation-preview-container").html(`
					<div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 18px; text-align: center;">
						<div style="font-weight: 600; color: #991b1b; font-size: 13.5px;">Error: ${frappe.utils.escape_html(err && err.message ? err.message : "Network error")}</div>
					</div>
				`);
			}
		});
	}

	d.show();

	// Event Handlers
	d.$wrapper.find("#btn-fetch-quotation-api").on("click", function () {
		fetch_data_from_api();
	});

	d.$wrapper.find("#quotation-api-url-input").on("keypress", function (e) {
		if (e.which === 13) {
			e.preventDefault();
			fetch_data_from_api();
		}
	});

	d.$wrapper.on("input", "#quotation-item-search", function () {
		render_items_table();
	});

	d.$wrapper.on("change", "#quotation-group-filter, #quotation-tier-filter", function () {
		render_items_table();
	});

	d.$wrapper.on("change", "#header-select-all", function () {
		const is_checked = $(this).is(":checked");
		d.$wrapper.find(".quotation-item-checkbox").prop("checked", is_checked);
		update_summary_stats();
	});

	d.$wrapper.on("change", ".quotation-item-checkbox, .quotation-qty-input", function () {
		update_summary_stats();
	});

	d.$wrapper.find("#btn-select-all").on("click", function () {
		d.$wrapper.find(".quotation-item-checkbox").prop("checked", true);
		d.$wrapper.find("#header-select-all").prop("checked", true);
		update_summary_stats();
	});

	d.$wrapper.find("#btn-deselect-all").on("click", function () {
		d.$wrapper.find(".quotation-item-checkbox").prop("checked", false);
		d.$wrapper.find("#header-select-all").prop("checked", false);
		update_summary_stats();
	});

	// Auto-fetch on open
	fetch_data_from_api();
};
