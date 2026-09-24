frappe.listview_settings["Website Cart Coupon"] = {
	onload(listview) {
		// ---------------- IMPORT BUTTON ----------------
		listview.page.add_inner_button(__("Import Coupons"), () => {
			frappe.prompt(
				[
					{
						fieldname: "file",
						label: "Upload Coupon Excel",
						fieldtype: "Attach",
						reqd: 1,
					},
				],
				function (values) {
					frappe.call({
						method: "impressio.impressio.cart_coupon.upload_coupon_excel",
						args: { file_url: values.file },
						freeze: true,
						freeze_message: "Validating and importing coupons...",
						callback: function (r) {
							if (!r.message) return;

							const data = r.message;
							const summary = data.summary;
							const errors = data.errors;

							// -------- REPORT VIEW --------
							let report_html = `
        <div style="padding:10px">
            <h3>Import Report</h3>
            <p>
                <b>Total Rows:</b> ${summary.total} <br>
                <span style="color:green"><b>Success:</b> ${summary.success}</span> <br>
                <span style="color:red"><b>Failed:</b> ${summary.failed}</span>
            </p>
        </div>
    `;

							// -------- ERRORS VIEW --------
							let error_html = "";

							if (errors.length > 0) {
								error_html = `
            <h3 style="color:red">Errors</h3>
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>Row</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>
        `;

								errors.forEach((e) => {
									error_html += `
                <tr>
                    <td><b>${e.row}</b></td>
                    <td>${e.error}</td>
                </tr>
            `;
								});

								error_html += "</tbody></table>";
							}

							frappe.msgprint({
								title: "Coupon Import Result",
								message: report_html + error_html,
								wide: true,
							});

							if (summary.success > 0) {
								listview.refresh();
							}
						},
					});
				},
				"Upload Coupon Excel",
				"Upload",
			);
		});

		// ---------------- DOWNLOAD TEMPLATE ----------------
		listview.page.add_inner_button(__("Download Template"), () => {
			frappe.call({
				method: "impressio.impressio.cart_coupon.download_coupon_template",
				callback: function (r) {
					if (r.message) {
						window.open(r.message);
					}
				},
			});
		});
	},
};
