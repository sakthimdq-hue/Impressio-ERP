// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pickslip Generation Against Sales Order", {
	refresh(frm) {
        frm.set_query("order_no", function() {
            return {
                filters: [
                    ["Sales Order", "docstatus", "=", 1]
                ]
            };
        });
        
        // Add buttons only if pickslip is submitted and has items
        if (frm.doc.docstatus === 1 && frm.doc.table_kino && frm.doc.table_kino.length > 0) {
            // Create Material Transfer button
            frm.add_custom_button(__('Create Material Transfer'), function() {
                create_individual_stock_entry(frm);
            }, __('Create'));

            // Create Packing button - NEW
            frm.add_custom_button(__('Create Packing'), function() {
                create_packing_from_pickslip(frm);
            }, __('Create'));
        }
	},
    
    order_no: function(frm) {
        if (frm.doc.order_no) {
            frappe.call({
                method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.fetch_items",
                args: {
                    order_no: frm.doc.order_no
                },
                callback: function(r) {
                    if (r.message) {
                        frm.clear_table("table_kino");
                        r.message.forEach(row => {
                            let child = frm.add_child("table_kino");
                            child.item_code = row.item_code;
                            child.product_name = row.product_name;
                            child.batch_no = row.batch_no;
                            child.category = row.category;
                            child.qty = row.qty;
                        });
                        frm.refresh_field("table_kino");
                        frappe.show_alert({
                            message: __("Items fetched successfully from Sales Order"),
                            indicator: 'green'
                        });
                    }
                }
            });
        }
    }
});

function create_individual_stock_entry(frm) {
    // Show confirmation dialog instead of auto-submit option
    frappe.confirm(
        __('Create Material Transfer from this pickslip?<br><br>The Stock Entry will be created as Draft. You can submit it manually afterwards.'),
        function() {
            // Yes button clicked
            create_stock_entry_process(frm);
        },
        function() {
            // No button clicked - do nothing
        }
    );
}

function create_stock_entry_process(frm) {
    frappe.call({
        method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.create_material_transfer_from_individual_pickslip",
        args: {
            pickslip_name: frm.doc.name,
            submit_stock_entry: true
 // Always false to avoid BrokenPipeError
        },
        freeze: true,
        freeze_message: __('Creating Material Transfer...'),
        callback: function(r) {
            if (r.message && r.message.success) {
                let msg = __('Stock Entry <a href="/app/stock-entry/{0}">{0}</a> has been created successfully as Draft.', 
                    [r.message.stock_entry]);
                
                // Show items processed count
                if (r.message.items_processed > 0) {
                    msg += '<br><br>' + __('Processed {0} items from this pickslip', [r.message.items_processed]);
                }
                
                // Add warnings if any
                if (r.message.warnings && r.message.warnings.length > 0) {
                    msg += '<br><br><strong>' + __('Warnings:') + '</strong><br>' + 
                           r.message.warnings.join('<br>');
                }
                
                // Add note
                if (r.message.note) {
                    msg += '<br><br><strong>' + __('Note:') + '</strong> ' + r.message.note;
                }
                
                frappe.msgprint({
                    title: __('Success'),
                    message: msg,
                    indicator: 'green'
                });
                
                // Refresh the form to show any changes (like comments added)
                frm.reload_doc();
                
                // Open the created Stock Entry
                if (r.message.stock_entry) {
                    setTimeout(() => {
                        frappe.set_route('Form', 'Stock Entry', r.message.stock_entry);
                    }, 1500);
                }
                
            } else if (r.message && r.message.error) {
                frappe.msgprint({
                    title: __('Error'),
                    message: r.message.error,
                    indicator: 'red'
                });
            } else {
                frappe.msgprint({
                    title: __('Error'),
                    message: __('Failed to create Stock Entry. Please try again.'),
                    indicator: 'red'
                });
            }
        },
        error: function(r) {
            frappe.msgprint({
                title: __('Error'),
                message: __('Failed to create Stock Entry: {0}', [r.message]),
                indicator: 'red'
            });
        }
    });
}

function create_packing_from_pickslip(frm) {
    frappe.confirm(
        __('Create Packing document from this Pickslip?<br><br>Items will be pulled from this Pickslip.'),
        function() {
            frappe.call({
                method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.create_packing_from_pickslip",
                args: {
                    pickslip_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __('Creating Packing document...'),
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('Success'),
                            message: __('Packing document <a href="/app/packing-of-orders/{0}">{0}</a> created successfully.', [r.message]),
                            indicator: 'green'
                        });

                        // Refresh form and navigate to Packing
                        frm.reload_doc();
                        setTimeout(() => {
                            frappe.set_route('Form', 'Packing Of orders', r.message);
                        }, 1500);
                    }
                },
                error: function(r) {
                    frappe.msgprint({
                        title: __('Error'),
                        message: __('Failed to create Packing: {0}', [r.message]),
                        indicator: 'red'
                    });
                }
            });
        }
    );
}