// File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/doctype/handover_to_logistics/handover_to_logistics_list.js

frappe.listview_settings['Handover To Logistics'] = {
    add_fields: ["status", "carrier_status", "logistics_tracking_number", "logistics_partner"],

    get_indicator: function (doc) {
        // Color indicators based on carrier status
        const status_colors = {
            "Pending": "grey",
            "Created": "blue",
            "Picked Up": "green",
            "In Transit": "blue",
            "Out for Delivery": "orange",
            "Delivered": "green",
            "RTO": "red",
            "Exception": "red",
            "Cancelled": "red"
        };

        if (doc.carrier_status) {
            return [doc.carrier_status, status_colors[doc.carrier_status] || "grey",
            "carrier_status,=," + doc.carrier_status];
        }

        return [doc.status, "grey", "status,=," + doc.status];
    },



    formatters: {
        logistics_partner: function (value) {
            const icons = {
                "Ekart": "fa-truck",
                "Amazon Shipping": "fa-amazon",
                "Shiprocket": "fa-rocket"
            };

            if (value && icons[value]) {
                return `<i class="fa ${icons[value]}"></i> ${value}`;
            }
            return value;
        },

        logistics_tracking_number: function (value, doc) {
            if (value) {
                return `<a href="#" onclick="frappe.set_route('Form', 'Handover To Logistics', '${doc.name}'); return false;">
                    <i class="fa fa-barcode"></i> ${value}
                </a>`;
            }
            return '<span class="text-muted">No tracking</span>';
        }
    },

    onload: function (listview) {
        // Add primary button for bulk creation (more visible)
        listview.page.add_inner_button(__('Bulk Create Shipments'), function () {
            bulkCreateShipments(listview);
        }, __('Actions'));

        // Add menu item for bulk creation
        listview.page.add_menu_item(__("Create Bulk Shipments"), function () {
            bulkCreateShipments(listview);
        });

        // Add bulk track option
        listview.page.add_menu_item(__("Bulk Track Shipments"), function () {
            bulkTrackShipments(listview);
        });
        
        // Add bulk download labels option
        listview.page.add_menu_item(__("Bulk Download Labels"), function () {
            bulkDownloadLabels(listview);
        });
    },

    button: {
        show: function(doc) {
            return doc.logistics_tracking_number;
        },
        get_label: function() {
            return __("Track");
        },
        get_description: function(doc) {
            return __("Track this shipment");
        },
        action: function(doc) {
            frappe.call({
                method: "impressio.material_out.api.logistics.utils.track_shipment",
                args: { docname: doc.name },
                freeze: true,
                freeze_message: __("Tracking shipment..."),
                callback: function (r) {
                    if (!r.exc) {
                        frappe.show_alert({
                            message: __("Tracking updated for {0}", [doc.logistics_tracking_number]),
                            indicator: "green"
                        });
                        frappe.set_route("Form", "Handover To Logistics", doc.name);
                    }
                }
            });
        }
    }
};

// ============================================
// HELPER FUNCTIONS FOR BULK OPERATIONS
// ============================================

/**
 * Bulk create shipments for selected documents
 */
function bulkCreateShipments(listview) {
    const selected = listview.get_checked_items();

    if (selected.length === 0) {
        frappe.msgprint(__("Please select documents to create shipments"));
        return;
    }

    // Filter only documents without tracking numbers
    const docs_to_process = selected.filter(doc => !doc.logistics_tracking_number);

    if (docs_to_process.length === 0) {
        frappe.msgprint(__("All selected documents already have tracking numbers"));
        return;
    }

    // Show confirmation with count
    frappe.confirm(
        __("Create shipments for {0} out of {1} selected documents?",
            [docs_to_process.length, selected.length]),
        function () {
            frappe.call({
                method: "impressio.material_out.api.logistics.utils.bulk_create_shipments",
                args: {
                    docnames: docs_to_process.map(doc => doc.name)
                },
                freeze: true,
                freeze_message: __("Creating {0} shipments...", [docs_to_process.length]),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        let success = r.message.success_count || 0;
                        let failed = r.message.failed_count || 0;

                        // Show detailed results
                        let message = '';
                        if (success > 0) {
                            message += `✅ ${success} created successfully<br>`;
                        }
                        if (failed > 0) {
                            message += `❌ ${failed} failed`;
                            
                            // Show failed details if available
                            if (r.message.failed && r.message.failed.length > 0) {
                                message += '<br><br><b>Failed Documents:</b><br>';
                                r.message.failed.forEach(f => {
                                    message += `• ${f.docname}: ${f.error || 'Unknown error'}<br>`;
                                });
                            }
                        }

                        frappe.msgprint({
                            title: __('Bulk Creation Complete'),
                            message: message,
                            indicator: failed > 0 ? 'orange' : 'green'
                        });

                        // Refresh the list view
                        listview.refresh();
                    }
                }
            });
        }
    );
}

/**
 * Bulk track shipments for selected documents
 */
function bulkTrackShipments(listview) {
    const selected = listview.get_checked_items();

    if (selected.length === 0) {
        frappe.msgprint(__("Please select documents to track"));
        return;
    }

    const docs_to_track = selected.filter(doc => doc.logistics_tracking_number);

    if (docs_to_track.length === 0) {
        frappe.msgprint(__("No selected documents have tracking numbers"));
        return;
    }

    frappe.confirm(
        __("Track {0} shipments? This may take a few moments.", [docs_to_track.length]),
        function () {
            frappe.call({
                method: "impressio.material_out.api.logistics.utils.bulk_track_shipments",
                args: {
                    docnames: docs_to_track.map(doc => doc.name)
                },
                freeze: true,
                freeze_message: __("Tracking {0} shipments...", [docs_to_track.length]),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        frappe.show_alert({
                            message: __("Updated {0} shipments", [r.message.count || 0]),
                            indicator: "green"
                        });
                        listview.refresh();
                    }
                }
            });
        }
    );
}

/**
 * Bulk download labels for selected documents
 */
function bulkDownloadLabels(listview) {
    const selected = listview.get_checked_items();

    if (selected.length === 0) {
        frappe.msgprint(__("Please select documents to download labels"));
        return;
    }

    const docs_with_labels = selected.filter(doc => doc.label_url);

    if (docs_with_labels.length === 0) {
        frappe.msgprint(__("No selected documents have labels available"));
        return;
    }

    frappe.confirm(
        __("Download labels for {0} documents?", [docs_with_labels.length]),
        function () {
            // Open each label in a new tab
            docs_with_labels.forEach(doc => {
                if (doc.label_url) {
                    window.open(doc.label_url, '_blank');
                }
            });
            
            frappe.show_alert({
                message: __("Opening {0} labels in new tabs", [docs_with_labels.length]),
                indicator: "green"
            });
        }
    );
}

/**
 * Bulk cancel shipments for selected documents
 */
function bulkCancelShipments(listview) {
    const selected = listview.get_checked_items();

    if (selected.length === 0) {
        frappe.msgprint(__("Please select documents to cancel"));
        return;
    }

    const cancellable_statuses = ['Pending', 'Created', 'Label Generated'];
    const docs_to_cancel = selected.filter(doc => 
        doc.logistics_tracking_number && 
        cancellable_statuses.includes(doc.carrier_status)
    );

    if (docs_to_cancel.length === 0) {
        frappe.msgprint(__("No cancellable shipments selected (only Pending, Created, or Label Generated)"));
        return;
    }

    frappe.confirm(
        __("Are you sure you want to cancel {0} shipments? This action cannot be undone.",
            [docs_to_cancel.length]),
        function () {
            // This would need a bulk_cancel_shipments method in utils.py
            frappe.show_alert({
                message: __("Bulk cancellation not implemented yet"),
                indicator: "orange"
            });
        }
    );
}