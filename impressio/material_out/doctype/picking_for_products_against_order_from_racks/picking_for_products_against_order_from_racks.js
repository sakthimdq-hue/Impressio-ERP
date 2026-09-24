// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Picking For Products against Order From racks", {
// 	refresh(frm) {

// 	},
// });
// Copyright (c) 2025, MDQ and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Picking For Products against Order From racks", {
// 	refresh(frm) {
//         // Set filter for order_no field to only show Submitted Sales Orders
//         frm.set_query("order_no", function() {
//             return {
//                 filters: [
//                     ["docstatus", "=", 1]
//                 ]
//             };
//         });
// 	},
    
//     order_no: function(frm) {
//         if (frm.doc.order_no) {
//             frappe.call({
//                 method: "impressio.material_out.doctype.picking_for_products_against_order_from_racks.picking_for_products_against_order_from_racks.fetch_items",
//                 args: {
//                     order_no: frm.doc.order_no
//                 },
//                 callback: function(r) {
//                     if (r.message) {
//                         frm.clear_table("table");
//                         r.message.forEach(row => {
//                             let child = frm.add_child("table");
//                             child.item_code = row.item_code;
//                             child.product_name = row.product_name;
//                             child.batch_no = row.batch_no;
//                             child.date = row.date;
//                             child.category = row.category;
//                             child.qty = row.qty;
//                         });
//                         frm.refresh_field("table");
//                     }
//                 }
//             });
//         } else {
//             frm.clear_table("table");
//             frm.refresh_field("table");
//         }
//     }
// });

frappe.ui.form.on("Picking For Products against Order From Racks", {
    refresh(frm) {

        if (!frm.is_new()) {

            frm.add_custom_button("Load Pickslip Items", () => {
                frm.trigger("load_items_from_pickslip");
            });

            frm.add_custom_button("Pick All Qty", () => {
                frm.trigger("pick_all_qty");
            });

            frm.add_custom_button("Pick Partial Qty", () => {
                frm.trigger("pick_partial_qty");
            });

            frm.add_custom_button("Proceed to Packing", () => {
                if (!frm.doc.pickslip_no) {
                    frappe.msgprint("Pickslip No is missing!");
                    return;
                }

                frappe.set_route("Form", "Packing Of Orders", {
                    pickslip_no: frm.doc.pickslip_no,
                    order_no: frm.doc.order_no
                });
            });

        }
    },

    load_items_from_pickslip(frm) {
        if (!frm.doc.pickslip_no) {
            frappe.msgprint("Please select Pickslip No.");
            return;
        }

        frappe.call({
            method: "impressio.material_out.doctype.picking_for_products_against_order_from_racks.picking_for_products_against_order_from_racks.fetch_items",
            args: {
                pickslip_no: frm.doc.pickslip_no
            },
            freeze: true,
            freeze_message: "Loading items...",
            callback: function (r) {
                if (r.message) {
                    frm.clear_table("table_tcvs");

                    r.message.forEach(row => {
                        let child = frm.add_child("table_tcvs");
                        child.item_code = row.item_code;
                        child.product_name = row.product_name;
                        child.batch_no = row.batch_no;
                        child.category = row.category;
                        child.qty = row.qty;
                        child.picked_qty = 0;
                    });

                    frm.refresh_field("table_tcvs");
                }
            }
        });
    },

    pick_all_qty(frm) {
        (frm.doc.table_tcvs || []).forEach(row => {
            row.picked_qty = row.qty;
        });
        frm.refresh_field("table_tcvs");
        frappe.msgprint("All quantities marked as picked.");
    },

    pick_partial_qty(frm) {
        frappe.msgprint(
            "Partial picking enabled. Modify the 'Picked Qty' column manually."
        );
    }
});
