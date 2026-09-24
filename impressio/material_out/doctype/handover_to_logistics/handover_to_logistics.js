// File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/doctype/handover_to_logistics/handover_to_logistics.js

// Shipment categorization thresholds
const LARGE_DIMENSION_THRESHOLD = 120;  // cm
const LARGE_CBM_THRESHOLD = 0.5;  // cubic meters
const LARGE_WEIGHT_THRESHOLD = 30;  // kg

frappe.ui.form.on('Handover To Logistics', {
    onload: function(frm) {
        // Wait for child table to load, then calculate CBM
        setTimeout(() => {
            calculateAndDisplayCBM(frm);
        }, 1500);
    },
    
    after_save: function(frm) {
        calculateAndDisplayCBM(frm);
    },

    logistics_partner: function(frm) {
        frm.refresh();
        if (frm.doc.logistics_partner) {
            // Clear previous service type
            frm.set_value('service_type', '');
            
            // Fetch available services for selected carrier
            frappe.call({
                method: 'impressio.material_out.api.logistics.utils.get_available_services',
                args: {
                    carrier: frm.doc.logistics_partner
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        // Update service type field options
                        let options = '\n' + r.message.join('\n');
                        frappe.meta.update_field_property(
                            'Handover To Logistics',
                            'service_type',
                            'options',
                            options
                        );
                        
                        // Set default service based on settings
                        frappe.db.get_single('Logistics Settings').then(settings => {
                            let default_service = '';
                            if (frm.doc.logistics_partner === 'Ekart') {
                                default_service = settings.ekart_default_service || 'Surface';
                            } else if (frm.doc.logistics_partner === 'Amazon Shipping') {
                                default_service = settings.amazon_default_service || 'Standard';
                            } else if (frm.doc.logistics_partner === 'Shiprocket') {
                                default_service = settings.shiprocket_default_courier || 'Shiprocket Surface';
                            }
                            
                            if (default_service && options.includes(default_service)) {
                                frm.set_value('service_type', default_service);
                            }
                        });
                        
                        // Refresh field
                        frm.refresh_field('service_type');
                    }
                }
            });
        }
    },

    refresh: function(frm) {
        // Calculate and display CBM and category
        calculateAndDisplayCBM(frm);
        displayShipmentCategoryIndicator(frm);
        setup_handover_scan_handler(frm);
        setup_dispatch_link_buttons(frm);

        // Show create shipment button if no tracking number
        if (!frm.doc.logistics_tracking_number) {
            frm.add_custom_button(
                __(`Create Shipment`),
                function() {
                    createShipment(frm);
                },
                __('Actions')
            ).addClass('btn-primary');
        }
        
        // Show create shipment button if no tracking number
// if (!frm.doc.logistics_tracking_number) {
//     if (!frm.doc.logistics_partner) {
//         // Show warning button when no carrier selected
//         frm.add_custom_button(
//             __('Select Carrier First'),
//             function() {
//                 frappe.msgprint({
//                     title: __('Action Required'),
//                     message: __('Please select a Logistics Partner from the dropdown before creating a shipment.'),
//                     indicator: 'orange'
//                 });
//                 frm.set_focus('logistics_partner');
//             },
//             __('Actions')
//         ).addClass('btn-warning');
//     } else {
//         // Show primary button when carrier is selected
//         frm.add_custom_button(
//             __(`Create ${frm.doc.logistics_partner} Shipment`),
//             function() {
//                 createShipment(frm);
//             },
//             __('Actions')
//         ).addClass('btn-primary');
//     }
// }

        // Show track button if has tracking
        if (frm.doc.logistics_tracking_number) {
            frm.add_custom_button(
                __('Track Shipment'),
                function() {
                    trackShipment(frm);
                },
                __('Actions')
            );

            // Show download label button
            frm.add_custom_button(
                __('Download Label'),
                function() {
                    downloadLabel(frm);
                },
                __('Actions')
            );

            // Show cancel button if status allows
            if (['Pending', 'Created', 'Picked Up'].includes(frm.doc.carrier_status)) {
                frm.add_custom_button(
                    __('Cancel Shipment'),
                    function() {
                        cancelShipment(frm);
                    },
                    __('Actions')
                ).addClass('btn-danger');
            }
        }

        // Add carrier-specific info
        if (frm.doc.carrier_response) {
            try {
                let response = JSON.parse(frm.doc.carrier_response);
                if (response.label_url) {
                    frm.add_custom_button(
                        __('View Label'),
                        function() {
                            window.open(response.label_url, '_blank');
                        },
                        __('Carrier Info')
                    );
                }
            } catch(e) {
                // Ignore parse error
            }
        }
        
        // Add button to check serviceability
        if (frm.doc.pincode) {
            frm.add_custom_button(
                __('Check Serviceability'),
                function() {
                    checkServiceability(frm);
                },
                __('Tools')
            );
        }
        
        // Add debug button for testing
        frm.add_custom_button(__('Debug CBM'), function() {
            console.log("=== DEBUG PACKING MATERIALS ===");
            if (frm.doc.packing_materials && frm.doc.packing_materials.length > 0) {
                frm.doc.packing_materials.forEach((item, idx) => {
                    console.log(`Item ${idx + 1}: ${item.item_code}`, {
                        length: item.pm_length,
                        width: item.pm_width,
                        height: item.pm_height,
                        weight: item.pm_weight,
                        unit_cbm: item.unit_cbm,
                        qty: item.qty
                    });
                });
            }
            calculateAndDisplayCBM(frm);
        }, __('Tools'));
    },

    pincode: function(frm) {
        // Auto-check serviceability on pincode change
        if (frm.doc.pincode && frm.doc.logistics_partner) {
            setTimeout(() => {
                if (frm.doc.pincode && frm.doc.pincode.length === 6) {
                    checkServiceability(frm, false);
                }
            }, 1000);
        }
    },

    // Dimension change handlers for real-time CBM calculation
    length: function(frm) {
        calculateAndDisplayCBM(frm);
    },

    width: function(frm) {
        calculateAndDisplayCBM(frm);
    },

    height: function(frm) {
        calculateAndDisplayCBM(frm);
    },

    weight: function(frm) {
        calculateAndDisplayCBM(frm);
    },

    sales_order: function(frm) {
        // Auto-fetch customer and delivery details from Sales Order
        if (frm.doc.sales_order && !frm.doc.__islocal === false) {
            fetchSalesOrderDetails(frm);
        }
    }
});

// Packing Material Item child table events
frappe.ui.form.on('Packing Material Item', {
    item_code: function(frm, cdt, cdn) {
        // Recalculate CBM when item is selected
        // Use longer timeout to ensure fetch_from has completed
        setTimeout(() => {
            calculatePackingMaterialTotals(frm);
            updateParentDimensionsFromPackingMaterials(frm);
            calculateAndDisplayCBM(frm);
        }, 1000);
    },

    qty: function(frm, cdt, cdn) {
        // Recalculate when quantity changes
        let row = locals[cdt][cdn];
        calculatePackingMaterialTotals(frm);
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },

    packing_materials_remove: function(frm) {
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },

    // Handle dimension field changes in child table
    pm_length: function(frm, cdt, cdn) {
        calculatePackingMaterialTotals(frm);
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },

    pm_width: function(frm, cdt, cdn) {
        calculatePackingMaterialTotals(frm);
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },

    pm_height: function(frm, cdt, cdn) {
        calculatePackingMaterialTotals(frm);
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },

    pm_weight: function(frm, cdt, cdn) {
        calculatePackingMaterialTotals(frm);
        updateParentDimensionsFromPackingMaterials(frm);
        calculateAndDisplayCBM(frm);
    },
    
    form_render: function(frm, cdt, cdn) {
        // When child table renders, calculate CBM
        setTimeout(() => {
            calculateAndDisplayCBM(frm);
        }, 500);
    }
});

// Helper functions
function createShipment(frm) {
    // ⚠️ FIRST: Save the document
    frm.save(null, function() {
        // ⚠️ THEN: Call the API
        frappe.call({
            method: 'impressio.material_out.api.logistics.utils.create_shipment',
            args: {
                docname: frm.doc.name
            },
            freeze: true,
            freeze_message: __('Creating shipment with {0}...', [frm.doc.logistics_partner]),
            callback: function(r) {
                if (!r.exc) {
                    frappe.show_alert({
                        message: __('Shipment created successfully! Tracking: {0}', [r.message.tracking_number]),
                        indicator: 'green'
                    });
                    frm.refresh();
                }
            }
        });
    });
}

function trackShipment(frm) {
    frappe.call({
        method: 'impressio.material_out.api.logistics.utils.track_shipment',
        args: {
            docname: frm.doc.name
        },
        freeze: true,
        freeze_message: __('Tracking shipment...'),
        callback: function(r) {
            if (!r.exc) {
                frappe.show_alert({
                    message: __('Status updated: {0}', [r.message.current_status]),
                    indicator: 'green'
                });
                frm.refresh();
            }
        }
    });
}

function downloadLabel(frm) {
    frappe.call({
        method: 'impressio.material_out.api.logistics.utils.download_label',
        args: {
            docname: frm.doc.name
        },
        freeze: true,
        freeze_message: __('Downloading label...'),
        callback: function(r) {
            if (!r.exc && r.message && r.message.file_url) {
                window.open(r.message.file_url, '_blank');
                frappe.show_alert({
                    message: __('Label downloaded successfully'),
                    indicator: 'green'
                });
            }
        }
    });
}
function cancelShipment(frm) {
    frappe.confirm(
        __('Are you sure you want to cancel this shipment?'),
        function() {
            frappe.call({
                method: 'impressio.material_out.api.logistics.utils.cancel_shipment',
                args: {
                    docname: frm.doc.name
                },
                freeze: true,
                freeze_message: __('Cancelling shipment...'),
                callback: function(r) {
                    if (!r.exc) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Shipment cancelled successfully'),
                                indicator: 'green'
                            });
                            frm.refresh();
                        } else if (r.message && r.message.eligible === false) {
                            // Shipment cannot be cancelled due to Amazon's rules
                            frappe.msgprint({
                                title: __('Cannot Cancel Shipment'),
                                message: r.message.message || __('Shipment cannot be cancelled at this stage'),
                                indicator: 'orange'
                            });
                        }
                    }
                },
                error: function(r) {
                    // Handle any other errors
                    let error_msg = 'Cannot cancel shipment';
                    try {
                        if (r.responseJSON && r.responseJSON._server_messages) {
                            let messages = JSON.parse(r.responseJSON._server_messages);
                            if (messages.length > 0) {
                                let msg = JSON.parse(messages[0]);
                                error_msg = msg.message;
                            }
                        }
                    } catch(e) {
                        console.log('Error parsing:', e);
                    }
                    
                    frappe.msgprint({
                        title: __('Cancellation Failed'),
                        message: error_msg,
                        indicator: 'red'
                    });
                }
            });
        }
    );
}

function checkServiceability(frm, showAlert = true) {
    if (!frm.doc.pincode || frm.doc.pincode.length !== 6) {
        if (showAlert) {
            frappe.msgprint(__('Please enter a valid 6-digit pincode'));
        }
        return;
    }
    
    frappe.call({
        method: 'impressio.material_out.api.logistics.utils.validate_address',
        args: {
            pincode: frm.doc.pincode,
            carrier: frm.doc.logistics_partner
        },
        freeze: showAlert,
        freeze_message: __('Checking serviceability...'),
        callback: function(r) {
            if (!r.exc && r.message) {
                if (showAlert) {
                    let message = '';
                    if (typeof r.message === 'object') {
                        if (r.message.serviceable) {
                            message = __('✅ {0} services this pincode. {1}', [
                                frm.doc.logistics_partner,
                                r.message.message || ''
                            ]);
                        } else {
                            message = __('❌ {0} does not service this pincode. {1}', [
                                frm.doc.logistics_partner,
                                r.message.message || ''
                            ]);
                        }
                    } else {
                        message = r.message;
                    }
                    
                    frappe.msgprint({
                        title: __('Serviceability Result'),
                        message: message,
                        indicator: r.message.serviceable ? 'green' : 'red'
                    });
                }
            }
        }
    });
}

/**
 * Calculate and display CBM from packing materials or manual dimensions
 */
function calculateAndDisplayCBM(frm) {
    console.log("=== calculateAndDisplayCBM called ===");
    
    let totalCBM = 0;
    let maxDimension = 0;
    let totalWeight = 0;

    // Calculate from packing materials table if present
    if (frm.doc.packing_materials && frm.doc.packing_materials.length > 0) {
        console.log(`Found ${frm.doc.packing_materials.length} packing materials`);
        
        frm.doc.packing_materials.forEach((item, index) => {
            // Calculate CBM from actual dimensions, not from unit_cbm field
            let length = parseFloat(item.pm_length) || 0;
            let width = parseFloat(item.pm_width) || 0;
            let height = parseFloat(item.pm_height) || 0;
            let qty = parseFloat(item.qty) || 1;
            
            // Calculate CBM for this item: (L×W×H in cm) ÷ 1,000,000 = CBM in m³
            let itemCBM = 0;
            if (length > 0 && width > 0 && height > 0) {
                itemCBM = (length * width * height) / 1000000;
                console.log(`Item ${index + 1} (${item.item_code}): ${length}×${width}×${height}cm = ${itemCBM.toFixed(6)} CBM × ${qty} qty = ${(itemCBM * qty).toFixed(6)}`);
            } else {
                // Fallback to unit_cbm if dimensions not available
                itemCBM = parseFloat(item.unit_cbm) || 0;
                console.log(`Item ${index + 1} (${item.item_code}): Using unit_cbm ${itemCBM} × ${qty} qty = ${(itemCBM * qty).toFixed(6)}`);
            }
            
            totalCBM += itemCBM * qty;

            let unitWeight = parseFloat(item.pm_weight) || 0;
            totalWeight += unitWeight * qty;

            // Track max dimension
            let itemMax = Math.max(length, width, height);
            if (itemMax > maxDimension) {
                maxDimension = itemMax;
            }
        });
        
        console.log(`Total CBM: ${totalCBM.toFixed(6)}, Max Dimension: ${maxDimension}, Total Weight: ${totalWeight}`);
    } else {
        console.log("No packing materials, using manual dimensions");
        
        // Calculate from manual dimensions
        let length = parseFloat(frm.doc.length) || 0;
        let width = parseFloat(frm.doc.width) || 0;
        let height = parseFloat(frm.doc.height) || 0;

        if (length > 0 && width > 0 && height > 0) {
            totalCBM = (length * width * height) / 1000000;
            maxDimension = Math.max(length, width, height);
            console.log(`Manual: ${length}×${width}×${height}cm = ${totalCBM.toFixed(6)} CBM`);
        }

        totalWeight = parseFloat(frm.doc.weight) || 0;
    }

    // Update fields
    frm.set_value('total_cbm', parseFloat(totalCBM.toFixed(6)));
    frm.set_value('max_dimension', maxDimension);

    // Determine shipment category
    let isLarge = false;

    if (maxDimension > LARGE_DIMENSION_THRESHOLD) {
        isLarge = true;
        console.log(`Large: max dimension ${maxDimension} > ${LARGE_DIMENSION_THRESHOLD}`);
    }
    if (totalCBM > LARGE_CBM_THRESHOLD) {
        isLarge = true;
        console.log(`Large: total CBM ${totalCBM.toFixed(6)} > ${LARGE_CBM_THRESHOLD}`);
    }
    if (totalWeight > LARGE_WEIGHT_THRESHOLD) {
        isLarge = true;
        console.log(`Large: weight ${totalWeight} > ${LARGE_WEIGHT_THRESHOLD}`);
    }

    frm.set_value('shipment_category', isLarge ? 'Large' : 'Non-Large');
    console.log(`Shipment Category: ${isLarge ? 'Large' : 'Non-Large'}`);

    // Refresh display
    frm.refresh_field('total_cbm');
    frm.refresh_field('max_dimension');
    frm.refresh_field('shipment_category');

    // Update visual indicator after category change
    setTimeout(() => {
        displayShipmentCategoryIndicator(frm);
    }, 100);
}

/**
 * Display shipment category with visual indicator
 */
function displayShipmentCategoryIndicator(frm) {
    // Safety check - ensure field exists
    if (!frm.fields_dict || !frm.fields_dict.shipment_category || !frm.fields_dict.shipment_category.$wrapper) {
        return;
    }

    let $wrapper = frm.fields_dict.shipment_category.$wrapper;

    // Remove existing indicator
    $wrapper.find('.category-indicator').remove();

    if (frm.doc.shipment_category) {
        let color = frm.doc.shipment_category === 'Large' ? '#ff6b6b' : '#51cf66';
        let icon = frm.doc.shipment_category === 'Large' ? '📦' : '📬';
        let textColor = '#ffffff';

        let indicator = $(`
            <div class="category-indicator" style="
                display: inline-block;
                padding: 6px 16px;
                border-radius: 6px;
                background-color: ${color};
                color: ${textColor};
                font-weight: bold;
                font-size: 13px;
                margin-left: 12px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                vertical-align: middle;
            ">
                ${icon} ${frm.doc.shipment_category}
            </div>
        `);

        // Try to append to control-value, fallback to wrapper
        let $controlValue = $wrapper.find('.control-value');
        if ($controlValue.length > 0) {
            $controlValue.append(indicator);
        } else {
            // Fallback: append to the field wrapper directly
            $wrapper.find('.like-disabled-input, .control-input').append(indicator);
        }
    }
}

/**
 * Calculate totals for each packing material row
 */
function calculatePackingMaterialTotals(frm) {
    let totalCBM = 0;
    let totalWeight = 0;

    (frm.doc.packing_materials || []).forEach(row => {
        // Calculate unit cbm
        if (row.pm_length && row.pm_width && row.pm_height) {
            row.unit_cbm = (row.pm_length * row.pm_width * row.pm_height) / 1000000;
        } else {
            row.unit_cbm = 0;
        }

        // Total cbm = unit_cbm * qty
        row.total_cbm = row.unit_cbm * (row.qty || 1);

        // Total weight = weight * qty
        row.total_weight = (row.pm_weight || 0) * (row.qty || 1);

        totalCBM += row.total_cbm;
        totalWeight += row.total_weight;
    });

    frm.set_value("total_cbm", totalCBM);
    frm.set_value("weight", totalWeight);

    frm.refresh_field("packing_materials");
}

/**
 * Update parent document dimension fields from packing materials child table
 *
 * Aggregation logic:
 * - Weight: Sum of all (pm_weight * qty)
 * - Length: Maximum pm_length across all items
 * - Width: Maximum pm_width across all items
 * - Height: Sum of all (pm_height * qty) - stacked vertically
 */
function updateParentDimensionsFromPackingMaterials(frm) {
    let maxLength = 0;
    let maxWidth = 0;
    let maxHeight = 0;

    (frm.doc.packing_materials || []).forEach(row => {
        if (row.pm_length > maxLength) maxLength = row.pm_length;
        if (row.pm_width > maxWidth) maxWidth = row.pm_width;
        if (row.pm_height > maxHeight) maxHeight = row.pm_height;
    });

    frm.set_value("length", maxLength);
    frm.set_value("width", maxWidth);
    frm.set_value("height", maxHeight);

    // Max dimension (for large/non-large)
    frm.set_value("max_dimension", Math.max(maxLength, maxWidth, maxHeight));
}


/**
 * Fetch and populate customer/delivery details from Sales Order
 */
function fetchSalesOrderDetails(frm) {
    if (!frm.doc.sales_order) return;

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Sales Order',
            name: frm.doc.sales_order
        },
        freeze: true,
        freeze_message: __('Fetching order details...'),
        callback: function(r) {
            if (r.message) {
                let so = r.message;

                // Set order number
                if (so.name && !frm.doc.order_no) {
                    frm.set_value('order_no', so.name);
                }

                // Set customer name
                if (so.customer_name) {
                    frm.set_value('customer_name', so.customer_name);
                } else if (so.customer) {
                    frm.set_value('customer_name', so.customer);
                }

                // Set payment type based on grand total and outstanding
                if (so.payment_terms_template || so.grand_total === so.advance_paid) {
                    frm.set_value('payment_type', 'Prepaid');
                }

                // Set declared value from grand total
                if (so.grand_total) {
                    frm.set_value('declared_value', so.grand_total);
                }

                // Fetch shipping address details
                if (so.shipping_address_name) {
                    fetchAddressDetails(frm, so.shipping_address_name);
                } else if (so.customer_address) {
                    fetchAddressDetails(frm, so.customer_address);
                }

                frappe.show_alert({
                    message: __('Customer details populated from Sales Order'),
                    indicator: 'green'
                }, 5);
            }
        },
        error: function(err) {
            frappe.msgprint({
                title: __('Error'),
                message: __('Could not fetch Sales Order details: {0}', [err.message || 'Unknown error']),
                indicator: 'red'
            });
        }
    });
}

/**
 * Fetch address details from Address doctype
 */
function fetchAddressDetails(frm, address_name) {
    if (!address_name) return;

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Address',
            name: address_name
        },
        callback: function(r) {
            if (r.message) {
                let addr = r.message;

                // Build full address
                let address_parts = [];
                if (addr.address_line1) address_parts.push(addr.address_line1);
                if (addr.address_line2) address_parts.push(addr.address_line2);

                if (address_parts.length > 0) {
                    frm.set_value('address', address_parts.join('\n'));
                }

                // Set location (typically city or area)
                if (addr.city) {
                    frm.set_value('location', addr.city);
                    frm.set_value('city', addr.city);
                }

                // Set state
                if (addr.state) {
                    frm.set_value('state', addr.state);
                }

                // Set pincode
                if (addr.pincode) {
                    frm.set_value('pincode', addr.pincode);
                }

                // Set phone from address or customer
                if (addr.phone) {
                    frm.set_value('customer_phone', addr.phone);
                }
            }
        }
    });
}

// ============================================
// QR Code Scanning Functions
// ============================================

function setup_handover_scan_handler(frm) {
    // Listen for barcode scanner input
    $(document).off('keypress.handover_scan').on('keypress.handover_scan', function(e) {
        if (e.which === 13 && frm.doc.scan_input) {
            process_handover_scan(frm, frm.doc.scan_input);
        }
    });
}

function process_handover_scan(frm, scan_data) {
    frappe.call({
        method: 'impressio.material_out.doctype.handover_to_logistics.handover_to_logistics.verify_handover_box',
        args: {
            docname: frm.doc.name,
            barcode_or_qr: scan_data
        },
        callback: function(r) {
            if (r.message) {
                if (r.message.success) {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'green'
                    });
                    frm.set_value('scan_input', '');

                    // Show dimensions if available
                    if (r.message.dimensions) {
                        let dims = r.message.dimensions;
                        frappe.msgprint({
                            title: __('Box Verified'),
                            message: `<strong>${r.message.item_code}</strong><br>
                                     Dimensions: ${dims.l} x ${dims.w} x ${dims.h} cm`,
                            indicator: 'green'
                        });
                    }
                } else {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'red'
                    });
                }
            }
        }
    });
}

// ============================================
// Dispatch Link Functions
// ============================================

function setup_dispatch_link_buttons(frm) {
    // Show link to dispatch if exists
    if (frm.doc.dispatch_order) {
        frm.add_custom_button(__('View Dispatch Order'), function() {
            frappe.set_route('Form', 'Dispatch Of Orders', frm.doc.dispatch_order);
        }, __('Links'));
    }

    // Show button to select from pending dispatches if no dispatch linked
    if (!frm.doc.dispatch_order && frm.is_new()) {
        frm.add_custom_button(__('Select from Pending Dispatches'), function() {
            show_pending_dispatches_dialog(frm);
        }, __('Actions'));
    }
}

function show_pending_dispatches_dialog(frm) {
    frappe.call({
        method: 'impressio.material_out.doctype.handover_to_logistics.handover_to_logistics.get_iawb_pending_dispatches',
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let options = r.message.map(d => ({
                    label: `${d.name} - ${d.customer_name} (${d.dispatch_date})`,
                    value: d.name
                }));

                frappe.prompt([
                    {
                        fieldtype: 'Select',
                        fieldname: 'dispatch',
                        label: __('Select Dispatch Order'),
                        options: options.map(o => o.value).join('\n'),
                        reqd: 1
                    }
                ], function(values) {
                    frm.set_value('dispatch_order', values.dispatch);

                    // Auto-populate from dispatch
                    let dispatch = r.message.find(d => d.name === values.dispatch);
                    if (dispatch) {
                        frm.set_value('order_no', dispatch.name);
                        frm.set_value('customer_name', dispatch.customer_name);
                    }
                }, __('Select Pending Dispatch'), __('Select'));
            } else {
                frappe.msgprint(__('No pending dispatches found'));
            }
        }
    });
}

// Handle scan_input field change
frappe.ui.form.on('Handover To Logistics', 'scan_input', function(frm) {
    if (frm.doc.scan_input) {
        process_handover_scan(frm, frm.doc.scan_input);
    }
});

// Handle dispatch_order field change
frappe.ui.form.on('Handover To Logistics', 'dispatch_order', function(frm) {
    if (frm.doc.dispatch_order) {
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Dispatch Of Orders',
                name: frm.doc.dispatch_order
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value('order_no', r.message.name);
                    frm.set_value('customer_name', r.message.customer_name);
                }
            }
        });
    }
});

// Camera scan trigger
frappe.ui.form.on('Handover To Logistics', 'trigger_camera_scan', function(frm) {
    frappe.prompt([
        {
            fieldtype: 'Data',
            fieldname: 'barcode',
            label: __('Enter Barcode/QR Code'),
            reqd: 1
        }
    ], function(values) {
        process_handover_scan(frm, values.barcode);
    }, __('Scan Box for IAWB Mapping'), __('Verify'));
});