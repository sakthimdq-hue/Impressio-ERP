// File: inventre/public/js/delivery_note_list.js
// Registered via hooks.py: doctype_list_js = {"Delivery Note": "public/js/delivery_note_list.js"}
// Bulk create Handover docs from DN list — NO carrier selection,
// carrier is chosen on each Handover To Logistics form.

frappe.listview_settings['Delivery Note'] = frappe.listview_settings['Delivery Note'] || {};

// let _orig_onload = frappe.listview_settings['Delivery Note'].onload;
// Fix: Frappe 15.88.2 blocks posting_date in list queries — remove it
let _orig_add_fields = frappe.listview_settings['Delivery Note'].add_fields || [];
frappe.listview_settings['Delivery Note'].add_fields = _orig_add_fields.filter(
    f => f !== 'posting_date'
);

let _orig_onload = frappe.listview_settings['Delivery Note'].onload;

frappe.listview_settings['Delivery Note'].onload = function(listview) {
    if (_orig_onload) _orig_onload(listview);

    // Store dimensions globally so bulk create can use them
    listview._handover_dimensions = null;

    listview.page.add_inner_button(__('📦 Set Package Dimensions'), function() {
        show_bulk_dimensions_dialog(listview);
    }, __('Logistics'));

    listview.page.add_inner_button(__('Bulk Create Handovers'), function() {
        bulk_create_handovers(listview);
    }, __('Logistics'));

    listview.page.add_inner_button(__('View All Handovers'), function() {
        frappe.set_route('List', 'Handover To Logistics');
    }, __('Logistics'));

        listview.page.add_inner_button(__('Track Shipments'), function() {
        bulk_track_shipments(listview);
    }, __('Logistics'));

    listview.page.add_inner_button(__('Mark as Delivered'), function() {
        show_mark_delivered_dialog(listview);
    }, __('Logistics'));

    listview.page.add_inner_button(__('Packaging Slip From Delivery Note'), function() {
        bulk_create_packing_slips(listview);
    });
};


function bulk_create_handovers(listview) {
    let selected = listview.get_checked_items();

    if (selected.length === 0) {
        frappe.msgprint({
            title:     __('No Documents Selected'),
            message:   __('Please select at least one Delivery Note.'),
            indicator: 'orange'
        });
        return;
    }

    // Only submitted DNs
    let valid   = selected.filter(d => d.docstatus === 1);
    let invalid = selected.filter(d => d.docstatus !== 1);

    if (valid.length === 0) {
        frappe.msgprint({
            title:     __('No Submitted Delivery Notes'),
            message:   __('Please submit the selected Delivery Notes before creating handovers.'),
            indicator: 'red'
        });
        return;
    }

    if (invalid.length > 0) {
        frappe.show_alert({
            message:   __(`{0} unsubmitted DN(s) will be skipped`, [invalid.length]),
            indicator: 'orange'
        });
    }

    // Get summary then confirm
    frappe.call({
        method: 'impressio.material_out.api.logistics.delivery_note_utils.get_bulk_dn_summary',
        args:   { delivery_notes: JSON.stringify(valid.map(d => d.name)) },
        freeze: true,
        freeze_message: __('Loading summary...'),
        callback: function(r) {
            let summary = (r.exc || !r.message) ? null : r.message;
            show_bulk_confirm_dialog(listview, valid, summary);
        },
        error: function() {
            show_bulk_confirm_dialog(listview, valid, null);
        }
    });
}


function show_bulk_confirm_dialog(listview, valid_docs, summary) {
    let total_items   = summary ? summary.total_items   : '?';
    let pending_items = summary ? summary.pending_items : '?';
    let skipped_items = summary ? summary.skipped_items : 0;

    let info_html = `
        <div style="padding:12px 14px;background:#f4f6f9;border-radius:6px;
                    font-size:13px;line-height:2;margin-bottom:8px;">
            <div>📋 <b>${valid_docs.length}</b> Delivery Note(s) selected</div>
            ${total_items !== '?' ? `
                <div>📦 <b>${total_items}</b> total items
                    → <b>${pending_items}</b> new Handover doc(s) will be created</div>
                ${skipped_items > 0
                    ? `<div style="color:#888;">⏭ ${skipped_items} item(s) already have handovers (will skip)</div>`
                    : ''}
            ` : ''}
            <div style="margin-top:6px;padding:8px 10px;background:#fff8e1;
                        border-left:3px solid #ffc107;border-radius:4px;font-size:12px;color:#666;">
                💡 After creation, open each Handover doc to select Ekart or Amazon and create the AWB.
            </div>
        </div>

        <div style="font-size:12px;font-weight:600;color:#555;text-transform:uppercase;
                    letter-spacing:.4px;margin-bottom:6px;">
            Selected Delivery Notes
        </div>
        <div style="max-height:160px;overflow-y:auto;border:1px solid #dee2e6;border-radius:4px;">
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#f0f4f9;">
                        <th style="padding:7px 10px;text-align:left;">DN #</th>
                        <th style="padding:7px 10px;text-align:left;">Customer</th>
                       
                    </tr>
                </thead>
                <tbody>
                    ${valid_docs.map(d => `
                        <tr style="border-bottom:1px solid #eee;">
                            <td style="padding:6px 10px;">${d.name}</td>
                            <td style="padding:6px 10px;">${d.customer_name || d.customer || ''}</td>
                      
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    // let dialog = new frappe.ui.Dialog({
    //     title:                __('Bulk Create Handovers'),
    //     size:                 'large',
    //     fields:               [{ fieldtype: 'HTML', fieldname: 'info' }],
    //     primary_action_label: __('Create Handovers'),
    //     primary_action: function() {
    //         dialog.hide();
    //         show_bulk_dimensions_dialog(listview, valid_docs);
    //     }
    // });
    let dialog = new frappe.ui.Dialog({
        title:                __('Bulk Create Handovers'),
        size:                 'large',
        fields:               [{ fieldtype: 'HTML', fieldname: 'info' }],
        primary_action_label: __('Create Handovers'),
        primary_action: function() {
            dialog.hide();
            if (!listview._handover_dimensions) {
                frappe.msgprint({
                    title: __('Dimensions Not Set'),
                    message: __('Please click "📦 Set Package Dimensions" first before creating handovers.'),
                    indicator: 'orange'
                });
                return;
            }
            execute_bulk_create(listview, valid_docs, listview._handover_dimensions);
        }
    });

    dialog.fields_dict.info.$wrapper.html(info_html);
    dialog.show();
}

// function show_bulk_dimensions_dialog(listview, valid_docs) {
//     let d = new frappe.ui.Dialog({
//         title: __('Enter Package Dimensions'),
//         fields: [
//             {
//                 fieldtype: 'HTML',
//                 options: `<div style="padding:10px;background:#fff8e1;
//                             border-left:3px solid #ffc107;border-radius:4px;
//                             font-size:12px;color:#666;margin-bottom:10px;">
//                             📦 These dimensions will apply to ALL selected handovers.
//                           </div>`
//             },
//             { fieldtype: 'Float',    fieldname: 'weight',         label: __('Weight (kg)'),       reqd: 1 },
//             { fieldtype: 'Column Break' },
//             { fieldtype: 'Float',    fieldname: 'length',         label: __('Length (cm)'),       reqd: 1 },
//             { fieldtype: 'Section Break' },
//             { fieldtype: 'Float',    fieldname: 'width',          label: __('Width (cm)'),        reqd: 1 },
//             { fieldtype: 'Column Break' },
//             { fieldtype: 'Float',    fieldname: 'height',         label: __('Height (cm)'),       reqd: 1 },
//             { fieldtype: 'Section Break' },
//             { fieldtype: 'Currency', fieldname: 'declared_value', label: __('Declared Value (₹)'), reqd: 1 },
//         ],
//         primary_action_label: __('Create Handovers'),
//         primary_action: function(values) {
//             if (!values.weight        || values.weight        <= 0) { frappe.msgprint(__('Weight must be greater than 0'));         return; }
//             if (!values.length        || values.length        <= 0) { frappe.msgprint(__('Length must be greater than 0'));         return; }
//             if (!values.width         || values.width         <= 0) { frappe.msgprint(__('Width must be greater than 0'));          return; }
//             if (!values.height        || values.height        <= 0) { frappe.msgprint(__('Height must be greater than 0'));         return; }
//             if (!values.declared_value|| values.declared_value<= 0) { frappe.msgprint(__('Declared Value must be greater than 0')); return; }
//             d.hide();
//             execute_bulk_create(listview, valid_docs, values);
//         }
//     });
//     d.show();
// }
function show_bulk_dimensions_dialog(listview) {
    let d = new frappe.ui.Dialog({
        title: __('Set Package Dimensions'),
        fields: [
            {
                fieldtype: 'HTML',
                options: `<div style="padding:10px;background:#fff8e1;
                            border-left:3px solid #ffc107;border-radius:4px;
                            font-size:12px;color:#666;margin-bottom:10px;">
                            📦 Set dimensions once — they will apply to all handovers created this session.
                          </div>`
            },
            { fieldtype: 'Float',    fieldname: 'weight',         label: __('Weight (kg)'),        reqd: 1 },
            { fieldtype: 'Column Break' },
            { fieldtype: 'Float',    fieldname: 'length',         label: __('Length (cm)'),        reqd: 1 },
            { fieldtype: 'Section Break' },
            { fieldtype: 'Float',    fieldname: 'width',          label: __('Width (cm)'),         reqd: 1 },
            { fieldtype: 'Column Break' },
            { fieldtype: 'Float',    fieldname: 'height',         label: __('Height (cm)'),        reqd: 1 },
            { fieldtype: 'Section Break' },
            { fieldtype: 'Currency', fieldname: 'declared_value', label: __('Declared Value (₹)'), reqd: 1 },
        ],
        primary_action_label: __('Save Dimensions'),
        primary_action: function(values) {
            if (!values.weight         || values.weight         <= 0) { frappe.msgprint(__('Weight must be greater than 0'));          return; }
            if (!values.length         || values.length         <= 0) { frappe.msgprint(__('Length must be greater than 0'));          return; }
            if (!values.width          || values.width          <= 0) { frappe.msgprint(__('Width must be greater than 0'));           return; }
            if (!values.height         || values.height         <= 0) { frappe.msgprint(__('Height must be greater than 0'));          return; }
            if (!values.declared_value || values.declared_value <= 0) { frappe.msgprint(__('Declared Value must be greater than 0')); return; }

            // Save to listview so bulk create can use it
            listview._handover_dimensions = values;
            d.hide();

            frappe.show_alert({
                message: __('✅ Dimensions saved! Now select DNs and click Bulk Create Handovers.'),
                indicator: 'green'
            }, 5);
        }
    });
    d.show();
}

function execute_bulk_create(listview, valid_docs,dimensions) {
    frappe.call({
        method: 'impressio.material_out.api.logistics.delivery_note_utils.bulk_create_handovers_from_dns',
        args: {
            delivery_notes: JSON.stringify(valid_docs.map(d => d.name)),
            weight:          dimensions ? dimensions.weight          : null,
            length:          dimensions ? dimensions.length          : null,
            width:           dimensions ? dimensions.width           : null,
            height:          dimensions ? dimensions.height          : null,
            declared_value:  dimensions ? dimensions.declared_value  : null,

        },
        freeze: true,
        freeze_message: __('Creating handovers for {0} Delivery Notes...', [valid_docs.length]),
        callback: function(r) {
            if (r.exc) return;
            show_bulk_results(listview, r.message);
        }
    });
}


function show_bulk_results(listview, result) {
    let msg = `<div style="font-size:13px;">
        <div style="display:flex;gap:20px;margin-bottom:14px;padding:10px 14px;
                    background:#f8f9fa;border-radius:6px;">
            <span style="color:#28a745;"><b>${result.created_count}</b> created</span>
            <span style="color:#ffc107;"><b>${result.skipped_count}</b> skipped</span>
            <span style="color:#dc3545;"><b>${result.failed_count}</b> failed</span>
        </div>
    `;

    if (result.created_count > 0) {
        msg += `<h5 style="color:#28a745;">✓ Created:</h5>
        <div style="max-height:200px;overflow-y:auto;font-size:12px;">
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr style="background:#f0f4f9;">
                    <th style="padding:6px 10px;text-align:left;">Delivery Note</th>
                 
                    <th style="padding:6px 10px;text-align:left;">Handover</th>
                </tr></thead><tbody>
        `;
        result.created.forEach(r => {
            msg += `<tr style="border-bottom:1px solid #eee;">
                <td style="padding:6px 10px;">${r.delivery_note}</td>
               
                <td style="padding:6px 10px;">
                    <a href="/app/handover-to-logistics/${r.handover}" target="_blank">
                        ${r.handover}
                    </a>
                </td>
            </tr>`;
        });
        msg += `</tbody></table></div>
            <p style="margin-top:10px;color:#555;font-size:12px;">
                💡 Open each Handover → select Logistics Partner → fill dimensions → Create Shipment.
            </p>
        `;
    }

    if (result.skipped_count > 0) {
        msg += `<p style="color:#888;margin-top:10px;font-size:12px;">
            ⏭ ${result.skipped_count} item(s) skipped — already had handover docs.
        </p>`;
    }

    if (result.failed_count > 0) {
        msg += `<h5 style="color:#dc3545;margin-top:12px;">✗ Failed:</h5>
            <ul style="font-size:12px;">`;
        result.failed.forEach(r => {
            msg += `<li>${r.delivery_note} / ${r.item_code || 'DN'}: ${r.error}</li>`;
        });
        msg += `</ul>`;
    }

    msg += `</div>`;

    frappe.msgprint({
        title:     __('Bulk Handover Creation Complete'),
        message:   msg,
        indicator: result.failed_count > 0 ? 'orange' : 'green',
        wide:      true
    });

    listview.refresh();
}


// 
// 
// 
// 
// 
// 
 
function bulk_track_shipments(listview) {
    let selected = listview.get_checked_items();
 
    if (!selected.length) {
        frappe.msgprint({ message: __('Please select at least one Delivery Note.'), indicator: 'orange' });
        return;
    }
 
    let dn_names    = selected.map(r => r.name);
    let total       = dn_names.length;
    let done        = 0;
    let success     = 0;
    let failed      = [];
    const BATCH_SIZE = 3;   // max concurrent requests — keeps server + browser happy
 
    frappe.show_alert({ message: __('Starting tracking… 0 / {0}', [total]), indicator: 'blue' }, 120);
 
    // Wraps a single frappe.call as a Promise — never rejects so batches never stall
    function track_one(dn_name) {
        return new Promise(function(resolve) {
            frappe.call({
                method:   'impressio.material_out.api.logistics.utils.get_tracking_by_dn',
                args:     { dn_name: dn_name },
                callback: function(r) {
                    let data = r.message && r.message.message ? r.message.message : r.message;
                    if (data && data.success) {
                        success++;
                    } else {
                        failed.push({
                            dn:  dn_name,
                            err: (data && data.message) ? data.message : __('No shipment found')
                        });
                    }
                    done++;
                    frappe.show_alert({
                        message:   __('Tracking… {0} / {1}', [done, total]),
                        indicator: 'blue'
                    }, 120);
                    resolve();
                },
                error: function() {
                    failed.push({ dn: dn_name, err: __('Server error') });
                    done++;
                    frappe.show_alert({
                        message:   __('Tracking… {0} / {1}', [done, total]),
                        indicator: 'blue'
                    }, 120);
                    resolve();
                }
            });
        });
    }
 
    // Process dn_names in chunks of BATCH_SIZE.
    // Each chunk runs in parallel; next chunk only starts after current chunk finishes.
    // This prevents flooding the server with 20 simultaneous requests.
    function run_batch(offset) {
        if (offset >= total) {
            // All done — show summary
            let msg = '<p>✅ <b>' + success + '</b> shipment(s) updated successfully.</p>';
            if (failed.length) {
                msg += '<p style="color:#dc3545;margin-top:8px;">⚠ ' + failed.length + ' failed:</p><ul>';
                failed.forEach(function(f) {
                    msg += '<li><b>' + f.dn + '</b>: ' + f.err + '</li>';
                });
                msg += '</ul>';
            }
            frappe.msgprint({
                title:     __('Bulk Tracking Complete'),
                message:   msg,
                indicator: failed.length ? 'orange' : 'green',
                wide:      true
            });
            listview.refresh();
            return;
        }
 
        let batch = dn_names.slice(offset, offset + BATCH_SIZE);
 
        // Fire this batch in parallel, then move to next batch
        Promise.all(batch.map(dn => track_one(dn))).then(function() {
            // Small yield to browser (4 ms) so UI can repaint between batches
            setTimeout(function() { run_batch(offset + BATCH_SIZE); }, 4);
        });
    }
 
    run_batch(0);
}
 
 
// ═════════════════════════════════════════════════════════════════════════════
// BULK MARK AS DELIVERED  (new)
// ═════════════════════════════════════════════════════════════════════════════
 
function show_mark_delivered_dialog(listview) {
    let selected = listview.get_checked_items();
 
    if (!selected.length) {
        frappe.msgprint({ message: __('Please select at least one Delivery Note.'), indicator: 'orange' });
        return;
    }
 
    let dn_names = selected.map(r => r.name);
 
    // ── Step 1: validate AWB + carrier status before showing the dialog ──────
    frappe.call({
        method:         'impressio.material_out.api.logistics.delivery_note_utils.validate_dns_for_delivery',
        args:           { delivery_notes: JSON.stringify(dn_names) },
        freeze:         true,
        freeze_message: __('Validating shipment statuses...'),
        callback: function(r) {
            if (r.exc) return;
            let result = r.message;
 
            let eligible   = result.eligible   || [];   // AWB exists + status = Delivered
            let no_awb     = result.no_awb     || [];   // no HLG / no tracking number
            let not_delivered = result.not_delivered || []; // AWB exists but status != Delivered
 
            // Nothing eligible at all — show a hard stop
            if (eligible.length === 0) {
                let msg = `<p style="color:#dc3545;">
                    ⚠ None of the selected Delivery Notes can be marked as delivered.</p>`;
 
                if (no_awb.length) {
                    msg += `<p style="margin-top:10px;font-weight:600;">No AWB generated (${no_awb.length}):</p>
                        <ul style="font-size:12px;">`;
                    no_awb.forEach(d => { msg += `<li>${d.dn} — ${d.customer}</li>`; });
                    msg += `</ul>`;
                }
                if (not_delivered.length) {
                    msg += `<p style="margin-top:10px;font-weight:600;">
                        AWB exists but carrier status is not "Delivered" (${not_delivered.length}):</p>
                        <ul style="font-size:12px;">`;
                    not_delivered.forEach(d => {
                        msg += `<li>${d.dn} — ${d.customer}
                            <span style="color:#888;">(${d.carrier_status || 'No status'}
                            · AWB: ${d.tracking_number})</span></li>`;
                    });
                    msg += `</ul>`;
                }
 
                frappe.msgprint({ title: __('Cannot Mark as Delivered'), message: msg,
                    indicator: 'red', wide: true });
                return;
            }
 
            // Some eligible, some not — show the confirmation dialog with split view
            _show_delivery_confirm_dialog(listview, selected, eligible, no_awb, not_delivered);
        }
    });
}
 
 
function _show_delivery_confirm_dialog(listview, selected, eligible, no_awb, not_delivered) {
 
    // Build the eligible rows table
    let eligible_rows = eligible.map(d => `
        <tr style="border-bottom:1px solid #eee;">
            <td style="padding:5px 10px;">${d.dn}</td>
            <td style="padding:5px 10px;">${d.customer}</td>
            <td style="padding:5px 10px;font-size:11px;color:#555;">${d.tracking_number}</td>
            <td style="padding:5px 10px;">
                <span style="background:#28a745;color:#fff;padding:2px 8px;
                             border-radius:10px;font-size:11px;">Delivered</span>
            </td>
        </tr>`).join('');
 
    // Build skipped rows (no AWB + not delivered)
    let skipped_rows = [
        ...no_awb.map(d => `
            <tr style="border-bottom:1px solid #eee;opacity:.7;">
                <td style="padding:5px 10px;">${d.dn}</td>
                <td style="padding:5px 10px;">${d.customer}</td>
                <td style="padding:5px 10px;font-size:11px;color:#dc3545;">No AWB</td>
                <td style="padding:5px 10px;">
                    <span style="background:#6c757d;color:#fff;padding:2px 8px;
                                 border-radius:10px;font-size:11px;">Skipped</span>
                </td>
            </tr>`),
        ...not_delivered.map(d => `
            <tr style="border-bottom:1px solid #eee;opacity:.7;">
                <td style="padding:5px 10px;">${d.dn}</td>
                <td style="padding:5px 10px;">${d.customer}</td>
                <td style="padding:5px 10px;font-size:11px;color:#555;">${d.tracking_number || '—'}</td>
                <td style="padding:5px 10px;">
                    <span style="background:#ffc107;color:#000;padding:2px 8px;
                                 border-radius:10px;font-size:11px;">${d.carrier_status || 'Pending'}</span>
                </td>
            </tr>`)
    ].join('');
 
    let skipped_total = no_awb.length + not_delivered.length;
 
    let preview_html = `
        <!-- Summary bar -->
        <div style="display:flex;gap:16px;padding:10px 14px;background:#f4f6f9;
                    border-radius:6px;font-size:13px;margin-bottom:12px;">
            <span style="color:#28a745;">✅ <b>${eligible.length}</b> will be marked delivered</span>
            ${skipped_total > 0
                ? `<span style="color:#888;">⏭ <b>${skipped_total}</b> will be skipped</span>`
                : ''}
        </div>
 
        <!-- Table -->
        <div style="max-height:220px;overflow-y:auto;border:1px solid #dee2e6;border-radius:4px;">
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <thead>
                    <tr style="background:#f0f4f9;position:sticky;top:0;">
                        <th style="padding:7px 10px;text-align:left;">DN #</th>
                        <th style="padding:7px 10px;text-align:left;">Customer</th>
                        <th style="padding:7px 10px;text-align:left;">AWB</th>
                        <th style="padding:7px 10px;text-align:left;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${eligible_rows}
                    ${skipped_rows}
                </tbody>
            </table>
        </div>
 
        ${skipped_total > 0 ? `
        <div style="margin-top:10px;padding:8px 12px;background:#fff8e1;
                    border-left:3px solid #ffc107;border-radius:4px;font-size:12px;color:#666;">
            ⚠ Skipped DNs have no AWB or their carrier status is not yet "Delivered".
            Run <b>Track Shipments</b> first to refresh statuses.
        </div>` : ''}
    `;
 
    let dialog = new frappe.ui.Dialog({
        title:  __('Mark {0} Delivery Note(s) as Delivered', [eligible.length]),
        size:   'large',
        fields: [
            { fieldtype: 'HTML', fieldname: 'preview' },
            {
                fieldtype: 'Date',
                fieldname: 'delivered_date',
                label:     __('Delivery Date'),
                reqd:      1,
                default:   frappe.datetime.get_today()
            }
        ],
        primary_action_label: __('Mark {0} DN(s) as Delivered', [eligible.length]),
        primary_action: function(values) {
            if (!values.delivered_date) {
                frappe.msgprint(__('Please select a delivery date.'));
                return;
            }
            dialog.hide();
            do_bulk_mark_delivered(eligible.map(e => e.dn), values.delivered_date, listview);
        }
    });
 
    dialog.fields_dict.preview.$wrapper.html(preview_html);
    dialog.show();
}
 
 
function do_bulk_mark_delivered(dn_names, delivered_date, listview) {
    frappe.call({
        method:         'impressio.material_out.api.logistics.delivery_note_utils.bulk_mark_delivered',
        args:           { delivery_notes: JSON.stringify(dn_names), delivered_date: delivered_date },
        freeze:         true,
        freeze_message: __('Marking {0} DN(s) as delivered...', [dn_names.length]),
        callback: function(r) {
            if (r.exc) return;
 
            let result = r.message;
            let msg    = '';
 
            if (result.success_count > 0) {
                msg += `<p>✅ <b>${result.success_count}</b> Delivery Note(s) marked as delivered
                            on <b>${delivered_date}</b>.</p>`;
            }
            if (result.failed_count > 0) {
                msg += `<p style="color:#dc3545;margin-top:10px;">⚠ ${result.failed_count} failed:</p><ul>`;
                result.failed.forEach(f => {
                    msg += `<li><b>${f.delivery_note}</b>: ${f.error}</li>`;
                });
                msg += `</ul>`;
            }
 
            frappe.msgprint({
                title:     __('Bulk Mark Delivered — Complete'),
                message:   msg,
                indicator: result.failed_count > 0 ? 'orange' : 'green',
                wide:      true
            });
 
            listview.refresh();
        }
    });
}




function bulk_create_packing_slips(listview) {
    let selected = listview.get_checked_items();

    if (!selected.length) {
        frappe.msgprint({
            title: __('No Documents Selected'),
            message: __('Please select at least one Delivery Note.'),
            indicator: 'orange'
        });
        return;
    }

    let dn_names = selected.map(d => d.name).join(",");

    frappe.confirm(
        __('Create Packing Slip for {0} Delivery Note(s)?', [selected.length]),
        function() {
            frappe.call({
                method: 'create_packing_slip_for_dn',
                args: { delivery_notes: dn_names },
                freeze: true,
                freeze_message: __('Creating Packing Slips...'),
                callback: function(r) {
                    if (r.message && r.message.length) {
                        frappe.show_alert({
                            message: __(`${r.message.length} Packing Slip(s) created successfully!`),
                            indicator: 'green'
                        });
                        listview.refresh();
                    }
                }
            });
        }
    );
}
 


