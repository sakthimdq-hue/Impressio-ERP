// File: pickslip_generation_against_sales_order_list.js

frappe.listview_settings['Pickslip Generation Against Sales Order'] = {
    onload: function(listview) {
        console.log('List view loaded - Adding workflow buttons');
        
        // -------------------------------------
        // BULK SLIP BUTTON
        // -------------------------------------
        // listview.page.add_inner_button(__('Bulk Slip'), function() {
        //     let selected_docs = listview.get_checked_items();
            
        //     if (selected_docs.length === 0) {
        //         frappe.msgprint({
        //             title: __('No Selection'),
        //             message: __('Please select one or more pickslips using the checkboxes')
        //         });
        //         return;
        //     }
            
        //     generate_combined_bulk_slip(selected_docs);
        // }).addClass('btn-primary');


        // -------------------------------------
        // NEW!! GENERATE STOCK ENTRY BUTTON
        // -------------------------------------
        listview.page.add_inner_button(__('Bulk Slip'), async function() {
            let selected_docs = listview.get_checked_items();

            if (selected_docs.length === 0) {
                frappe.msgprint(__('Please select at least one Pick Slip'));
                return;
            }

            let pickslip_names = selected_docs.map(d => d.name);

            let result = await frappe.call({
                method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.create_material_transfer_from_pickslips",
                args: { pickslip_names , source_warehouse: "Stores - MQA",
            target_warehouse: "Finished Goods - MQA",
            company: "MD quality apps"}
            });

            frappe.msgprint({
                title: __('Stock Entry Created'),
                message: __('Created Stock Entry'),
                indicator: 'green'
            });

            frappe.set_route("Form", "Stock Entry", result.message);
        }).addClass('btn-success');


        // -------------------------------------
        // AUTO ASSIGN FIFO
        // -------------------------------------
        // listview.page.add_inner_button(__('Auto Assign Batches (FIFO)'), function() {
        //     let selected_docs = listview.get_checked_items();
            
        //     if (selected_docs.length === 0) {
        //         frappe.msgprint(__('Please select at least one pickslip'));
        //         return;
        //     }
            
        //     auto_assign_batches(selected_docs);
        // }).addClass('btn-secondary');

        // -------------------------------------
        // WORKFLOW BUTTONS
        // -------------------------------------
        listview.page.add_menu_item(__('Start Picking'), function() {
            let selected_docs = listview.get_checked_items();
            update_workflow_state(selected_docs, 'start_picking');
        });
        
        listview.page.add_menu_item(__('Complete Picking'), function() {
            let selected_docs = listview.get_checked_items();
            update_workflow_state(selected_docs, 'complete_picking');
        });
    },
    
    get_bulk_actions: function() {
        return [
            {
                label: __('Generate Bulk Slip'),
                action: function() {
                    let selected_docs = this.get_checked_items(true);
                    if (selected_docs.length === 0) return;
                    generate_combined_bulk_slip(selected_docs);
                }
            },
            {
                label: __('Generate Stock Entry'),
                action: function() {
                    let selected_docs = this.get_checked_items(true);
                    if (!selected_docs.length) return;
                    let pickslip_names = selected_docs.map(d => d.name);
                    
                    frappe.call({
                        method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.create_material_transfer_from_pickslips",
                        args: { pickslip_names, source_warehouse: "Stores - MQA",
            target_warehouse: "Finished Goods - MQA",
            company: "MD quality apps", }
                    }).then(r => {
                        frappe.msgprint("Stock Entry Created: " + r.message);
                        frappe.set_route("Form", "Stock Entry", r.message);
                    });
                }
            },
            {
                label: __('Auto Assign Batches (FIFO)'),
                action: function() {
                    let selected_docs = this.get_checked_items(true);
                    if (selected_docs.length === 0) return;
                    auto_assign_batches(selected_docs);
                }
            },
            {
                label: __('Start Picking'),
                action: function() {
                    let selected_docs = this.get_checked_items(true);
                    if (selected_docs.length === 0) return;
                    update_workflow_state(selected_docs, 'start_picking');
                }
            },
            {
                label: __('Complete Picking'),
                action: function() {
                    let selected_docs = this.get_checked_items(true);
                    if (selected_docs.length === 0) return;
                    update_workflow_state(selected_docs, 'complete_picking');
                }
            }
        ];
    },
    
    get_indicator: function(doc) {
        const state_colors = {
            "Draft": "orange",
            "Ready for Picking": "blue",
            "Picking In Progress": "yellow",
            "Picking Completed": "green",
            "Cancelled": "red"
        };
        
        if (doc.workflow_state && state_colors[doc.workflow_state]) {
            return [__(doc.workflow_state), state_colors[doc.workflow_state]];
        }
        
        if (doc.docstatus === 0) {
            return [__("Draft"), "orange"];
        } else if (doc.docstatus === 1) {
            return [__("Submitted"), "green"];
        } else if (doc.docstatus === 2) {
            return [__("Cancelled"), "red"];
        }
    }
};


// =========================
// WORKFLOW FUNCTIONS
// =========================
function auto_assign_batches(selected_docs) {
    selected_docs.forEach((doc) => {
        frappe.call({
            method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.auto_assign_batches_fifo",
            args: { doc_name: doc.name },
            callback: function(r) {
                frappe.show_alert({
                    message: __("Batches assigned for {0}", [doc.name]),
                    indicator: 'green'
                });
            }
        });
    });
}

function update_workflow_state(selected_docs, action) {
    selected_docs.forEach((doc) => {
        frappe.call({
            method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order." + action,
            args: { doc_name: doc.name },
            callback: function(r) {
                frappe.show_alert({
                    message: __("Workflow updated for {0}", [doc.name]),
                    indicator: 'green'
                });
                frappe.ui.toolbar.clear_cache();
            }
        });
    });
}


// =========================
// PRINT SLIP FUNCTIONS
// ================

function generate_individual_slips(selected_docs) {
    selected_docs.forEach((doc, index) => {
        setTimeout(() => {
            frappe.call({
                method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.get_individual_slip_html",
                args: { doc_name: doc.name },
                callback: function(r) {
                    if (r.message) {
                        let win = window.open();
                        win.document.write(r.message);
                        win.document.close();
                        setTimeout(() => { win.print(); }, 500);
                    }
                }
            });
        }, index * 1000);
    });
}


// =========================
// FORM SCRIPT
// =========================
frappe.ui.form.on("Pickslip Generation Against Sales Order", {
	refresh(frm) {
        frm.set_query("order_no", function() {
            return {
                filters: [
                    ["Sales Order", "docstatus", "=", 1]
                ]
            };
        });

        if (frm.doc.docstatus === 1) {
            if (frm.doc.workflow_state === "Ready for Picking") {
                frm.add_custom_button(__('Start Picking'), function() {
                    frm.call('start_picking').then(() => frm.reload_doc());
                }).addClass('btn-primary');

                frm.add_custom_button(__('Auto Assign Batches (FIFO)'), function() {
                    frm.call('auto_assign_batches_fifo').then(() => frm.reload_doc());
                }).addClass('btn-secondary');
            }
            
            if (frm.doc.workflow_state === "Picking In Progress") {
                frm.add_custom_button(__('Complete Picking'), function() {
                    frm.call('complete_picking').then(() => frm.reload_doc());
                }).addClass('btn-success');
            }
        }
	},
    
    order_no: function(frm) {
        frappe.call({
            method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.fetch_items",
            args: { order_no: frm.doc.order_no },
            callback: function (r) {
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
                }
            }
        });
    }
});

function generate_combined_bulk_slip(selected_docs) {
    let pickslip_names = selected_docs.map(doc => doc.name);
    
    frappe.call({
        method: "impressio.material_out.doctype.pickslip_generation_against_sales_order.pickslip_generation_against_sales_order.create_material_transfer_from_pickslips",
        args: { 
            pickslip_names: pickslip_names,
            source_warehouse: "Stores - MQA",
            target_warehouse: "Finished Goods - MQA",
            company: "MD quality apps",
            auto_submit: false
        },
        callback: function(r) {
            if (r.message) {
                if (r.message.error) {
                    // Handle error
                    frappe.msgprint({
                        title: __('Error'),
                        message: __('Failed to create Stock Entry: {0}', [r.message.error]),
                        indicator: 'red'
                    });
                } else {
                    // Success - r.message should be the stock entry name
                    frappe.msgprint({
                        title: __('Success'),
                        message: __(`
                            <b>Stock Entry Created Successfully!</b><br><br>
                            <b>Name:</b> <a href="/app/stock-entry/${r.message}" onclick="frappe.set_route('Form', 'Stock Entry', '${r.message}')">${r.message}</a><br>
                            <b>Click the link above to view the Stock Entry</b>
                        `),
                        indicator: 'green'
                    });
                    
                    // Refresh the list view
                    frappe.ui.toolbar.clear_cache();
                }
            }
        },
        error: function(r) {
            frappe.msgprint({
                title: __('Error'),
                message: __('Failed to create Stock Entry: {0}', [r.message || 'Unknown error']),
                indicator: 'red'
            });
        }
    });
}