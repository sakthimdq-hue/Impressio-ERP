import frappe


# =====================================================
# RESOLVE BOM TREE (RECURSIVE)
# =====================================================

def resolve_bom_tree(item_code):

    bom_name = frappe.get_value(
        "BOM",
        {
            "item": item_code,
            "is_active": 1,
            "docstatus": ["!=", 2]
        },
        "name"
    )

    if not bom_name:
        return []

    bom_items = frappe.get_all(
        "BOM Item",
        filters={"parent": bom_name},
        fields=["item_code", "qty"],
        order_by="idx asc"
    )

    result = []

    for bi in bom_items:

        node = {
            "item_code": bi.item_code,
            "qty": int(bi.qty)
        }

        children = resolve_bom_tree(bi.item_code)

        if children:
            node["items"] = children

        result.append(node)

    return result


# =====================================================
# FLATTEN BOM TREE
# =====================================================

def flatten_bom(items, multiplier=1):

    final_items = []

    for it in items:

        qty = it["qty"] * multiplier

        if "items" in it:

            final_items.extend(
                flatten_bom(it["items"], qty)
            )

        else:

            final_items.append({
                "item_code": it["item_code"],
                "qty": qty
            })

    return final_items



# =====================================================
# RESOLVE SALES ORDER ITEMS
# =====================================================

def resolve_sales_order_items(so_name):

    final_items = []

    so = frappe.get_value(
        "Sales Order",
        so_name,
        ["custom_magic_box"],
        as_dict=1
    )

    # -----------------------------
    # MAGIC BOX
    # -----------------------------

    if so and so.custom_magic_box:

        rows = frappe.get_all(
            "Sale Order Sub Items",
            filters={"parent": so_name},
            fields=["item_code", "qty"]
        )

        for r in rows:
            final_items.append({
                "item_code": r.item_code,
                "qty": r.qty
            })

        return final_items


    # -----------------------------
    # NORMAL SALES ORDER ITEMS
    # -----------------------------

    so_items = frappe.get_all(
        "Sales Order Item",
        filters={"parent": so_name},
        fields=["item_code", "qty"]
    )

    for item in so_items:

        item_group = frappe.get_value(
            "Item",
            item.item_code,
            "item_group"
        )

        # -----------------------------
        # BOOK BUNDLE
        # -----------------------------

        if item_group == "Books Bundle":

            bom_tree = resolve_bom_tree(item.item_code)

            flat_items = flatten_bom(bom_tree, item.qty)

            final_items.extend(flat_items)

        else:

            final_items.append({
                "item_code": item.item_code,
                "qty": item.qty
            })

    return final_items




# =====================================================
# GET BUNDLE ITEMS (EXPLODE)
# =====================================================

def get_bundle_items(item_code, qty=1):

    bom_tree = resolve_bom_tree(item_code)

    if not bom_tree:
        return []

    return flatten_bom(bom_tree, qty)


# =====================================================
# STORE BUNDLE ITEMS IN SALES ORDER
# =====================================================

def append_bundle_items_to_so(so, parent_item_code, qty):

    try:

        qty = int(qty)
        bundle_items = get_bundle_items(parent_item_code, qty)

        for bi in bundle_items:

            so.append("custom_sub_items", {
                "parent_item_code": parent_item_code,
                "item_code": bi["item_code"],
                "qty": bi["qty"]
            })
    except Exception as e:
        frappe.log_error(f"Error while appending bundle items for {parent_item_code} - {str(e)}", "append_bundle_items_to_so")
