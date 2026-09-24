frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && !frm.doc.handover_created) {
            frm.add_custom_button("Handover to Logistics", () => {
                frappe.call({
                    method: "impressio.overrides.sales_invoice.sales_invoice.create_handover_from_si",
                    args: {
                        sales_invoice: frm.doc.name
                    },
                    freeze: true,
                    callback(r) {
                        if (r.message?.success) {
                            frappe.msgprint({
                                title: "Success",
                                message: "Handover Created: " + r.message.handover,
                                indicator: "green"
                            });
                            frm.reload_doc();
                        }
                    }
                });
            });
        }

        // Optional: Add a button to open existing handover
        // if (frm.doc.handover_created) {
        //     frm.add_custom_button("Open Handover", () => {
        //         // Get the handover document linked to this SI
        //         frappe.db.get_value("Handover To Logistics", 
        //             {"sales_invoice": frm.doc.name}, 
        //             "name", 
        //             (r) => {
        //                 if (r.name) {
        //                     frappe.set_route("Form", "Handover To Logistics", r.name);
        //                 }
        //             }
        //         );
        //     });
        // }
    }
});