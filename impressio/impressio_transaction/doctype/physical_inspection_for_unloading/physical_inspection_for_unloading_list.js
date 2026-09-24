// frappe.listview_settings["Physical Inspection For Unloading"] = {
// 	add_fields: ["name", "company", "report_date", "status"],

// 	get_indicator: function (doc) {
// 		const colors = {
// 			Accepted: "green",
// 			Rejected: "red",
// 			"Partially Accepted": "blue",
// 		};

// 		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
// 	},
// };
