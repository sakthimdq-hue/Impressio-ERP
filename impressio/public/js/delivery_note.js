// File: inventre/public/js/delivery_note.js
// Registered via hooks.py: doctype_js = {"Delivery Note": "public/js/delivery_note.js"}
// Adds "Create Handover" button on individual DN form — NO carrier selection here,
// carrier is chosen on the Handover To Logistics form itself.

frappe.ui.form.on('Delivery Note', {

    refresh: function(frm) {
        if (frm.doc.docstatus !== 1) return;

        // Fetch existing handovers for this DN
        frappe.db.get_list('Handover To Logistics', {
            filters: { delivery_note: frm.doc.name, docstatus: ['!=', 2] },
            // filters: { order_no: frm.doc.name, docstatus: ['!=', 2] },
            fields:  ['name', 'carrier_status', 'logistics_tracking_number', 'logistics_partner'],
            limit:   50
        }).then(function(handovers) {

            let pending = frm.doc.items.length - (handovers ? handovers.length : 0);

            // Always show Create Handover button if any items still pending
            // if (pending > 0) {
            //     frm.add_custom_button(
            //         __('Create Handover ({0} items)', [pending]),
            //         function() { show_handover_dialog(frm, handovers || []); },
            //         __('Logistics')
            //     ).addClass('btn-primary');
            // }

            // Show View Handovers if any exist
            if (handovers && handovers.length > 0) {
                frm.add_custom_button(
                    __('View Handovers ({0})', [handovers.length]),
                    function() {
                        frappe.set_route('List', 'Handover To Logistics', {
                            // order_no: frm.doc.name
                            delivery_note: frm.doc.name
                        });
                    },
                    __('Logistics')
                );

                // Status summary on form
                let delivered  = handovers.filter(h => h.carrier_status === 'Delivered').length;
                let in_transit = handovers.filter(h =>
                    ['In Transit', 'Out for Delivery', 'Picked Up'].includes(h.carrier_status)
                ).length;
                let created    = handovers.filter(h => h.carrier_status === 'Created').length;
                let no_awb     = handovers.filter(h =>
                    !h.carrier_status || h.carrier_status === 'Pending'
                ).length;

                let parts = [];
                if (delivered)  parts.push(`<span style="background:#28a745;color:#fff;padding:2px 9px;border-radius:10px;font-size:12px;">✓ ${delivered} Delivered</span>`);
                if (in_transit) parts.push(`<span style="background:#007bff;color:#fff;padding:2px 9px;border-radius:10px;font-size:12px;">→ ${in_transit} In Transit</span>`);
                if (created)    parts.push(`<span style="background:#17a2b8;color:#fff;padding:2px 9px;border-radius:10px;font-size:12px;">📦 ${created} AWB Created</span>`);
                if (no_awb)     parts.push(`<span style="background:#ffc107;color:#000;padding:2px 9px;border-radius:10px;font-size:12px;">⏳ ${no_awb} No AWB yet</span>`);

                if (parts.length) {
                    frm.dashboard.add_comment(
                        `<div style="padding:6px 0;display:flex;gap:8px;flex-wrap:wrap;">${parts.join('')}</div>`,
                        'blue', true
                    );
                }
            }
        });
    }
});


// ─────────────────────────────────────────────────────────────────────────────
// Dialog — shows item status, creates handovers directly (no carrier selection)
// ─────────────────────────────────────────────────────────────────────────────

// function show_handover_dialog(frm, existing_handovers) {
//     // Build a map of item row → handover
//     let done_map = {};
//     existing_handovers.forEach(h => {
//         // We store order_no = dn.name, so we match by item position
//         // The actual key is stored as dn_detail if field exists
//     });

//     // Fetch full status from server
//     frappe.call({
//         method: 'impressio.material_out.api.logistics.delivery_note_utils.get_dn_handover_status',
//         args:   { delivery_note: frm.doc.name },
//         freeze: true,
//         freeze_message: __('Loading items...'),
//         callback: function(r) {
//             if (r.exc) return;
//             build_confirm_dialog(frm, r.message);
//         }
//     });
// }
// REPLACE WITH:
function show_handover_dialog(frm, existing_handovers) {
    show_dimensions_dialog(frm);
}

function show_dimensions_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Enter Package Dimensions'),
        fields: [
            {
                fieldtype: 'HTML',
                options: `<div style="padding:10px;background:#fff8e1;
                            border-left:3px solid #ffc107;border-radius:4px;
                            font-size:12px;color:#666;margin-bottom:10px;">
                            📦 Please enter the package dimensions before creating the handover.
                          </div>`
            },
            {
                fieldtype: 'Float',
                fieldname: 'weight',
                label: __('Weight (kg)'),
                reqd: 1
            },
            {
                fieldtype: 'Column Break'
            },
            {
                fieldtype: 'Float',
                fieldname: 'length',
                label: __('Length (cm)'),
                reqd: 1
            },
            {
                fieldtype: 'Section Break'
            },
            {
                fieldtype: 'Float',
                fieldname: 'width',
                label: __('Width (cm)'),
                reqd: 1
            },
            {
                fieldtype: 'Column Break'
            },
            {
                fieldtype: 'Float',
                fieldname: 'height',
                label: __('Height (cm)'),
                reqd: 1
            }
        ],
        primary_action_label: __('Next →'),
        primary_action: function(values) {
            if (!values.weight || values.weight <= 0) {
                frappe.msgprint(__('Weight must be greater than 0')); return;
            }
            if (!values.length || values.length <= 0) {
                frappe.msgprint(__('Length must be greater than 0')); return;
            }
            if (!values.width || values.width <= 0) {
                frappe.msgprint(__('Width must be greater than 0')); return;
            }
            if (!values.height || values.height <= 0) {
                frappe.msgprint(__('Height must be greater than 0')); return;
            }
            d.hide();
            frappe.call({
                method: 'impressio.material_out.api.logistics.delivery_note_utils.get_dn_handover_status',
                args:   { delivery_note: frm.doc.name },
                freeze: true,
                freeze_message: __('Loading items...'),
                callback: function(r) {
                    if (r.exc) return;
                    build_confirm_dialog(frm, r.message, values);
                }
            });
        }
    });
    d.show();
}


function build_confirm_dialog(frm, status,dimensions) {
    let items         = status.items || [];
    let pending_items = items.filter(i => !i.has_handover);
    let done_items    = items.filter(i =>  i.has_handover);

    // If nothing to create
    if (pending_items.length === 0) {
        frappe.msgprint({
            title:     __('All Items Have Handover Docs'),
            message:   __('All {0} items already have Handover docs. '
                        + '<a href="/app/handover-to-logistics?order_no={1}">View them here</a>.',
                          [items.length, frm.doc.name]),
            indicator: 'blue'
        });
        return;
    }

    // Build table HTML
    let table_html = `
        <style>
            .hlg-table { width:100%; border-collapse:collapse; font-size:13px; }
            .hlg-table th { background:#f0f4f9; padding:9px 12px; text-align:left;
                            border-bottom:2px solid #dee2e6; font-weight:600; color:#444; }
            .hlg-table td { padding:9px 12px; border-bottom:1px solid #eee; }
            .hlg-table tr:hover { background:#f9fbff; }
            .badge-done    { background:#28a745;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px; }
            .badge-pending { background:#ffc107;color:#000;padding:2px 8px;border-radius:10px;font-size:11px; }
        </style>

        <div style="display:flex;gap:16px;margin-bottom:12px;padding:10px 14px;
                    background:#f8f9fa;border-radius:6px;font-size:13px;">
            <span>📦 <b>${items.length}</b> total items</span>
            <span style="color:#28a745;">✓ <b>${done_items.length}</b> already have Handover</span>
            <span style="color:#e67e22;">⏳ <b>${pending_items.length}</b> will be created now</span>
        </div>
    `;

    // Items to be created
    table_html += `
        <div style="font-size:12px;font-weight:600;color:#555;text-transform:uppercase;
                    letter-spacing:.4px;margin-bottom:6px;">
            Will create Handover docs for:
        </div>
        <table class="hlg-table">
            <thead><tr>
                <th>Item Code</th><th>Item Name</th><th>Qty</th><th>Amount</th>
            </tr></thead><tbody>
    `;
    pending_items.forEach(item => {
        table_html += `<tr>
            <td><b>${item.item_code}</b></td>
            <td>${item.item_name || ''}</td>
            <td>${item.qty}</td>
            <td></td>
        </tr>`;
    });
    table_html += `</tbody></table>`;

    // Already done items
    if (done_items.length > 0) {
        table_html += `
            <div style="font-size:12px;font-weight:600;color:#555;text-transform:uppercase;
                        letter-spacing:.4px;margin:14px 0 6px;">
                Already have Handover docs (skipped):
            </div>
            <table class="hlg-table">
                <thead><tr>
                    <th>Item Code</th><th>Handover</th><th>Carrier</th><th>Status</th>
                </tr></thead><tbody>
        `;
        done_items.forEach(item => {
            table_html += `<tr>
                <td>${item.item_code}</td>
                <td><a href="/app/handover-to-logistics/${item.handover_name}"
                       target="_blank" style="font-size:12px;">${item.handover_name}</a></td>
                <td style="font-size:12px;color:#555;">${item.logistics_partner || '—'}</td>
                <td>${item.carrier_status
                    ? `<span class="badge-done">${item.carrier_status}</span>`
                    : '<span class="badge-pending">No AWB</span>'}</td>
            </tr>`;
        });
        table_html += `</tbody></table>`;
    }

    table_html += `
        <div style="margin-top:14px;padding:10px 14px;background:#fff8e1;
                    border-left:3px solid #ffc107;border-radius:4px;font-size:12px;color:#555;">
            💡 After creation, open each Handover doc to select the carrier
            (Ekart / Amazon) and create the AWB.
        </div>
    `;

    let dialog = new frappe.ui.Dialog({
        title:                __('Create Handover To Logistics'),
        size:                 'large',
        fields:               [{ fieldtype: 'HTML', fieldname: 'content' }],
        primary_action_label: __('Create {0} Handover Doc(s)', [pending_items.length]),
        primary_action: function() {
            dialog.hide();
            do_create_handovers(frm, pending_items.length,dimensions);
        }
    });

    dialog.fields_dict.content.$wrapper.html(table_html);
    dialog.show();
}


function do_create_handovers(frm, count,dimensions) {
    frappe.call({
        method: 'impressio.material_out.api.logistics.delivery_note_utils.create_handover_from_dn',
        args: {
            delivery_note: frm.doc.name,
            weight: dimensions ? dimensions.weight : null,
            length: dimensions ? dimensions.length : null,
            width:  dimensions ? dimensions.width  : null,
            height: dimensions ? dimensions.height : null
        },
        freeze: true,
        freeze_message: __('Creating {0} Handover doc(s)...', [count]),
        callback: function(r) {
            if (r.exc) return;
            show_creation_results(frm, r.message);
        }
    });
}


function show_creation_results(frm, result) {
    let msg = '';

    if (result.created_count > 0) {
        msg += `<h5 style="color:#28a745;">✓ ${result.created_count} Handover doc(s) created:</h5><ul>`;
        result.created.forEach(r => {
            msg += `<li>
                <b>${r.item_code}</b> — Qty ${r.qty} →
                <a href="/app/handover-to-logistics/${r.handover}" target="_blank">${r.handover}</a>
            </li>`;
        });
        msg += `</ul>
            <p style="margin-top:8px;color:#555;font-size:12px;">
                💡 Open each Handover doc → select Logistics Partner → fill dimensions → Create Shipment.
            </p>`;
    }

    if (result.skipped_count > 0) {
        msg += `<p style="color:#888;margin-top:10px;font-size:12px;">
            ⏭ ${result.skipped_count} item(s) skipped — already had handover docs.
        </p>`;
    }

    if (result.failed_count > 0) {
        msg += `<h5 style="color:#dc3545;margin-top:12px;">✗ ${result.failed_count} failed:</h5><ul>`;
        result.failed.forEach(r => {
            msg += `<li>${r.item_code}: ${r.error}</li>`;
        });
        msg += `</ul>`;
    }

    frappe.msgprint({
        title:     __('Handover Creation Complete'),
        message:   msg,
        indicator: result.failed_count > 0 ? 'orange' : 'green',
        wide:      true
    });

    frm.refresh();
}



// ─────────────────────────────────────────────────────────────────────────────
// TRACKING HISTORY — reads from custom_status_tracking child table on DN
// ─────────────────────────────────────────────────────────────────────────────

frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        // existing refresh logic is already above — this just adds tracking button
        if (frm.doc.docstatus !== 1) return;

        frm.add_custom_button(__('Track Shipments'), function() {
            fetch_and_show_tracking(frm);
        }, __('Logistics'));
    }
});


function fetch_and_show_tracking(frm) {
    frappe.call({
        method: 'impressio.material_out.api.logistics.utils.get_tracking_by_dn',
        args: { dn_name: frm.doc.name },
        freeze: true,
        freeze_message: __('Fetching tracking info...'),
        callback: function(r) {
            let data = r.message && r.message.message ? r.message.message : r.message;
            if (!data || !data.success) {
                frappe.msgprint({
                    title: __('No Tracking Found'),
                    message: r.message ? r.message.message : __('No shipment found for this Delivery Note.'),
                    indicator: 'orange'
                });
                return;
            }
            show_tracking_dialog(frm, data);
            frm.reload_doc(); // refresh DN to show updated child table
        }
    });
}


function show_tracking_dialog(frm, data) {
    let partner_color = data.shipping_partner === 'Ekart' ? '#e67e22' : '#1a73e8';

    let header_html = `
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:10px 14px;background:#f0f4f9;border-radius:6px;margin-bottom:14px;">
            <div>
                <span style="font-weight:600;font-size:13px;">${data.hlg_name}</span>
                <span style="margin-left:10px;background:${partner_color};color:#fff;
                             padding:2px 9px;border-radius:10px;font-size:11px;">
                    ${data.shipping_partner}
                </span>
            </div>
            <div style="font-size:12px;color:#555;">
                AWB: <b>${data.tracking_number || '—'}</b>
            </div>
        </div>
    `;

    let timeline_html = build_timeline(data.tracking_history || []);

    let footer_html = `
        <div style="margin-top:10px;font-size:11px;color:#aaa;text-align:right;">
            Last updated: ${data.last_updated || '—'}
        </div>
    `;

    let dialog = new frappe.ui.Dialog({
        title: __('Shipment Tracking — {0}', [frm.doc.name]),
        size: 'large',
        fields: [{ fieldtype: 'HTML', fieldname: 'tracking_html' }]
    });

    dialog.fields_dict.tracking_html.$wrapper.html(
        header_html + timeline_html + footer_html
    );
    dialog.show();
}


function build_timeline(history) {
    if (!history || history.length === 0) {
        return `<p style="color:#888;font-size:13px;padding:10px;">No tracking events yet.</p>`;
    }

    // Show latest first
    let events = [...history].reverse();

    let rows = events.map(function(event, idx) {
        let is_first = idx === 0;

        // Color by status
        let status_color = '#6c757d';
        let dot_color    = '#adb5bd';
        if (['Delivered'].includes(event.status))                          { status_color = '#28a745'; dot_color = '#28a745'; }
        else if (['Out for Delivery'].includes(event.status))              { status_color = '#007bff'; dot_color = '#007bff'; }
        else if (['In Transit', 'Reached Hub'].includes(event.status))    { status_color = '#17a2b8'; dot_color = '#17a2b8'; }
        else if (['Picked Up'].includes(event.status))                     { status_color = '#e67e22'; dot_color = '#e67e22'; }
        else if (['Exception', 'RETO'].includes(event.status))             { status_color = '#dc3545'; dot_color = '#dc3545'; }
        else if (['Created'].includes(event.status))                       { status_color = '#6c757d'; dot_color = '#6c757d'; }

        return `
            <div style="display:flex;gap:12px;padding-bottom:${idx < events.length - 1 ? '14px' : '0'};">
                <!-- dot + line -->
                <div style="display:flex;flex-direction:column;align-items:center;min-width:16px;">
                    <div style="width:14px;height:14px;border-radius:50%;background:${dot_color};
                                margin-top:3px;flex-shrink:0;
                                ${is_first ? 'box-shadow:0 0 0 3px ' + dot_color + '33;' : ''}">
                    </div>
                    ${idx < events.length - 1
                        ? `<div style="width:2px;flex:1;background:#dee2e6;margin-top:3px;min-height:18px;"></div>`
                        : ''}
                </div>
                <!-- content -->
                <div style="flex:1;padding-bottom:4px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="font-weight:600;font-size:13px;color:${status_color};">
                            ${event.status}
                        </span>
                        <span style="font-size:11px;color:#888;">${event.date || ''}</span>
                    </div>
                    ${event.location && event.location !== 'N/A'
                        ? `<div style="font-size:12px;color:#555;margin-top:2px;">📍 ${event.location}</div>`
                        : ''}
                    ${event.description
                        ? `<div style="font-size:12px;color:#777;margin-top:2px;">${event.description}</div>`
                        : ''}
                </div>
            </div>
        `;
    }).join('');

    return `<div style="padding:4px 0;">${rows}</div>`;
}