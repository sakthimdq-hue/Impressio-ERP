frappe.views.calendar["ASN Creation"] = {
	field_map: {
		start: "start",
		end: "end",
		id: "name",
		title: "title",
		docstatus: 1,
	},

	get_events_method:
		"impressio.impressio_transaction.doctype.asn_creation.asn_creation.get_asn_events",

	options: {
		header: {
			left: "prev,next today",
			center: "title",
			right: "month,agendaWeek,agendaDay",
		},

		eventRender: function (event, element) {
			let time = moment(event.start).format("h:mm A");

			if (event.type === "Departure") {
				element.css({
					"background-color": "#1E90FF",
					"border-color": "#1E90FF",
					color: "white",
				});

				element.find(".fc-title").html(`
					<b>${event.asn_id}</b><br>
					PO: ${event.po_no}<br>
					Departure: ${time}
				`);
			}

			if (event.type === "Arrival") {
				element.css({
					"background-color": "#28A745",
					"border-color": "#28A745",
					color: "white",
				});

				element.find(".fc-title").html(`
					<b>${event.asn_id}</b><br>
					PO: ${event.po_no}<br>
					Arrival: ${time}
				`);
			}

			element.find(".fc-time").remove();
		},
	},
};
