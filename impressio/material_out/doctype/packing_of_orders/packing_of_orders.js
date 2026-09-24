// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

frappe.ui.form.on("Packing Of orders", {
    refresh: function (frm) {
        setup_packing_buttons(frm);
        setup_progress_indicator(frm);
        setup_scan_handler(frm);
        setup_camera_button(frm);

        // Set query filter for pickslip_no to only show submitted pickslips
        frm.set_query("pickslip_no", function () {
            return {
                filters: {
                    "docstatus": 1
                }
            };
        });
    },

    onload: function (frm) {
        if (frm.is_new()) {
            frm.set_value('pickslip_date', frappe.datetime.get_today());
            frm.set_value('packing_status', 'Pending');
        }
    },

    // When Pickslip is selected, fetch items from Pickslip
    pickslip_no: function (frm) {
        if (frm.doc.pickslip_no) {
            frappe.call({
                method: 'impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.fetch_pickslip_items',
                args: {
                    pickslip_name: frm.doc.pickslip_no
                },
                freeze: true,
                freeze_message: __('Fetching items from Pickslip...'),
                callback: function (r) {
                    if (r.message) {
                        // Set Sales Order and Customer from Pickslip
                        frm.set_value('sales_order', r.message.sales_order);
                        frm.set_value('customer_name', r.message.customer_name);

                        // Clear and populate items table
                        frm.clear_table('table');
                        r.message.items.forEach(item => {
                            let row = frm.add_child('table');
                            row.school = item.school;
                            row.product = item.product;
                            row.product_name = item.product_name;
                            row.barcode = item.barcode;
                            row.qty = item.qty;
                            row.rack_no = item.rack_no;
                            row.bin_no = item.bin_no;
                            row.pallet_no = item.pallet_no;
                            row.scan_status = item.scan_status || 'Pending';
                        });
                        frm.refresh_field('table');

                        // Calculate totals
                        frm.set_value('total_items', r.message.items.length);
                        frm.set_value('items_confirmed', 0);
                        frm.set_value('packing_progress', 0);

                        frappe.show_alert({
                            message: __('Items fetched from Pickslip successfully'),
                            indicator: 'green'
                        });
                    }
                }
            });
        }
    },

    // Fallback: When Sales Order is selected directly (without Pickslip)
    sales_order: function (frm) {
        // Only fetch from Sales Order if no Pickslip is selected
        if (frm.doc.sales_order && !frm.doc.pickslip_no) {
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Sales Order',
                    name: frm.doc.sales_order
                },
                callback: function (r) {
                    if (r.message) {
                        frm.set_value('customer_name', r.message.customer);
                    }
                }
            });
        }
    },

    scan_input: function(frm) {
    if (frm.doc.scan_input) {
        process_scan(frm, frm.doc.scan_input);
        frm.set_value('scan_input', '');
    } else {
        open_scanner();
    }
},


    trigger_camera_scan: function (frm) {
        open_qr_scanner(frm);
    },

    calculate_progress: function (frm) {
        if (frm.doc.table && frm.doc.table.length > 0) {
            let confirmed = 0;
            frm.doc.table.forEach(row => {
                if (row.scan_status === 'Confirmed') confirmed++;
            });

            frm.set_value('items_confirmed', confirmed);
            frm.set_value('total_items', frm.doc.table.length);
            frm.set_value('packing_progress', Math.round((confirmed / frm.doc.table.length) * 100));
        }
    }
});

// Child table events
frappe.ui.form.on('Packing Of orders Table', {
    barcode: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.barcode && row.scan_status !== 'Confirmed') {
            frappe.model.set_value(cdt, cdn, 'scan_status', 'Confirmed');
            frm.trigger('calculate_progress');
        }
    }
});

function setup_packing_buttons(frm) {
    if (!frm.is_new() && frm.doc.docstatus === 0) {
        frm.add_custom_button(__('Confirm All Items'), function () {
            confirm_all_items(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Reset All Scans'), function () {
            reset_all_scans(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Start QR Verification'), function () {
            start_qr_verification_process(frm);
        }, __('Actions'));

        frm.add_custom_button(__('Quick Scan'), function () {
            open_quick_scan_dialog(frm);
        }, __('Actions'));
    }

    // if (frm.doc.packing_status === 'Completed' && frm.doc.docstatus === 1) {
    //     frm.add_custom_button(__('Create Dispatch Order'), function () {
    //         create_dispatch_from_packing(frm);
    //     }, __('Actions'));
    // }
}

function setup_progress_indicator(frm) {
    if (frm.doc.packing_progress !== undefined) {
        let progress = frm.doc.packing_progress || 0;
        let color = progress < 50 ? 'red' : (progress < 100 ? 'orange' : 'green');

        frm.dashboard.add_progress(__('Packing Progress'), [
            {
                title: __('Confirmed'),
                width: `${progress}%`,
                progress_class: `progress-bar-${color}`
            }
        ]);
    }
}

function setup_scan_handler(frm) {
    // Listen for barcode scanner input (Enter key)
    $(document).off('keypress.packing_scan').on('keypress.packing_scan', function (e) {
        // Check if focus is on scan_input field and Enter is pressed
        if (e.which === 13 && document.activeElement.name === 'scan_input') {
            if (frm.doc.scan_input && frm.doc.scan_input.trim() !== '') {
                process_scan(frm, frm.doc.scan_input.trim());
                frm.set_value('scan_input', '');
            }
        }
    });
}

function setup_camera_button(frm) {
    // Update the scan button HTML
    let button_html = `
        <div style="display: flex; gap: 10px; margin-top: 10px;">
            <button class="btn btn-primary btn-sm" onclick="cur_frm.trigger('trigger_camera_scan')">
                <i class="fa fa-camera"></i> ${__('Scan QR Code')}
            </button>
            
        </div>
    `;

    frm.get_field('scan_button_html').$wrapper.html(button_html);
}

// ----------------------------
// QR CODE SCANNING FUNCTIONS
// ----------------------------

function open_qr_scanner(frm) {
    const scanner = new frappe.ui.Scanner({
        dialog: true,
        multiple: false,
        title: __('Scan QR Code'),
        on_scan: function (data) {
            const scanned_data = data.decodedText;
            scanner.stop_scan();

            if (scanned_data) {
                process_scan(frm, scanned_data);
            } else {
                frappe.show_alert({
                    message: __('No QR code detected. Please try again.'),
                    indicator: 'red'
                });
            }
        },
        on_error: function (error) {
            frappe.show_alert({
                message: __('Scanner error: ') + error.message,
                indicator: 'red'
            });
        }
    });

    // Show instruction
    setTimeout(() => {
        frappe.show_alert({
            message: __('Point camera at QR code to scan'),
            indicator: 'blue',
            duration: 3
        });
    }, 5000);
}
function open_scanner(expected_item_code) {
    return new Promise((resolve) => {
        let scan_completed = false;

        const scanner = new frappe.ui.Scanner({
            dialog: true,
            multiple: false,
            title: __("Scan Item QR"),
            on_scan: function (data) {
                const text = data.decodedText;
                const scanned_item = extract(text, "ITEM:");

                if (!scanned_item) {
                    frappe.show_alert({
                        message: __("❌ Invalid QR. ITEM code not found."),
                        indicator: "red",
                    });
                    return;
                }

                if (scanned_item !== expected_item_code) {
                    frappe.show_alert({
                        message: __(
                            `❌ Wrong Item. Expected: ${expected_item_code}, Scanned: ${scanned_item}`
                        ),
                        indicator: "red",
                    });
                    return;
                }

                // ✅ SUCCESS
                scan_completed = true;

                frappe.show_alert({
                    message: __(`✅ Item Verified: ${scanned_item}`),
                    indicator: "green",
                });

                setTimeout(() => {
                    scanner.stop_scan();
                    resolve(true);
                }, 500);
            },
        });

        // If user closes scanner without scan
        scanner.dialog.onhide = function () {
            if (!scan_completed) {
                resolve(false);
            }
        };
    });
}

function process_scan(frm, scan_data) {
    if (!scan_data || scan_data.trim() === '') {
        frappe.show_alert({
            message: __('Please scan a valid QR code'),
            indicator: 'red'
        });
        return;
    }

    frappe.call({
        method: 'impressio.material_out.doctype.packing_of_orders.packing_of_orders.confirm_packing_item',
        args: {
            docname: frm.doc.name,
            barcode_or_qr: scan_data
        },
        freeze: true,
        freeze_message: __('Verifying scan...'),
        callback: function (r) {
            if (r.message) {
                if (r.message.success) {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'green'
                    });

                    // Update progress display
                    if (r.message.progress) {
                        update_scan_progress(r.message.progress);
                    }

                    // Reload the form to show updated status
                    frm.reload_doc();
                } else {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'red'
                    });
                }
            }
        },
        error: function (err) {
            console.error('Scan error:', err);
            frappe.show_alert({
                message: __('Error processing scan. Please try again.'),
                indicator: 'red'
            });
        }
    });
}

function start_qr_verification_process(frm) {
    if (!frm.doc.table || frm.doc.table.length === 0) {
        frappe.msgprint({
            title: __('No Items'),
            message: __('Please add items to the packing list first'),
            indicator: 'red'
        });
        return;
    }

    // Get pending items
    const pending_items = frm.doc.table.filter(item =>
        item.scan_status !== 'Confirmed'
    );

    if (pending_items.length === 0) {
        frappe.msgprint({
            title: __('All Items Confirmed'),
            message: __('All items are already confirmed!'),
            indicator: 'green'
        });
        return;
    }

    const progress_dialog = new frappe.ui.Dialog({
        title: __('QR Code Verification'),
        fields: [
            {
                fieldname: "progress_html",
                fieldtype: "HTML",
            },
        ],
        primary_action_label: __('Scan Next Item'),
        primary_action: function () {
            scan_next_item(frm, progress_dialog, pending_items);
        },
        secondary_action_label: __('Finish'),
        secondary_action: function () {
            progress_dialog.hide();
            frappe.show_alert({
                message: __('Verification process completed'),
                indicator: 'blue'
            });
        },
    });

    update_verification_progress_ui(progress_dialog, frm, pending_items);
    progress_dialog.show();
}

function scan_next_item(frm, dialog, pending_items) {
    if (pending_items.length === 0) {
        frappe.show_alert({
            message: __('All items have been scanned!'),
            indicator: 'green'
        });
        dialog.hide();
        return;
    }

    const next_item = pending_items[0];
    const product_name = next_item.product_name || next_item.product;

    const scanner = new frappe.ui.Scanner({
        dialog: true,
        multiple: false,
        title: __('Scan: ') + product_name,
        on_scan: function (data) {
            const scanned_data = data.decodedText;
            scanner.stop_scan();

            if (scanned_data) {
                process_scan_with_feedback(frm, scanned_data, next_item, pending_items, dialog);
            } else {
                frappe.show_alert({
                    message: __('No QR code detected. Please try again.'),
                    indicator: 'red'
                });
            }
        }
    });

    // Show instruction
    frappe.show_alert({
        message: __('Please scan item: ') + product_name,
        indicator: 'blue',
        duration: 3
    });
}

function process_scan_with_feedback(frm, scan_data, expected_item, pending_items, dialog) {
    frappe.call({
        method: 'impressio.material_out.doctype.packing_of_orders.packing_of_orders.confirm_packing_item',
        args: {
            docname: frm.doc.name,
            barcode_or_qr: scan_data
        },
        freeze: true,
        freeze_message: __('Verifying scan...'),
        callback: function (r) {
            if (r.message) {
                if (r.message.success) {
                    // Remove scanned item from pending list
                    const index = pending_items.findIndex(item =>
                        item.name === expected_item.name
                    );
                    if (index > -1) {
                        pending_items.splice(index, 1);
                    }

                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'green'
                    });

                    // Update UI
                    update_verification_progress_ui(dialog, frm, pending_items);

                    // If all done, auto-close after delay
                    if (pending_items.length === 0) {
                        setTimeout(() => {
                            dialog.hide();
                            frappe.show_alert({
                                message: __('All items verified successfully!'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }, 1000);
                    }
                } else {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'red'
                    });
                }
            }
        }
    });
}

function update_verification_progress_ui(dialog, frm, pending_items) {
    if (!dialog || !dialog.fields_dict.progress_html) return;

    const total_items = frm.doc.table.length;
    const confirmed_items = total_items - pending_items.length;
    const progress_percent = Math.round((confirmed_items / total_items) * 100);

    let items_table = '';
    frm.doc.table.forEach(item => {
        const is_pending = pending_items.some(p => p.name === item.name);
        const status_class = is_pending ? 'text-muted' : 'text-success';
        const status_icon = is_pending ? '○' : '✅';
        const product_name = item.product_name || item.product;

        items_table += `
            <tr ${is_pending ? 'class="table-warning"' : ''}>
                <td class="${status_class}">${status_icon}</td>
                <td>${product_name}</td>
                <td>${item.qty || 0}</td>
                <td>${item.barcode || ''}</td>
                <td class="${status_class}">
                    ${is_pending ? 'Pending' : 'Confirmed'}
                </td>
            </tr>
        `;
    });

    const html = `
        <div class="text-center">
            <div class="alert ${pending_items.length === 0 ? 'alert-success' : 'alert-info'}">
                <h4>
                    <i class="fa fa-${pending_items.length === 0 ? 'check-circle' : 'qrcode'}"></i>
                    Item Scanning Progress
                </h4>
                <p><b>Progress:</b> ${confirmed_items} of ${total_items} items confirmed</p>
                <p><b>Remaining:</b> ${pending_items.length} items to scan</p>
                <div class="progress" style="height: 20px; margin: 10px 0;">
                    <div class="progress-bar progress-bar-striped ${pending_items.length === 0 ? '' : 'progress-bar-animated'}" 
                         style="width: ${progress_percent}%">
                        ${progress_percent}%
                    </div>
                </div>
            </div>
            
            <div class="table-responsive" style="max-height: 300px; overflow-y: auto;">
                <table class="table table-bordered table-sm">
                    <thead>
                        <tr>
                            <th width="50px">Status</th>
                            <th>Product Name</th>
                            <th>Quantity</th>
                            <th>Barcode</th>
                            <th>Scan Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items_table}
                    </tbody>
                </table>
            </div>
            
            ${pending_items.length > 0 ? `
                <div class="alert alert-warning">
                    <i class="fa fa-info-circle"></i>
                    Next item to scan: <b>${pending_items[0].product_name || pending_items[0].product}</b>
                </div>
            ` : ''}
        </div>
    `;

    dialog.fields_dict.progress_html.$wrapper.html(html);
}

function update_scan_progress(progress) {
    // Update any progress indicators if needed
    if (typeof progress !== 'undefined') {
        // You can update UI elements here if needed
    }
}

function open_quick_scan_dialog(frm) {
    frappe.prompt([
        {
            fieldtype: 'Data',
            fieldname: 'barcode',
            label: __('Enter Barcode/QR Code'),
            reqd: 1,
            description: __('Manually enter or paste the scanned code')
        }
    ], function (values) {
        if (values.barcode) {
            process_scan(frm, values.barcode);
        }
    }, __('Quick Scan'), __('Scan'));
}

function confirm_all_items(frm) {
    frappe.confirm(
        __('Are you sure you want to confirm ALL items without scanning?'),
        function () {

            // Prepare clean table data
            let updated_table = frm.doc.table.map(row => {
                return {
                    product: row.product,
                    product_name: row.product_name,
                    barcode: row.barcode,
                    qty: row.qty,
                    scan_status: 'Confirmed'
                };
            });

            frappe.call({
                method: 'impressio.material_out.doctype.packing_of_orders.packing_of_orders.update_packing_table',
                args: {
                    docname: frm.doc.name,
                    table_data: updated_table
                },
                callback: function (r) {
                    if (!r.exc) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('All items confirmed successfully'),
                            indicator: 'green'
                        });
                    }
                }
            });

        }
    );
}

function reset_all_scans(frm) {
    frappe.confirm(
        __('Are you sure you want to reset ALL scan confirmations?'),
        function () {
            frappe.call({
                method: 'frappe.client.set_value',
                args: {
                    doctype: 'Packing Of orders',
                    name: frm.doc.name,
                    fieldname: 'table',
                    value: frm.doc.table.map(row => {
                        return {
                            ...row,
                            scan_status: 'Pending'
                        };
                    })
                },
                callback: function () {
                    frm.reload_doc();
                    frappe.show_alert({
                        message: __('All scans reset to pending'),
                        indicator: 'orange'
                    });
                }
            });
        }
    );
}

function create_dispatch_from_packing(frm) {
    frappe.call({
        method: 'impressio.material_out.doctype.packing_of_orders.packing_of_orders.create_dispatch_from_packing',
        args: {
            packing_name: frm.doc.name
        },
        callback: function (r) {
            if (r.message) {
                frappe.set_route('Form', 'Dispatch Of Orders', r.message);
            }
        }
    });
}