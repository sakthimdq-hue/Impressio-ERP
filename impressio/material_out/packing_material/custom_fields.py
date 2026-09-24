# File: apps/inventre/inventre/material_out/packing_material/custom_fields.py
"""
Custom fields for Packing Material dimensions on Item DocType
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def get_packing_material_custom_fields():
    """Return custom field definitions for packing material items"""
    return {
        "Item": [
            {
                "fieldname": "packing_material_section",
                "fieldtype": "Section Break",
                "label": "Packing Material Dimensions",
                "insert_after": "weight_uom",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "collapsible": 0
            },
            {
                "fieldname": "pm_length",
                "fieldtype": "Float",
                "label": "Length (cm)",
                "insert_after": "packing_material_section",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "mandatory_depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "description": "Length of the packing material in centimeters"
            },
            {
                "fieldname": "pm_width",
                "fieldtype": "Float",
                "label": "Width (cm)",
                "insert_after": "pm_length",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "mandatory_depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "description": "Width of the packing material in centimeters"
            },
            {
                "fieldname": "pm_height",
                "fieldtype": "Float",
                "label": "Height (cm)",
                "insert_after": "pm_width",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "mandatory_depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "description": "Height of the packing material in centimeters"
            },
            {
                "fieldname": "pm_column_break",
                "fieldtype": "Column Break",
                "insert_after": "pm_height"
            },
            {
                "fieldname": "pm_weight",
                "fieldtype": "Float",
                "label": "Weight (kg)",
                "insert_after": "pm_column_break",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "mandatory_depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "description": "Weight of the packing material in kilograms"
            },
            {
                "fieldname": "pm_cbm",
                "fieldtype": "Float",
                "label": "CBM (Cubic Meters)",
                "insert_after": "pm_weight",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "read_only": 1,
                "description": "Auto-calculated: (Length × Width × Height) ÷ 1,000,000"
            },
            {
                "fieldname": "pm_qr_section",
                "fieldtype": "Section Break",
                "label": "QR Code",
                "insert_after": "pm_cbm",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "collapsible": 1
            },
            {
                "fieldname": "pm_qr_code",
                "fieldtype": "Attach Image",
                "label": "QR Code Image",
                "insert_after": "pm_qr_section",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "read_only": 1,
                "description": "Auto-generated QR code for scanning"
            },
            {
                "fieldname": "pm_qr_data",
                "fieldtype": "Code",
                "label": "QR Code Data",
                "insert_after": "pm_qr_code",
                "depends_on": "eval:doc.item_group && doc.item_group.toLowerCase().includes('packing')",
                "read_only": 1,
                "options": "JSON",
                "hidden": 1
            }
        ]
    }


@frappe.whitelist()
def setup_packing_material_custom_fields():
    """Create custom fields for packing material items

    Run this once to create the custom fields in the database.
    Can be called via:
    - bench console: frappe.call('impressio.material_out.packing_material.custom_fields.setup_packing_material_custom_fields')
    - API: POST /api/method/impressio.material_out.packing_material.custom_fields.setup_packing_material_custom_fields
    """
    custom_fields = get_packing_material_custom_fields()
    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Item")
    frappe.msgprint("Packing Material custom fields created successfully!", alert=True)
    return {"success": True, "message": "Custom fields created successfully"}


def remove_packing_material_custom_fields():
    """Remove custom fields for packing material items"""
    fields_to_remove = [
        "packing_material_section",
        "pm_length",
        "pm_width",
        "pm_height",
        "pm_column_break",
        "pm_weight",
        "pm_cbm",
        "pm_qr_section",
        "pm_qr_code",
        "pm_qr_data"
    ]
    
    for fieldname in fields_to_remove:
        frappe.db.delete("Custom Field", {
            "dt": "Item",
            "fieldname": fieldname
        })
    
    frappe.db.commit()
    frappe.msgprint("Packing Material custom fields removed successfully!", alert=True)
