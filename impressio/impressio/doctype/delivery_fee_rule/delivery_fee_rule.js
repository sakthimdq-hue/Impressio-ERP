// Copyright (c) 2026, MDQ and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Delivery Fee Rule", {
// 	refresh(frm) {

// 	},
// });


frappe.ui.form.on('Delivery Fee Rule', {
    form_render(frm, cdt, cdn) {
        frm.fields_dict.delivery_fee_rules.grid.get_field('item_group').get_query = function() {
            return {
                filters: {
                    parent_item_group: "All Item Groups",
                    is_group: 1
                }
            };
        };
    }
});