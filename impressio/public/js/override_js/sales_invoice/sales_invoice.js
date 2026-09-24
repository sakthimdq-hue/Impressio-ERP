// inventre/overrides/sales_invoice/sales_invoice.js

frappe.ui.form.on("Sales Invoice", {
    refresh: function(frm) {
        // Only show button if invoice is submitted
        if (frm.doc.docstatus === 1 && !frm.doc.dispatch_created) {
            frm.add_custom_button("Create Dispatch", function() {
                frappe.call({
                    method: "impressio.overrides.sales_invoice.sales_invoice.create_dispatch_from_si",
                    args: {
                        sales_invoice: frm.doc.name
                    },
                    callback: function(r) {
                        if(r.message) {
                            frappe.msgprint("Dispatch Created: " + r.message);
                            frm.set_value("dispatch_created", 1);
                            frm.refresh_field("dispatch_created");
                        }
                    }
                });
            });
        }
    }
});
