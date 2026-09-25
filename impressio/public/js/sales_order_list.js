frappe.listview_settings["Sales Order"] = Object.assign(
	frappe.listview_settings["Sales Order"] || {},
	{
		 // Tell Frappe to fetch these extra fields in every list row
        add_fields: [
            "custom_gateway_provider",
            "custom_payment_finalized",
            "custom_payment_status",
            "per_delivered",
            "custom_display_status" 
        ],

         _sub_counts: {},
_fetch_sub_counts(listview) {
    let so_names = (listview.data || []).map(d => d.name);
    if (!so_names.length) return;
    frappe.call({
        method: "impressio.impressio.bulk_delivery_note.get_sub_item_delivery_counts",
        args: { sales_orders: so_names },
        callback: (r) => {
            if (!r.message) return;
            Object.assign(
                frappe.listview_settings["Sales Order"]._sub_counts,
                r.message
            );
            // ✅ Only repaint indicator badges — no server refetch, no loop
            $(listview.wrapper).find(".list-row").each(function() {
                let row_name = $(this).attr("data-name");
                if (!row_name) return;
                let doc = (listview.data || []).find(d => d.name === row_name);
                if (!doc) return;
                let indicator = listview.get_indicator(doc);
                if (!indicator) return;
                $(this).find(".indicator-pill")
                    .removeClass()
                    .addClass(`indicator-pill ${indicator[1]}`)
                    .text(indicator[0]);
            });
        }
    });
},



		// Override indicator to use simple status filter on click
		// REPLACE WITH THIS NEW get_indicator:
get_indicator(doc) {
    // First priority: Use custom_display_status if set
    
    
    
    // Only fall back to default status if custom status is not set
    const status_map = {
        Draft: ["Draft", "red", "status,=,Draft"],
        "On Hold": ["On Hold", "orange", "status,=,On Hold"],
        "To Deliver and Bill": ["To Deliver and Bill", "orange", "status,=,To Deliver and Bill"],
        "To Bill": ["To Bill", "yellow", "status,=,To Bill"],
        "To Deliver": ["To Deliver", "cyan", "status,=,To Deliver"],
        Completed: ["Completed", "green", "status,=,Completed"],
        Cancelled: ["Cancelled", "red", "status,=,Cancelled"],
        Closed: ["Closed", "green", "status,=,Closed"],
    };
    return status_map[doc.status] || [doc.status, "grey", "status,=," + doc.status];
},

		onload(listview) {


            listview.page.wrapper.on("list-update", () => {
        frappe.listview_settings["Sales Order"]._fetch_sub_counts(listview);
    });

        // ✅ Add quick filter for Partially Delivered
    //     listview.page.add_inner_button("Partially Delivered", function () {
    //     listview.filter_area.clear();

    //     frappe.call({
    //         method: "frappe.client.get_list",
    //         args: {
    //             doctype: "Sales Order",
    //             filters: [
    //                 ["status", "in", ["To Deliver and Bill", "To Deliver"]]
    //             ],
    //             or_filters: [
    //                 ["custom_display_status", "=", "Partially Delivered"],
    //                 ["delivery_status", "=", "Partly Delivered"]
    //             ],
    //             fields: ["name"],
    //             limit: 1000
    //         },
    //         callback(r) {
    //             if (!r.message || !r.message.length) {
    //                 frappe.msgprint("No Partially Delivered orders found.");
    //                 return;
    //             }
    //             let names = r.message.map(d => d.name);
    //             listview.filter_area.add([
    //                 ["Sales Order", "name", "in", names.join(",")]
    //             ]);
    //             listview.refresh();
    //         }
    //     });

    // }, __("Delivery Filter"));



    listview.page.add_inner_button("Filter by Bulk IDs", function () {
    frappe.prompt([
        {
            fieldname: "ids",
            label: "Enter Sales Order IDs (comma separated)",
            fieldtype: "Small Text",
            reqd: 1
        }
    ], function (values) {

        let raw_ids = values.ids
            .split(",")
            .map(v => v.trim())
            .filter(v => v);

        let ids = raw_ids.map(v => {
            // If only number → convert
            if (/^\d+$/.test(v)) {
                return "SAL-ORD-2026-" + String(v).padStart(5, "0");
            }
            return v;
        });

        if (!ids.length) {
            frappe.msgprint("Please enter valid IDs");
            return;
        }

        listview.filter_area.clear();

        listview.filter_area.add([
            ["Sales Order", "name", "in", ids]
        ]);

        listview.refresh();
    }, "Bulk Filter");
});


			listview.page.add_inner_button(__("Dashboard"), () => open_sales_dashboard());
			listview.page.add_inner_button(__("Analytics"), () => open_sales_analytics());

			listview.page.add_inner_button(__("Import Orders from API's"), function () {
				impressio_sync_orders(listview);
			}, __("Orders"));

			if (listview.page.inner_toolbar && !listview.page.inner_toolbar.find(`button[data-label="${encodeURIComponent("Import Orders from API's")}"]`).length) {
				listview.page.add_inner_button(
					__("Import Orders from API's"),
					function () {
						impressio_sync_orders(listview);
					}
				);
			}

			listview.page.add_inner_button("Reset to Draft", function () {
				let selected = listview.get_checked_items();
				if (!selected.length) {
					frappe.msgprint("Please select Sales Orders");
					return;
				}
				open_reset_modal(selected.map((d) => d.name));
			},__("Orders"));

			listview.page.add_inner_button("Rebuild Sales Orders", function () {
				let selected = listview.get_checked_items();

				if (!selected.length) {
					frappe.msgprint("Please select Sales Orders");
					return;
				}

				open_rebuild_modal(selected.map((d) => d.name));
			},__("Orders"));

			// Place this BEFORE the "Create Delivery Note" button
			listview.page.add_inner_button("Track CCAvenue Orders", function () {
				let selected = listview.get_checked_items();

				if (!selected.length) {
					frappe.msgprint("Please select Sales Orders to track");
					return;
				}

				// Filter: Draft + CCAVENUE + not finalized
				let eligible = selected.filter(
					(d) =>
						d.docstatus === 0 &&
						d.custom_gateway_provider === "CCAVENUE" &&
                        d.custom_payment_status !== "SUCCESS" &&   // ← fixed
						d.custom_payment_finalized != 1,
				);

				if (!eligible.length) {
					frappe.msgprint(
						"No eligible Draft CCAvenue orders found in selection.<br/>" +
							"<small class='text-muted'>Orders must be: Draft + CCAVENUE provider + not finalized</small>",
					);
					return;
				}

				open_track_ccavenue_modal(eligible.map((d) => d.name));
			}, __("Payments"));

			// =====================================================
			// ADD THIS INSIDE your onload(listview) { ... } block
			// alongside your existing buttons
			// =====================================================

			listview.page.add_inner_button("Create Delivery Note", function () {
				let selected = listview.get_checked_items();

				if (!selected.length) {
					frappe.msgprint("Please select Sales Orders");
					return;
				}

				if (selected.length > 100) {
					frappe.msgprint("Maximum 100 Sales Orders allowed at once");
					return;
				}

				open_bulk_dn_modal(selected.map((d) => d.name));
			});
		},
	},
);

// ... rest of your functions unchanged

function open_sales_dashboard() {
	let dialog = new frappe.ui.Dialog({
		title: "Sales Fulfillment Dashboard",
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "dashboard" }],
	});

	dialog.current_page = 1;
	dialog.page_size = 5;
	dialog.total_pages = 1;

	dialog.show();

	dialog.fields_dict.dashboard.$wrapper.html(`

	<div class="row mb-3">

		<div class="col-md-3">
			<label><b>Warehouse</b></label>
			<div id="warehouse_filter"></div>
			<div id="warehouse_selected" class="text-muted small mt-1"></div>
		</div>

		<div class="col-md-9 text-right">

			<button class="btn btn-primary btn-sm" id="refresh_dashboard">
				Refresh
			</button>

		</div>

	</div>


	<div class="row mb-4">

		<div class="col-md-3">
			<div class="dash-card">
				<h6>Total Orders</h6>
				<h2 id="total_orders">0</h2>
			</div>
		</div>

		<div class="col-md-3">
			<div class="dash-card">
				<h6>Total Revenue</h6>
				<h2 id="total_amount">0</h2>
			</div>
		</div>

		<div class="col-md-3">
			<div class="dash-card">
				<h6>Fulfillable Orders</h6>
				<h2 id="fulfillable_orders">0</h2>
			</div>
		</div>

		<div class="col-md-3">
			<div class="dash-card">
				<h6>Delivery Probability</h6>
				<h2 id="overall_percentage">0%</h2>
			</div>
		</div>

	</div>


	<h4 class="mb-2">Sales Order Fulfillment</h4>

	<div class="table-responsive">

	<table class="table table-bordered table-hover">

		<thead>
			<tr>
				<th>Sales Order</th>
				<th>Customer</th>
				<th>Amount</th>
				<th>Fulfillment</th>
			</tr>
		</thead>

		<tbody id="orders_table"></tbody>

	</table>

	</div>


	<div class="d-flex justify-content-center align-items-center mt-3">

		<button class="btn btn-default btn-sm mr-2" id="prev_page">
			Previous
		</button>

		<span id="page_info"></span>

		<button class="btn btn-default btn-sm ml-2" id="next_page">
			Next
		</button>

	</div>


	<style>

	.dash-card{
		background:white;
		padding:20px;
		border-radius:10px;
		text-align:center;
		box-shadow:0 2px 8px rgba(0,0,0,0.1);
	}

	.so-row{
		background:#ffffff;
		font-weight:600;
	}

	.item-row{
		background:#f9fbff;
	}

	.item-table{
		margin:12px 0 5px 30px;
		border-left:4px solid #5e64ff;
		background:white;
	}

	.item-table thead{
		background:#eef2ff;
	}

	</style>

	`);

	dialog.warehouse_filter = frappe.ui.form.make_control({
		parent: dialog.$wrapper.find("#warehouse_filter"),
		df: {
			fieldtype: "MultiSelectList",
			label: "Warehouse",
			fieldname: "warehouses",
			options: "Warehouse",
			get_data: function (txt) {
				return frappe.db.get_link_options("Warehouse", txt);
			},
			onchange: function () {
				dialog.current_page = 1;
				load_sales_dashboard(dialog);
			},
		},
		render_input: true,
	});

	bind_dashboard_events(dialog);
	load_sales_dashboard(dialog);
}

function bind_dashboard_events(dialog) {
	let wrapper = dialog.$wrapper;

	wrapper.on("click", "#refresh_dashboard", function () {
		load_sales_dashboard(dialog);
	});

	wrapper.on("click", "#next_page", function () {
		if (dialog.current_page < dialog.total_pages) {
			dialog.current_page++;
			load_sales_dashboard(dialog);
		}
	});

	wrapper.on("click", "#prev_page", function () {
		if (dialog.current_page > 1) {
			dialog.current_page--;
			load_sales_dashboard(dialog);
		}
	});
}

function load_sales_dashboard(dialog) {
	let warehouses = dialog.warehouse_filter.get_value() || [];

	dialog.$wrapper
		.find("#warehouse_selected")
		.text(warehouses.length ? "Selected: " + warehouses.join(", ") : "All Warehouses");

	frappe.call({
		method: "impressio.impressio.sales_dashboard.get_sales_dashboard",

		args: {
			page: dialog.current_page,
			page_size: dialog.page_size,
			warehouses: warehouses,
		},

		callback: function (r) {
			let d = r.message;

			if (!d) return;

			let wrapper = dialog.$wrapper;

			wrapper.find("#total_orders").text(d.total_orders);
			wrapper.find("#total_amount").text("₹ " + d.total_amount);
			wrapper.find("#fulfillable_orders").text(d.fulfillable_orders);

			let percent = 0;

			if (d.total_orders) {
				percent = Math.round((d.fulfillable_orders / d.total_orders) * 100);
			}

			wrapper.find("#overall_percentage").text(percent + "%");

			dialog.total_pages = Math.ceil(d.total_rows / dialog.page_size);

			let rows = "";

			d.orders.forEach((o) => {
				let color = "bg-success";

				if (o.fulfillment === 0) {
					color = "bg-danger";
				} else if (o.fulfillment < 100) {
					color = "bg-warning";
				}

				let so_link = `/app/sales-order/${o.sales_order}`;

				rows += `

				<tr class="so-row">

					<td>
						<a href="${so_link}" target="_blank">
						${o.sales_order}
						</a>
					</td>

					<td>${o.customer}</td>

					<td>₹ ${o.amount}</td>

					<td>

						<div class="progress">

							<div class="progress-bar ${color}"
								style="width:${o.fulfillment}%">

								${o.fulfillment}%

							</div>

						</div>

					</td>

				</tr>

				<tr class="item-row">

					<td colspan="4">
						${render_items(o.items)}
					</td>

				</tr>

				`;
			});

			wrapper.find("#orders_table").html(rows);

			wrapper
				.find("#page_info")
				.text("Page " + dialog.current_page + " / " + dialog.total_pages);
		},
	});
}

function render_items(items) {
	let html = `

	<table class="table table-sm item-table">

	<thead>

	<tr>

		<th>Item</th>
		<th>Type</th>
		<th>Min</th>
		<th>Requested</th>
		<th>Stock Used</th>
		<th>ASN Used</th>
		<th>Need</th>
		<th>Remaining</th>

	</tr>

	</thead>

	<tbody>
	`;

	items.forEach((i) => {
		let type = i.is_stock_item ? "📦 Stock" : "📝 Non Stock";

		let min = i.min_stock || 0;

		let bal = i.total_balance;

		let color = "text-success";
		let icon = "🟢";

		if (bal < 0) {
			color = "text-danger";
			icon = "🔴";
		} else if (bal < min && i.is_stock_item) {
			color = "text-warning";
			icon = "🟡";
		}

		html += `

		<tr>

			<td>
				<a href="/app/item/${encodeURIComponent(i.item_code)}" target="_blank">
				${i.item_code}
				</a>
			</td>

			<td>${type}</td>

			<td>${min}</td>

			<td>${i.requested_qty}</td>

			<td class="text-success">${i.stock_used}</td>

			<td class="text-info">${i.asn_used}</td>

			<td class="text-danger">${i.remaining_need}</td>

			<td class="${color}" style="font-weight:600">

				${icon} ${bal}

			</td>

		</tr>

		`;
	});

	html += "</tbody></table>";

	return html;
}

// Sales Analytics - Dialog

// ==============================
// OPEN ANALYTICS
// ==============================

function open_sales_analytics() {
	let dialog = new frappe.ui.Dialog({
		title: "Sales Analytics",
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "analytics_html" }],
	});

	dialog.show();

	dialog.fields_dict.analytics_html.$wrapper.html(`

	<style>

		.inventory-card{
			background:white;
			border-radius:10px;
			padding:18px;
			text-align:center;
			box-shadow:0 3px 8px rgba(0,0,0,0.08);
			height:100%;
		}

		.inventory-icon{
			font-size:22px;
			margin-bottom:5px;
		}

		.inventory-value{
			font-size:28px;
			font-weight:700;
		}

		.inventory-label{
			font-size:13px;
			color:#666;
		}

		.available-card{
			border-top:4px solid #28a745;
		}

		.shortage-card{
			border-top:4px solid #dc3545;
		}

		.total-card{
			border-top:4px solid #007bff;
		}

		.health-card{
			border-top:4px solid #17a2b8;
		}
		.table-responsive{
			max-height: 700px;
			overflow-y: auto;
		}

		.table-responsive thead th{
			position: sticky;
			top: 0;
			background: #ffffff;
			z-index: 10;
		}

	</style>

	<div class="row mb-3">

		<div class="col-md-3">
			<div class="inventory-card available-card">
				<div class="inventory-icon">📦</div>
				<div class="inventory-value" id="available_items">0</div>
				<div class="inventory-label">Available Items</div>
			</div>
		</div>

		<div class="col-md-3">
			<div class="inventory-card shortage-card">
				<div class="inventory-icon">⚠️</div>
				<div class="inventory-value" id="unavailable_items">0</div>
				<div class="inventory-label">Shortage Items</div>
			</div>
		</div>

		<div class="col-md-3">
			<div class="inventory-card total-card">
				<div class="inventory-icon">📊</div>
				<div class="inventory-value" id="total_items">0</div>
				<div class="inventory-label">Total Items</div>
			</div>
		</div>

		<div class="col-md-3">
			<div class="inventory-card health-card">
				<div class="inventory-icon">💚</div>
				<div class="inventory-value" id="inventory_health">0%</div>
				<div class="inventory-label">Inventory Health</div>
			</div>
		</div>
	</div>

	<div class="row mb-3 justify-content-between align-items-center">

		 <div class="col-md-4">
			<label><b>Warehouse</b></label>
			<div id="warehouse_filter"></div>
			<div id="warehouse_selected" class="text-muted small mt-1"></div>
		</div>

		<div class="col-md-4 alert alert-light border mb-3 d-flex flex-column gap-3 ">

			<b class="mb-2">Stock Status Guide</b>

			<span class="ml-3 text-success">🟢 Healthy</span>
			<span class="ml-3 text-warning">🟡 Low Stock (Below Minimum)</span>
			<span class="ml-3 text-danger">🔴 Shortage</span>
			<span class="ml-3 text-muted">⚪ Exact Balance</span>

		</div>

	</div>

	<h4 class="mt-3 mb-3">Sales Order Inventory Projection</h4>

	<div class="table-responsive">

	<table class="table table-bordered">

	<thead >
	<tr>
		<th>Item</th>
		<th>Type</th>
		<th>Min Stock</th>
        <th>Stock</th>
		<th>Sales Order Demand</th>
		<th>ASN Coming</th>
		<th>Balance / Shortage</th>
	</tr>
	</thead>

	<tbody id="shortage_table"></tbody>

	</table>

	</div>

	`);

	// Create MultiSelect Warehouse Field
	dialog.warehouse_filter = frappe.ui.form.make_control({
		parent: dialog.$wrapper.find("#warehouse_filter"),
		df: {
			fieldtype: "MultiSelectList",
			label: "Warehouse",
			fieldname: "warehouses",
			options: "Warehouse",

			get_data: function (txt) {
				return frappe.db.get_link_options("Warehouse", txt);
			},

			onchange: function () {
				load_projection(dialog);
			},
		},
		render_input: true,
	});

	load_projection(dialog);
}

// ==============================
// LOAD DATA
// ==============================

function load_projection(dialog) {
	let warehouses = dialog.warehouse_filter.get_value() || [];

	dialog.$wrapper
		.find("#warehouse_selected")
		.text(
			warehouses.length
				? "Selected:( " + warehouses.join(", ") + " )"
				: "Collected data from All Warehouses",
		);

	frappe.call({
		method: "impressio.impressio.sales_dashboard.get_warehouse_sales_projection",
		args: {
			warehouses: warehouses,
		},
		callback: function (r) {
			let items = r.message || [];
			render_projection_table(items, dialog);
		},
	});
}

// ==============================
// TABLE RENDER
// ==============================

function render_projection_table(items, dialog) {
	let rows = "";

	// Negative balance items at the top
	items.sort((a, b) => a.balance_after_orders - b.balance_after_orders);

	items.forEach((i) => {
		let balance = i.balance_after_orders || 0;
		let type = i.is_stock_item ? "📦 Stock" : "📝 Non-Stock";

		let cls = "text-success";
		let icon = "🟢";

		let min_stock = i.min_stock || 0;

		if (balance < 0) {
			cls = "text-danger";
			icon = "🔴";
		} else if (balance < min_stock && i.is_stock_item) {
			cls = "text-warning";
			icon = "🟡";
		} else if (balance === 0) {
			cls = "text-muted";
			icon = "⚪";
		}

		let row_class = "";

		if (balance < 0) {
			row_class = "table-danger";
		} else if (balance < min_stock && i.is_stock_item) {
			row_class = "table-warning";
		}

		rows += `

		<tr class="${row_class}">

			<td>
				<a href="/app/item/${encodeURIComponent(i.item_code)}" target="_blank">
				${i.item_code}
				</a>
			</td>

			<td>${type}</td>

			<td>${i.min_stock || 0}</td>


            <td>${i.stock || 0}</td>

			<td>${i.sales_order_demand || 0}</td>

			<td>${i.asn || 0}</td>

			<td class="${cls}" style="font-weight:600">
				${icon} ${balance}
			</td>

		</tr>

		`;
	});

	if (!rows) {
		rows = `<tr><td colspan="7" class="text-center text-muted">No Data</td></tr>`;
	}

	let available = 0;
	let unavailable = 0;

	items.forEach((i) => {
		if (i.balance_after_orders >= 0) {
			available++;
		} else {
			unavailable++;
		}
	});

	let total = items.length;
	let health = total ? Math.round((available / total) * 100) : 0;

	dialog.$wrapper.find("#available_items").text(available);
	dialog.$wrapper.find("#unavailable_items").text(unavailable);
	dialog.$wrapper.find("#total_items").text(total);
	dialog.$wrapper.find("#inventory_health").text(health + "%");

	dialog.$wrapper.find("#shortage_table").html(rows);
}

function open_reset_modal(orders) {
	frappe.confirm(
		`
        <div style="text-align:left">

        <h5>⚠ Reset Sales Orders to Draft</h5>

        <p>You are about to reset <b>${orders.length}</b> Sales Orders back to Draft.</p>

        <b>Possible Risks:</b>

        <ul style="margin-top:8px">
            <li>Users may modify order quantities after reset</li>
            <li>Stock projections may temporarily change</li>
            <li>Cancelled workflow history may be overridden</li>
        </ul>

        <b>Safety Checks Applied:</b>

        <ul>
            <li>Orders with Delivery Notes will be blocked</li>
            <li>Orders with Sales Invoices will be blocked</li>
            <li>Orders with Payment Entries will be blocked</li>
        </ul>

        <p style="color:#d9534f">
        Only proceed if you are sure these orders should return to Draft.
        </p>

        </div>
        `,

		function () {
			// user confirmed
			launch_reset_modal(orders);
		},

		function () {
			frappe.show_alert({
				message: "Reset operation cancelled",
				indicator: "orange",
			});
		},
	);
}

function launch_reset_modal(orders) {
	let dialog = new frappe.ui.Dialog({
		title: "Reset Sales Orders to Draft",
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "result_html",
			},
		],
	});

	dialog.show();

	dialog.fields_dict.result_html.$wrapper.html(`
        <div class="text-muted mb-2">
            Processing ${orders.length} Sales Orders...
        </div>

        <div class="table-responsive">
        <table class="table table-bordered">
            <thead>
                <tr>
                    <th>Sales Order</th>
                    <th>Status</th>
                    <th>Message</th>
                    <th>Reference</th>
                </tr>
            </thead>
            <tbody id="reset_results"></tbody>
        </table>
        </div>
    `);

	run_reset_orders(orders, dialog);
}

function run_reset_orders(orders, dialog) {
	frappe.call({
		method: "impressio.impressio.api.order.reset_sales_orders_to_draft",
		args: {
			sales_orders: orders,
		},
		freeze: true,
		freeze_message: "Resetting Sales Orders...",
		callback: function (r) {
			let res = r.message.results || [];

			render_reset_results(res, dialog);
		},
	});
}

function render_reset_results(results, dialog) {
	let rows = "";

	results.forEach((r) => {
		let color = "text-success";
		let icon = "✔";

		if (r.result === "blocked") {
			color = "text-danger";
			icon = "✖";
		}

		if (r.result === "skipped") {
			color = "text-warning";
			icon = "⚠";
		}

		let ref = "";

		if (r.reference_doctype && r.reference_name) {
			ref = `
            <a href="/app/${frappe.router.slug(r.reference_doctype)}/${r.reference_name}" target="_blank">
                ${r.reference_name}
            </a>
            `;
		}

		rows += `

        <tr>

            <td>
                <a href="/app/sales-order/${r.sales_order}" target="_blank">
                    ${r.sales_order}
                </a>
            </td>

            <td class="${color}">
                ${icon} ${r.result}
            </td>

            <td>${r.message || ""}</td>

            <td>${ref}</td>

        </tr>

        `;
	});

	dialog.$wrapper.find("#reset_results").html(rows);
}

//  for Update missed Sales order fields

function open_rebuild_modal(orders) {
	let dialog = new frappe.ui.Dialog({
		title: "Rebuild Sales Orders",
		size: "large",
		fields: [
			{
				fieldtype: "Check",
				label: "Update School & Grade",
				fieldname: "update_school",
				default: 1,
			},

			{
				fieldtype: "Check",
				label: "Update Pincode",
				fieldname: "update_pincode",
				default: 1,
			},

			{
				fieldtype: "Check",
				label: "Rebuild Sub Items",
				fieldname: "update_subitems",
			},

			{
				fieldtype: "HTML",
				fieldname: "result_html",
			},
		],

		primary_action_label: "Run Rebuild",

		primary_action(values) {
			run_rebuild_orders(orders, values, dialog);
		},
	});

	dialog.show();

	dialog.fields_dict.result_html.$wrapper.html(`

	<div class="text-muted mb-2">

		Processing ${orders.length} Sales Orders...

	</div>

	<div class="table-responsive">

	<table class="table table-bordered">

		<thead>

			<tr>

				<th>Sales Order</th>
				<th>Status</th>
				<th>Message</th>

			</tr>

		</thead>

		<tbody id="rebuild_results"></tbody>

	</table>

	</div>

	`);
}

function run_rebuild_orders(orders, values, dialog) {
	frappe.call({
		method: "impressio.impressio.api.order.rebuild_sales_order_sub_items",

		args: {
			sales_orders: orders,
			update_school: values.update_school,
			update_pincode: values.update_pincode,
			update_subitems: values.update_subitems,
		},

		freeze: true,
		freeze_message: "Rebuilding Sales Orders...",

		callback: function (r) {
			let res = r.message.details || [];

			render_rebuild_results(res, dialog);
		},
	});
}

function render_rebuild_results(results, dialog) {
	let rows = "";

	results.forEach((r) => {
		let color = "text-success";
		let icon = "✔";
		let msg = "";

		if (r.status === "error") {
			color = "text-danger";
			icon = "✖";
			msg = r.message || "";
		}

		if (r.status === "magic box skipped") {
			color = "text-warning";
			icon = "⚠";
			msg = "Magic Box order skipped";
		}

		if (r.status === "skipped") {
			color = "text-muted";
			icon = "⚪";
			msg = r.message || "Skipped";
		}

		if (r.status === "success") {
			msg = `${r.rows_prepared} rows rebuilt`;
		}

		rows += `

		<tr>

			<td>

				<a href="/app/sales-order/${r.sales_order}" target="_blank">

					${r.sales_order}

				</a>

			</td>

			<td class="${color}">

				${icon} ${r.status}

			</td>

			<td>${msg}</td>

		</tr>

		`;
	});

	dialog.$wrapper.find("#rebuild_results").html(rows);
}

// =====================================================
// TRACK CCAVENUE ORDERS — Modal
// =====================================================

function open_track_ccavenue_modal(so_names) {
	let dialog = new frappe.ui.Dialog({
		title: "Track CCAvenue Payment Status",
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "track_html" }],
	});

	dialog.show();

	// Show loading state
	dialog.fields_dict.track_html.$wrapper.html(`
        <div class="text-center text-muted py-4">
            <div class="spinner-border spinner-border-sm mr-2" role="status"></div>
            Checking CCAvenue status for <b>${so_names.length}</b> order(s)...
        </div>
    `);

	frappe.call({
		method: "impressio.impressio.api.cc_avenue.track_ccavenue_orders",
		args: { sales_orders: so_names },
		callback(r) {
			render_track_results(r.message || {}, dialog);
		},
		error() {
			dialog.fields_dict.track_html.$wrapper.html(`
                <div class="alert alert-danger">
                    ❌ API call failed. Check error logs.
                </div>
            `);
		},
	});
}

function render_track_results(results, dialog) {
	let rows = "";

	// Summary counters
	let success = 0,
		failed = 0,
		pending = 0,
		error = 0,
		expired = 0;

	Object.entries(results).forEach(([so_name, data]) => {
		let status = data.action_taken || data.status || "—";
		let gw_status = data.gateway_status || data.erp_payment_status || "—";
		let amount = data.amount ? "₹ " + data.amount : "—";
		let ref = data.reference_no || "—";

		let color = "text-muted";
		let icon = "⏳";

		if (status.includes("SUCCESS")) {
			color = "text-success";
			icon = "✔";
			success++;
		} else if (status.includes("FAILED")) {
			color = "text-danger";
			icon = "✖";
			failed++;
		} else if (status.includes("WAITING") || status.includes("PENDING")) {
			color = "text-warning";
			icon = "🕐";
			pending++;
		} else if (status === "EXPIRED") {
			color = "text-secondary";
			icon = "⌛";
			expired++;
		} else if (status === "EXCEPTION" || status === "API_FAILED") {
			color = "text-danger";
			icon = "⚠";
			error++;
		} else {
			pending++;
		}

		rows += `
        <tr>
            <td>
                <a href="/app/sales-order/${so_name}" target="_blank">${so_name}</a>
            </td>
            <td class="${color}"><b>${icon} ${status}</b></td>
            <td>${gw_status}</td>
            <td>${amount}</td>
            <td class="text-muted small">${ref}</td>
        </tr>`;
	});

	if (!rows) {
		rows = `<tr><td colspan="5" class="text-center text-muted">No results returned</td></tr>`;
	}

	dialog.fields_dict.track_html.$wrapper.html(`
        <style>
            .track-card {
                background: white;
                border-radius: 8px;
                padding: 14px;
                text-align: center;
                box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            }
        </style>

        <!-- Summary Cards -->
        <div class="row mb-3">
            <div class="col-md-3">
                <div class="track-card" style="border-top:4px solid #28a745">
                    <div style="font-size:24px;font-weight:700" class="text-success">${success}</div>
                    <div class="text-muted small">Finalized ✔</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="track-card" style="border-top:4px solid #dc3545">
                    <div style="font-size:24px;font-weight:700" class="text-danger">${failed}</div>
                    <div class="text-muted small">Failed ✖</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="track-card" style="border-top:4px solid #ffc107">
                    <div style="font-size:24px;font-weight:700" class="text-warning">${pending}</div>
                    <div class="text-muted small">Still Pending 🕐</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="track-card" style="border-top:4px solid #6c757d">
                    <div style="font-size:24px;font-weight:700" class="text-secondary">${expired + error}</div>
                    <div class="text-muted small">Expired / Error ⚠</div>
                </div>
            </div>
        </div>

        <!-- Results Table -->
        <div class="table-responsive">
        <table class="table table-bordered table-hover">
            <thead class="thead-light">
                <tr>
                    <th>Sales Order</th>
                    <th>Action Taken</th>
                    <th>Gateway Status</th>
                    <th>Amount</th>
                    <th>Reference No</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
        </div>
    `);

	dialog.set_title(`CCAvenue Track — ${Object.keys(results).length} order(s) checked`);
}

///mar16 - Soorya

// STEP 1 : PREVIEW MODAL
// Shows sub items + delivered / pending per SO
// User reviews then confirms creation
// =====================================================

// =====================================================
// GLOBAL STATE
// =====================================================

let dn_item_selection = {}; // item_code → true/false
let dn_so_data = []; // full SO data from API
let dn_item_qty = {}; // so_name:item_code → qty

// =====================================================
// STEP 1 : OPEN MODAL
// =====================================================

function open_bulk_dn_modal(so_names) {
	dn_item_selection = {};
	dn_so_data = [];
	dn_item_qty = {};

	let dialog = new frappe.ui.Dialog({
		title: "Create Delivery Notes",
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "preview_html" }],
		primary_action_label: "Confirm & Create",
		// primary_action() {
		// 	dialog.disable_primary_action();
		// 	run_bulk_dn_creation(so_names, dialog);
		// },
	   
    primary_action() {
    // ---- 1. Stock validation (your existing logic) ----
    let no_stock_items = [];
    let insufficient_stock_items = [];
 
    dn_so_data.forEach((so) => {
        (so.items || []).forEach((i) => {
            let key = `${so.so_name}:${i.item_code}`;
            let requested_qty = dn_item_qty[key] || 0;
 
            if (requested_qty > 0) {
                let stock_qty = i.stock_qty || 0;
                if (stock_qty === 0) {
                    no_stock_items.push(`${i.item_code} (Order: ${so.so_name})`);
                } else if (stock_qty < requested_qty) {
                    insufficient_stock_items.push(
                        `${i.item_code}: Need ${requested_qty}, Only ${stock_qty} available`
                    );
                }
            }
        });
    });
 
    if (no_stock_items.length > 0 || insufficient_stock_items.length > 0) {
        let warning_html = `
            <div style="max-height:300px;overflow-y:auto">
                <h5 class="text-danger">⚠️ Stock Issues Detected</h5>
                ${no_stock_items.length ? `
                    <div class="mt-2">
                        <b>❌ No Stock:</b>
                        <ul class="text-danger">${no_stock_items.map(i => `<li>${i}</li>`).join("")}</ul>
                    </div>` : ""}
                ${insufficient_stock_items.length ? `
                    <div class="mt-2">
                        <b>⚠️ Insufficient Stock:</b>
                        <ul class="text-warning">${insufficient_stock_items.map(i => `<li>${i}</li>`).join("")}</ul>
                    </div>` : ""}
                <p class="mt-3 text-muted">Quantities will be auto-adjusted to available stock.</p>
            </div>`;
 
        frappe.confirm(warning_html,
            function () {
                // Auto-adjust quantities to available stock then proceed to pick list
                dn_so_data.forEach((so) => {
                    (so.items || []).forEach((i) => {
                        let key = `${so.so_name}:${i.item_code}`;
                        let current_qty = dn_item_qty[key] || 0;
                        let max_allowed = Math.min(i.pending_qty || 0, i.stock_qty || 0);
                        if (current_qty > max_allowed) {
                            dn_item_qty[key] = max_allowed;
                            if (max_allowed === 0) {
                                dn_item_selection[i.item_code] = false;
                            }
                        }
                    });
                });
                dialog.disable_primary_action();
                open_pick_list_step(so_names, dialog);   // ← NEW: go to pick list first
            },
            function () {
                dialog.enable_primary_action();
            }
        );
        return;
    }
 
    // ---- 2. No stock issues — go straight to Pick List step ----
    dialog.disable_primary_action();
    open_pick_list_step(so_names, dialog);   // ← NEW
},
	});

	dialog.show();

	dialog.fields_dict.preview_html.$wrapper.html(`
        <div class="text-center text-muted py-4">
            <div class="spinner-border spinner-border-sm mr-2" role="status"></div>
            Loading delivery status...
        </div>
    `);

	frappe.call({
		method: "impressio.impressio.bulk_delivery_note.get_so_delivery_status",
		args: { sales_orders: so_names },
		callback(r) {
			dn_so_data = r.message || [];
			init_item_selection(dn_so_data);
			render_dn_preview(dn_so_data, dialog);
		},
	});
}

// =====================================================
// INIT SELECTION
// checked = has stock AND has pending qty
// disabled = no stock OR no pending qty
// =====================================================

// function init_item_selection(so_data) {
// 	dn_item_selection = {};
// 	dn_item_qty = {};

// 	so_data.forEach((so) => {
// 		(so.items || []).forEach((i) => {
// 			if (!(i.item_code in dn_item_selection)) {
// 				let has_stock = (i.stock_qty || 0) > 0;
// 				let has_pending = (i.pending_qty || 0) > 0;
// 				dn_item_selection[i.item_code] = has_stock && has_pending;
// 			}
// 			let key = `${so.so_name}:${i.item_code}`;
// 			if (!(key in dn_item_qty)) {
// 				dn_item_qty[key] = i.pending_qty || 0;
// 			}
// 		});
// 	});
// }
function init_item_selection(so_data) {
    dn_item_selection = {};
    dn_item_qty = {};

    so_data.forEach((so) => {
        (so.items || []).forEach((i) => {
            let has_stock  = (i.stock_qty || 0) > 0;
            let has_pending = (i.pending_qty || 0) > 0;
            let key = `${so.so_name}:${i.item_code}`;

            // SUM qty if same item appears more than once in the same SO
            if (!(key in dn_item_qty)) {
    dn_item_qty[key] = has_stock ? (i.pending_qty || 0) : 0;
} 

            // Mark as selected if ANY occurrence has stock + pending
            if (!(i.item_code in dn_item_selection)) {
                dn_item_selection[i.item_code] = has_stock && has_pending;
            } else if (has_stock && has_pending) {
                dn_item_selection[i.item_code] = true;
            }
        });
    });
}

// =====================================================
// RENDER PREVIEW
// =====================================================

function render_dn_preview(so_data, dialog) {
	let total_sos = so_data.length;
	let ready_sos = so_data.filter(
		(s) => s.items && s.items.some((i) => i.pending_qty > 0),
	).length;
	let done_sos = so_data.filter(
		(s) => s.items && s.items.length && s.items.every((i) => i.pending_qty === 0),
	).length;
	let no_item_sos = so_data.filter((s) => !s.items || !s.items.length).length;

	let html = `
 
    <style>
        .dn-summary-card { background:white; border-radius:8px; padding:14px; text-align:center; box-shadow:0 2px 6px rgba(0,0,0,0.08); }
        .dn-summary-value { font-size:28px; font-weight:700; }
        .dn-summary-label { font-size:12px; color:#666; margin-top:2px; }
        .total-card  { border-top:4px solid #007bff; }
        .ready-card  { border-top:4px solid #28a745; }
        .done-card   { border-top:4px solid #6c757d; }
        .warn-card   { border-top:4px solid #ffc107; }
        .dn-so-section { border:1px solid #e2e6ea; border-radius:6px; overflow:hidden; margin-bottom:8px; }
        .dn-so-header  { background:#f8f9fa; padding:10px 14px; border-bottom:1px solid #e2e6ea; cursor:pointer; }
        .dn-so-header:hover { background:#eef2ff; }
        .dn-search-box { width:100%; padding:7px 12px; border:1px solid #ced4da; border-radius:6px; font-size:13px; }
        .dn-search-box:focus { outline:none; border-color:#5e64ff; box-shadow:0 0 0 2px rgba(94,100,255,0.15); }
        .item-cb { width:16px; height:16px; cursor:pointer; }
        .item-cb:disabled { cursor:not-allowed; opacity:0.4; }
        tr.no-stock-row { background:#fff8f8 !important; }
        tr.search-highlight { background:#fffbe6 !important; outline:2px solid #ffc107; }
        .dn-search-panel-inner { background:#f8f9ff; border:1px solid #c5ceff; border-radius:6px; padding:12px; margin-bottom:8px; }
        .btn-xs { padding:2px 8px; font-size:11px; }
        tr.unchecked-row { opacity:0.5; }
        .stock-ok   { background:#d4edda; color:#155724; padding:2px 7px; border-radius:10px; font-size:11px; }
        .stock-none { background:#f8d7da; color:#721c24; padding:2px 7px; border-radius:10px; font-size:11px; }
    </style>
 
    <div class="row mb-3">
        <div class="col-md-3">
            <div class="dn-summary-card total-card">
                <div class="dn-summary-value">${total_sos}</div>
                <div class="dn-summary-label">Selected Orders</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-summary-card ready-card">
                <div class="dn-summary-value">${ready_sos}</div>
                <div class="dn-summary-label">Ready to Deliver</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-summary-card done-card">
                <div class="dn-summary-value">${done_sos}</div>
                <div class="dn-summary-label">Already Completed</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-summary-card warn-card">
                <div class="dn-summary-value">${no_item_sos}</div>
                <div class="dn-summary-label">No Sub Items</div>
            </div>
        </div>
    </div>
 
    <!-- Search Box -->
    <div class="mb-2">
        <input type="text" id="dn_item_search" class="dn-search-box"
               placeholder="🔍 Type item code to find and check/uncheck across all orders..." />
    </div>
 
    <!-- Search Result Panel -->
    <div id="dn_search_panel" class="mb-2" style="display:none"></div>
 
    <p class="text-muted small mb-2">
        ✅ In-stock pending items are pre-selected. &nbsp;
        🔴 No-stock items are disabled. &nbsp;
        Search an item to see which orders it appears in and check/uncheck it.
    </p>
 
    <div id="dn_so_list">
        ${build_so_sections(so_data)}
    </div>
 
    <div id="dn_result_area"></div>
    `;

	dialog.fields_dict.preview_html.$wrapper.html(html);
	bind_dn_preview_events(dialog);
}

// =====================================================
// BUILD SO SECTION HTML
// =====================================================

function build_so_sections(so_data) {
	let html = "";

	so_data.forEach((so, so_idx) => {
		let all_ordered = (so.items || []).reduce((s, i) => s + (i.ordered_qty || 0), 0);
		let all_delivered = (so.items || []).reduce((s, i) => s + (i.delivered_qty || 0), 0);
		let so_pct = all_ordered ? Math.round((all_delivered / all_ordered) * 100) : 0;

		let has_items = so.items && so.items.length > 0;
		let all_done = has_items && so.items.every((i) => (i.pending_qty || 0) === 0);

		let badge_class = all_done
			? "badge-warning"
			: !has_items
				? "badge-secondary"
				: "badge-success";

		let badge_text = all_done
			? "Completed"
			: !has_items
				? so.warning
					? "Skipped"
					: "No Items"
				: "Ready";

		let so_id = so.so_name.replace(/-/g, "_");

		// ---- Item rows ----
		let item_rows = "";

		if (!has_items) {
			item_rows = `
            <tr>
                <td colspan="8" class="text-center text-muted py-2">
                    ${so.warning || "No sub items found"}
                </td>
            </tr>`;
		} else {
			let show_global_cb = so_idx === 0;

			// =====================================================
			// DEDUPLICATION FIX
			// Merge duplicate item_codes within the same SO.
			// e.g. Crown 200 pages: qty 22 + qty 2 → one row qty 24
			// =====================================================
			let deduped_items = [];
			let seen_keys = {};
			(so.items || []).forEach((i) => {
				if (i.item_code in seen_keys) {
					// Item already exists — just add the quantities
					let ex = deduped_items[seen_keys[i.item_code]];
					ex.ordered_qty   += (i.ordered_qty  || 0);
					ex.delivered_qty += (i.delivered_qty || 0);
					ex.pending_qty   += (i.pending_qty  || 0);
					// stock_qty is the same physical stock — do NOT sum it
				} else {
					// First time seeing this item — add it
					seen_keys[i.item_code] = deduped_items.length;
					deduped_items.push(Object.assign({}, i));
				}
			});
			// =====================================================

			deduped_items.forEach((i) => {
				let has_stock = (i.stock_qty || 0) > 0;
				let has_pending = (i.pending_qty || 0) > 0;
				let is_disabled = !has_stock || !has_pending;
				let is_checked = dn_item_selection[i.item_code] === true && has_stock;

				// Calculate max deliverable (can't deliver more than stock)
				let max_qty = Math.min(i.pending_qty || 0, i.stock_qty || 0);

				let row_cls = "";
				if (!has_stock) row_cls = "no-stock-row";
				if (!is_checked && !is_disabled) row_cls += " unchecked-row";

				let status_icon = !has_pending ? "✅" : i.delivered_qty > 0 ? "🟡" : "🟢";

				// Stock badge
				let stock_badge = "";
				if (!has_stock) {
					stock_badge = `<span class="stock-none" style="background:#f8d7da; color:#721c24; padding:2px 7px; border-radius:10px; font-size:11px;">
                        ✖ NO STOCK
                      </span>`;
				} else if (i.stock_qty < i.pending_qty) {
					stock_badge = `<span class="stock-warning" style="background:#fff3cd; color:#856404; padding:2px 7px; border-radius:10px; font-size:11px;">
                        ⚠️ Only ${i.stock_qty} left
                      </span>`;
				} else {
					stock_badge = `<span class="stock-ok" style="background:#d4edda; color:#155724; padding:2px 7px; border-radius:10px; font-size:11px;">
                        ✔ ${i.stock_qty} available
                      </span>`;
				}

				let link_field = i.is_parent
					? `<span class="badge badge-light border" style="font-size:10px">against_so</span>`
					: `<span class="badge badge-info" style="font-size:10px">custom_against_so</span>`;

				item_rows += `
    <tr class="${row_cls}" data-item="${i.item_code}">
        <td class="text-center" style="width:36px">
            <input type="checkbox"
                   class="item-cb dn-item-checkbox"
                   data-item="${i.item_code}"
                   ${is_checked ? "checked" : ""}
                   ${is_disabled ? "disabled" : ""}
                   ${!has_stock ? 'title="Cannot deliver - No stock available"' : ''}
            />
        </td>
        <td style="padding-left:8px">
            ${i.is_parent ? `<span class="text-muted small">📦</span>` : `<span class="text-muted small pl-2">↳</span>`}
            <a href="/app/item/${encodeURIComponent(i.item_code)}" target="_blank">
                ${i.item_code}
            </a>
        </td>
        <td class="text-center">${stock_badge}</td>
        <td class="text-center">${i.ordered_qty}</td>
        <td class="text-center text-success"><b>${i.delivered_qty}</b></td>
        <td class="text-center">
            ${
                i.pending_qty > 0 && has_stock
                    ? `<input type="number"
                           class="dn-qty-input form-control form-control-sm text-center"
                           data-item="${i.item_code}"
                           data-so="${so.so_name}"
                           data-max="${i.pending_qty}"
                           data-stock="${i.stock_qty}"
                           value="${max_qty}"
                           min="0"
                           max="${max_qty}"
                           style="width:80px; display:inline-block"
                      />`
                    : `<b class="text-muted">${i.pending_qty}</b>`
            }
        </td>
        <td class="text-center">${link_field}</td>
        <td class="text-center">${status_icon}</td>
    </tr>`;
			});

			item_rows = `
            <thead class="thead-light">
                <tr>
                    <th class="text-center">
                        ${
							show_global_cb
								? `<input type="checkbox" class="item-cb" id="dn_selectall_global"
                                      checked title="Select / Deselect ALL items in ALL orders" />`
								: ""
						}
                    </th>
                    <th>Item Code</th>
                    <th class="text-center">Stock</th>
                    <th class="text-center">Ordered</th>
                    <th class="text-center">Delivered</th>
                    <th class="text-center">Pending</th>
                    <th class="text-center">DN Field</th>
                    <th class="text-center">Status</th>
                </tr>
            </thead>
            <tbody>${item_rows}</tbody>`;
		}

		html += `
        <div class="dn-so-section">
            <div class="dn-so-header"
                 data-toggle="collapse"
                 data-target="#so_items_${so_id}">

                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        ${
							has_items
								? `
                        <input type="checkbox"
                               class="item-cb dn-so-selectall"
                               data-so="${so.so_name}"
                               checked
                               onclick="event.stopPropagation()"
                               title="Select / Deselect all items in this order"
                        />`
								: ""
						}
                        <b>
                            <a href="/app/sales-order/${so.so_name}" target="_blank"
                               onclick="event.stopPropagation()">
                                ${so.so_name}
                            </a>
                        </b>
                        <span class="text-muted ml-2 small">${so.customer}</span>
                        <span class="badge ${badge_class} ml-2">${badge_text}</span>
                    </div>
                    <div class="d-flex align-items-center">
                        <div class="progress mr-2" style="width:80px; height:8px">
                            <div class="progress-bar ${so_pct === 100 ? "bg-success" : so_pct > 0 ? "bg-warning" : "bg-danger"}"
                                 style="width:${so_pct}%"></div>
                        </div>
                        <span class="small mr-2">${all_delivered}/${all_ordered}</span>
                        <span class="text-muted small">▼</span>
                    </div>
                </div>

            </div>

            <div id="so_items_${so_id}" class="collapse show">
                <div class="table-responsive">
                <table class="table table-sm table-bordered mb-0">
                    ${item_rows}
                </table>
                </div>
            </div>
        </div>`;
	});

	return html;
}
// =====================================================
// BIND EVENTS
// =====================================================

function bind_dn_preview_events(dialog) {
	let wrapper = dialog.fields_dict.preview_html.$wrapper;

	// ---- Individual item checkbox ----
	wrapper.on("change", ".dn-item-checkbox", function () {
		let item_code = $(this).data("item");
		let checked = $(this).is(":checked");

		dn_item_selection[item_code] = checked;

		wrapper
			.find(`.dn-item-checkbox[data-item="${item_code}"]:not(:disabled)`)
			.each(function () {
				$(this).prop("checked", checked);
				$(this).closest("tr").toggleClass("unchecked-row", !checked);
			});
	});

	// ---- SO-level select all ----
	wrapper.on("change", ".dn-so-selectall", function () {
		let so_name = $(this).data("so");
		let checked = $(this).is(":checked");
		let so_id = so_name.replace(/-/g, "_");

		wrapper.find(`#so_items_${so_id} .dn-item-checkbox:not(:disabled)`).each(function () {
			let item_code = $(this).data("item");
			$(this).prop("checked", checked);
			dn_item_selection[item_code] = checked;
			$(this).closest("tr").toggleClass("unchecked-row", !checked);
		});
	});

	// ---- Global select all ----
	wrapper.on("change", "#dn_selectall_global", function () {
		let checked = $(this).is(":checked");
		toggle_all_dn_items(checked, wrapper);
	});

	// ---- Qty input change ----
	// wrapper.on("input", ".dn-qty-input", function () {
	// 	let item_code = $(this).data("item");
	// 	let so_name = $(this).data("so");
	// 	let max = parseInt($(this).data("max")) || 0;
	// 	let val = parseInt($(this).val()) || 0;

	// 	if (val > max) {
	// 		val = max;
	// 		$(this).val(val);
	// 	}
	// 	if (val < 0) {
	// 		val = 0;
	// 		$(this).val(val);
	// 	}

	// 	let key = `${so_name}:${item_code}`;
	// 	dn_item_qty[key] = val;

	// 	if (val === 0) {
	// 		dn_item_selection[item_code] = false;
	// 		wrapper.find(`.dn-item-checkbox[data-item="${item_code}"]`).prop("checked", false);
	// 		$(this).closest("tr").addClass("unchecked-row");
	// 	} else {
	// 		dn_item_selection[item_code] = true;
	// 		wrapper.find(`.dn-item-checkbox[data-item="${item_code}"]`).prop("checked", true);
	// 		$(this).closest("tr").removeClass("unchecked-row");
	// 	}
	// });
	wrapper.on("input", ".dn-qty-input", function () {
    let item_code = $(this).data("item");
    let so_name = $(this).data("so");
    let max_pending = parseInt($(this).data("max")) || 0;
    let stock_qty = parseInt($(this).data("stock")) || 0;
    let val = parseInt($(this).val()) || 0;
    
    // CRITICAL: Can't deliver more than available stock
    let max_allowed = Math.min(max_pending, stock_qty);
    
    if (val > max_allowed) {
        val = max_allowed;
        $(this).val(val);
        
        // Show warning
        if (stock_qty < max_pending) {
            frappe.show_alert({
                message: `⚠️ Only ${stock_qty} units available in stock for ${item_code}`,
                indicator: "orange"
            }, 3);
        }
    }
    
    if (val < 0) {
        val = 0;
        $(this).val(val);
    }
    
    let key = `${so_name}:${item_code}`;
    dn_item_qty[key] = val;
    
    // Update checkbox based on quantity
    if (val === 0 || stock_qty === 0) {
        dn_item_selection[item_code] = false;
        wrapper.find(`.dn-item-checkbox[data-item="${item_code}"]`).prop("checked", false);
        $(this).closest("tr").addClass("unchecked-row");
    } else {
        dn_item_selection[item_code] = true;
        wrapper.find(`.dn-item-checkbox[data-item="${item_code}"]`).prop("checked", true);
        $(this).closest("tr").removeClass("unchecked-row");
    }
});

	// ---- Search box ----
	let search_timeout;
	wrapper.on("input", "#dn_item_search", function () {
		clearTimeout(search_timeout);
		let query = $(this).val().trim().toLowerCase();
		let panel = wrapper.find("#dn_search_panel");

		if (!query) {
			panel.html("").hide();
			wrapper.find("tr.search-highlight").removeClass("search-highlight");
			return;
		}

		search_timeout = setTimeout(() => {
			let matched = Object.keys(dn_item_selection).filter((code) =>
				code.toLowerCase().includes(query),
			);

			if (!matched.length) {
				panel
					.html(
						`
                    <div class="text-warning small p-2">
                        ⚠ No item found matching "<b>${query}</b>"
                    </div>
                `,
					)
					.show();
				return;
			}

			wrapper.find("tr.search-highlight").removeClass("search-highlight");
			matched.forEach((item_code) => {
				wrapper.find(`tr[data-item="${item_code}"]`).addClass("search-highlight");
			});

			let panel_rows = "";
			matched.forEach((item_code) => {
				let so_appearances = [];
				dn_so_data.forEach((so) => {
					let found = (so.items || []).find((i) => i.item_code === item_code);
					if (found) {
						so_appearances.push({
							so_name: so.so_name,
							pending_qty: found.pending_qty,
							stock_qty: found.stock_qty,
							is_checked: dn_item_selection[item_code],
						});
					}
				});

				let currently_checked = dn_item_selection[item_code];

				panel_rows += `
                <tr>
                    <td>
                        <b>${item_code}</b><br/>
                        <span class="text-muted small">Found in ${so_appearances.length} order(s)</span>
                    </td>
                    <td>
                        ${so_appearances
							.map(
								(s) => `
                            <span class="badge badge-light border mr-1 mb-1">
                                ${s.so_name}
                                <span class="text-danger ml-1">qty: ${s.pending_qty}</span>
                            </span>
                        `,
							)
							.join("")}
                    </td>
                    <td class="text-center">
                        <span class="${currently_checked ? "text-success" : "text-muted"}">
                            ${currently_checked ? "✔ Selected" : "✖ Unselected"}
                        </span>
                    </td>
                    <td class="text-center">
                        <button class="btn btn-xs btn-danger dn-uncheck-item"
                                data-item="${item_code}"
                                ${!currently_checked ? "disabled" : ""}>
                            Uncheck All
                        </button>
                        <button class="btn btn-xs btn-success dn-check-item ml-1"
                                data-item="${item_code}"
                                ${currently_checked ? "disabled" : ""}>
                            Check All
                        </button>
                    </td>
                </tr>`;
			});

			panel
				.html(
					`
                <div class="dn-search-panel-inner">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <b class="small">🔍 Search Results for "<span class="text-primary">${query}</span>"
                            — ${matched.length} item(s) found</b>
                        <button class="btn btn-xs btn-default" id="dn_clear_search">✖ Clear</button>
                    </div>
                    <div class="table-responsive">
                    <table class="table table-sm table-bordered mb-0">
                        <thead class="thead-light">
                            <tr>
                                <th>Item Code</th>
                                <th>Appears In Orders</th>
                                <th class="text-center">Current State</th>
                                <th class="text-center">Action</th>
                            </tr>
                        </thead>
                        <tbody>${panel_rows}</tbody>
                    </table>
                    </div>
                </div>
            `,
				)
				.show();
		}, 300);
	});

	// ---- Uncheck All button in search panel ----
	wrapper.on("click", ".dn-uncheck-item", function () {
		let item_code = $(this).data("item");
		dn_item_selection[item_code] = false;

		wrapper
			.find(`.dn-item-checkbox[data-item="${item_code}"]:not(:disabled)`)
			.each(function () {
				$(this).prop("checked", false);
				$(this).closest("tr").addClass("unchecked-row");
			});

		$(this).prop("disabled", true);
		$(this).siblings(".dn-check-item").prop("disabled", false);
		$(this).closest("td").prev().html('<span class="text-muted">✖ Unselected</span>');
	});

	// ---- Check All button in search panel ----
	wrapper.on("click", ".dn-check-item", function () {
		let item_code = $(this).data("item");
		dn_item_selection[item_code] = true;

		wrapper
			.find(`.dn-item-checkbox[data-item="${item_code}"]:not(:disabled)`)
			.each(function () {
				$(this).prop("checked", true);
				$(this).closest("tr").removeClass("unchecked-row");
			});

		$(this).prop("disabled", true);
		$(this).siblings(".dn-uncheck-item").prop("disabled", false);
		$(this).closest("td").prev().html('<span class="text-success">✔ Selected</span>');
	});

	// ---- Clear search ----
	wrapper.on("click", "#dn_clear_search", function () {
		wrapper.find("#dn_item_search").val("");
		wrapper.find("#dn_search_panel").html("").hide();
		wrapper.find("tr.search-highlight").removeClass("search-highlight");
	});
}

// =====================================================
// GLOBAL TOGGLE ALL
// =====================================================

function toggle_all_dn_items(checked, wrapper) {
	Object.keys(dn_item_selection).forEach((code) => {
		dn_item_selection[code] = checked;
	});

	wrapper.find(".dn-item-checkbox:not(:disabled)").each(function () {
		$(this).prop("checked", checked);
		$(this).closest("tr").toggleClass("unchecked-row", !checked);
	});

	wrapper.find(".dn-so-selectall").prop("checked", checked);
}

// =====================================================
// STEP 2 : RUN CREATION
// =====================================================

// =====================================================
// COMPLETE WORKING SOLUTION
// Replace your entire run_bulk_dn_creation and 
// render_dn_creation_results functions with this
// =====================================================

 
function run_bulk_dn_creation(so_names, dialog) {
    let selected_items = {};
 
    dn_so_data.forEach((so) => {
        let items_with_qty = (so.items || [])
            .filter((i) => dn_item_selection[i.item_code] === true)
            .map((i) => {
                let key = `${so.so_name}:${i.item_code}`;
                return {
                    item_code: i.item_code,
                    qty: dn_item_qty[key] !== undefined ? dn_item_qty[key] : i.pending_qty,
                };
            })
            .filter((i) => i.qty > 0);
 
        if (items_with_qty.length) {
            selected_items[so.so_name] = items_with_qty;
        }
    });
 
    // Clear old content and show loading
    let wrapper = dialog.$wrapper;
    wrapper.find("#dn_so_list").html(`
        <div class="text-center text-muted py-4">
            <div class="spinner-border spinner-border-sm mr-2" role="status"></div>
            Creating Delivery Notes... please wait.
        </div>
    `);
    wrapper.find("#dn_result_area").html("");
 
    frappe.call({
        method: "impressio.impressio.bulk_delivery_note.create_bulk_delivery_notes",
        args: {
            sales_orders: so_names,
            selected_items: selected_items,
        },
        freeze: true,
        freeze_message: "Creating Delivery Notes...",
        callback: function(r) {
            console.log("✅ API Response received:", r);
            
            // Check if response has message and results
            let results = [];
            if (r.message) {
                if (r.message.results) {
                    results = r.message.results;
                } else if (Array.isArray(r.message)) {
                    results = r.message;
                } else {
                    results = [r.message];
                }
            }
            
            console.log("📋 Parsed results:", results);
            
            // If no results found, show error
            if (!results || results.length === 0) {
                wrapper.find("#dn_result_area").html(`
                    <div class="alert alert-danger">
                        <strong>Error:</strong> No response received from server.
                        <br>Check console for details.
                    </div>
                `);
                console.error("❌ No results in response:", r);
                return;
            }
            
            // Call the render function with results and dialog
            render_dn_creation_results(results, dialog);
        },
        error: function(err) {
            console.error("❌ API call failed:", err);
            wrapper.find("#dn_result_area").html(`
                <div class="alert alert-danger">
                    <strong>Error:</strong> ${err.responseJSON?.message || err.message || "Failed to create delivery notes"}
                    <br>Check console for details.
                </div>
            `);
        }
    });
}

// =====================================================
// RENDER RESULTS - COMPLETE WORKING VERSION
// =====================================================


function render_dn_creation_results(results, dialog) {
    console.log("🎨 render_dn_creation_results called with results:", results);
    
    // Ensure dialog exists
    if (!dialog || !dialog.$wrapper) {
        console.error("❌ Dialog not available!");
        return;
    }
    
    // Update dialog title
    dialog.set_title("Delivery Note Creation — Results");
    
    // ⚠️ IMPORTANT: Use correct Frappe method
    // Instead of: dialog.hide_primary_action()
    // Use: dialog.get_primary_btn().hide()
    if (dialog.get_primary_btn && typeof dialog.get_primary_btn === 'function') {
        try {
            dialog.get_primary_btn().hide();
        } catch(e) {
            console.log("Primary button hiding skipped");
        }
    }
 
    // Parse results array properly
    let results_array = results;
    if (results && results.results && Array.isArray(results.results)) {
        results_array = results.results;
    }
    if (!Array.isArray(results_array)) {
        console.error("❌ Results is not an array:", results_array);
        results_array = [];
    }
 
    console.log("📊 Total results:", results_array.length);
 
    // Count statuses
    let success = results_array.filter(r => r.status === "success").length;
    let skipped = results_array.filter(r => r.status === "skipped").length;
    let errors = results_array.filter(r => r.status === "error").length;
 
    console.log(`📈 Stats - Success: ${success}, Skipped: ${skipped}, Errors: ${errors}`);
 
    // =====================================================
    // BUILD ERROR DETAILS SECTION
    // =====================================================
    
    let error_details_html = "";
    if (errors > 0) {
        let error_results = results_array.filter(r => r.status === "error");
        
        error_details_html = `
        <div style="
            background: #f8d7da;
            border: 2px solid #f5c6cb;
            border-radius: 8px;
            padding: 18px;
            margin-bottom: 24px;
            color: #721c24;
        ">
            <div style="
                display: flex;
                align-items: center;
                margin-bottom: 16px;
                font-weight: bold;
                font-size: 15px;
            ">
                <span style="font-size: 20px; margin-right: 10px;">⚠️</span>
                Stock Issues Detected — ${errors} Order(s) Cannot Be Delivered
            </div>
            
            ${error_results.map((r, idx) => {
                let message = r.message || "";
                let items = [];
                
                if (message.includes("Stock insufficient:")) {
                    items = message.replace("Stock insufficient: ", "").split("; ");
                } else {
                    items = [message];
                }
                
                return `
                <div style="
                    margin-bottom: ${idx === error_results.length - 1 ? '0' : '16px'};
                    padding-bottom: 16px;
                    border-bottom: ${idx === error_results.length - 1 ? 'none' : '1px solid rgba(0,0,0,0.1)'};
                ">
                    <div style="
                        font-weight: bold;
                        font-size: 13px;
                        margin-bottom: 10px;
                        color: #c71c22;
                    ">
                        📦 Order: ${r.sales_order}
                    </div>
                    <div style="
                        font-size: 12px;
                        line-height: 1.7;
                        margin-left: 20px;
                    ">
                        <div style="margin-bottom: 8px; font-weight: 500;"><b>❌ Missing Stock Items:</b></div>
                        <ol style="
                            margin: 0;
                            padding-left: 20px;
                            list-style: decimal;
                        ">
                            ${items.map((item, idx) => {
                                if (!item.trim()) return "";
                                return `<li style="margin-bottom: 4px; word-break: break-word;">${item}</li>`;
                            }).join('')}
                        </ol>
                    </div>
                </div>
                `;
            }).join('')}
        </div>
        `;
    }
 
    // =====================================================
    // BUILD RESULTS TABLE
    // =====================================================
    
    let rows = results_array.map((r) => {
        let status_class = r.status === "error" ? "text-danger" 
                          : r.status === "skipped" ? "text-warning" 
                          : "text-success";
        let icon = r.status === "error" ? "✖" 
                   : r.status === "skipped" ? "⚠" 
                   : "✔";
        
        let dn_link = r.dn_name 
            ? `<a href="/app/delivery-note/${r.dn_name}" target="_blank" style="color: #0066cc;">${r.dn_name}</a>`
            : "—";
        
        let message_text = r.message || "";
        let summary = "";
        
        if (r.status === "error") {
            let item_count = (message_text.match(/;/g) || []).length + 1;
            summary = `<strong>❌ ${item_count} items out of stock</strong><br><small style="color: #666;">See details above ⬆️</small>`;
        } else if (r.status === "skipped") {
            summary = message_text;
        } else if (r.status === "success") {
            summary = message_text;
        }
 
        return `
        <tr style="border-bottom: 1px solid #dee2e6; vertical-align: top;">
            <td style="
                width: 140px;
                padding: 12px;
                font-weight: 600;
                word-break: break-word;
            ">
                <a href="/app/sales-order/${r.sales_order}" target="_blank" style="color: #0066cc;">
                    ${r.sales_order}
                </a>
            </td>
            <td style="
                width: 100px;
                padding: 12px;
                text-align: center;
                font-weight: 600;
            " class="${status_class}">
                ${icon} ${r.status.toUpperCase()}
            </td>
            <td style="
                width: 140px;
                padding: 12px;
                word-break: break-word;
            ">
                ${dn_link}
            </td>
            <td style="
                padding: 12px;
                font-size: 12px;
                word-break: break-word;
                line-height: 1.6;
            ">
                ${summary}
            </td>
        </tr>`;
    }).join("");
 
    if (!rows) {
        rows = `<tr><td colspan="4" style="text-align: center; padding: 20px; color: #999;">No results</td></tr>`;
    }
 
    // =====================================================
    // RENDER COMPLETE HTML
    // =====================================================
    
    let final_html = `
    <style>
        .dn-result-summary {
            background: white;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            margin-bottom: 0;
        }
        .dn-result-value {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 6px;
        }
        .dn-result-label {
            font-size: 13px;
            color: #666;
            font-weight: 500;
        }
        .result-success { border-top: 4px solid #28a745; }
        .result-warning { border-top: 4px solid #ffc107; }
        .result-danger { border-top: 4px solid #dc3545; }
        .result-info { border-top: 4px solid #17a2b8; }
        .results-table-wrapper {
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            margin-top: 20px;
        }
        .results-table-wrapper table {
            margin: 0;
            width: 100%;
        }
        .results-table-wrapper thead {
            position: sticky;
            top: 0;
            background: #f8f9fa;
            z-index: 10;
        }
        .results-table-wrapper thead th {
            padding: 12px !important;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            color: #495057;
            border-bottom: 2px solid #dee2e6;
        }
    </style>
 
    <!-- Summary Cards Row -->
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="dn-result-summary result-success">
                <div class="dn-result-value text-success">${success}</div>
                <div class="dn-result-label">Successfully Created</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-result-summary result-warning">
                <div class="dn-result-value text-warning">${skipped}</div>
                <div class="dn-result-label">Skipped / Completed</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-result-summary result-danger">
                <div class="dn-result-value text-danger">${errors}</div>
                <div class="dn-result-label">Stock Errors</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="dn-result-summary result-info">
                <div class="dn-result-value text-info">${results_array.length}</div>
                <div class="dn-result-label">Total Orders</div>
            </div>
        </div>
    </div>
 
    <!-- Error Details Panel -->
    ${error_details_html}
 
    <!-- Results Table -->
    <h5 style="margin-top: 24px; margin-bottom: 16px; font-weight: 600;">Detailed Results</h5>
    
    <div class="results-table-wrapper">
        <table class="table table-sm table-bordered mb-0">
            <thead>
                <tr>
                    <th>Sales Order</th>
                    <th>Status</th>
                    <th>Delivery Note</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    </div>
 
    <!-- Action Buttons -->
    <div style="
        margin-top: 24px;
        padding-top: 16px;
        border-top: 1px solid #dee2e6;
        display: flex;
        gap: 10px;
        justify-content: center;
    ">
        <button class="btn btn-primary btn-sm" onclick="location.reload()">
            <i class="fa fa-refresh mr-2"></i> Refresh Sales Order List
        </button>
        <button class="btn btn-secondary btn-sm" onclick="if(frappe.ui.dialog.get_open_dialog()) frappe.ui.dialog.get_open_dialog().hide();">
            <i class="fa fa-times mr-2"></i> Close
        </button>
    </div>
    `;
 
    // Set the HTML to the dialog
    dialog.$wrapper.find("#dn_result_area").html(final_html);
    dialog.$wrapper.find("#dn_so_list").hide();
    
    console.log("✅ Results rendered successfully");
    
    // Log errors for debugging
    if (errors > 0) {
        console.log("❌ Errors found:", results_array.filter(r => r.status === "error"));
    }
}
 


function show_stock_warning_dialog(no_stock_items, insufficient_stock_items) {
    let message = "";
    
    if (no_stock_items.length > 0) {
        message += `<div class="mb-2">
            <strong>❌ No Stock Available:</strong><br>
            ${no_stock_items.map(item => `• ${item}`).join('<br>')}
        </div>`;
    }
    
    if (insufficient_stock_items.length > 0) {
        message += `<div class="mb-2">
            <strong>⚠️ Insufficient Stock:</strong><br>
            ${insufficient_stock_items.map(item => `• ${item}`).join('<br>')}
        </div>`;
    }
    
    message += `<div class="mt-2 text-muted">
        <small>These items will be skipped or quantities will be adjusted.</small>
    </div>`;
    
    frappe.msgprint({
        title: "⚠️ Stock Issues",
        indicator: "orange",
        message: message,
        is_minimizable: true
    });
}


function open_pick_list_step(so_names, dn_dialog) {

    // ---- Build selected_items payload ----
    let selected_items = {};

    dn_so_data.forEach((so) => {
        let items_with_qty = (so.items || [])
             .filter((i) => {
    // STRICT: only include items explicitly checked by user
    let is_selected = dn_item_selection[i.item_code] === true;
    let key = `${so.so_name}:${i.item_code}`;
    let qty = dn_item_qty[key] !== undefined
                ? dn_item_qty[key]
                : (i.pending_qty || 0);
    let has_pending = (i.pending_qty || 0) > 0;

    // If user unchecked it → exclude it completely
    return is_selected && has_pending && qty > 0;
})
            .map((i) => {
                let key = `${so.so_name}:${i.item_code}`;
                let qty = dn_item_qty[key] !== undefined
                            ? dn_item_qty[key]
                            : (i.pending_qty || 0);
                return {
                    item_code: i.item_code,
                    qty      : Math.min(qty, i.pending_qty || 0),  // ← cap to pending
                };
            })
            .filter((i) => i.qty > 0);

        if (items_with_qty.length) {
            selected_items[so.so_name] = items_with_qty;
        }
    });

    // ---- Guard: nothing to pick ----
    if (Object.keys(selected_items).length === 0) {
        frappe.msgprint({
            title    : "No Items Selected",
            indicator: "orange",
            message  : "No pending items with available stock found. " +
                       "Please select at least one item.",
        });
        dn_dialog.enable_primary_action();
        return;
    }

    // ---- Show loading ----
    let wrapper = dn_dialog.$wrapper;
    wrapper.find("#dn_so_list").html(`
        <div class="text-center py-5">
            <div class="spinner-border text-primary mb-3" role="status"
                 style="width:2.5rem;height:2.5rem"></div>
            <h5 class="text-muted">Creating Bulk Pick List...</h5>
            <p class="text-muted small">
                Consolidating items across ${so_names.length} order(s)
            </p>
        </div>
    `);

    // ---- Call Python backend ----
    frappe.call({
        method: "impressio.impressio.bulk_delivery_note.create_bulk_pick_list",
        args: {
            sales_orders  : so_names,
            selected_items: selected_items,
        },
        freeze        : true,
        freeze_message: "Creating Bulk Pick List...",

        callback(r) {
            if (!r.message) {
                frappe.msgprint({
                    title    : "Pick List Error",
                    indicator: "red",
                    message  : "No response from server. Check error logs.",
                });
                dn_dialog.enable_primary_action();
                return;
            }
            show_pick_list_summary(r.message, so_names, dn_dialog, selected_items);
        },

        error() {
            frappe.msgprint({
                title    : "Pick List Failed",
                indicator: "red",
                message  : "Failed to create Pick List. Check error logs.",
            });
            dn_dialog.enable_primary_action();
        },
    });
}





 
// =====================================================
// NEW FUNCTION 2: show_pick_list_summary
// Shows Pick List result: doc link + item table.
// Has "Now Create Delivery Notes" button.
// =====================================================
 
function show_pick_list_summary(data, so_names, dn_dialog, selected_items) {

    let pl_name      = data.pick_list_name;
    let pl_link      = `/app/pick-list/${pl_name}`;
    let items        = data.items || [];
    let total_qty    = data.total_qty || 0;
    let total_items  = data.total_items || 0;
    let total_orders = data.total_orders || so_names.length;

    // ---- Build item rows ----
    let rows = items.map((i) => {
        let so_badges = i.so_list.slice(0, 3).map(s =>
            `<span class="badge badge-light border mr-1 mb-1"
                   style="display:inline-block;font-size:10px">${s}</span>`
        ).join("") + (i.so_list.length > 3
            ? `<span class="badge badge-secondary mb-1">+${i.so_list.length - 3} more</span>`
            : "");

        return `
        <tr>
            <td style="word-break:break-word">
                <b>${i.item_code}</b>
                <div class="text-muted small">
                    ${i.item_name !== i.item_code ? i.item_name : ""}
                </div>
            </td>
            <td class="text-center"
                style="font-size:18px;font-weight:700;color:#2d6a4f">
                ${i.total_qty}
            </td>
            <td class="text-center text-muted small">${i.uom}</td>
            <td class="text-muted small">${i.warehouse || "—"}</td>
            <td class="text-center">
                <span class="badge badge-info">
                    ${i.so_count} order${i.so_count > 1 ? "s" : ""}
                </span>
            </td>
            <td class="small" style="word-break:break-word">${so_badges}</td>
        </tr>`;
    }).join("");

    if (!rows) {
        rows = `<tr>
            <td colspan="6" class="text-center text-muted">No items found</td>
        </tr>`;
    }

    let html = `
    <style>
        .pl-card {
            background: white;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        }
        .pl-card-value { font-size: 30px; font-weight: 700; margin-bottom: 4px; }
        .pl-card-label { font-size: 12px; color: #666; }
        .pl-success-banner {
            background: linear-gradient(135deg, #d4edda, #c3e6cb);
            border: 2px solid #28a745;
            border-radius: 10px;
            padding: 18px 24px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .pl-table-wrapper {
            max-height: 320px;
            overflow-y: auto;
            border: 1px solid #dee2e6;
            border-radius: 6px;
        }
        .pl-table-wrapper table {
            table-layout: fixed;
            width: 100%;
        }
        .pl-table-wrapper thead th {
            position: sticky;
            top: 0;
            background: #f8f9fa;
            z-index: 5;
            font-size: 11px;
            text-transform: uppercase;
            color: #495057;
            padding: 10px 12px;
        }
        .pl-table-wrapper tbody td {
            padding: 10px 12px;
            vertical-align: middle;
            word-break: break-word;
        }
        .pl-action-bar {
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid #dee2e6;
            display: flex;
            gap: 10px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
        }
    </style>

    <!-- Success Banner -->
    <div class="pl-success-banner">
        <div>
            <div style="font-size:16px;font-weight:700;color:#155724">
                ✅ Pick List Created Successfully!
            </div>
            <div class="text-muted small mt-1">
                Warehouse staff can now pick items before delivery.
            </div>
        </div>
        <div>
            <a href="${pl_link}" target="_blank"
               class="btn btn-success btn-sm"
               style="font-weight:600;padding:8px 18px">
                📋 Open ${pl_name}
            </a>
        </div>
    </div>

    <!-- Summary Cards -->
    <div class="row mb-4">
        <div class="col-md-4">
            <div class="pl-card" style="border-top:4px solid #007bff">
                <div class="pl-card-value text-primary">${total_orders}</div>
                <div class="pl-card-label">Sales Orders</div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="pl-card" style="border-top:4px solid #28a745">
                <div class="pl-card-value text-success">${total_items}</div>
                <div class="pl-card-label">Unique Items</div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="pl-card" style="border-top:4px solid #17a2b8">
                <div class="pl-card-value text-info">${total_qty}</div>
                <div class="pl-card-label">Total Qty to Pick</div>
            </div>
        </div>
    </div>

    <!-- Consolidated Item Table -->
    <h6 style="font-weight:700;margin-bottom:10px">
        📦 Consolidated Pick List Items
        <span class="text-muted small font-weight-normal ml-1">
            (same item summed across all orders)
        </span>
    </h6>

    <div class="pl-table-wrapper">
        <table class="table table-sm table-bordered mb-0">
            <thead>
                <tr>
                    <th style="width:28%">Item Code</th>
                    <th style="width:8%;text-align:center">Total Qty</th>
                    <th style="width:6%;text-align:center">UOM</th>
                    <th style="width:15%">Warehouse</th>
                    <th style="width:8%;text-align:center">Orders</th>
                    <th style="width:35%">Appears In</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    </div>

    <!-- Action Bar -->
    <div class="pl-action-bar">
        <div class="text-muted small">
            ✔ Pick List saved as <b>${pl_name}</b> in ERPNext
        </div>
        <button class="btn btn-success" id="pl_download_excel_btn"
                style="padding:8px 18px;font-weight:600">
            📥 Download Excel
        </button>
        <button class="btn btn-danger" id="pl_download_pdf_btn"
                style="padding:8px 18px;font-weight:600">
            📄 Download PDF
        </button>
        <button class="btn btn-primary" id="pl_create_dn_btn"
                style="padding:8px 24px;font-weight:600">
            🚚 Now Create Delivery Notes
        </button>
        <button class="btn btn-default btn-sm" id="pl_close_btn">
            Close (Skip DN)
        </button>
    </div>
    `;

    // ---- Inject into the DN dialog ----
    let wrapper = dn_dialog.$wrapper;
    wrapper.find("#dn_so_list").html(html);
    wrapper.find("#dn_result_area").html("");

    // ---- Hide the dialog's own primary button ----
    try { dn_dialog.get_primary_btn().hide(); } catch(e) {}

    // ================================================================
    // EXCEL DOWNLOAD — using SheetJS (already bundled in Frappe)
    // ================================================================
    wrapper.find("#pl_download_excel_btn").on("click", function () {
    let btn = $(this);
    btn.prop("disabled", true).text("Preparing...");

    try {
        // Build CSV content (works without any library)
        let csv_rows = [
            ["Item Code", "Item Name", "Total Qty", "UOM",
             "Warehouse", "No. of Orders", "Source Sales Orders"]
        ];

        items.forEach(i => {
            csv_rows.push([
                `"${(i.item_code || "").replace(/"/g, '""')}"`,
                `"${(i.item_name || i.item_code || "").replace(/"/g, '""')}"`,
                i.total_qty,
                i.uom,
                `"${(i.warehouse || "").replace(/"/g, '""')}"`,
                i.so_count,
                `"${i.so_list.join(", ").replace(/"/g, '""')}"`,
            ]);
        });

        // Summary rows
        csv_rows.push([]);
        csv_rows.push([
            "Total Orders", total_orders,
            "Total Items", total_items,
            "Total Qty", total_qty
        ]);

        let csv_content = csv_rows.map(r => r.join(",")).join("\n");

        // Download as .csv (opens in Excel automatically)
        let blob = new Blob(
            ["\uFEFF" + csv_content],   // BOM for Excel UTF-8
            { type: "text/csv;charset=utf-8;" }
        );
        let url      = URL.createObjectURL(blob);
        let link     = document.createElement("a");
        let filename = `PickList_${frappe.datetime.now_date()}.csv`;

        link.setAttribute("href", url);
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        frappe.show_alert({
            message  : `✅ Downloaded ${filename}`,
            indicator: "green"
        }, 3);

    } catch(e) {
        frappe.msgprint({
            title    : "Download Failed",
            indicator: "red",
            message  : "Could not generate file: " + e.message,
        });
        console.error(e);
    }

    btn.prop("disabled", false).html("📥 Download Excel");
});

    // ================================================================
    // PDF DOWNLOAD — builds a clean HTML table and uses browser print
    // ================================================================
    wrapper.find("#pl_download_pdf_btn").on("click", function () {

        let pdf_rows = items.map((i, idx) => `
            <tr style="background:${idx % 2 === 0 ? "#fff" : "#f9f9f9"}">
                <td style="padding:8px;border:1px solid #ddd">${idx + 1}</td>
                <td style="padding:8px;border:1px solid #ddd">
                    <b>${i.item_code}</b>
                    ${i.item_name !== i.item_code
                        ? `<br><span style="color:#666;font-size:11px">
                               ${i.item_name}
                           </span>`
                        : ""}
                </td>
                <td style="padding:8px;border:1px solid #ddd;
                           text-align:center;font-size:16px;
                           font-weight:700;color:#2d6a4f">
                    ${i.total_qty}
                </td>
                <td style="padding:8px;border:1px solid #ddd;
                           text-align:center">${i.uom}</td>
                <td style="padding:8px;border:1px solid #ddd">
                    ${i.warehouse || "—"}
                </td>
                <td style="padding:8px;border:1px solid #ddd;
                           text-align:center">${i.so_count}</td>
                <td style="padding:8px;border:1px solid #ddd;
                           font-size:11px;color:#333">
                    ${i.so_list.join("<br>")}
                </td>
            </tr>`
        ).join("");

        let print_html = `
        <!DOCTYPE html>
        <html>
        <head>
            <title>Pick List — ${pl_name}</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 20px; }
                h2   { margin-bottom: 4px; }
                .meta { color: #666; font-size: 13px; margin-bottom: 20px; }
                .summary {
                    display: flex; gap: 20px;
                    margin-bottom: 20px;
                }
                .summary-card {
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    padding: 10px 20px;
                    text-align: center;
                    min-width: 100px;
                }
                .summary-card .val {
                    font-size: 24px;
                    font-weight: 700;
                }
                .summary-card .lbl {
                    font-size: 11px;
                    color: #666;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 13px;
                }
                thead th {
                    background: #343a40;
                    color: white;
                    padding: 10px 8px;
                    border: 1px solid #343a40;
                    text-align: left;
                }
                @media print {
                    button { display: none; }
                }
            </style>
        </head>
        <body>
            <h2>📦 Bulk Pick List</h2>
            <div class="meta">
                Generated on ${frappe.datetime.now_datetime()} &nbsp;|&nbsp;
                Pick List Ref: <b>${pl_name}</b>
            </div>

            <div class="summary">
                <div class="summary-card">
                    <div class="val" style="color:#007bff">${total_orders}</div>
                    <div class="lbl">Sales Orders</div>
                </div>
                <div class="summary-card">
                    <div class="val" style="color:#28a745">${total_items}</div>
                    <div class="lbl">Unique Items</div>
                </div>
                <div class="summary-card">
                    <div class="val" style="color:#17a2b8">${total_qty}</div>
                    <div class="lbl">Total Qty</div>
                </div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th style="width:4%">#</th>
                        <th style="width:28%">Item Code / Name</th>
                        <th style="width:8%;text-align:center">Total Qty</th>
                        <th style="width:6%;text-align:center">UOM</th>
                        <th style="width:16%">Warehouse</th>
                        <th style="width:8%;text-align:center">Orders</th>
                        <th style="width:30%">Source Sales Orders</th>
                    </tr>
                </thead>
                <tbody>${pdf_rows}</tbody>
            </table>

            <div style="margin-top:30px;font-size:12px;color:#999;
                        border-top:1px solid #eee;padding-top:10px">
                Inventre Edu Services Pvt Ltd &nbsp;|&nbsp;
                Printed from ERPNext
            </div>
        </body>
        </html>`;

        // Open in new window and trigger print dialog
        let print_win = window.open("", "_blank", "width=900,height=700");
        print_win.document.write(print_html);
        print_win.document.close();
        print_win.focus();
        setTimeout(() => print_win.print(), 500);
    });

    // ---- "Now Create Delivery Notes" button ----
    wrapper.find("#pl_create_dn_btn").on("click", function () {
        $(this).prop("disabled", true).text("Creating Delivery Notes...");
        run_bulk_dn_creation(so_names, dn_dialog);
    });

    // ---- "Close" button ----
    wrapper.find("#pl_close_btn").on("click", function () {
        dn_dialog.hide();
    });
}

function impressio_sync_orders(listview) {
	frappe.show_progress(__("Importing Orders"), 0, 100, __("Connecting to Orders API..."));

	frappe.call({
		method: "impressio.api.fetch_orders_from_api",
		callback: function (r) {
			if (!r || !r.message || !r.message.orders || r.message.orders.length === 0) {
				frappe.hide_progress();
				frappe.msgprint({
					title: __("No Orders Found"),
					indicator: "orange",
					message: __("The Orders API returned no orders to import.")
				});
				return;
			}

			const orders = r.message.orders;
			const total = orders.length;
			frappe.show_progress(__("Importing Orders"), 0, total, __("Found {0} orders. Starting sync...", [total]));

			const chunkSize = 2;
			const chunks = [];
			for (let i = 0; i < orders.length; i += chunkSize) {
				chunks.push(orders.slice(i, i + chunkSize));
			}

			let processedCount = 0;
			let totalCreated = 0;
			let totalUpdated = 0;
			let allErrors = [];
			let chunkIndex = 0;

			function processNextChunk() {
				if (chunkIndex >= chunks.length) {
					frappe.show_progress(__("Importing Orders"), total, total, __("Sync completed"));
					setTimeout(function () {
						frappe.hide_progress();
						if (allErrors.length > 0) {
							frappe.msgprint({
								title: __("Orders Sync Completed with Warnings/Errors"),
								indicator: "orange",
								message: __("Created: <b>{0}</b>, Updated: <b>{1}</b><br><br><b>Errors:</b><br>{2}", [
									totalCreated,
									totalUpdated,
									allErrors.map(e => `• ${frappe.utils.escape_html(e)}`).join("<br>")
								])
							});
						} else {
							frappe.show_alert({
								message: __("Orders Synced: {0} Created, {1} Updated", [totalCreated, totalUpdated]),
								indicator: "green"
							}, 6);
						}
						if (listview) {
							listview.refresh();
						}
					}, 400);
					return;
				}

				const currentChunk = chunks[chunkIndex];
				const firstOrder = currentChunk[0];
				const orderLabel = firstOrder.orderId || `Order #${firstOrder.id}`;
				const customerLabel = firstOrder.orderedBy || (firstOrder.address && firstOrder.address.fullName) || "";

				const currentStatus = customerLabel
					? __("Importing {0} ({1})... ({2}/{3})", [orderLabel, customerLabel, processedCount, total])
					: __("Importing {0}... ({1}/{2})", [orderLabel, processedCount, total]);

				frappe.show_progress(__("Importing Orders"), processedCount, total, currentStatus);

				frappe.call({
					method: "impressio.api.import_orders_from_api",
					args: {
						orders_data: currentChunk
					},
					callback: function (res) {
						processedCount += currentChunk.length;
						if (processedCount > total) processedCount = total;

						if (res && res.message) {
							totalCreated += (res.message.imported_count || 0);
							totalUpdated += (res.message.updated_count || 0);
							if (res.message.errors && res.message.errors.length) {
								allErrors.push(...res.message.errors);
							}
						}

						frappe.show_progress(__("Importing Orders"), processedCount, total, currentStatus);

						chunkIndex++;
						setTimeout(processNextChunk, 80);
					},
					error: function (err) {
						frappe.hide_progress();
						let msg = (err && err.message) ? err.message : __("Error importing orders from API.");
						frappe.msgprint({
							title: __("API Import Error"),
							indicator: "red",
							message: msg
						});
						if (listview) {
							listview.refresh();
						}
					}
				});
			}

			processNextChunk();
		},
		error: function (err) {
			frappe.hide_progress();
			let msg = (err && err.message) ? err.message : __("Could not connect to the Orders API or API response format changed.");
			frappe.msgprint({
				title: __("Orders API Error"),
				indicator: "red",
				message: msg
			});
		}
	});
}

