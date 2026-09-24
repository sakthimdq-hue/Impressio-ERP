frappe.listview_settings["Students"] = {
	onload(listview) {
		// 1. Direct button in inner toolbar
		if (listview.page && listview.page.inner_toolbar && !listview.page.inner_toolbar.find(`button[data-label="${encodeURIComponent("Import Students from API")}"]`).length) {
			listview.page.add_inner_button(
				__("Import Students from API"),
				() => {
					impressio_sync_students(listview);
				}
			);
		}

		// 3. Actions menu
		if (listview.page) {
			listview.page.add_inner_button(
				__("Import Students from API"),
				() => {
					impressio_sync_students(listview);
				},
				__("Actions")
			);
		}

		// ➕ Import Button (Excel)
		listview.page.add_inner_button(__("Import Students (Excel)"), () => {
			frappe.prompt(
				[
					{
						fieldname: "file",
						label: "Upload Excel File",
						fieldtype: "Attach",
						reqd: 1,
					},
				],
				function (values) {
					frappe.call({
						method: "impressio.impressio.student.upload_student_excel",
						args: { file_url: values.file },
						callback: function (r) {
							if (!r.exc && r.message) {
								const msg = r.message;
								const summary = msg.summary;
								const results = msg.result;

								let html = `<div style="padding:10px;">`;
								html += `<h4>${msg.message}</h4>`;
								html += `<p><b>Total Rows:</b> ${summary.total_count} &nbsp; | &nbsp; <b>Success:</b> ${summary.success_count} &nbsp; | &nbsp; <b>Failed:</b> ${summary.failed_count}</p>`;

								if (results.length > 0) {
									html += `<table class="table table-bordered" style="width:100%; border-collapse: collapse;">
                                            <thead>
                                                <tr>
                                                    <th>Enrollment / Row</th>
                                                    <th>Status</th>
                                                    <th>Details / Error</th>
                                                </tr>
                                            </thead>
                                            <tbody>`;

									results.forEach((res) => {
										let status_color =
											res.status === "Inserted" ? "green" : "red";
										let enrollment_or_row =
											res.enrollment_number ||
											res.row_number ||
											(res.rows ? res.rows.join(", ") : "-");
										let details =
											res.status === "Inserted"
												? "Inserted successfully"
												: res.error || "Unknown Error";

										html += `<tr>
                                                <td>${enrollment_or_row}</td>
                                                <td style="color:${status_color}; font-weight:bold;">${res.status}</td>
                                                <td>${details}</td>
                                            </tr>`;
									});

									html += `</tbody></table>`;
								}

								html += `</div>`;

								frappe.msgprint({
									title: __("Import Result"),
									message: html,
									wide: true,
								});

								if (summary.success_count > 0) {
									listview.refresh();
								}
							} else if (r.exc) {
								frappe.msgprint(__("Error during import: ") + r.exc);
							}
						},
					});
				},
				__("Upload Student Excel"),
				__("Upload"),
			);
		});

		// ➕ Download Template Button
		listview.page.add_inner_button(__("Download Students"), () => {
			frappe.call({
				method: "impressio.impressio.student.download_student_template",
				callback: function (r) {
					if (r.message) {
						window.open(r.message);
					}
				},
			});
		});

		// ✅ Bulk Enable Button
		listview.page.add_action_item(__("Enable Students"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Please select at least one student."));
				return;
			}

			frappe.confirm(__(`Enable ${selected.length} selected student(s)?`), () => {
				const names = selected.map((s) => s.name);
				frappe.call({
					method: "impressio.impressio.student.bulk_toggle_students",
					args: { names: JSON.stringify(names), enable: 1 },
					callback: function (r) {
						if (!r.exc && r.message) {
							frappe.msgprint(r.message);
							listview.refresh();
						}
					},
				});
			});
		});

		listview.page.add_action_item(__("Disable Students"), () => {
			const selected = listview.get_checked_items();
			if (!selected.length) {
				frappe.msgprint(__("Please select at least one student."));
				return;
			}

			frappe.confirm(__(`Disable ${selected.length} selected student(s)?`), () => {
				const names = selected.map((s) => s.name);
				frappe.call({
					method: "impressio.impressio.student.bulk_toggle_students",
					args: { names: JSON.stringify(names), enable: 0 },
					callback: function (r) {
						if (!r.exc && r.message) {
							frappe.msgprint(r.message);
							listview.refresh();
						}
					},
				});
			});
		});

		listview.page.add_action_item(__("Create Customer"), async () => {
			let selected = listview.get_checked_items();

			if (!selected.length) {
				frappe.msgprint("Please select students");
				return;
			}

			let names = selected.map((d) => d.name);

			let r = await frappe.call({
				method: "impressio.impressio.api.student.create_customers_from_students",
				args: {
					student_names: names,
				},
			});

			let msg = `<b>Created:</b> ${r.message.created.length}<br>`;
			msg += `<b>Skipped:</b> ${r.message.skipped.length}<br>`;
			msg += `<b>Failed:</b> ${r.message.failed.length}<br><br>`;

			if (r.message.skipped.length) {
				msg += "<b>Skipped Details:</b><br>";
				r.message.skipped.forEach((d) => {
					msg += `• ${d.student} → ${d.reason}<br>`;
				});
			}

			if (r.message.failed.length) {
				msg += "<br><b>Failed Details:</b><br>";
				r.message.failed.forEach((d) => {
					msg += `• ${d.student} → ${d.error}<br>`;
				});
			}

			frappe.msgprint({
				title: "Customer Creation Summary",
				message: msg,
				wide: true,
			});

			listview.refresh();
		});
	},

	refresh(listview) {
		if (listview.page && listview.page.inner_toolbar && !listview.page.inner_toolbar.find(`button[data-label="${encodeURIComponent("Import Students from API")}"]`).length) {
			listview.page.add_inner_button(
				__("Import Students from API"),
				() => {
					impressio_sync_students(listview);
				}
			);
		}

		if (listview.page) {
			listview.page.add_inner_button(
				__("Import Students from API"),
				() => {
					impressio_sync_students(listview);
				},
				__("Actions")
			);
		}
	},
};

function impressio_sync_students(listview) {
	// Clean up any legacy overlay/styles if left over
	const oldOverlay = document.getElementById("impressio-student-sync-overlay");
	if (oldOverlay) oldOverlay.remove();
	const oldStyle = document.getElementById("impressio-student-sync-modal-styles");
	if (oldStyle) oldStyle.remove();

	frappe.show_progress(__("Syncing Students"), 0, 100, __("Connecting to API..."));

	frappe.call({
		method: "impressio.api.fetch_students_from_api",
		args: {
			page: 1,
			limit: 50,
		},
		callback: function (r) {
			if (!r || !r.message || !r.message.students || r.message.students.length === 0) {
				frappe.hide_progress();
				frappe.msgprint({
					title: __("No Students Found"),
					indicator: "orange",
					message: __("The API returned no students to import.")
				});
				return;
			}

			const students = r.message.students;
			const total = students.length;
			frappe.show_progress(__("Syncing Students"), 0, total, __("Found {0} students. Starting sync...", [total]));

			const chunkSize = 5;
			const chunks = [];
			for (let i = 0; i < students.length; i += chunkSize) {
				chunks.push(students.slice(i, i + chunkSize));
			}

			let processedCount = 0;
			let totalCreated = 0;
			let totalUpdated = 0;
			let chunkIndex = 0;

			function processNextChunk() {
				if (chunkIndex >= chunks.length) {
					frappe.show_progress(__("Syncing Students"), total, total, __("Sync completed"));
					setTimeout(function () {
						frappe.hide_progress();
						frappe.show_alert({
							message: __("Students Synced: {0} Created, {1} Updated", [totalCreated, totalUpdated]),
							indicator: "green"
						}, 5);
						if (listview) {
							listview.refresh();
						}
					}, 400);
					return;
				}

				const currentChunk = chunks[chunkIndex];
				const firstStudent = currentChunk[0];
				const nameLabel = firstStudent.name || `ID #${firstStudent.id}`;
				const schoolLabel = firstStudent.school_name || firstStudent.school_code || "";

				const currentStatus = schoolLabel
					? __("Importing {0} ({1})...", [nameLabel, schoolLabel])
					: __("Importing {0}...", [nameLabel]);

				frappe.show_progress(__("Syncing Students"), processedCount, total, currentStatus);

				frappe.call({
					method: "impressio.api.import_students_from_api",
					args: {
						students_data: currentChunk
					},
					callback: function (res) {
						processedCount += currentChunk.length;
						if (processedCount > total) processedCount = total;

						if (res && res.message) {
							totalCreated += (res.message.imported_count || 0);
							totalUpdated += (res.message.updated_count || 0);
						}

						frappe.show_progress(__("Syncing Students"), processedCount, total, currentStatus);

						chunkIndex++;
						setTimeout(processNextChunk, 60);
					},
					error: function () {
						processedCount += currentChunk.length;
						chunkIndex++;
						setTimeout(processNextChunk, 60);
					}
				});
			}

			processNextChunk();
		},
		error: function () {
			frappe.hide_progress();
			frappe.msgprint({
				title: __("API Error"),
				indicator: "red",
				message: __("Could not connect to the Students API.")
			});
		}
	});
}
