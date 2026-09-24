frappe.ui.form.on("Stock Entry", {
	before_submit: function (frm) {
		const types = [
			"Material Transfer for Manufacture",
			"Manufacture",
			"Material Transfer",
			"Material Issue",
			"Material Receipt",
		];

		// if (types.includes(frm.doc.purpose)) {
		// 	return validate_all_with_qr(frm);
		// }
	},
});

function resolve_warehouse(frm, verification_type) {
    const items = frm.doc.items || [];
    const is_transfer = [
    "Material Transfer",
    "Material Transfer for Manufacture"
].includes(frm.doc.purpose);


    if (is_transfer) {
        return verification_type === "source"
            ? items.find(r => r.s_warehouse)?.s_warehouse
            : items.find(r => r.t_warehouse)?.t_warehouse;
    }

    return verification_type === "source"
        ? frm.doc.from_warehouse
        : frm.doc.to_warehouse;
}


// ----------------------------
// MASTER VALIDATION FUNCTION
// ----------------------------
async function validate_all_with_qr(frm) {
	return new Promise(async (resolve, reject) => {
		try {

			


			const type = frm.doc.purpose;
            const skip_source = type === "Material Receipt";

			// Source check
			if (
				["Material Issue", "Material Transfer", "Manufacture", "Material Transfer for Manufacture"]
					.includes(type)
			) {
				const has_source_wh =
					frm.doc.from_warehouse ||
					(frm.doc.items || []).some(row => row.s_warehouse);

				if (!has_source_wh) {
					show_friendly_error("Please set Source Warehouse (header or item row) before verification.");
					return reject();
				}
			}

			// Target check
			if (
				["Material Receipt", "Material Transfer", "Manufacture", "Material Transfer for Manufacture"]
					.includes(type)
			) {
				const has_target_wh =
					frm.doc.to_warehouse ||
					(frm.doc.items || []).some(row => row.t_warehouse);

				if (!has_target_wh) {
					show_friendly_error("Please set Target Warehouse (header or item row) before verification.");
					return reject();
				}
			}


			if (!frm.doc.items || frm.doc.items.length === 0) {
				show_friendly_error("Please add items before verification.");
				reject();
				return;
			}


			// const source_wh =
			// 	frm.doc.from_warehouse ||
			// 	(frm.doc.items || []).find(row => row.s_warehouse)?.s_warehouse ||
			// 	"Not Set";

			// const target_wh =
			// 	frm.doc.to_warehouse ||
			// 	(frm.doc.items || []).find(row => row.t_warehouse)?.t_warehouse ||
			// 	"Not Set";

			const source_wh = resolve_warehouse(frm, "source") || "Not Set";
            const target_wh = resolve_warehouse(frm, "target") || "Not Set";


			// Create a progress dialog
			const progress_dialog = new frappe.ui.Dialog({
				title: __("QR Code Verification Process"),
				fields: [
					{
						fieldname: "progress_html",
						fieldtype: "HTML",
					},
				],
				primary_action_label: __("Begin Verification"),
				primary_action: async function () {
					progress_dialog.get_primary_btn().prop("disabled", true);
					const success = await start_verification_process(frm, progress_dialog, skip_source);
					if (success) {
						resolve(); // Allow submission
					} else {
						reject(); // Prevent submission
					}
				},
				secondary_action_label: __("Cancel"),
				secondary_action: function () {
					progress_dialog.hide();
					reject(); // Prevent submission
				},
			});

			const progress_html = `
            <div class="text-center">
               <div class="alert alert-info">
                  <h4>📱 QR Code Verification Required</h4>
                  <p>Please follow the step-by-step verification process to complete your stock entry</p>
               </div>
               
               <div class="progress" style="height: 25px; margin: 20px 0;">
                  <div class="progress-bar progress-bar-striped progress-bar-animated" 
                       role="progressbar" style="width: 0%" id="verification_progress">
                     <b>0% Complete</b>
                  </div>
               </div>
               
               <div class="verification-steps">
                  ${skip_source ? "" : `
<div class="step" id="step1">
   <i class="fa fa-circle-o text-muted"></i> 
   <span class="text-muted">Verify Source Warehouse: ${source_wh}</span>
</div>
<div class="step" id="step2">
   <i class="fa fa-circle-o text-muted"></i> 
   <span class="text-muted">Source Items Verification (${frm.doc.items.length} items)</span>
</div>
`}
                  <div class="step" id="step3">
                     <i class="fa fa-circle-o text-muted"></i> 
                     <span class="text-muted">Verify Target Warehouse: ${target_wh}</span>
                  </div>
                  <div class="step" id="step4">
                     <i class="fa fa-circle-o text-muted"></i> 
                     <span class="text-muted">Target Items Verification (${frm.doc.items.length} items)</span>
                  </div>
                  <div class="step" id="step5">
                     <i class="fa fa-circle-o text-muted"></i> 
                     <span class="text-muted">Final Confirmation</span>
                  </div>
               </div>
               
               <style>
                  .verification-steps {
                     text-align: left;
                     margin: 20px 0;
                  }
                  .step {
                     padding: 10px;
                     margin: 5px 0;
                     border-left: 3px solid #dee2e6;
                  }
                  .step.active {
                     border-left-color: #007bff;
                     background-color: #f8f9fa;
                  }
                  .step.completed {
                     border-left-color: #28a745;
                     background-color: #f8fff9;
                  }
                  .step i {
                     margin-right: 10px;
                  }
                  .step.completed i::before {
                     content: "\\f00c";
                     color: #28a745;
                  }
                  .step.active i::before {
                     content: "\\f192";
                     color: #007bff;
                  }
               </style>
            </div>
         `;

			progress_dialog.fields_dict.progress_html.$wrapper.html(progress_html);
			progress_dialog.show();
		} catch (error) {
			console.error("Verification process could not start:", error);
			show_friendly_error("Verification process could not start. Please try again.");
			reject();
		}
	});
}

// ----------------------------
// VERIFICATION PROCESS CONTROLLER
// ----------------------------
async function start_verification_process(frm, progress_dialog,skip_source) {
	try {
		 if (!skip_source) {
    update_progress(0, "Verifying Source Warehouse...");
    await update_step(1, "active");

    // const source_wh =
    //     frm.doc.from_warehouse ||
    //     (frm.doc.items || []).find(r => r.s_warehouse)?.s_warehouse;
	const source_wh = resolve_warehouse(frm, "source");


    const source_valid = await scan_with_instruction(
        source_wh,
        "Source Warehouse",
        "Please scan the QR code for Source Warehouse"
    );

    if (!source_valid) {
        show_friendly_error(
            "Source Warehouse verification failed! Please check the QR code and try again."
        );
        progress_dialog.hide();
        return false;
    }

    await update_step(1, "completed");
    update_progress(10, "Source Warehouse verified successfully!");
}

		// Step 2: Source Items Verification
		if (!skip_source) {
    await update_step(2, "active");
    update_progress(15, "Verifying source items...");

    const source_items_verified = await verify_items_with_method(
        frm,
        "source",
        progress_dialog
    );

    if (!source_items_verified) {
        show_friendly_error(
            "Source items verification failed! Please verify all items from source."
        );
        progress_dialog.hide();
        return false;
    }

    await update_step(2, "completed");
    update_progress(40, "Source items verified successfully!");
}

		// Step 3: Target Warehouse
		await update_step(3, "active");

		// const target_valid = await scan_with_instruction(
		// 	frm.doc.to_warehouse,
		// 	"Target Warehouse",
		// 	"Please scan the QR code for Target Warehouse"
		// );

		const target_wh = resolve_warehouse(frm, "target");

const target_valid = await scan_with_instruction(
    target_wh,
    "Target Warehouse",
    "Please scan the QR code for Target Warehouse"
);


		if (!target_valid) {
			show_friendly_error(
				"Target Warehouse verification failed! Please check the QR code and try again."
			);
			progress_dialog.hide();
			return false;
		}

		await update_step(3, "completed");
		update_progress(50, "Target Warehouse verified successfully!");

		// Step 4: Target Items Verification
		await update_step(4, "active");
		update_progress(55, "Verifying target items...");

		// Do the SAME verification process for target items
		const target_items_verified = await verify_items_with_method(
			frm,
			"target",
			progress_dialog
		);
		console.log("Target items verified:", target_items_verified);

		if (!target_items_verified) {
			show_friendly_error(
				"Target items verification failed! Please verify all items for target."
			);
			progress_dialog.hide();
			return false;
		}

		await update_step(4, "completed");
		update_progress(90, "Target items verified successfully!");

		// Step 5: Final Confirmation
		await update_step(5, "active");

		const final_confirmation = await show_final_confirmation();
		if (final_confirmation) {
			update_progress(100, "Verification completed successfully!");
			await update_step(5, "completed");

			setTimeout(() => {
				progress_dialog.hide();
				frappe.show_alert({
					message: __(
						"All QR code verifications completed successfully! You can now submit the document."
					),
					indicator: "green",
				});
			}, 1000);
			return true; // Allow submission
		} else {
			show_friendly_error("Submission was cancelled. Your document is still in draft mode.");
			progress_dialog.hide();
			return false;
		}
	} catch (error) {
		console.error("Verification process error:", error);
		show_friendly_error("Verification process was interrupted. Please try again.");
		progress_dialog.hide();
		return false;
	}
}

// ----------------------------
// VERIFY ITEMS WITH METHOD (SIMPLIFIED)
// ----------------------------
async function verify_items_with_method(frm, verification_type, progress_dialog) {
	console.log("Starting verify_items_with_method for", verification_type);

	try {
		const items_count = frm.doc.items.length;
		
			const warehouse = resolve_warehouse(frm, verification_type);

		// Ask user for verification method
		const verification_method = await show_verification_method_dialog(
			`${verification_type === "source" ? "Source" : "Target"} Items Verification`,
			`You need to verify ${items_count} items for ${verification_type === "source" ? "source" : "target"
			} warehouse: ${warehouse}`,
			items_count,
			verification_type
		);

		if (!verification_method) {
			console.log("User cancelled verification method selection");
			return false;
		}

		let verification_success = false;

		if (verification_method === "scan_all") {
			// Option 1: Scan all items one by one (ONE-BY-ONE PROCESS)
			console.log("Starting scan_all method");
			verification_success = await scan_items_one_by_one(frm, verification_type);
		} else if (verification_method === "scan_once") {
			// Option 2: Scan once and enter total quantity
			console.log("Starting scan_once method");
			verification_success = await scan_once_with_total_qty(frm, verification_type);
		} else if (verification_method === "manual_entry") {
			// Option 3: Manual entry without scanning
			console.log("Starting manual_entry method");
			verification_success = await manual_quantity_entry(frm, verification_type);
		}

		console.log("Verification success for", verification_type, ":", verification_success);
		return verification_success;
	} catch (error) {
		console.error("Items verification error:", error);
		return false;
	}
}

// ----------------------------
// SHOW VERIFICATION METHOD DIALOG
// ----------------------------
function show_verification_method_dialog(title, description, items_count, verification_type) {
	return new Promise((resolve) => {
		const dialog = new frappe.ui.Dialog({
			title: __(title),
			fields: [
				{
					fieldname: "instruction_html",
					fieldtype: "HTML",
					options: `
                  <div class="text-center">
                     <div class="alert alert-info">
                        <i class="fa fa-qrcode fa-2x"></i>
                        <h4>${title}</h4>
                        <p>${description}</p>
                        <p><b>Total Items:</b> ${items_count}</p>
                        <p><b>Verification Type:</b> ${verification_type === "source" ? "Source Items" : "Target Items"
						}</p>
                     </div>
                     <div class="alert alert-warning">
                        <p>Select your preferred verification method:</p>
                     </div>
                  </div>
               `,
				},
				{
					fieldname: "verification_method",
					fieldtype: "Select",
					label: __("Verification Method"),
					options: [
						{ label: "" },
						{ label: "🔍 Scan Each Quantity One-by-One", value: "scan_all" },
						{ label: "📱 Scan Once + Enter Total Quantity", value: "scan_once" },
						// { label: '✍️ Manual Quantity Entry (No Scan)', value: 'manual_entry' }
					],
					// default: 'scan_all',
					reqd: 1,
				},
			],
			primary_action_label: __("Continue"),
			primary_action: function () {
				const method = dialog.get_value("verification_method");
				dialog.hide();
				resolve(method);
			},
			secondary_action_label: __("Cancel"),
			secondary_action: function () {
				dialog.hide();
				resolve(null);
			},
		});

		dialog.show();
	});
}

// ----------------------------
// SCAN ITEMS ONE BY ONE
// ----------------------------
async function scan_items_one_by_one(frm, verification_type) {
	console.log("Starting scan_items_one_by_one for", verification_type);

	return new Promise((resolve) => {
		const items = frm.doc.items;
		const scanned_items = new Map();
		const warehouse = resolve_warehouse(frm, verification_type);
		// Get item details
		get_item_details(items.map((item) => item.item_code))
			.then((item_details) => {
				// Create scanning dialog
				const scan_dialog = new frappe.ui.Dialog({
					title: __(
						`${verification_type === "source" ? "Source" : "Target"} Items Scanning`
					),
					fields: [
						{
							fieldname: "progress_html",
							fieldtype: "HTML",
						},
					],
					primary_action_label: __("Start Scanning"),
					primary_action: function () {
						start_scanning_session();
					},
					secondary_action_label: __("Skip Item"),
					secondary_action: function () {
						skip_current_item();
					},
				});

				// Store current state
				let current_state = {
					item_index: -1,
					batch_index: -1,
					current_item: null,
					current_batch: null,
					is_scanning: false,
				};

				// Function to start scanning session
				function start_scanning_session() {
					if (current_state.is_scanning) return;

					const next_scan_info = get_next_item_to_scan(
						items,
						scanned_items,
						current_state
					);

					if (!next_scan_info) {
						// All items scanned
						frappe.show_alert({
							message: __("✅ All items have been scanned!"),
							indicator: "green",
						});
						update_ui();
						return;
					}

					current_state.item_index = next_scan_info.item_index;
					current_state.batch_index = next_scan_info.batch_index;
					current_state.current_item = items[next_scan_info.item_index];
					current_state.current_batch = next_scan_info.batch_no;
					current_state.is_scanning = true;

					// Open scanner
					open_scanner();
				}

				// Function to open scanner
				function open_scanner() {
					const current_item = current_state.current_item;
					const item_detail = item_details[current_item.item_code] || {};

					const scanner_instance = new frappe.ui.Scanner({
						dialog: true,
						multiple: false,
						title: `Scan ${item_detail.item_name || current_item.item_code}`,
						on_scan: function (data) {
							const text = data.decodedText;
							const scanned_item = extract(text, "ITEM:");
							const scanned_batch = extract(text, "BATCH:");

							if (!scanned_item) {
								frappe.show_alert({
									message: __("❌ No valid item QR code detected."),
									indicator: "red",
								});
								return;
							}

							// Validate scanned item
							if (scanned_item !== current_item.item_code) {
								frappe.show_alert({
									message: __(
										`❌ Wrong item! Expected: ${current_item.item_code}, Scanned: ${scanned_item}`
									),
									indicator: "red",
								});
								return;
							}

							// Validate batch if required
							if (current_item.batch_no && current_state.current_batch) {
								if (scanned_batch !== current_state.current_batch) {
									frappe.show_alert({
										message: __(
											`❌ Wrong batch! Expected: ${current_state.current_batch}, Scanned: ${scanned_batch}`
										),
										indicator: "red",
									});
									return;
								}
							}

							// Update scanned items
							const key = scanned_batch
								? `${scanned_item}_${scanned_batch}`
								: scanned_item;
							scanned_items.set(key, (scanned_items.get(key) || 0) + 1);

							// Show success message
							const batch_info = scanned_batch ? ` (Batch: ${scanned_batch})` : "";
							const success_msg = `✅ Scanned: ${item_detail.item_name || scanned_item
								}${batch_info} for ${warehouse}`;

							frappe.show_alert({
								message: __(success_msg),
								indicator: "green",
								duration: 2,
							});

							// Close scanner
							scanner_instance.stop_scan();
							current_state.is_scanning = false;

							// Update UI
							setTimeout(() => {
								update_ui();
							}, 500);
						},
					});

					// Handle scanner close
					scanner_instance.dialog.onhide = function () {
						current_state.is_scanning = false;
						update_ui();
					};

					// Show scanning instruction
					frappe.show_alert({
						message: __(
							`📷 Please scan 1 unit of ${item_detail.item_name || current_item.item_code
							}`
						),
						indicator: "blue",
						duration: 3,
					});
				}

				// Function to skip current item
				function skip_current_item() {
					if (!current_state.current_item) return;

					const item = current_state.current_item;
					const key = current_state.current_batch
						? `${item.item_code}_${current_state.current_batch}`
						: item.item_code;

					// Get current scanned quantity
					const current_scanned = get_scanned_quantity_for_item(scanned_items, item);
					const required_qty = flt(item.qty);

					// Calculate how many more to mark as scanned
					const to_add = required_qty - current_scanned;

					if (to_add > 0) {
						scanned_items.set(key, (scanned_items.get(key) || 0) + to_add);
						frappe.show_alert({
							message: __(`⚠️ Skipped ${to_add} unit(s) for ${item.item_code}`),
							indicator: "orange",
						});
					}

					update_ui();
				}

				// Function to update UI
				function update_ui() {
					const all_complete = check_all_items_complete(items, scanned_items);

					// Update progress display
					update_scan_progress_ui(
						scan_dialog,
						items,
						scanned_items,
						current_state,
						item_details,
						verification_type,
						warehouse,
						all_complete
					);

					// Update buttons
					const primary_btn = scan_dialog.get_primary_btn();
					const secondary_btn = scan_dialog.get_secondary_btn();

					if (primary_btn) {
						if (all_complete) {
							primary_btn.hide();
						} else {
							primary_btn.show();
							primary_btn.text(
								current_state.is_scanning
									? __("Scanning...")
									: __("Scan Next Quantity")
							);
							primary_btn.prop("disabled", current_state.is_scanning);
						}
					}

					if (secondary_btn) {
						secondary_btn.prop("disabled", all_complete || current_state.is_scanning);
						if (all_complete) {
							secondary_btn.hide();
						}
					}

					// Add complete button if needed
					if (all_complete) {
						add_complete_button(scan_dialog, resolve);
					} else {
						remove_complete_button();
					}
				}

				// Function to add complete button
				function add_complete_button(dialog, resolve_callback) {
					let completeBtn = $("#completeBtn");

					if (completeBtn.length === 0) {
						const footer = dialog.$wrapper.find(".modal-footer");
						completeBtn = $(`
                  <button class="btn btn-success" id="completeBtn" style="margin-left: 10px;">
                     <i class="fa fa-check"></i> Complete & Proceed
                  </button>
               `);

						completeBtn.on("click", function () {
							console.log("Complete & Proceed clicked");
							dialog.hide();
							frappe.show_alert({
								message: __(
									`✅ All ${verification_type} items scanned successfully! Moving to next step...`
								),
								indicator: "green",
								duration: 3,
							});
							resolve_callback(true);
						});

						footer.append(completeBtn);
					}

					completeBtn.show();
				}

				// Function to remove complete button
				function remove_complete_button() {
					$("#completeBtn").hide();
				}

				// Show dialog
				scan_dialog.show();
				update_ui();

				// Handle dialog close
				scan_dialog.onhide = function () {
					const all_complete = check_all_items_complete(items, scanned_items);

					if (all_complete) {
						console.log("Dialog closed, all complete, resolving true");
						resolve(true);
					} else {
						// Ask user if they want to proceed with incomplete verification
						frappe.confirm(
							`<div class="alert alert-warning text-center">
                     <i class="fa fa-exclamation-triangle fa-2x"></i>
                     <h4>⚠️ Verification Incomplete!</h4>
                     <p>Not all items have been scanned for ${warehouse}.</p>
                     <p>Do you want to proceed anyway?</p>
                  </div>`,
							function () {
								// User wants to proceed anyway
								console.log("User chose to proceed with incomplete verification");
								frappe.show_alert({
									message: __(
										`⚠️ Proceeding with incomplete verification for ${warehouse}`
									),
									indicator: "orange",
									duration: 3,
								});
								resolve(true);
							},
							function () {
								// User wants to continue scanning
								console.log("User chose to continue scanning");
								frappe.show_alert({
									message: __(`Please continue scanning items for ${warehouse}`),
									indicator: "blue",
								});
								scan_dialog.show(); // Reopen dialog
							}
						);
					}
				};
			})
			.catch((error) => {
				console.error("Error getting item details:", error);
				resolve(false);
			});
	});
}

// ----------------------------
// UPDATE SCAN PROGRESS UI
// ----------------------------
function update_scan_progress_ui(
	dialog,
	items,
	scanned_items,
	current_state,
	item_details,
	verification_type,
	warehouse,
	all_complete
) {
	if (!dialog || !dialog.fields_dict.progress_html) return;

	let total_scanned_qty = 0;
	let total_required_qty = 0;

	// Calculate progress
	items.forEach((item) => {
		const scanned_qty = get_scanned_quantity_for_item(scanned_items, item);
		total_scanned_qty += scanned_qty;
		total_required_qty += flt(item.qty);
	});

	const progress_percent = Math.round((total_scanned_qty / total_required_qty) * 100);

	// Create scanned items table
	let items_table = "";
	items.forEach((item, index) => {
		const item_detail = item_details[item.item_code] || {};
		const scanned_qty = get_scanned_quantity_for_item(scanned_items, item);
		const required_qty = flt(item.qty);
		const remaining_qty = required_qty - scanned_qty;

		const is_current_item = current_state.item_index === index;
		const status_class =
			scanned_qty >= required_qty
				? "text-success"
				: is_current_item
					? "text-primary"
					: scanned_qty > 0
						? "text-warning"
						: "text-muted";

		const status_icon =
			scanned_qty >= required_qty
				? "✅"
				: is_current_item
					? "🔵"
					: scanned_qty > 0
						? "⏳"
						: "○";

		items_table += `
         <tr ${is_current_item ? 'class="table-primary"' : ""}>
            <td class="${status_class}">${status_icon}</td>
            <td>${item.item_code}</td>
            <td>${item_detail.item_name || ""}</td>
            <td>${item.batch_no ? "Batch: " + item.batch_no.split("\n").join(", ") : "No Batch"
			}</td>
            <td>${required_qty}</td>
            <td class="${status_class}"><b>${scanned_qty}</b></td>
            <td>${remaining_qty}</td>
            <td>${is_current_item ? '<i class="fa fa-camera text-primary"></i> Ready to scan...' : ""
			}</td>
         </tr>
      `;
	});

	const html = `
      <div class="text-center">
         <div class="alert ${all_complete ? "alert-success" : "alert-info"}">
            <h4>
               <i class="fa fa-${all_complete ? "check-circle" : "qrcode"}"></i>
               ${verification_type === "source" ? "Source" : "Target"} Items Scanning
            </h4>
            <p><b>Warehouse:</b> ${warehouse}</p>
            <p><b>Progress:</b> ${total_scanned_qty} of ${total_required_qty} units scanned</p>
            <div class="progress" style="height: 20px; margin: 10px 0;">
               <div class="progress-bar progress-bar-striped ${all_complete ? "" : "progress-bar-animated"
		}" 
                    style="width: ${progress_percent}%">
                  ${progress_percent}%
               </div>
            </div>
            ${all_complete
			? `<p class="mb-0"><i class="fa fa-check"></i> All items scanned! Click "Complete & Proceed" below.</p>`
			: `<p class="mb-0"><i class="fa fa-info-circle"></i> Click "Start Scanning" to scan next quantity.</p>`
		}
         </div>
         
         <div class="table-responsive" style="max-height: 300px; overflow-y: auto;">
            <table class="table table-bordered table-sm">
               <thead>
                  <tr>
                     <th width="50px">Status</th>
                     <th>Item Code</th>
                     <th>Item Name</th>
                     <th>Batch Info</th>
                     <th>Required Qty</th>
                     <th>Scanned Qty</th>
                     <th>Remaining</th>
                     <th>Action</th>
                  </tr>
               </thead>
               <tbody>
                  ${items_table}
               </tbody>
            </table>
         </div>
      </div>
   `;

	dialog.fields_dict.progress_html.$wrapper.html(html);
}

// ----------------------------
// SCAN ONCE WITH TOTAL QTY (FIXED VERSION)
// ----------------------------
async function scan_once_with_total_qty(frm, verification_type) {
	console.log("Starting scan_once_with_total_qty for", verification_type);

	return new Promise(async (resolve) => {
		try {
			const items = frm.doc.items;
			const warehouse = resolve_warehouse(frm, verification_type);
				//const warehouse  = verification_type === "source" ? frm.doc.from_warehouse : frm.doc.to_warehouse;

			// Calculate total quantity
			const total_quantity = items.reduce((sum, item) => sum + flt(item.qty), 0);

			console.log("Total quantity:", total_quantity, "for warehouse:", warehouse);

			// Get item details FIRST, before creating the dialog
			const item_details = await get_item_details(items.map((item) => item.item_code));
			console.log("Item details loaded:", Object.keys(item_details).length, "items");

			// Create instruction dialog
			const instruction_dialog = new frappe.ui.Dialog({
				title: __(
					`${verification_type === "source" ? "Source" : "Target"} - Scan Reference Item`
				),
				fields: [
					{
						fieldname: "instruction_html",
						fieldtype: "HTML",
						options: `
                     <div class="text-center">
                        <div class="alert alert-info">
                           <i class="fa fa-camera fa-2x"></i>
                           <h4>Scan One Reference Item for ${warehouse}</h4>
                           <p>Scan any one item from the list below as reference</p>
                           <p><b>Warehouse:</b> ${warehouse}</p>
                           <p><b>Total Items:</b> ${items.length}</p>
                           <p><b>Total Quantity:</b> ${total_quantity}</p>
                        </div>
                        
                        <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                           <table class="table table-bordered table-sm">
                              <thead>
                                 <tr>
                                    <th>Item Code</th>
                                    <th>Item Name</th>
                                    <th>Quantity</th>
                                 </tr>
                              </thead>
                              <tbody>
                                 ${items
								.map((item) => {
									const detail = item_details[item.item_code] || {};
									return `
                                       <tr>
                                          <td>${item.item_code}</td>
                                          <td>${detail.item_name || ""}</td>
                                          <td>${item.qty}</td>
                                       </tr>
                                    `;
								})
								.join("")}
                              </tbody>
                           </table>
                        </div>
                     </div>
                  `,
					},
				],
				primary_action_label: __("Open Scanner"),
				primary_action: function () {
					instruction_dialog.hide();
					open_single_scanner_for_total_qty(
						items,
						item_details,
						total_quantity,
						resolve,
						verification_type,
						warehouse
					);
				},
				secondary_action_label: __("Cancel"),
				secondary_action: function () {
					instruction_dialog.hide();
					resolve(false);
				},
			});

			instruction_dialog.show();
		} catch (error) {
			console.error("Scan once with total qty error:", error);
			frappe.show_alert({
				message: __("❌ Error loading item details. Please try again."),
				indicator: "red",
			});
			resolve(false);
		}
	});
}

// ----------------------------
// OPEN SINGLE SCANNER FOR TOTAL QTY (FIXED)
// ----------------------------
// ----------------------------
// OPEN SINGLE SCANNER FOR TOTAL QTY (COMPLETELY REWRITTEN TO FIX THE ISSUE)
// ----------------------------
function open_single_scanner_for_total_qty(
	items,
	item_details,
	total_quantity,
	resolve_callback,
	verification_type,
	warehouse
) {
	console.log("Opening scanner for total quantity verification");

	let scanner_completed = false;

	const scanner = new frappe.ui.Scanner({
		dialog: true,
		multiple: false,
		on_scan: function (data) {
			console.log("Scanner on_scan triggered");

			const text = data.decodedText;
			const scanned_item = extract(text, "ITEM:");

			console.log("Scanned QR code text:", text);
			console.log("Extracted item:", scanned_item);

			if (!scanned_item) {
				frappe.show_alert({
					message: __("❌ No valid item QR code detected."),
					indicator: "red",
				});
				return;
			}

			// Check if scanned item is in our items list
			const item_index = items.findIndex((item) => item.item_code === scanned_item);
			console.log("Item found at index:", item_index);

			if (item_index === -1) {
				frappe.show_alert({
					message: __(`❌ Item ${scanned_item} not in the transfer list.`),
					indicator: "red",
				});
				return;
			}

			const item_detail = item_details[scanned_item] || {};
			console.log("Item detail:", item_detail);

			// Mark as completed
			scanner_completed = true;

			// Stop the scanner FIRST
			try {
				if (scanner.stop_scan) {
					scanner.stop_scan();
				}
			} catch (error) {
				console.warn("Error stopping scanner:", error);
			}

			// Close scanner dialog with delay to avoid state conflict
			setTimeout(() => {
				try {
					if (scanner.dialog && scanner.dialog.hide) {
						scanner.dialog.hide();
					}
				} catch (error) {
					console.warn("Error hiding scanner dialog:", error);
				}

				// Show quantity confirmation dialog
				setTimeout(() => {
					confirm_total_quantity(
						total_quantity,
						scanned_item,
						item_detail.item_name,
						resolve_callback,
						verification_type,
						warehouse
					);
				}, 100);
			}, 100);
		},
	});

	// Store the dialog reference
	const scanner_dialog = scanner.dialog;

	// Handle scanner dialog close - only reject if not completed
	if (scanner_dialog) {
		const originalOnHide = scanner_dialog.onhide;
		scanner_dialog.onhide = function () {
			console.log("Scanner dialog onhide triggered, completed:", scanner_completed);

			if (!scanner_completed) {
				console.log("Scanner closed without successful scan");
				// Only call resolve_callback if it hasn't been called yet
				// Use setTimeout to ensure it's called after any pending operations
				setTimeout(() => {
					resolve_callback(false);
				}, 100);
			}

			// Call original onhide if it exists
			if (originalOnHide) {
				originalOnHide.call(this);
			}
		};
	}

	// Show instruction
	setTimeout(() => {
		frappe.show_alert({
			message: __("📷 Please scan any one item QR code"),
			indicator: "blue",
			duration: 3,
		});
	}, 500);
}

// ----------------------------
// CONFIRM TOTAL QUANTITY (IMPROVED VERSION)
// ----------------------------
function confirm_total_quantity(
	total_quantity,
	item_code,
	item_name,
	resolve_callback,
	verification_type,
	warehouse
) {
	console.log("Showing quantity confirmation dialog");

	// Create a custom dialog
	const confirm_dialog = new frappe.ui.Dialog({
		title: __(`Confirm Total Quantity for ${warehouse}`),
		fields: [
			{
				fieldname: "total_qty",
				label: __("Total Quantity"),
				fieldtype: "Float",
				reqd: 1,
				default: total_quantity,
				description: `Warehouse: ${warehouse}<br>Reference item: ${item_name || item_code
					}<br>Expected total: ${total_quantity}`,
			},
			{
				fieldname: "verification_notes",
				label: __("Verification Notes"),
				fieldtype: "Small Text",
				placeholder: "Optional notes about the verification...",
			},
		],
		primary_action_label: __("Confirm"),
		primary_action: function (values) {
			console.log("User entered quantity:", values.total_qty, "Expected:", total_quantity);

			// Hide dialog first
			try {
				confirm_dialog.hide();
			} catch (error) {
				console.warn("Error hiding confirmation dialog:", error);
			}

			if (Math.abs(flt(values.total_qty) - flt(total_quantity)) <= 0.01) {
				frappe.show_alert({
					message: __(`✅ Total quantity confirmed successfully for ${warehouse}!`),
					indicator: "green",
				});
				// Use setTimeout to ensure dialog is fully closed
				setTimeout(() => {
					resolve_callback(true);
				}, 100);
			} else {
				// Show mismatch confirmation
				frappe.confirm(
					`<div class="alert alert-warning text-center">
                  <i class="fa fa-exclamation-triangle fa-2x"></i>
                  <h4>Quantity Mismatch for ${warehouse}!</h4>
                  <p><b>Expected Total:</b> ${total_quantity}</p>
                  <p><b>Entered Total:</b> ${values.total_qty}</p>
                  <p class="text-muted">Do you want to proceed with this quantity?</p>
               </div>`,
					function () {
						frappe.show_alert({
							message: __(`⚠️ Proceeding with quantity mismatch for ${warehouse}`),
							indicator: "orange",
						});
						setTimeout(() => {
							resolve_callback(true);
						}, 100);
					},
					function () {
						frappe.show_alert({
							message: __(`Please enter correct quantity for ${warehouse}`),
							indicator: "blue",
						});
						// Reopen confirmation dialog with delay
						setTimeout(() => {
							confirm_total_quantity(
								total_quantity,
								item_code,
								item_name,
								resolve_callback,
								verification_type,
								warehouse
							);
						}, 500);
					}
				);
			}
		},
		secondary_action_label: __("Cancel"),
		secondary_action: function () {
			try {
				confirm_dialog.hide();
			} catch (error) {
				console.warn("Error hiding confirmation dialog on cancel:", error);
			}
			console.log("User cancelled quantity confirmation");
			setTimeout(() => {
				resolve_callback(false);
			}, 100);
		},
	});

	// Show dialog with slight delay to avoid conflicts
	setTimeout(() => {
		confirm_dialog.show();
	}, 100);
}

// ----------------------------
// MANUAL QUANTITY ENTRY (FIXED)
// ----------------------------
async function manual_quantity_entry(frm, verification_type) {
	console.log("Starting manual_quantity_entry for", verification_type);

	return new Promise(async (resolve) => {
		try {
			const items = frm.doc.items;
			// const warehouse =
			// 	verification_type === "source" ? frm.doc.from_warehouse : frm.doc.to_warehouse;
                const warehouse = resolve_warehouse(frm, verification_type);

			// Get item details FIRST
			const item_details = await get_item_details(items.map((item) => item.item_code));
			console.log("Item details loaded for manual entry:", Object.keys(item_details).length);

			// Create fields for each item quantity
			const fields = items.map((item, index) => {
				const detail = item_details[item.item_code] || {};
				return {
					fieldname: `qty_${item.item_code}`,
					label: `${item.item_code} - ${detail.item_name || ""}`,
					fieldtype: "Float",
					default: item.qty,
					description: `Required: ${item.qty}`,
					reqd: 1,
				};
			});

			// Add verification notes field
			fields.push({
				fieldname: "verification_notes",
				label: __("Verification Notes"),
				fieldtype: "Small Text",
				placeholder: "Optional notes about the manual verification...",
			});

			frappe.prompt(
				fields,
				(values) => {
					let all_correct = true;
					let verification_table = "";

					items.forEach((item) => {
						const entered_qty = flt(values[`qty_${item.item_code}`]);
						const required_qty = flt(item.qty);
						const is_correct = Math.abs(entered_qty - required_qty) <= 0.01;

						if (!is_correct) all_correct = false;

						verification_table += `
                  <tr>
                     <td>${item.item_code}</td>
                     <td>${required_qty}</td>
                     <td>${entered_qty}</td>
                     <td class="${is_correct ? "text-success" : "text-danger"}">
                        ${is_correct ? "✅" : "❌"}
                     </td>
                  </tr>
               `;
					});

					if (all_correct) {
						frappe.show_alert({
							message: __(`✅ All quantities confirmed correctly for ${warehouse}!`),
							indicator: "green",
						});
						resolve(true);
					} else {
						frappe.confirm(
							`<div class="alert alert-warning">
                     <h4><i class="fa fa-exclamation-triangle"></i> Quantity Mismatch for ${warehouse}</h4>
                     <p>Some entered quantities don't match required quantities.</p>
                     <div class="table-responsive" style="max-height: 300px; overflow-y: auto;">
                        <table class="table table-bordered table-sm">
                           <thead>
                              <tr>
                                 <th>Item Code</th>
                                 <th>Required Qty</th>
                                 <th>Entered Qty</th>
                                 <th>Match</th>
                              </tr>
                           </thead>
                           <tbody>
                              ${verification_table}
                           </tbody>
                        </table>
                     </div>
                     <p class="text-muted">Do you want to proceed anyway?</p>
                  </div>`,
							function () {
								frappe.show_alert({
									message: __(
										`⚠️ Proceeding with quantity mismatch for ${warehouse}`
									),
									indicator: "orange",
								});
								resolve(true);
							},
							function () {
								frappe.show_alert({
									message: __(`Please correct the quantities for ${warehouse}`),
									indicator: "blue",
								});
								// Reopen manual entry
								manual_quantity_entry(frm, verification_type).then(resolve);
							}
						);
					}
				},
				__(
					`${verification_type === "source" ? "Source" : "Target"
					} - Manual Quantity Entry for ${warehouse}`
				),
				__("Confirm")
			);
		} catch (error) {
			console.error("Manual quantity entry error:", error);
			frappe.show_alert({
				message: __("❌ Error in manual quantity entry. Please try again."),
				indicator: "red",
			});
			resolve(false);
		}
	});
}

// ----------------------------
// HELPER FUNCTIONS
// ----------------------------
function get_next_item_to_scan(items, scanned_items, current_state) {
	// First, find the current item and see if it still needs scanning
	if (current_state.item_index >= 0 && current_state.current_item) {
		const current_item = items[current_state.item_index];
		const scanned_qty = get_scanned_quantity_for_item(scanned_items, current_item);

		if (scanned_qty < flt(current_item.qty)) {
			// Current item still needs scanning
			return {
				item_index: current_state.item_index,
				batch_index: current_state.batch_index,
				batch_no: current_state.current_batch,
				remaining_qty: flt(current_item.qty) - scanned_qty,
			};
		}
	}

	// If current item is complete, find next item that needs scanning
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		const scanned_qty = get_scanned_quantity_for_item(scanned_items, item);
		const required_qty = flt(item.qty);

		if (scanned_qty < required_qty) {
			// This item needs scanning
			if (item.batch_no) {
				// For batched items, find which batch needs scanning
				const batches = item.batch_no.split("\n").filter((b) => b.trim());
				for (let j = 0; j < batches.length; j++) {
					const batch = batches[j].trim();
					const key = `${item.item_code}_${batch}`;
					const batch_scanned = scanned_items.get(key) || 0;

					if (batch_scanned < 1) {
						return {
							item_index: i,
							batch_index: j,
							batch_no: batch,
							remaining_qty: 1,
						};
					}
				}
			} else {
				// For non-batched items
				return {
					item_index: i,
					batch_index: 0,
					batch_no: null,
					remaining_qty: required_qty - scanned_qty,
				};
			}
		}
	}
	return null; // All items scanned
}

function get_scanned_quantity_for_item(scanned_items, item) {
	return Array.from(scanned_items.entries())
		.filter(([key]) => key.startsWith(item.item_code))
		.reduce((sum, [, qty]) => sum + qty, 0);
}

function check_all_items_complete(items, scanned_items) {
	for (const item of items) {
		const scanned_qty = get_scanned_quantity_for_item(scanned_items, item);

		if (scanned_qty < flt(item.qty)) {
			return false;
		}
	}
	return true;
}

// ----------------------------
// GET ITEM DETAILS (FIXED)
// ----------------------------
async function get_item_details(item_codes) {
	console.log("Getting item details for:", item_codes);

	try {
		if (!item_codes || item_codes.length === 0) {
			console.log("No item codes provided");
			return {};
		}

		const result = await frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Item",
				filters: { name: ["in", item_codes] },
				fields: ["item_code", "item_name"],
				limit_page_length: 1000,
			},
			freeze: true,
			freeze_message: __("Loading item details..."),
		});

		console.log("Item details result:", result);

		const details = {};
		if (result.message && Array.isArray(result.message)) {
			result.message.forEach((item) => {
				details[item.item_code] = {
					item_name: item.item_name,
				};
			});
		}

		console.log("Processed item details:", details);
		return details;
	} catch (error) {
		console.error("Error getting item details:", error);
		return {};
	}
}

// ----------------------------
// SCAN WITH FRAEPE SCANNER
// ----------------------------
function scan_with_instruction(expected_value, title, instruction) {
	return new Promise((resolve) => {
		// Show instruction dialog first
		const instruction_dialog = new frappe.ui.Dialog({
			title: __(title),
			fields: [
				{
					fieldname: "instruction_html",
					fieldtype: "HTML",
					options: `
                  <div class="text-center">
                     <div class="alert alert-info">
                        <i class="fa fa-camera fa-2x"></i>
                        <h4>${instruction}</h4>
                        <p><b>Expected Code:</b> <span style="color: #28a745; font-weight: bold;">${expected_value || "Not set"
						}</span></p>
                     </div>
                     <div class="alert alert-warning">
                        <p><small>Click "Open Camera" to open camera and scan QR code</small></p>
                     </div>
                  </div>
               `,
				},
			],
			primary_action_label: __("Open Camera"),
			primary_action: function () {
				instruction_dialog.hide();
				open_scanner_dialog(expected_value, resolve);
			},
			secondary_action_label: __("Cancel"),
			secondary_action: function () {
				instruction_dialog.hide();
				resolve(false);
			},
		});

		instruction_dialog.show();
	});
}

function open_scanner_dialog(expected_value, resolve) {
	let scan_completed = false;

	const scanner = new frappe.ui.Scanner({
		dialog: true,
		multiple: false,
		on_scan: function (data) {
			const text = data.decodedText;
			const scanned_id = extract(text, "ID:");

			if (!scanned_id) {
				frappe.show_alert({
					message: __(`❌ No valid QR code detected. Please try again.`),
					indicator: "red",
				});
				return;
			}

			if (scanned_id === expected_value) {
				scan_completed = true;
				frappe.show_alert({
					message: __(`✅ Verified Successfully! Matched: ${scanned_id}`),
					indicator: "green",
				});

				setTimeout(() => {
					scanner.stop_scan();
					resolve(true);
				}, 1500);
			} else {
				frappe.show_alert({
					message: __(
						`❌ Does Not Match! Expected: ${expected_value}, Scanned: ${scanned_id}`
					),
					indicator: "red",
				});
			}
		},
	});

	scanner.dialog.onhide = function () {
		if (!scan_completed) {
			resolve(false);
		}
	};
}

function show_final_confirmation() {
	return new Promise((resolve) => {
		frappe.confirm(
			`<div class="text-center">
            <i class="fa fa-check-circle fa-4x text-success"></i>
            <h4 class="text-success">All Verifications Completed!</h4>
            <p>All QR code scans have been verified successfully.</p>
            <p>Your stock entry is ready to be submitted.</p>
            <p>Do you want to proceed with submission?</p>
         </div>`,
			() => resolve(true),
			() => resolve(false)
		);
	});
}

function update_progress(percent, message) {
	const progress_bar = $("#verification_progress");
	if (progress_bar.length) {
		progress_bar.css("width", percent + "%");
		progress_bar.html(`<b>${percent}% Complete</b>`);
	}

	if (message) {
		frappe.show_alert({ message: __(message), indicator: "blue" });
	}
}

function update_step(step_number, status) {
	return new Promise((resolve) => {
		const step_element = $(`#step${step_number}`);
		step_element.removeClass("active completed");
		step_element.addClass(status);
		setTimeout(resolve, 500);
	});
}

function show_friendly_error(message) {
	frappe.msgprint({
		title: __("Verification Incomplete"),
		message: `
         <div class="alert alert-warning text-center">
            <i class="fa fa-exclamation-triangle fa-2x"></i>
            <h4>${message}</h4>
            <p class="text-muted">Your document has not been submitted and remains in draft mode.</p>
            <p class="text-muted">Please complete the verification process to submit.</p>
         </div>
      `,
		indicator: "orange",
	});
}

function extract(text, label) {
	let pattern = new RegExp(label + "\\s*(.*)");
	let match = text.match(pattern);
	return match ? match[1].trim() : "";
}
