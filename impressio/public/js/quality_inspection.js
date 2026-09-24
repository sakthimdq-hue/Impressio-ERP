frappe.ui.form.on("Quality Inspection", {
   refresh: function (frm) {
      if (!frm.doc.__islocal) {
         frm.add_custom_button(__('Create Stock Entry'), function () {
            frappe.set_route("Form", "Stock Entry", "new-stock-entry");
         });
      }
   }
});
