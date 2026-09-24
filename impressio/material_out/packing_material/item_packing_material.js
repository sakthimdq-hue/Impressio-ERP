// File: apps/inventre/inventre/material_out/packing_material/item_packing_material.js
// Client script for Item DocType - Packing Material fields

frappe.ui.form.on('Item', {
    refresh: function(frm) {
        // Check and update packing material fields visibility
        togglePackingMaterialFields(frm);
        
        // Calculate CBM if packing material
        if (isPackingMaterial(frm)) {
            calculateCBM(frm);
        }
    },

    item_group: function(frm) {
        // Toggle packing material fields based on item group
        togglePackingMaterialFields(frm);
        
        // Clear values if not packing material
        if (!isPackingMaterial(frm)) {
            frm.set_value('pm_length', null);
            frm.set_value('pm_width', null);
            frm.set_value('pm_height', null);
            frm.set_value('pm_weight', null);
            frm.set_value('pm_cbm', null);
        }
    },

    pm_length: function(frm) {
        calculateCBM(frm);
        validatePositiveNumber(frm, 'pm_length');
    },

    pm_width: function(frm) {
        calculateCBM(frm);
        validatePositiveNumber(frm, 'pm_width');
    },

    pm_height: function(frm) {
        calculateCBM(frm);
        validatePositiveNumber(frm, 'pm_height');
    },

    pm_weight: function(frm) {
        validatePositiveNumber(frm, 'pm_weight');
    },

    validate: function(frm) {
        // Validate packing material dimensions if applicable
        if (isPackingMaterial(frm)) {
            let errors = [];
            
            if (!frm.doc.pm_length || frm.doc.pm_length <= 0) {
                errors.push(__('Length must be a positive number'));
            }
            if (!frm.doc.pm_width || frm.doc.pm_width <= 0) {
                errors.push(__('Width must be a positive number'));
            }
            if (!frm.doc.pm_height || frm.doc.pm_height <= 0) {
                errors.push(__('Height must be a positive number'));
            }
            if (!frm.doc.pm_weight || frm.doc.pm_weight <= 0) {
                errors.push(__('Weight must be a positive number'));
            }
            
            if (errors.length > 0) {
                frappe.msgprint({
                    title: __('Packing Material Validation Error'),
                    message: errors.join('<br>'),
                    indicator: 'red'
                });
                frappe.validated = false;
            }
        }
    }
});

/**
 * Check if item belongs to Packing Material group
 */
function isPackingMaterial(frm) {
    if (!frm.doc.item_group) return false;
    return frm.doc.item_group.toLowerCase().includes('packing');
}

/**
 * Toggle packing material section visibility
 */
function togglePackingMaterialFields(frm) {
    let isPM = isPackingMaterial(frm);
    
    // Refresh the section to trigger depends_on evaluation
    frm.refresh_field('packing_material_section');
    frm.refresh_field('pm_length');
    frm.refresh_field('pm_width');
    frm.refresh_field('pm_height');
    frm.refresh_field('pm_weight');
    frm.refresh_field('pm_cbm');
}

/**
 * Calculate CBM (Cubic Meter) from dimensions
 * Formula: (Length × Width × Height) ÷ 1,000,000
 */
function calculateCBM(frm) {
    let length = parseFloat(frm.doc.pm_length) || 0;
    let width = parseFloat(frm.doc.pm_width) || 0;
    let height = parseFloat(frm.doc.pm_height) || 0;
    
    if (length > 0 && width > 0 && height > 0) {
        // Convert cm³ to m³: divide by 1,000,000
        let cbm = (length * width * height) / 1000000;
        frm.set_value('pm_cbm', parseFloat(cbm.toFixed(6)));
    } else {
        frm.set_value('pm_cbm', 0);
    }
}

/**
 * Validate that a field contains a positive number
 */
function validatePositiveNumber(frm, fieldname) {
    let value = frm.doc[fieldname];
    if (value !== null && value !== undefined && value < 0) {
        frappe.msgprint({
            title: __('Validation Error'),
            message: __('Value for {0} must be a positive number', [frappe.meta.get_label('Item', fieldname, frm.doc.name)]),
            indicator: 'red'
        });
        frm.set_value(fieldname, Math.abs(value));
    }
}
