frappe.listview_settings["Sales Order"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Dashboard"), () => {
			open_sales_dashboard();
		});

		listview.page.add_inner_button(__("Analytics"), () => {
			open_sales_analytics();
		});

		listview.page.add_inner_button("Reset to Draft", function () {
			let selected = listview.get_checked_items();

			if (!selected.length) {
				frappe.msgprint("Please select Sales Orders");
				return;
			}

			let orders = selected.map((d) => d.name);

			open_reset_modal(orders);
		});
	},
};

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
