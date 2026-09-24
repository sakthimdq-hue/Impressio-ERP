// Copyright (c) 2025, MDQ
// Student Dashboard Clean Version

let orders_chart = null;
let amount_chart = null;

let current_page = 1;
let page_size = 20;
let total_rows = 0;

// ------------------------------------------------------
// DASHBOARD LAYOUT
// ------------------------------------------------------

function render_dashboard_layout(frm) {
	let html = `

<style>

.student-dashboard{
    padding:10px;
}

/* FILTER */

.filter-box{
    display:flex;
    gap:10px;
    flex-wrap:wrap;
    margin-bottom:20px;
}

/* KPI */

.kpi-grid{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
    gap:15px;
    margin-bottom:25px;
}

.kpi-card{
    background:#fff;
    border:1px solid #e4e6eb;
    border-radius:8px;
    padding:15px;
}

.kpi-label{
    font-size:13px;
    color:#777;
}

.kpi-value{
    font-size:24px;
    font-weight:600;
}

/* CHARTS */

.chart-box{
    background:#fff;
    border:1px solid #e4e6eb;
    border-radius:8px;
    padding:15px;
    margin-bottom:20px;
}

/* SALES ORDERS */

.sales-orders-grid{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
    gap:15px;
}

.sales-order-card{
    background:#fff;
    border:1px solid #e4e6eb;
    border-radius:8px;
    padding:15px;
}

.so-header{
    display:flex;
    justify-content:space-between;
    margin-bottom:10px;
}

.so-number{
    font-weight:600;
}

.so-date{
    font-size:12px;
    color:#888;
}

.so-amount{
    font-weight:600;
}

.items-wrapper{
    margin-top:10px;
}

.item-row{
    display:flex;
    justify-content:space-between;
    padding:4px 0;
    border-bottom:1px dashed #eee;
}

.pagination-box{
    margin-top:20px;
    text-align:center;
}

</style>

<div class="student-dashboard">

<!-- FILTER -->

<div class="filter-box">

<input type="date" id="filter_start" class="form-control" style="max-width:200px">

<input type="date" id="filter_end" class="form-control" style="max-width:200px">

<button id="apply_filter" class="btn btn-primary">
Apply
</button>

</div>


<!-- KPI -->

<div class="kpi-grid">

<div class="kpi-card">
<div class="kpi-label">Guardians</div>
<div class="kpi-value" id="total_guardians">0</div>
</div>

<div class="kpi-card">
<div class="kpi-label">Orders</div>
<div class="kpi-value" id="total_orders">0</div>
</div>

<div class="kpi-card">
<div class="kpi-label">Revenue</div>
<div class="kpi-value" id="total_revenue">0</div>
</div>

<div class="kpi-card">
<div class="kpi-label">Filtered Sales</div>
<div class="kpi-value" id="sales_amount">0</div>
</div>

</div>


<!-- CHARTS -->

<div class="chart-box">
<div id="orders_chart"></div>
</div>

<div class="chart-box">
<div id="amount_chart"></div>
</div>


<!-- ORDERS -->

<h4 style="margin-top:20px">Sales Orders</h4>

<div id="sales_orders_container" ></div>


<!-- PAGINATION -->

<div class="pagination-box">

<button id="prev_page" class="btn btn-default btn-sm">
Prev
</button>

<span id="page_info" style="margin:0 10px"></span>

<button id="next_page" class="btn btn-default btn-sm">
Next
</button>

</div>

</div>
`;

	frm.fields_dict.student_dashboard.$wrapper.html(html);
}

// ------------------------------------------------------
// STUDENT FORM
// ------------------------------------------------------
frappe.ui.form.on("Students", {
	refresh(frm) {
		// Hide dashboard tab if new document
		if (frm.is_new()) {
			frm.set_df_property("dashboard_tab", "hidden", 1);
			return;
		}

		// Show dashboard tab after save
		frm.set_df_property("dashboard_tab", "hidden", 0);

		// existing logic
		if (!frm.page.sidebar) {
			setTimeout(() => frm.trigger("refresh"), 100);
			return;
		}

		let sidebar = $(frm.page.sidebar);

		let logo_html = `
    <div id="school-logo-box"
    style="
        width:150px;
        height:150px;
        border:1px solid #e4e6eb;
        border-radius:6px;
        margin:10px auto;
        display:flex;
        align-items:center;
        justify-content:center;
        overflow:hidden;
        background:#fafbfc;
    ">
    ${
		frm.doc.profile_picture_attach
			? `<img src="${frm.doc.profile_picture_attach}" style="max-width:100%">`
			: ""
	}
    </div>
    `;

		sidebar.find("#school-logo-box").remove();
		sidebar.prepend(logo_html);

		current_page = 1;

		render_dashboard_layout(frm);

		load_student_dashboard(frm);
	},
});


frappe.ui.form.on("Students", {
	refresh(frm) {

		if (frm.is_new()) return;

		frm.add_custom_button("Download Orders", () => {

			let d = new frappe.ui.Dialog({
				title: "Download Sales Orders",

				fields: [
					{
						label: "Start Date",
						fieldname: "start_date",
						fieldtype: "Date",
						reqd: 1,
						default: frappe.datetime.year_start(),
					},
					{
						label: "End Date",
						fieldname: "end_date",
						fieldtype: "Date",
						reqd: 1,
						default: frappe.datetime.now_date(),
					},
				],

				primary_action_label: "Download",

				primary_action(values) {

					// VALIDATION
					if (!values.start_date || !values.end_date) {
						frappe.msgprint("Start Date and End Date are required");
						return;
					}

					let url = `/api/method/impressio.impressio.doctype.students.students.download_student_sales_orders?student=${frm.doc.name}&start_date=${values.start_date}&end_date=${values.end_date}`;

					window.open(url);

					d.hide();
				},
			});

			d.show();
		});
	},
});
// ------------------------------------------------------
// LOAD DASHBOARD
// ------------------------------------------------------

function load_student_dashboard(frm, start = null, end = null) {
	$("#orders_chart").html("Loading...");
	$("#amount_chart").html("Loading...");

	frappe.call({
		method: "impressio.impressio.doctype.students.students.get_student_dashboard",

		args: {
			student: frm.doc.name,
			start_date: start,
			end_date: end,
			page: current_page,
			page_size: page_size,
		},

		callback: function (r) {
			let d = r.message;
			if (!d) return;

			// FILTER VALUES FROM API

			$("#filter_start").val(d.filter.start_date);
			$("#filter_end").val(d.filter.end_date);

			// KPI

			$("#total_guardians").text(d.all_time.guardians);
			$("#total_orders").text(d.all_time.orders);
			$("#total_revenue").text("₹ " + d.all_time.sales_amount);
			$("#sales_amount").text("₹ " + d.filtered.sales_amount);

			// CHARTS

			setTimeout(() => {
				render_orders_chart(frm, d.charts);
				render_amount_chart(frm, d.charts);
			}, 100);

			// ORDERS

			render_sales_orders(d.sales_orders);

			// PAGINATION

			update_pagination(d.pagination);
		},
	});
}

// ------------------------------------------------------
// ORDERS CHART
// ------------------------------------------------------

function render_orders_chart(frm, chart) {
	let container = frm.fields_dict.student_dashboard.$wrapper.find("#orders_chart")[0];

	if (orders_chart) orders_chart.destroy();

	orders_chart = new frappe.Chart(container, {
		title: "Sales Orders Count",
		data: {
			labels: chart.labels || [],
			datasets: [
				{
					name: "Orders",
					values: chart.orders || [],
				},
			],
		},
		type: "bar",
		height: 280,
		colors: ["#5e64ff"],
	});
}

// ------------------------------------------------------
// AMOUNT CHART
// ------------------------------------------------------

function render_amount_chart(frm, chart) {
	let container = frm.fields_dict.student_dashboard.$wrapper.find("#amount_chart")[0];

	if (amount_chart) amount_chart.destroy();

	amount_chart = new frappe.Chart(container, {
		title: "Sales Amount Trend",
		data: {
			labels: chart.labels || [],
			datasets: [
				{
					name: "Sales Amount",
					values: chart.amounts || [],
				},
			],
		},
		type: "line",
		height: 280,
		colors: ["#28a745"],
	});
}

// ------------------------------------------------------
// SALES ORDERS
// ------------------------------------------------------

function render_sales_orders(orders) {
	let html = "";

	if (!orders || !orders.length) {
		$("#sales_orders_container").html("<p>No Sales Orders Found</p>");
		return;
	}

	orders.forEach((order) => {
		let items_html = order.items
			.map(
				(i) => `

<div class="item-row">
<span>${i.item_code}</span>
<span>x ${i.qty}</span>
</div>

`,
			)
			.join("");

		html += `

<div class="sales-order-card">

<div class="so-header">

<div>
<div class="so-number">${order.name}</div>
<div class="so-date">${order.transaction_date}</div>
</div>

<div style="text-align:right">
<div class="so-amount">₹ ${order.grand_total}</div>
<div class="badge badge-info">${order.status}</div>
</div>

</div>


<div class="items-wrapper">

<button class="btn btn-xs btn-light toggle-items">
View Items (${order.items.length})
</button>

<div class="items-list" style="display:none;margin-top:8px">

${items_html}

</div>

</div>

</div>

`;
	});

	$("#sales_orders_container").html(html);
}

// ------------------------------------------------------
// FILTER
// ------------------------------------------------------

$(document).on("click", "#apply_filter", function () {
	let start = $("#filter_start").val();
	let end = $("#filter_end").val();

	current_page = 1;

	load_student_dashboard(cur_frm, start, end);
});

// ------------------------------------------------------
// TOGGLE ITEMS
// ------------------------------------------------------

$(document).on("click", ".toggle-items", function () {
	let list = $(this).closest(".items-wrapper").find(".items-list");

	list.toggle();

	$(this).text(list.is(":visible") ? "Hide Items" : "View Items");
});

// ------------------------------------------------------
// PAGINATION
// ------------------------------------------------------

function update_pagination(pagination) {
	if (!pagination) return;

	total_rows = pagination.total_rows;

	let total_pages = Math.ceil(total_rows / page_size);

	$("#page_info").text(`Page ${pagination.page} of ${total_pages}`);

	$("#prev_page").prop("disabled", pagination.page <= 1);

	$("#next_page").prop("disabled", pagination.page >= total_pages);
}

$(document).on("click", "#prev_page", function () {
	if (current_page > 1) {
		current_page--;

		load_student_dashboard(cur_frm);
	}
});

$(document).on("click", "#next_page", function () {
	let total_pages = Math.ceil(total_rows / page_size);

	if (current_page < total_pages) {
		current_page++;

		load_student_dashboard(cur_frm);
	}
});
