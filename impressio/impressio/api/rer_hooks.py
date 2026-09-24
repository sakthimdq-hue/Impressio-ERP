import frappe


# ─────────────────────────────────────────────────────────────────────────────
# hooks.py  →  add this line:
#
#   doc_events = {
#       "Return Exchange Request": {
#           "before_save": "impressio.impressio.api.rer_hooks.before_save"
#       }
#   }
# ─────────────────────────────────────────────────────────────────────────────


def before_save(doc, method=None):
    """
    Entry point called by Frappe before every RER save.

    Guard conditions (all must pass before touching anything):
      1. Status must be "Approved" on this save.
      2. A Return Delivery Note must not already be linked.
      3. Status must be *changing* to Approved, not already Approved
         (prevents re-running on unrelated saves of an approved doc).
    """
    if doc.status != "Approved":
        return

    if doc.return_delivery_note:
        return

    prev = doc.get_doc_before_save()
    if prev and prev.status == "Approved":
        return                            # already was Approved — no-op

    _create_return_delivery_note(doc)


# ─────────────────────────────────────────────────────────────────────────────
# CORE LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def _create_return_delivery_note(rer):
    """
    Creates a submitted Return Delivery Note scoped to rer.delivery_note.

    Key fix: We now copy `dn_detail` (the row `name` from the original DN
    items table) into each return item row. ERPNext's internal
    validate_returned_quantity uses this field to match return items back
    to their source row — without it, the submit throws:
        "Returned Item X does not exist in Delivery Note Y"

    Linkage rules (mirrors how get_dn_items_for_so reads them):
      - If the original DN item row had against_sales_order set
        → copy it as-is  (dn_normal path)
      - If it had custom_custom_against_sales_order set instead
        → copy that field  (dn_sub path)
    """
    original_dn = frappe.get_doc("Delivery Note", rer.delivery_note)

    # ── Build a lookup: item_code → first matching DN item row ───────────
    # We need the full row (name, linkage fields, rate, uom, etc.)
    dn_item_row_map = {}
    for row in original_dn.items:
        if row.item_code not in dn_item_row_map:
            dn_item_row_map[row.item_code] = row

    # ── Validate every RERI item exists in the original DN ───────────────
    missing = [
        reri.old_item_code
        for reri in rer.return_exchange_request_item
        if reri.old_item_code not in dn_item_row_map
    ]
    if missing:
        frappe.throw(
            f"The following items were not found in Delivery Note "
            f"{rer.delivery_note}: {', '.join(missing)}",
            title="Return DN creation failed"
        )

    # ── Build the Return DN header ────────────────────────────────────────
    return_dn = frappe.new_doc("Delivery Note")
    return_dn.is_return          = 1
    return_dn.return_against     = rer.delivery_note
    return_dn.customer           = original_dn.customer
    return_dn.company            = original_dn.company
    return_dn.posting_date       = frappe.utils.today()
    return_dn.set_warehouse      = original_dn.set_warehouse or "Stores - IESPL"
    return_dn.currency           = original_dn.currency

    # ── Append one return item per RERI row ───────────────────────────────
    for reri in rer.return_exchange_request_item:
        src = dn_item_row_map[reri.old_item_code]

        return_dn.append("items", {
            "item_code":          reri.old_item_code,
            "qty":                -abs(int(reri.qty)),   # return DNs store negative qty
            "warehouse":          src.warehouse or return_dn.set_warehouse,
            "uom":                src.uom,
            "stock_uom":          src.stock_uom,
            "conversion_factor":  src.conversion_factor or 1,

            # ── Critical: row name from original DN items table ───────────
            # ERPNext's validate_returned_quantity matches return items
            # back to source rows using this field. Without it, submit
            # throws "Returned Item X does not exist in Delivery Note Y".
            "dn_detail":          src.name,

            # ── Pricing — required for return valuation ───────────────────
            "rate":               src.rate,
            "price_list_rate":    src.price_list_rate or src.rate,

            # ── SO linkage — copy whichever field the original row used ───
            # Preserves get_dn_items_for_so net_qty_map subtraction logic.
            "against_sales_order":
                src.against_sales_order or "",

            "custom_custom_against_sales_order":
                src.get("custom_custom_against_sales_order") or "",

            # Preserve SO detail row reference (important for qty tracking)
            "so_detail":          src.so_detail or "",
        })

    # ── Insert + submit ───────────────────────────────────────────────────
    try:
        return_dn.flags.ignore_permissions = True
        return_dn.flags.ignore_mandatory   = True
        return_dn.insert(ignore_permissions=True)
        return_dn.submit()
        frappe.db.commit()

    except Exception:
        # If insert succeeded but submit failed, cancel the draft DN
        # so it doesn't sit as a stuck draft in the system.
        try:
            if return_dn.name and frappe.db.exists("Delivery Note", return_dn.name):
                stuck = frappe.get_doc("Delivery Note", return_dn.name)
                if stuck.docstatus == 0:
                    stuck.flags.ignore_permissions = True
                    frappe.delete_doc(
                        "Delivery Note",
                        return_dn.name,
                        force=True,
                        ignore_permissions=True
                    )
                    frappe.db.commit()
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Cleanup of stuck draft DN failed for RER {rer.name}"
            )

        frappe.log_error(
            frappe.get_traceback(),
            f"_create_return_delivery_note failed for RER {rer.name}"
        )
        frappe.throw(
            "Failed to create Return Delivery Note automatically. "
            "Please check the error log and create it manually.",
            title="Return DN creation failed"
        )

    # ── Write back to RER (before_save → will be saved with the doc) ─────
    rer.return_delivery_note = return_dn.name

    frappe.msgprint(
        f"Return Delivery Note <b>{return_dn.name}</b> created and submitted.",
        indicator="green",
        alert=True
    )