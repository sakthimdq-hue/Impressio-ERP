# File: apps/inventre/inventre/material_out/packing_material/utils.py
"""
Utility functions for Packing Material handling
"""

import frappe
from frappe import _


def is_packing_material(item_group):
    """Check if item group is a packing material type"""
    if not item_group:
        return False
    return 'packing' in item_group.lower()


def validate_packing_material(doc, method=None):
    """Validate packing material dimensions - called via doc_events hook"""
    if not is_packing_material(doc.item_group):
        return
    
    errors = []
    
    # Validate positive dimensions
    if doc.get('pm_length') is not None and doc.pm_length is not None:
        if doc.pm_length <= 0:
            errors.append(_("Length must be a positive number"))
    else:
        errors.append(_("Length is required for Packing Material items"))
    
    if doc.get('pm_width') is not None and doc.pm_width is not None:
        if doc.pm_width <= 0:
            errors.append(_("Width must be a positive number"))
    else:
        errors.append(_("Width is required for Packing Material items"))
    
    if doc.get('pm_height') is not None and doc.pm_height is not None:
        if doc.pm_height <= 0:
            errors.append(_("Height must be a positive number"))
    else:
        errors.append(_("Height is required for Packing Material items"))
    
    if doc.get('pm_weight') is not None and doc.pm_weight is not None:
        if doc.pm_weight <= 0:
            errors.append(_("Weight must be a positive number"))
    else:
        errors.append(_("Weight is required for Packing Material items"))
    
    if errors:
        frappe.throw("<br>".join(errors), title=_("Packing Material Validation Error"))


def calculate_packing_material_cbm(doc, method=None):
    """Calculate CBM for packing material - called via doc_events hook"""
    if not is_packing_material(doc.item_group):
        return
    
    length = float(doc.pm_length or 0)
    width = float(doc.pm_width or 0)
    height = float(doc.pm_height or 0)
    
    if length > 0 and width > 0 and height > 0:
        # Formula: (Length × Width × Height) ÷ 1,000,000
        # Converts cm³ to m³
        cbm = (length * width * height) / 1000000
        doc.pm_cbm = round(cbm, 6)
    else:
        doc.pm_cbm = 0


@frappe.whitelist()
def get_packing_material_dimensions(item_code):
    """Get packing material dimensions for an item"""
    if not item_code:
        return None
    
    item = frappe.get_doc("Item", item_code)
    
    if not is_packing_material(item.item_group):
        return None
    
    return {
        "item_code": item_code,
        "item_name": item.item_name,
        "length": float(item.pm_length or 0),
        "width": float(item.pm_width or 0),
        "height": float(item.pm_height or 0),
        "weight": float(item.pm_weight or 0),
        "cbm": float(item.pm_cbm or 0)
    }


@frappe.whitelist()
def calculate_total_cbm(items):
    """Calculate total CBM for multiple packing material items
    
    Args:
        items: JSON string of list of dicts with item_code and qty
        
    Returns:
        dict with total_cbm, total_weight, and item details
    """
    import json
    
    if isinstance(items, str):
        items = json.loads(items)
    
    total_cbm = 0
    total_weight = 0
    item_details = []
    max_dimension = 0
    
    for item in items:
        item_code = item.get("item_code")
        qty = float(item.get("qty", 1))
        
        dimensions = get_packing_material_dimensions(item_code)
        if dimensions:
            item_cbm = dimensions["cbm"] * qty
            item_weight = dimensions["weight"] * qty
            total_cbm += item_cbm
            total_weight += item_weight
            
            # Track maximum single dimension
            max_dim = max(dimensions["length"], dimensions["width"], dimensions["height"])
            if max_dim > max_dimension:
                max_dimension = max_dim
            
            item_details.append({
                "item_code": item_code,
                "item_name": dimensions["item_name"],
                "qty": qty,
                "cbm": item_cbm,
                "weight": item_weight,
                "dimensions": dimensions
            })
    
    return {
        "total_cbm": round(total_cbm, 6),
        "total_weight": round(total_weight, 3),
        "max_dimension": max_dimension,
        "item_count": len(item_details),
        "items": item_details
    }

def set_sku_code(doc,method=None):
    if doc.has_variants:
        sch_code = frappe.db.get_value('School',doc.custom_school_name,'school_code')
        # sch_name = sch_doc.school_name
        # if sch_name:
        #     main_name = sch_name.split('-')[0].strip()
        #     words = main_name.split()

        #     # Mandatory 3-character school code
        #     if len(words) >= 3:
        #         sch_code = "".join(word[0].upper() for word in words[:3])

        #     elif len(words) == 2:
        #         w1, w2 = words
        #         sch_code = (w1[0] + w2[0] + w2[1]).upper()

        #     elif len(words) == 1:
        #         sch_code = words[0][:3].upper()

        #     else:
        #         sch_code = ""

            # main_name = sch_name.split('-')[0].strip()
            # sch_code = "".join(word[0].upper() for word in main_name.split())

            # branch_name = sch_doc.branch_name
            # if branch_name:
            #     branch_code = branch_name[:2].upper()
                
        category = doc.custom_code
        sub_category = frappe.db.get_value('Item Group',doc.item_group,['custom_code','parent_item_group'], as_dict=1)
        sub_sub_category = frappe.db.get_value('Item Group',sub_category.parent_item_group,['custom_code'])
            
        doc.item_code = f"{sch_code}{branch_code}{doc.custom_code}{sub_category.custom_code}{sub_sub_category}"

def custom_make_variant_item_code(template_item_code, template_item_name, variant):
    """Uses template's item code and abbreviations to make variant's item code"""
    if variant.item_code:
        return
        
    abbreviations = []
    for attr in variant.attributes:
        item_attribute = frappe.db.sql(
			"""select i.numeric_values, v.abbr
			from `tabItem Attribute` i left join `tabItem Attribute Value` v
				on (i.name=v.parent)
			where i.name=%(attribute)s and (v.attribute_value=%(attribute_value)s or i.numeric_values = 1)""",
			{"attribute": attr.attribute, "attribute_value": attr.attribute_value},
			as_dict=True,
		)
        
        if not item_attribute:
            continue
            
        abbr_or_value = (
			cstr(attr.attribute_value) if item_attribute[0].numeric_values else item_attribute[0].abbr
		)
        abbreviations.append(abbr_or_value)
        
    if abbreviations:
        variant.item_code = "{}{}".format(template_item_code, "".join(abbreviations))
        variant.item_name = "{}{}".format(template_item_name, "".join(abbreviations))
