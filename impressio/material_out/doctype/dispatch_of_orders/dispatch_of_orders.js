frappe.ui.form.on('Dispatch Of Orders', {
    refresh: function(frm) {
        setup_custom_buttons(frm);
        setup_grid_events(frm);
        apply_custom_formatting(frm);
    },

    dispatch_id: function(frm) {
        if (frm.doc.dispatch_id) {
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Dispatch Of Orders',
                    name: frm.doc.dispatch_id
                },
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('customer_name', r.message.customer_name);
                        frm.set_value('dispatch_date', r.message.dispatch_date);
                    }
                }
            });
        }
    },

    customer_name: function(frm) {
        if (frm.doc.customer_name) {
            frappe.call({
                method: 'impressio.material_out.doctype.dispatch_of_orders.dispatch_of_orders.get_customer_details',
                args: {
                    customer_name: frm.doc.customer_name
                },
                callback: function(r) {
                    if (r.message) {
                        show_customer_info(frm, r.message);
                    }
                }
            });
        }
    },

    dispatch_date: function(frm) {
        validate_dates(frm);
    },

    picking_date: function(frm) {
        validate_dates(frm);
    },

    packing_no: function(frm) {
        if (frm.doc.packing_no && frm.doc.packing_no <= 0) {
            frappe.msgprint(__('Packing Number must be greater than 0'));
            frm.set_value('packing_no', 1);
        }
    },

    before_save: function(frm) {
        return validate_dispatch(frm);
    },

    onload: function(frm) {
        set_default_values(frm);
    }
});

// Child Table Events - ADD THIS SECTION
frappe.ui.form.on('Dispatch Of Orders Table', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code) {
            frappe.call({
                method: 'impressio.material_out.doctype.dispatch_of_orders.dispatch_of_orders.get_item_details',
                args: {
                    item_code: row.item_code
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, {
                            'product_name': r.message.product_name,
                            'category': r.message.category,
                            'rate': r.message.rate
                        });
                        calculate_row_amount(frm, cdt, cdn);
                    }
                }
            });
        }
    },

    qty: function(frm, cdt, cdn) {
        calculate_row_amount(frm, cdt, cdn);
    },

    rate: function(frm, cdt, cdn) {
        calculate_row_amount(frm, cdt, cdn);
    }
});

// Custom Functions
function setup_custom_buttons(frm) {
    frm.add_custom_button(__('Print Dispatch'), function() {
        frappe.msgprint(__('Print functionality would go here'));
    });

    frm.add_custom_button(__('Create Stock Entry'), function() {
        create_stock_entry_from_dispatch(frm);
    });

    frm.page.add_menu_item(__('Duplicate Dispatch'), function() {
        duplicate_dispatch(frm);
    });
}

function setup_grid_events(frm) {
    if (frm.fields_dict.table_ytnc) {
        frm.fields_dict.table_ytnc.grid.wrapper.on('change', function(e) {
            calculate_totals(frm);
        });
    }
}

function validate_dates(frm) {
    if (frm.doc.dispatch_date && frm.doc.picking_date) {
        let dispatch_date = new Date(frm.doc.dispatch_date);
        let picking_date = new Date(frm.doc.picking_date);
        
        if (picking_date < dispatch_date) {
            frappe.msgprint({
                title: __('Date Validation'),
                message: __('Picking Date cannot be before Dispatch Date'),
                indicator: 'red'
            });
            frm.set_value('picking_date', '');
        }
    }
}

function validate_dispatch(frm) {
    let errors = [];
    
    if (!frm.doc.customer_name) {
        errors.push('Customer Name is required');
    }
    
    if (!frm.doc.dispatch_date) {
        errors.push('Dispatch Date is required');
    }
    
    if (!frm.doc.table_ytnc || frm.doc.table_ytnc.length === 0) {
        errors.push('At least one item is required in the table');
    } else {
        // Validate each row
        frm.doc.table_ytnc.forEach((row, index) => {
            if (!row.item_code) {
                errors.push(`Row ${index + 1}: Item Code is required`);
            }
            if (!row.qty || row.qty <= 0) {
                errors.push(`Row ${index + 1}: Quantity must be greater than 0`);
            }
        });
    }
    
    if (errors.length > 0) {
        frappe.msgprint({
            title: __('Validation Errors'),
            message: errors.join('<br>'),
            indicator: 'red'
        });
        return false;
    }
    
    return true;
}

function calculate_row_amount(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let amount = 0;
    
    if (row.qty && row.rate) {
        amount = row.qty * row.rate;
    }
    
    frappe.model.set_value(cdt, cdn, 'amount', amount);
    calculate_totals(frm);
}

function calculate_totals(frm) {
    if (frm.doc.table_ytnc) {
        let total_qty = 0;
        let total_amount = 0;
        
        frm.doc.table_ytnc.forEach(row => {
            total_qty += row.qty || 0;
            total_amount += row.amount || 0;
        });
        
        // Display totals (you can add custom fields for these)
        console.log(`Total Qty: ${total_qty}, Total Amount: ${total_amount}`);
        
        // Optional: Show in alert or custom field
        if (total_amount > 0) {
            frappe.show_alert({
                message: __(`Total Amount: ${format_currency(total_amount)}`),
                indicator: 'blue'
            });
        }
    }
}

function show_customer_info(frm, customer_data) {
    let message = `
        <div>
            <strong>Customer Group:</strong> ${customer_data.customer_group || 'N/A'}<br>
            <strong>Territory:</strong> ${customer_data.territory || 'N/A'}<br>
            <strong>Primary Address:</strong> ${customer_data.customer_primary_address || 'N/A'}
        </div>
    `;
    
    frappe.show_alert({
        message: __('Customer details loaded'),
        indicator: 'green'
    });
}

function create_stock_entry_from_dispatch(frm) {
    frappe.confirm(
        __('Create Stock Entry for this dispatch?'),
        function() {
            frappe.call({
                method: 'impressio.material_out.doctype.dispatch_of_orders.dispatch_of_orders.create_stock_entry',
                args: {
                    dispatch_id: frm.doc.name
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint(__('Stock Entry created: {0}', [r.message]));
                    }
                }
            });
        },
        function() {
            frappe.msgprint(__('Cancelled'));
        }
    );
}

function duplicate_dispatch(frm) {
    frappe.confirm(
        __('Create a duplicate of this dispatch?'),
        function() {
            frappe.set_route('Form', 'Dispatch Of Orders', 'new-dispatch-of-orders-1');
        }
    );
}

function set_default_values(frm) {
    if (frm.is_new()) {
        if (!frm.doc.dispatch_date) {
            frm.set_value('dispatch_date', frappe.datetime.get_today());
        }
        if (!frm.doc.packing_no) {
            frm.set_value('packing_no', 1);
        }
    }
}

function apply_custom_formatting(frm) {
    frm.fields_dict.customer_name.$input.css('border', '2px solid #e8da13');
}