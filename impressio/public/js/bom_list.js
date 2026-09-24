frappe.listview_settings['BOM'] = {
	onload(listview) {
		listview.page.add_inner_button(__('Bulk Enable'), function () {
			bulk_enable_boms(listview);
		}, __('Actions'));

		listview.page.add_inner_button(__('Bulk Disable'), function () {
			bulk_disable_boms(listview);
		}, __('Actions'));
	}
};


function bulk_enable_boms(listview) {
	const selected = listview.get_checked_items();

	if (selected.length === 0) {
		frappe.msgprint(__('Please select BOMs to enable'));
		return;
	}

	const bom_names = selected.map(function (bom) {
		return bom.name;
	});

	frappe.confirm(
		__('Are you sure you want to enable {0} BOM(s)?', [bom_names.length]),
		function () {
			frappe.call({
				method: 'impressio.overrides.bom.bulk_update_bom_status',
				args: {
					boms: JSON.stringify(bom_names),
					action: 'enable'
				},
				freeze: true,
				freeze_message: __('Enabling {0} BOM(s)...', [bom_names.length]),
				callback: function (r) {
					if (r.message) {
						if (r.message.success_count > 0) {
							frappe.show_alert({
								message: __('{0} BOM(s) enabled successfully', [r.message.success_count]),
								indicator: 'green'
							});
						}
						listview.refresh();

						if (r.message.failed_count > 0) {
							frappe.msgprint({
								title: __('Partial Success'),
								message: __(
									'Success: {0}<br>Failed: {1}<br><br>Failed BOMs: {2}',
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


function bulk_disable_boms(listview) {
	const selected = listview.get_checked_items();

	if (selected.length === 0) {
		frappe.msgprint(__('Please select BOMs to disable'));
		return;
	}

	const bom_names = selected.map(function (bom) {
		return bom.name;
	});

	frappe.confirm(
		__('Are you sure you want to disable {0} BOM(s)?', [bom_names.length]),
		function () {
			frappe.call({
				method: 'impressio.overrides.bom.bulk_update_bom_status',
				args: {
					boms: JSON.stringify(bom_names),
					action: 'disable'
				},
				freeze: true,
				freeze_message: __('Disabling {0} BOM(s)...', [bom_names.length]),
				callback: function (r) {
					if (r.message) {
						if (r.message.success_count > 0) {
							frappe.show_alert({
								message: __('{0} BOM(s) disabled successfully', [r.message.success_count]),
								indicator: 'green'
							});
						}
						listview.refresh();

						if (r.message.failed_count > 0) {
							frappe.msgprint({
								title: __('Partial Success'),
								message: __(
									'Success: {0}<br>Failed: {1}<br><br>Failed BOMs: {2}',
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