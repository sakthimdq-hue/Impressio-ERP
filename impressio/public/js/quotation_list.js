frappe.provide("impressio");

frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {};

(function () {
	const original_onload = frappe.listview_settings["Quotation"].onload;
	const original_refresh = frappe.listview_settings["Quotation"].refresh;

	frappe.listview_settings["Quotation"].onload = function (listview) {
		if (original_onload) {
			original_onload(listview);
		}
		add_quotation_api_button(listview);
	};

	frappe.listview_settings["Quotation"].refresh = function (listview) {
		if (original_refresh) {
			original_refresh(listview);
		}
		add_quotation_api_button(listview);
	};

	function add_quotation_api_button(listview) {
		if (!listview || !listview.page) return;

		// 1. Direct button in inner toolbar
		if (listview.page.inner_toolbar && !listview.page.inner_toolbar.find(`button[data-label="${encodeURIComponent("Import Quotations from API")}"]`).length) {
			listview.page.add_inner_button(
				__("Import Quotations from API"),
				function () {
					impressio_sync_quotations(listview);
				}
			);
		}

		// 3. In Actions menu dropdown
		listview.page.add_inner_button(
			__("Import Quotations from API"),
			function () {
				impressio_sync_quotations(listview);
			},
			__("Actions")
		);
	}
})();

function impressio_sync_quotations(listview) {
	// Clean up any old custom overlay/styles if left over
	const oldOverlay = document.getElementById("impressio-sync-modal-overlay");
	if (oldOverlay) oldOverlay.remove();
	const oldStyle = document.getElementById("impressio-sync-modal-styles");
	if (oldStyle) oldStyle.remove();

	frappe.show_progress(__("Importing Quotations"), 0, 100, __("Connecting to API..."));

	frappe.call({
		method: "impressio.api.fetch_quotations_from_api",
		callback: function (r) {
			if (!r || !r.message || !r.message.quotations || r.message.quotations.length === 0) {
				frappe.hide_progress();
				frappe.msgprint({
					title: __("No Quotations Found"),
					indicator: "orange",
					message: __("The API returned no quotations to import.")
				});
				return;
			}

			const quotations = r.message.quotations;
			const total = quotations.length;
			frappe.show_progress(__("Importing Quotations"), 0, total, __("Found {0} quotations. Starting sync...", [total]));

			const chunkSize = 2;
			const chunks = [];
			for (let i = 0; i < quotations.length; i += chunkSize) {
				chunks.push(quotations.slice(i, i + chunkSize));
			}

			let processedCount = 0;
			let totalCreated = 0;
			let totalUpdated = 0;
			let chunkIndex = 0;

			function processNextChunk() {
				if (chunkIndex >= chunks.length) {
					frappe.show_progress(__("Importing Quotations"), total, total, __("Sync completed"));
					setTimeout(function () {
						frappe.hide_progress();
						frappe.show_alert({
							message: __("Quotations Synced: {0} Created, {1} Updated", [totalCreated, totalUpdated]),
							indicator: "green"
						}, 5);
						if (listview) {
							listview.refresh();
						}
					}, 400);
					return;
				}

				const currentChunk = chunks[chunkIndex];
				const quoteIds = currentChunk.map(q => q.id);
				const firstQuote = currentChunk[0];
				const quoteLabel = firstQuote.quote_number || `Quote #${firstQuote.id}`;
				const schoolLabel = firstQuote.school_name || firstQuote.customer_name || "";

				const currentStatus = schoolLabel
					? __("Importing {0} ({1})... ({2}/{3})", [quoteLabel, schoolLabel, processedCount, total])
					: __("Importing {0}... ({1}/{2})", [quoteLabel, processedCount, total]);

				frappe.show_progress(__("Importing Quotations"), processedCount, total, currentStatus);

				frappe.call({
					method: "impressio.api.import_quotations_from_api",
					args: {
						quote_ids: quoteIds
					},
					callback: function (res) {
						processedCount += currentChunk.length;
						if (processedCount > total) processedCount = total;

						if (res && res.message) {
							totalCreated += (res.message.imported_count || 0);
							totalUpdated += (res.message.updated_count || 0);
						}

						frappe.show_progress(__("Importing Quotations"), processedCount, total, currentStatus);

						chunkIndex++;
						setTimeout(processNextChunk, 80);
					},
					error: function () {
						processedCount += currentChunk.length;
						chunkIndex++;
						setTimeout(processNextChunk, 80);
					}
				});
			}

			processNextChunk();
		},
		error: function () {
			frappe.hide_progress();
			frappe.msgprint({
				title: __("API Error"),
				indicator: "red",
				message: __("Could not connect to the Quotations API.")
			});
		}
	});
}
