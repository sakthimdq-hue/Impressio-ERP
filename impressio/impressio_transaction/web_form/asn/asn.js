frappe.call({
   method: "impressio.impressio_transaction.web_form.asn.asn.get_allowed_suppliers_with_pos",
   args: {
      doctype: "Supplier",
      txt: "",
      searchfield: "name",
      start: 0,
      page_len: 20,
      filters: JSON.stringify({
         user: frappe.session.user
      })
   },
   callback: function (response) {
      let data = response.message || {};
      let suppliers = data.suppliers || [];
      let purchase_orders = data.purchase_orders || [];

      // Format supplier options
      let supplier_options = suppliers.map(supplier => ({
         label: supplier.name,
         value: supplier.name
      }));

      frappe.web_form.fields_dict.vendor_code.set_data(supplier_options);


      // Add change event to fetch supplier details
      frappe.web_form.fields_dict.vendor_code.$input.on('change', function () {
         let selected_supplier_code = frappe.web_form.get_value('vendor_code');
         if (selected_supplier_code) {
            frappe.call({
               method: "frappe.client.get_value",
               args: {
                  doctype: "Supplier",
                  filters: { name: selected_supplier_code },
                  fieldname: ["supplier_name"]
               },
               callback: function (response) {
                  if (response.message && response.message.supplier_name) {
                     frappe.web_form.set_value('vendor_name', response.message.supplier_name);
                  }
               }
            });
         } else {
            frappe.web_form.set_value('vendor_name', '');
         }
      });

      // Format PO options (all POs for all allowed suppliers)
      let po_options = purchase_orders.map(po => ({
         label: po.name,
         value: po.name
      }));

      frappe.web_form.fields_dict.po_no.set_data(po_options);

      // Add change event to fetch supplier details
      frappe.web_form.fields_dict.po_no.$input.on('change', function () {
         let selected_po = frappe.web_form.get_value('po_no');
         if (selected_po) {
            frappe.call({
               method: "frappe.client.get",
               args: {
                  doctype: "Purchase Order",
                  name: selected_po
               },
               callback: function (response) {
                  if (response.message) {
                     let po_doc = response.message;

                     frappe.web_form.set_value('po_date', po_doc.transaction_date);

                     if (po_doc.items && po_doc.items.length > 0) {
                        // Clear existing rows first
                        frappe.web_form.set_value('product_table', []);

                        // Add rows with a small delay to ensure DOM is ready
                        po_doc.items.forEach(function (item, index) {
                           setTimeout(function () {
                              // Click the "Add Row" button
                              $('[data-fieldname="product_table"] .grid-add-row').click();

                              // Wait for DOM update then fill data
                              setTimeout(function () {
                                 let rows = $('[data-fieldname="product_table"] .grid-row');
                                 let new_row = rows.last();

                                 // Fill the fields and trigger change events
                                 new_row.find('[data-fieldname="product_code"] input')
                                    .val(item.item_code)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="product_name"] input')
                                    .val(item.item_name)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="po_quantity"] input')
                                    .val(item.qty)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="po_no"] input')
                                    .val(selected_po)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="po_date"] input')
                                    .val(po_doc.transaction_date)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="delivered_qty"] input')
                                    .val(item.received_qty || 0)
                                    .trigger('change');
                                 new_row.find('[data-fieldname="received_qty"] input')
                                    .val(0)
                                    .trigger('change');

                              }, 100);
                           }, index * 200); // Stagger the row creation
                        });

                        // Final refresh after all rows are added
                        setTimeout(function () {
                           frappe.web_form.fields_dict.product_table.refresh();
                           frappe.show_alert({
                              message: __("Added {0} items from PO", [po_doc.items.length]),
                              indicator: 'green'
                           });
                        }, (po_doc.items.length * 200) + 500);
                     }
                  }
               }
            });
         } else {
            frappe.web_form.set_value('po_date', '');
         }
      });
   }
});
