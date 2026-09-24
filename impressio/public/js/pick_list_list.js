frappe.listview_settings["Pick List"] = Object.assign(
	frappe.listview_settings["Pick List"] || {},
	{
		add_fields: ["status", "purpose", "owner", "creation"],

		onload(listview) {

			// ── Download Pick List ──────────────────────────────────────────
			listview.page.add_inner_button("Download Pick List", function () {
				let selected = listview.get_checked_items();

				if (!selected.length) {
					frappe.msgprint({
						title: "No Selection",
						indicator: "orange",
						message: "Please select one or more Pick Lists to download.",
					});
					return;
				}

				if (selected.length === 1) {
					// Single pick list → show format chooser dialog
					open_single_picklist_download(selected[0].name);
				} else {
					// Multiple pick lists → consolidated download dialog
					open_bulk_picklist_download(selected.map((d) => d.name));
				}
			});
		},
	}
);


// ═══════════════════════════════════════════════════════════════
// SINGLE PICK LIST DOWNLOAD
// ═══════════════════════════════════════════════════════════════

function open_single_picklist_download(pl_name) {
	let dialog = new frappe.ui.Dialog({
		title: `Download — ${pl_name}`,
		size: "small",
		fields: [{ fieldtype: "HTML", fieldname: "content_html" }],
	});

	dialog.show();

	dialog.fields_dict.content_html.$wrapper.html(`
		<style>
			.dl-btn {
				display: flex;
				align-items: center;
				gap: 12px;
				width: 100%;
				padding: 14px 18px;
				border-radius: 8px;
				border: 1px solid #dee2e6;
				background: white;
				cursor: pointer;
				margin-bottom: 10px;
				transition: all 0.15s ease;
				font-size: 14px;
				font-weight: 600;
			}
			.dl-btn:hover { background: #f8f9fa; border-color: #adb5bd; }
			.dl-btn .icon { font-size: 22px; }
			.dl-btn .desc { font-size: 11px; color: #888; font-weight: 400; }
		</style>

		<p class="text-muted mb-3">Choose a format to download <b>${pl_name}</b>:</p>

		<button class="dl-btn" id="dl_excel_single">
			<span class="icon">📥</span>
			<div>
				<div>Download as Excel / CSV</div>
				<div class="desc">Opens in Microsoft Excel or Google Sheets</div>
			</div>
		</button>

		<button class="dl-btn" id="dl_pdf_single">
			<span class="icon">📄</span>
			<div>
				<div>Download as PDF</div>
				<div class="desc">Opens browser print dialog — Save as PDF</div>
			</div>
		</button>
	`);

	// Fetch pick list data then trigger download
	dialog.$wrapper.find("#dl_excel_single").on("click", function () {
		fetch_and_download_picklist(pl_name, "excel", dialog);
	});

	dialog.$wrapper.find("#dl_pdf_single").on("click", function () {
		fetch_and_download_picklist(pl_name, "pdf", dialog);
	});
}


// ═══════════════════════════════════════════════════════════════
// BULK PICK LIST DOWNLOAD (multiple selected)
// ═══════════════════════════════════════════════════════════════

function open_bulk_picklist_download(pl_names) {
	let dialog = new frappe.ui.Dialog({
		title: `Download ${pl_names.length} Pick Lists`,
		size: "small",
		fields: [{ fieldtype: "HTML", fieldname: "content_html" }],
	});

	dialog.show();

	dialog.fields_dict.content_html.$wrapper.html(`
		<style>
			.dl-btn {
				display: flex;
				align-items: center;
				gap: 12px;
				width: 100%;
				padding: 14px 18px;
				border-radius: 8px;
				border: 1px solid #dee2e6;
				background: white;
				cursor: pointer;
				margin-bottom: 10px;
				transition: all 0.15s ease;
				font-size: 14px;
				font-weight: 600;
			}
			.dl-btn:hover { background: #f8f9fa; border-color: #adb5bd; }
			.dl-btn .icon { font-size: 22px; }
			.dl-btn .desc { font-size: 11px; color: #888; font-weight: 400; }
		</style>

		<p class="text-muted mb-3">
			Download <b>${pl_names.length}</b> Pick Lists consolidated into one file:
		</p>

		<button class="dl-btn" id="dl_excel_bulk">
			<span class="icon">📥</span>
			<div>
				<div>Download as Excel / CSV</div>
				<div class="desc">All pick lists combined with separators</div>
			</div>
		</button>

		<button class="dl-btn" id="dl_pdf_bulk">
			<span class="icon">📄</span>
			<div>
				<div>Download as PDF</div>
				<div class="desc">All pick lists on separate pages</div>
			</div>
		</button>
	`);

	dialog.$wrapper.find("#dl_excel_bulk").on("click", function () {
		fetch_and_download_bulk(pl_names, "excel", dialog);
	});

	dialog.$wrapper.find("#dl_pdf_bulk").on("click", function () {
		fetch_and_download_bulk(pl_names, "pdf", dialog);
	});
}


// ═══════════════════════════════════════════════════════════════
// FETCH PICK LIST DATA FROM FRAPPE
// The pick list locations table stores ONE row per item even when
// multiple SOs are involved — so we ALSO query the Sales Order
// Items table to recover all linked SOs for each item.
// ═══════════════════════════════════════════════════════════════

function fetch_picklist_data(pl_name, callback) {
    // Step 1: Get Pick List header (status, creation, etc.)
    frappe.call({
        method: "frappe.client.get",
        args: { doctype: "Pick List", name: pl_name },
        callback(r) {
            if (!r.message) {
                frappe.msgprint({
                    title: "Error", indicator: "red",
                    message: `Could not load ${pl_name}`
                });
                return;
            }
            let doc = r.message;

            // Step 2: Use whitelisted server method to get item→SO mapping.
            // This reads tabPick List Item directly from DB — no child-table
            // permission errors, and correctly aggregates multiple rows
            // per item (one row per SO) that frappe.client.get_list can't reach.
            frappe.call({
                method: "impressio.impressio.bulk_delivery_note.get_pick_list_so_details",
                args: { pick_list_name: pl_name },
                callback(r2) {
                    let item_map = {};

                    if (r2.message && r2.message.length) {
                        // Server method returned full item→SO data
                        r2.message.forEach((item) => {
                            item_map[item.item_code] = {
                                item_code  : item.item_code,
                                item_name  : item.item_name || item.item_code,
                                warehouse  : item.warehouse || "",
                                uom        : item.uom || "Nos",
                                total_qty  : item.total_qty || 0,
                                picked_qty : item.picked_qty || 0,
                                so_list    : item.so_list || [],
                            };
                        });
                    } else {
                        // Fallback: build from doc.locations (single SO per item)
                        _build_item_map_from_locations(doc.locations || [], item_map);
                    }

                    _finalize_picklist_data(pl_name, doc, item_map, callback);
                },
                error() {
                    // Fallback if method call itself fails
                    let item_map = {};
                    _build_item_map_from_locations(doc.locations || [], item_map);
                    _finalize_picklist_data(pl_name, doc, item_map, callback);
                },
            });
        },
    });
}

// Helper: builds item_map from doc.locations (used as fallback)
function _build_item_map_from_locations(locations, item_map) {
    locations.forEach((loc) => {
        let key = loc.item_code;
        if (!item_map[key]) {
            item_map[key] = {
                item_code  : loc.item_code,
                item_name  : loc.item_name || loc.item_code,
                warehouse  : loc.warehouse || "",
                uom        : loc.uom || "Nos",
                total_qty  : 0,
                picked_qty : 0,
                so_list    : [],
            };
        }
        item_map[key].total_qty  += (loc.qty || 0);
        item_map[key].picked_qty += (loc.picked_qty || 0);

        let so_ref = (loc.sales_order || loc.against_sales_order || "").trim();
        if (!so_ref) {
            Object.keys(loc).forEach((f) => {
                if (!so_ref && typeof loc[f] === "string" &&
                    loc[f].startsWith("SAL-ORD-"))
                    so_ref = loc[f];
            });
        }
        if (so_ref && !item_map[key].so_list.includes(so_ref))
            item_map[key].so_list.push(so_ref);
    });
}




function _finalize_picklist_data(pl_name, doc, item_map, callback) {
	let items        = Object.values(item_map);
	let total_qty    = items.reduce((s, i) => s + i.total_qty, 0);
	let total_items  = items.length;
	let so_set       = new Set();
	items.forEach((i) => i.so_list.forEach((s) => so_set.add(s)));
	let total_orders = so_set.size;

	callback({
		pl_name,
		doc,
		items,
		total_qty,
		total_items,
		total_orders,
		creation: doc.creation || "",
		status  : doc.status || "",
	});
}


// ═══════════════════════════════════════════════════════════════
// SINGLE — FETCH THEN DOWNLOAD
// ═══════════════════════════════════════════════════════════════

function fetch_and_download_picklist(pl_name, format, dialog) {
	dialog.hide();

	frappe.show_alert({ message: `Preparing ${pl_name}...`, indicator: "blue" }, 2);

	fetch_picklist_data(pl_name, (data) => {
		if (format === "excel") {
			download_picklist_csv([data]);
		} else {
			download_picklist_pdf([data]);
		}
	});
}


// ═══════════════════════════════════════════════════════════════
// BULK — FETCH ALL THEN DOWNLOAD
// ═══════════════════════════════════════════════════════════════

function fetch_and_download_bulk(pl_names, format, dialog) {
	dialog.hide();

	frappe.show_alert({ message: `Loading ${pl_names.length} Pick Lists...`, indicator: "blue" }, 2);

	let all_data = [];
	let fetched  = 0;

	pl_names.forEach((pl_name) => {
		fetch_picklist_data(pl_name, (data) => {
			all_data.push(data);
			fetched++;

			if (fetched === pl_names.length) {
				// Sort by name for consistent order
				all_data.sort((a, b) => a.pl_name.localeCompare(b.pl_name));

				if (format === "excel") {
					download_picklist_csv(all_data);
				} else {
					download_picklist_pdf(all_data);
				}
			}
		});
	});
}


// ═══════════════════════════════════════════════════════════════
// CSV / EXCEL DOWNLOAD
// ═══════════════════════════════════════════════════════════════

function download_picklist_csv(all_data) {
	let csv_rows = [];

	all_data.forEach((data, idx) => {
		// Section header per pick list
		if (idx > 0) csv_rows.push([]); // blank separator
		csv_rows.push([`"Pick List: ${data.pl_name}"`, `"Status: ${data.status}"`, `"Created: ${data.creation}"`]);
		csv_rows.push([`"Sales Orders: ${data.total_orders}"`, `"Unique Items: ${data.total_items}"`, `"Total Qty: ${data.total_qty}"`]);
		csv_rows.push([]); // blank

		// Column headers
		csv_rows.push([
			"#",
			"Item Code",
			"Item Name",
			"Total Qty",
			"Picked Qty",
			"UOM",
			"Warehouse",
			"No. of Orders",
			"Source Sales Orders",
		]);

		// Item rows
		data.items.forEach((i, item_idx) => {
			csv_rows.push([
				item_idx + 1,
				`"${(i.item_code || "").replace(/"/g, '""')}"`,
				`"${(i.item_name || i.item_code || "").replace(/"/g, '""')}"`,
				i.total_qty,
				i.picked_qty,
				i.uom,
				`"${(i.warehouse || "").replace(/"/g, '""')}"`,
				i.so_list.length,
				`"${i.so_list.join(", ").replace(/"/g, '""')}"`,
			]);
		});
	});

	let csv_content = csv_rows.map((r) => r.join(",")).join("\n");
	let blob        = new Blob(["\uFEFF" + csv_content], { type: "text/csv;charset=utf-8;" });
	let url         = URL.createObjectURL(blob);
	let link        = document.createElement("a");
	let filename    = all_data.length === 1
		? `PickList_${all_data[0].pl_name}_${frappe.datetime.now_date()}.csv`
		: `PickLists_Bulk_${frappe.datetime.now_date()}.csv`;

	link.setAttribute("href", url);
	link.setAttribute("download", filename);
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);

	frappe.show_alert({ message: `✅ Downloaded ${filename}`, indicator: "green" }, 4);
}


// ═══════════════════════════════════════════════════════════════
// PDF DOWNLOAD  (matches the format from your existing pick list PDF)
// ═══════════════════════════════════════════════════════════════

function download_picklist_pdf(all_data) {

	// Build one page per pick list
	let pages_html = all_data.map((data, page_idx) => {

		let item_rows = data.items.map((i, idx) => `
			<tr style="background:${idx % 2 === 0 ? "#fff" : "#f9fbff"}">
				<td style="padding:8px 10px;border:1px solid #dde3ec;text-align:center;color:#888">${idx + 1}</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec">
					<b style="color:#1a1a2e">${i.item_code}</b>
					${i.item_name && i.item_name !== i.item_code
						? `<br><span style="color:#888;font-size:11px">${i.item_name}</span>`
						: ""}
				</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec;text-align:center;
				           font-size:18px;font-weight:800;color:#2d6a4f">${i.total_qty}</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec;text-align:center;color:#666">${i.uom}</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec;color:#555;font-size:12px">${i.warehouse || "—"}</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec;text-align:center">
					<span style="background:#dbeafe;color:#1d4ed8;border-radius:12px;
					             padding:2px 10px;font-size:12px;font-weight:600">
						${i.so_list.length}
					</span>
				</td>
				<td style="padding:8px 10px;border:1px solid #dde3ec;font-size:11px;color:#444;line-height:1.7">
					${i.so_list.join("<br>")}
				</td>
			</tr>`
		).join("");

		if (!item_rows) {
			item_rows = `<tr><td colspan="7" style="text-align:center;padding:20px;color:#aaa">No items found</td></tr>`;
		}

		return `
		<div class="pl-page" style="${page_idx > 0 ? "page-break-before:always;padding-top:30px" : ""}">

			<!-- Header -->
			<div style="display:flex;align-items:center;justify-content:space-between;
			            border-bottom:3px solid #1a1a2e;padding-bottom:14px;margin-bottom:20px">
				<div>
					<div style="font-size:22px;font-weight:800;color:#1a1a2e;letter-spacing:-0.5px">
						📦 Pick List
					</div>
					<div style="font-size:12px;color:#888;margin-top:4px">
						Ref: <b style="color:#1a1a2e">${data.pl_name}</b>
						&nbsp;|&nbsp; Status: <b>${data.status || "—"}</b>
						&nbsp;|&nbsp; ${frappe.datetime.now_datetime()}
					</div>
				</div>
				<div style="text-align:right;font-size:12px;color:#888">
					<div style="font-weight:700;color:#1a1a2e;font-size:14px">Inventre Edu Services Pvt Ltd</div>
					<div>Printed from ERPNext</div>
				</div>
			</div>

			<!-- Summary Cards -->
			<div style="display:flex;gap:16px;margin-bottom:24px">
				<div style="flex:1;border:1px solid #dde3ec;border-top:4px solid #3b82f6;
				            border-radius:8px;padding:14px;text-align:center;background:white">
					<div style="font-size:28px;font-weight:800;color:#3b82f6">${data.total_orders}</div>
					<div style="font-size:11px;color:#888;margin-top:2px">Sales Orders</div>
				</div>
				<div style="flex:1;border:1px solid #dde3ec;border-top:4px solid #22c55e;
				            border-radius:8px;padding:14px;text-align:center;background:white">
					<div style="font-size:28px;font-weight:800;color:#22c55e">${data.total_items}</div>
					<div style="font-size:11px;color:#888;margin-top:2px">Unique Items</div>
				</div>
				<div style="flex:1;border:1px solid #dde3ec;border-top:4px solid #06b6d4;
				            border-radius:8px;padding:14px;text-align:center;background:white">
					<div style="font-size:28px;font-weight:800;color:#06b6d4">${data.total_qty}</div>
					<div style="font-size:11px;color:#888;margin-top:2px">Total Qty to Pick</div>
				</div>
			</div>

			<!-- Item Table -->
			<table style="width:100%;border-collapse:collapse;font-size:13px">
				<thead>
					<tr style="background:#1a1a2e;color:white">
						<th style="padding:10px;border:1px solid #1a1a2e;text-align:center;width:4%">#</th>
						<th style="padding:10px;border:1px solid #1a1a2e;width:26%">Item Code / Name</th>
						<th style="padding:10px;border:1px solid #1a1a2e;text-align:center;width:9%">Total Qty</th>
						<th style="padding:10px;border:1px solid #1a1a2e;text-align:center;width:6%">UOM</th>
						<th style="padding:10px;border:1px solid #1a1a2e;width:17%">Warehouse</th>
						<th style="padding:10px;border:1px solid #1a1a2e;text-align:center;width:8%">Orders</th>
						<th style="padding:10px;border:1px solid #1a1a2e;width:30%">Source Sales Orders</th>
					</tr>
				</thead>
				<tbody>${item_rows}</tbody>
			</table>

			<!-- Footer -->
			<div style="margin-top:24px;padding-top:12px;border-top:1px solid #eee;
			            font-size:11px;color:#aaa;display:flex;justify-content:space-between">
				<span>Inventre Edu Services Pvt Ltd &nbsp;|&nbsp; Printed from ERPNext</span>
				<span>${data.pl_name} &nbsp;|&nbsp; ${frappe.datetime.now_date()}</span>
			</div>

		</div>`;
	}).join("\n");

	let print_html = `
	<!DOCTYPE html>
	<html>
	<head>
		<meta charset="utf-8">
		<title>Pick List — ${all_data.map(d => d.pl_name).join(", ")}</title>
		<style>
			* { box-sizing: border-box; margin: 0; padding: 0; }
			body { font-family: Arial, sans-serif; padding: 28px; background: white; color: #1a1a2e; }
			@media print {
				body { padding: 16px; }
				button { display: none !important; }
				.no-print { display: none !important; }
			}
		</style>
	</head>
	<body>
		${pages_html}
	</body>
	</html>`;

	let print_win = window.open("", "_blank", "width=950,height=750");
	print_win.document.write(print_html);
	print_win.document.close();
	print_win.focus();
	setTimeout(() => print_win.print(), 600);
}