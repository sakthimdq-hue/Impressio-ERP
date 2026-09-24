frappe.ui.form.on('Order Processing Against Website Orders', {
    refresh: function(frm) {
        // Add custom buttons
        frm.add_custom_button(__('Create Sales Order'), function() {
            frm.trigger('create_sales_order');
        });
        
        frm.add_custom_button(__('Add Row'), function() {
            let child = frm.add_child('table');
            child.date = frm.doc.date || frappe.datetime.get_today();
            frm.refresh_field('table');
        });
    },
    
    // FILTER METHODS
    show_0_to_50_orders: function(frm) {
        frappe.call({
            method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.get_0_to_50_completed_orders",
            callback: function(r) {
                if (r.message) {
                    show_completion_results(r.message, "0-50% Completed Orders");
                }
            }
        });
    },

    show_50_to_100_orders: function(frm) {
        frappe.call({
            method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.get_50_to_100_completed_orders",
            callback: function(r) {
                if (r.message) {
                    show_completion_results(r.message, "50-100% Completed Orders");
                }
            }
        });
    },

    show_fully_completed_orders: function(frm) {
        frappe.call({
            method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.get_fully_completed_orders",
            callback: function(r) {
                if (r.message) {
                    show_completion_results(r.message, "Fully Completed Orders (100%)");
                }
            }
        });
    },
    
    // MAIN FUNCTION — FETCH ORDER + AUTO CALCULATE COMPLETION %
    order_no: function(frm) {
        console.log('Order No changed to:', frm.doc.order_no);
        
        if (frm.doc.order_no) {
            frappe.call({
                method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.fetch_order_details_and_items",
                args: {
                    order_no: frm.doc.order_no
                },
                callback: function(r) {
                    console.log('Fetch order details response:', r);
                    
                    if (r.message) {
                        let data = r.message;
                        
                        // Update main fields
                        frm.set_value('customer_name', data.customer_name);
                        frm.set_value('date', data.date);

                        // ---- AUTO CALCULATE COMPLETION % ----
                        let ordered_qty = 0;
                        let delivered_qty = 0;

                        if (data.items && data.items.length > 0) {
                            data.items.forEach(item => {
                                ordered_qty += item.qty || 0;
                                delivered_qty += item.delivered_qty || 0;
                            });
                        }

                        let percentage = 0;
                        if (ordered_qty > 0) {
                            percentage = (delivered_qty / ordered_qty) * 100;
                        }

                        frm.set_value("completion_percentage", percentage.toFixed(2));

                        // Update table rows
                        if (data.items && data.items.length > 0) {
                            frm.clear_table("table");
                            
                            data.items.forEach((row) => {
                                let child = frm.add_child("table");
                                child.date = row.date || data.date || frappe.datetime.get_today();
                                child.item_code = row.item_code;
                                child.item_name = row.item_name;
                                child.qty = row.qty;
                            child.delivered_qty = row.delivered_qty;
                            child.warehouse = row.warehouse;
                                child.batch_no = row.batch_no || '';
                                child.category = row.category;
                                child.qty = row.qty;
                                child.warehouse = row.warehouse || "";
                            });
                            
                            frm.refresh_field("table");
                        }
                        
                        frappe.show_alert({
                            message: __(`Order details fetched successfully!`),
                            indicator: 'green'
                        });
                        
                        frm.save();
                    }
                },
                error: function(err) {
                    console.error('Error fetching order details:', err);
                    frappe.show_alert({
                        message: __("Error fetching order details"),
                        indicator: 'red'
                    });
                }
            });
            
        } else {
            frm.set_value('customer_name', '');
            frm.set_value('date', '');
            frm.set_value('completion_percentage', 0);
            frm.clear_table("table");
            frm.refresh_field("table");
        }
    },
    
    create_sales_order: function(frm) {
        if (!frm.doc.customer_name) {
            frappe.msgprint(__('Please select a customer first'));
            return;
        }
        
        if (!frm.doc.table || frm.doc.table.length === 0) {
            frappe.msgprint(__('Please add items to the table first'));
            return;
        }
        
        frappe.model.open_mapped_doc({
            method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.make_sales_order",
            frm: frm
        });
    }
});

// CHILD TABLE EVENTS
frappe.ui.form.on('Order Processing Against Website Orders Table', {
    item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        if (child.item_code) {
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Item",
                    fieldname: ["item_name", "item_group"],
                    filters: { name: child.item_code }
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, {
                            'item_name': r.message.item_name,
                            'category': r.message.item_group
                        });
                    }
                }
            });
        } else {
            frappe.model.set_value(cdt, cdn, {
                'item_name': '',
                'category': '',
                'batch_no': ''
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        frm.dirty();
    }
});

// SHARED FUNCTIONS
function show_completion_results(orders, title) {
    let dialog = new frappe.ui.Dialog({
        title: title,
        fields: [
            { fieldtype: 'HTML', fieldname: 'results_html' }
        ],
        size: 'large'
    });
    
    let html = `
        <div class="results-container" style="max-height: 400px; overflow-y: auto;">
            <table class="table table-bordered">
                <thead>
                    <tr>
                        <th>${__('Order No')}</th>
                        <th>${__('Customer')}</th>
                        <th>${__('Date')}</th>
                        <th>${__('Completion %')}</th>
                        <th>${__('Status')}</th>
                        <th>${__('Action')}</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    if (orders.length === 0) {
        html += `<tr><td colspan="6" class="text-center">${__('No orders found')}</td></tr>`;
    } else {
        orders.forEach(order => {
            html += `
                <tr>
                    <td>${order.order_no || ''}</td>
                    <td>${order.customer_name || ''}</td>
                    <td>${order.date || ''}</td>
                    <td>${order.completion_percentage || 0}%</td>
                    <td>
                        <span class="indicator ${get_indicator_color(order.completion_status)}">
                            ${order.completion_status || ''}
                        </span>
                    </td>
                    <td>
                        <button class="btn btn-xs btn-primary" 
                            onclick="frappe.set_route('Form', 'Order Processing Against Website Orders', '${order.name}')">
                            ${__('Open')}
                        </button>
                    </td>
                </tr>
            `;
        });
    }
    
    html += `
                </tbody>
            </table>
        </div>
    `;
    
    dialog.fields_dict.results_html.$wrapper.html(html);
    dialog.show();
}

function get_indicator_color(status) {
    const colors = {
        'Fully Completed': 'green',
        '50-100% Completed': 'blue',
        '0-50% Completed': 'orange',
        'Not Started': 'red',
        'Order Not Found': 'red',
        'Error': 'red'
    };
    return colors[status] || 'gray';
}
