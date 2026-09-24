frappe.listview_settings['Item'] = {
   onload(listview) {
      listview.page.add_inner_button(__('Upload Books File'), () => {
         new frappe.ui.FileUploader({
            allow_multiple: false,
            on_success(file) {
               frappe.call({
                  method: "impressio.overrides.item.create_bundle_master",
                  args: {
                     file_url: file.file_url
                  },
                  callback(r) {
                     const res = r.message;
                     frappe.msgprint(`
                                <b>Created:</b> ${res.created.length}<br>
                                <b>Skipped (Already Exists):</b> ${res.skipped.length}<br>
                                <b>Errors:</b> ${res.errors.length}
                            `);
                     listview.refresh();
                  }
               });
            }
         });
      });
      listview.page.add_inner_button(__('Upload Uniform File'), () => {
         new frappe.ui.FileUploader({
            allow_multiple: false,
            on_success(file) {
               frappe.call({
                  method: "impressio.overrides.item.create_uniform",
                  args: {
                     file_url: file.file_url
                  },
                  callback(r) {
                     const res = r.message;
                     frappe.msgprint(`
                                <b>Created:</b> ${res.created.length}<br>
                                <b>Skipped (Already Exists):</b> ${res.skipped.length}<br>
                                <b>Errors:</b> ${res.errors.length}
                            `);
                     listview.refresh();
                  }
               });
            }
         });
      });
        // Add Import Products from API button
        if (listview.page && listview.page.inner_toolbar && !listview.page.inner_toolbar.find(`button[data-label="${encodeURIComponent("Import Products from API")}"]`).length) {
           listview.page.add_inner_button(
              __("Import Products from API"),
              function() {
                 impressio_direct_sync_products(listview);
              }
           );
        }

        listview.page.add_inner_button(__('Import Products from API'), function() {
           impressio_direct_sync_products(listview);
        }, __('Actions'));

        // Add bulk disable button
        listview.page.add_inner_button(__('Bulk Disable'), function() {
            bulk_disable_items(listview);
        }, __('Actions'));
        
        // Add bulk enable button (optional)
        listview.page.add_inner_button(__('Bulk Enable'), function() {
            bulk_enable_items(listview);
        }, __('Actions'));
   }
};

function impressio_direct_sync_products(listview) {
	frappe.show_progress(__("Importing Products"), 0, 100, __("Connecting to API..."));

	frappe.call({
		method: "impressio.api.fetch_pricing_from_api",
		callback: function (r) {
			if (!r || !r.message || !r.message.items || r.message.items.length === 0) {
				frappe.hide_progress();
				frappe.msgprint({
					title: __("No Products Found"),
					indicator: "orange",
					message: __("The API returned no products to import.")
				});
				return;
			}

			const items = r.message.items;
			const total = items.length;
			frappe.show_progress(__("Importing Products"), 0, total, __("Found {0} products. Starting sync...", [total]));

			const chunkSize = 5;
			const chunks = [];
			for (let i = 0; i < items.length; i += chunkSize) {
				chunks.push(items.slice(i, i + chunkSize));
			}

			let processedCount = 0;
			let totalCreated = 0;
			let totalUpdated = 0;
			let chunkIndex = 0;

			function processNextChunk() {
				if (chunkIndex >= chunks.length) {
					frappe.show_progress(__("Importing Products"), total, total, __("Sync completed"));
					setTimeout(function () {
						frappe.hide_progress();
						frappe.show_alert({
							message: __("Products Synced: {0} Created, {1} Updated", [totalCreated, totalUpdated]),
							indicator: "green"
						}, 5);
						if (listview) {
							listview.refresh();
						}
					}, 400);
					return;
				}

				const currentChunk = chunks[chunkIndex];
				const firstItem = currentChunk[0];
				const itemLabel = firstItem.product_name || firstItem.item_name || firstItem.item_code || `Product #${firstItem.id}`;
				const categoryLabel = firstItem.category_name || firstItem.item_group || "";

				const currentStatus = categoryLabel
					? __("Importing {0} ({1})... ({2}/{3})", [itemLabel, categoryLabel, processedCount, total])
					: __("Importing {0}... ({1}/{2})", [itemLabel, processedCount, total]);

				frappe.show_progress(__("Importing Products"), processedCount, total, currentStatus);

				frappe.call({
					method: "impressio.api.import_pricing_items",
					args: {
						items_data: currentChunk
					},
					callback: function (res) {
						processedCount += currentChunk.length;
						if (processedCount > total) processedCount = total;

						if (res && res.message) {
							totalCreated += (res.message.created || 0);
							totalUpdated += (res.message.updated || 0);
						}

						frappe.show_progress(__("Importing Products"), processedCount, total, currentStatus);

						chunkIndex++;
						setTimeout(processNextChunk, 60);
					},
					error: function () {
						processedCount += currentChunk.length;
						chunkIndex++;
						setTimeout(processNextChunk, 60);
					}
				});
			}

			processNextChunk();
		},
		error: function () {
			frappe.hide_progress();
			frappe.msgprint({
				title: __("API Connection Failed"),
				indicator: "red",
				message: __("Could not connect to the Products API endpoint.")
			});
		}
	});
}



// In item_list.js
function bulk_disable_items(listview) {
    const selected_items = listview.get_checked_items();
    
    if (selected_items.length === 0) {
        frappe.msgprint(__('Please select items to disable'));
        return;
    }
    
    const item_names = selected_items.map(function(item) {
        return item.name;
    });
    
    frappe.confirm(
        __('Are you sure you want to disable {0} item(s)?', [item_names.length]),
        function() {
            frappe.call({
                method: 'impressio.overrides.item.bulk_update_item_status',
                args: {
                    items: JSON.stringify(item_names),  // ← Stringify the array
                    status: 'Disabled'
                },
                freeze: true,
                freeze_message: __('Disabling {0} items...', [item_names.length]),
                callback: function(r) {
                    if (r.message) {
                        if (r.message.success_count > 0) {
                            frappe.show_alert({
                                message: __('{0} item(s) disabled successfully', [r.message.success_count]),
                                indicator: 'green'
                            });
                        }
                        listview.refresh();
                        
                        if (r.message.failed_count > 0) {
                            frappe.msgprint({
                                title: __('Partial Success'),
                                message: __(
                                    'Success: {0}<br>Failed: {1}<br><br>Failed items: {2}',
                                    [r.message.success_count, r.message.failed_count, r.message.failed_items.join(', ')]
                                ),
                                indicator: 'orange'
                            });
                        }
                    }
                }
            });
        }
    );
}

function bulk_enable_items(listview) {
    const selected_items = listview.get_checked_items();
    
    if (selected_items.length === 0) {
        frappe.msgprint(__('Please select items to enable'));
        return;
    }
    
    const item_names = selected_items.map(function(item) {
        return item.name;
    });
    
    frappe.confirm(
        __('Are you sure you want to enable {0} item(s)?', [item_names.length]),
        function() {
            frappe.call({
                method: 'impressio.overrides.item.bulk_update_item_status',
                args: {
                    items: JSON.stringify(item_names),  // ← Stringify the array
                    status: 'Enabled'
                },
                freeze: true,
                freeze_message: __('Enabling {0} items...', [item_names.length]),
                callback: function(r) {
                    if (r.message) {
                        frappe.show_alert({
                            message: __('{0} item(s) enabled successfully', [r.message.success_count]),
                            indicator: 'green'
                        });
                        listview.refresh();
                    }
                }
            });
        }
    );
}