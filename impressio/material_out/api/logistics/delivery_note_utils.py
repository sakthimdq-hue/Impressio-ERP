"""
delivery_note_utils.py
Whitelisted APIs to create Handover To Logistics docs from Delivery Notes.
Rule: 1 Delivery Note = 1 Handover To Logistics document (all items in same handover)
"""

import frappe
from frappe import _
from frappe.utils import today, nowtime
from impressio.material_out.api.logistics.utils import get_item_description

# ══════════════════════════════════════════════════════════════════════════════
# SINGLE DN → CREATE HANDOVER (called from DN form)
# ══════════════════════════════════════════════════════════════════════════════

# @frappe.whitelist()
# def create_handover_from_dn(delivery_note):
#     """
#     Create ONE Handover To Logistics for the entire Delivery Note.
#     All items from the DN are included in a single handover document.
#     No carrier selection here — user picks carrier on the Handover form itself.
#     Called from the DN form when user clicks 'Create Handover'.
#     """
#     logistics_partner = ""   # blank — user selects on Handover form
#     try:
#         dn = frappe.get_doc("Delivery Note", delivery_note)

#         if dn.docstatus != 1:
#             frappe.throw(_("Delivery Note must be submitted before creating handovers."))

#         # Check if handover already exists for this Delivery Note
#         existing_handover = _get_existing_handover_for_dn(delivery_note)
        
#         if existing_handover:
#             return {
#                 "success": False,
#                 "message": _("Handover already exists for this Delivery Note: {0}").format(existing_handover),
#                 "existing_handover": existing_handover
#             }

#         try:
#             handover_name = _create_single_handover_for_dn(
#                 dn = dn,
#                 logistics_partner = logistics_partner,
#             )
            
#             frappe.db.commit()

#             return {
#                 "success": True,
#                 "message": _("Handover created successfully"),
#                 "handover": handover_name,
#                 "delivery_note": delivery_note,
#                 "items_count": len(dn.items)
#             }
            
#         except Exception as exc:
#             frappe.log_error(
#                 title=f"Handover Creation Failed - {delivery_note}",
#                 message=frappe.get_traceback()
#             )
#             frappe.throw(_("Failed to create handover: {0}").format(str(exc)))

#     except frappe.exceptions.ValidationError:
#         raise
#     except Exception as exc:
#         frappe.log_error(
#             title=f"create_handover_from_dn failed - {delivery_note}",
#             message=frappe.get_traceback()
#         )
#         frappe.throw(_("Failed to create handover: {0}").format(str(exc)))
@frappe.whitelist()
def create_handover_from_dn(delivery_note, weight=None, length=None, width=None, height=None,declared_value=None):
    """
    Create ONE Handover To Logistics for the entire Delivery Note.
    """
    logistics_partner = ""   # blank — user selects on Handover form
    
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note)

        if dn.docstatus != 1:
            frappe.throw("Delivery Note must be submitted before creating handovers.")

        # CHECK FOR EXISTING HANDOVER - THIS BLOCKS DUPLICATES
        existing = frappe.db.get_value(
            "Handover To Logistics", 
            # {"delivery_note": delivery_note}, 
            {"delivery_note": delivery_note, "docstatus": ["!=", 2]},
            "name"
        )
        
        if existing:
            frappe.throw(
                f"Cannot create duplicate handover!\n\n"
                f"Delivery Note {delivery_note} already has Handover {existing}"
            )

        # Create new handover
        # handover_name = _create_single_handover_for_dn(
        #     dn = dn,
        #     logistics_partner = logistics_partner,
        # )
        handover_name = _create_single_handover_for_dn(
            dn = dn,
            logistics_partner = logistics_partner,
            weight = float(weight) if weight else None,
            length = float(length) if length else None,
            width  = float(width)  if width  else None,
            height = float(height) if height else None,
        )
        
        frappe.db.commit()

        return {
            "success": True,
            "message": "Handover created successfully",
            "handover": handover_name,
            "delivery_note": delivery_note,
        }
        
    except Exception as exc:
        frappe.log_error(
            title=f"Handover Creation Failed - {delivery_note}",
            message=frappe.get_traceback()
        )
        frappe.throw(f"Failed to create handover: {str(exc)}")
        
        


# ══════════════════════════════════════════════════════════════════════════════
# BULK DN → CREATE HANDOVERS (called from DN list)
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def bulk_create_handovers_from_dns(delivery_notes,weight=None, length=None, width=None, height=None, declared_value=None):
    """
    Bulk create Handover To Logistics for multiple Delivery Notes.
    Creates ONE handover per Delivery Note (all items combined).
    Called from DN list view.

    delivery_notes: JSON string or list of DN names
    """
    import json

    if isinstance(delivery_notes, str):
        delivery_notes = json.loads(delivery_notes)

    if not delivery_notes:
        frappe.throw(_("No Delivery Notes provided."))

    logistics_partner = ""   # blank — user selects on Handover form

    all_results = {
        "created":       [],
        "skipped":       [],
        "failed":        [],
        "created_count": 0,
        "skipped_count": 0,
        "failed_count":  0,
    }

    for dn_name in delivery_notes:
        try:
            dn = frappe.get_doc("Delivery Note", dn_name)

            # Skip non-submitted DNs silently in bulk
            if dn.docstatus != 1:
                all_results["failed"].append({
                    "delivery_note": dn_name,
                    "error": "Delivery Note is not submitted"
                })
                all_results["failed_count"] += 1
                continue

            # Check if handover already exists for this DN
            existing_handover = _get_existing_handover_for_dn(dn_name)
            
            if existing_handover:
                all_results["skipped"].append({
                    "delivery_note": dn_name,
                    "handover": existing_handover,
                    "reason": "Already has a handover"
                })
                all_results["skipped_count"] += 1
                continue

            try:
                handover_name = _create_single_handover_for_dn(
                    dn = dn,
                    logistics_partner = logistics_partner,
                    weight=float(weight) if weight else None,
                    length=float(length) if length else None,
                    width=float(width)   if width  else None,
                    height=float(height) if height else None,
                    declared_value=float(declared_value) if declared_value else None,
                )
                
                all_results["created"].append({
                    "delivery_note": dn_name,
                    "handover": handover_name,
                    "items_count": len(dn.items),
                })
                all_results["created_count"] += 1

            except Exception as exc:
                frappe.log_error(
                    title=f"Bulk Handover Failed - {dn_name}",
                    message=frappe.get_traceback()
                )
                all_results["failed"].append({
                    "delivery_note": dn_name,
                    "error": str(exc),
                })
                all_results["failed_count"] += 1

        except Exception as exc:
            all_results["failed"].append({
                "delivery_note": dn_name,
                "error": str(exc),
            })
            all_results["failed_count"] += 1

    frappe.db.commit()
    return all_results


# ══════════════════════════════════════════════════════════════════════════════
# CHECK STATUS — whether DN already has handover
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_dn_handover_status(delivery_note):
    """
    Returns status of Delivery Note — does it already have a handover?
    Called from JS to show status.
    """
    dn = frappe.get_doc("Delivery Note", delivery_note)
    handover_name = _get_existing_handover_for_dn(delivery_note)
    
    handover_details = None
    if handover_name:
        handover_details = frappe.db.get_value(
            "Handover To Logistics",
            handover_name,
            ["logistics_tracking_number", "carrier_status", "logistics_partner", "name"],
            as_dict=True
        )

    return {
        "delivery_note": delivery_note,
        "customer": dn.customer_name,
        "has_handover": bool(handover_name),
        "handover": handover_details,
        "total_items": len(dn.items),
    }


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_existing_handover_for_dn(delivery_note):
    """
    Returns name of Handover To Logistics document for this Delivery Note if exists.
    Uses delivery_note field on Handover doctype.
    """
    meta = frappe.get_meta("Handover To Logistics")

    if meta.get_field("delivery_note"):
        # Check if handover exists for this DN (excluding cancelled docs)
        handover = frappe.db.get_value(
            "Handover To Logistics",
            {"delivery_note": delivery_note, "docstatus": ["!=", 2]},
            "name"
        )
        return handover

    return None


def _create_single_handover_for_dn(dn, logistics_partner, weight=None, length=None, width=None, height=None, declared_value=None):
    """
    Creates a single Handover To Logistics for the entire Delivery Note.
    All items from DN are included in packing_materials table.
    Uses Delivery Note ID as the primary reference instead of Sales Order.
    ALL SHIPMENTS ARE FORCED TO PREPAID WITH 0 COD AMOUNT
    """
    settings = frappe.get_single("Logistics Settings")

    # ── Address from DN shipping address ──────────────────────────────────────
    address_line1 = ""
    address_line2 = ""
    city          = ""
    state         = ""
    pincode       = settings.warehouse_pincode or "560001"
    phone         = ""

    if dn.shipping_address_name:
        try:
            addr = frappe.get_doc("Address", dn.shipping_address_name)
            address_line1 = addr.address_line1 or ""
            address_line2 = addr.address_line2 or ""
            city          = addr.city          or ""
            state         = addr.state         or ""
            pincode       = addr.pincode       or pincode
            phone         = addr.phone         or ""
        except Exception:
            pass

    # Fallback to customer address
    if not address_line1 and dn.customer_address:
        try:
            addr = frappe.get_doc("Address", dn.customer_address)
            address_line1 = addr.address_line1 or ""
            city          = addr.city          or ""
            state         = addr.state         or ""
            pincode       = addr.pincode       or pincode
            phone         = addr.phone         or ""
        except Exception:
            pass

    # Get phone from contact if still missing
    if not phone and dn.contact_mobile:
        phone = dn.contact_mobile

    full_address = "\n".join(filter(None, [address_line1, address_line2]))

    # ── Calculate totals across all items ────────────────────────────────────
    total_weight = 0
    total_value = 0
    
    # FORCE ALL SHIPMENTS TO BE PREPAID
    payment_type = "Prepaid"
    total_cod_amount = 0  # Always 0 for prepaid
    
    # Track items for packing_materials table
    packing_items = []
    
    for item in dn.items:
        # Item weight
        pm_weight = float(
            frappe.db.get_value("Item", item.item_code, "pm_weight") 
            or item.get("weight_per_unit") 
            or 0.5
        )
        item_weight = pm_weight * float(item.qty or 1)
        total_weight += item_weight
        
        # Item value
        item_value = float(item.amount or item.rate or 0) * float(item.qty or 1)
        total_value += item_value
        
        # REMOVED: All COD logic - No longer needed since all shipments are prepaid
        
        # Get dimensions from Item master
        try:
            item_master = frappe.db.get_value(
                "Item",
                item.item_code,
                ["pm_length", "pm_width", "pm_height", "pm_weight", "weight_per_unit"],
                as_dict=True
            ) or {}
        except Exception:
            item_master = {}
        
        pm_length = float(item_master.get("pm_length") or 0)
        pm_width  = float(item_master.get("pm_width")  or 0)
        pm_height = float(item_master.get("pm_height") or 0)
        pm_weight = float(
            item_master.get("pm_weight")
            or item_master.get("weight_per_unit")
            or item.get("weight_per_unit")
            or 0.5
        )
        
        packing_items.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "uom": item.uom or "Nos",
            "pm_length": pm_length,
            "pm_width": pm_width,
            "pm_height": pm_height,
            "pm_weight": pm_weight,
            "dn_detail": item.name,  # Link to DN item row
        })

    # ── Create Handover doc ───────────────────────────────────────────────────
    effective_carrier = (
        logistics_partner
        or getattr(settings, "default_carrier", "")
        or "Ekart"
    )

    handover = frappe.new_doc("Handover To Logistics")

    handover.status            = "Pending"
    handover.logistics_partner = effective_carrier

    # Link fields - Use Delivery Note as primary reference
    handover.delivery_note  = dn.name  # Link to Delivery Note
    handover.order_no       = dn.name  # Use DN number as order_no (not SO)
    
    # Get first Sales Order if needed for reference
    first_so = None
    for item in dn.items:
        if item.get("against_sales_order"):
            first_so = item.against_sales_order
            break
    handover.sales_order = first_so  # Optional reference

    # Customer info
    handover.customer_name    = dn.customer_name or dn.customer
    handover.customer_phone   = phone

    # Address
    handover.address          = full_address or settings.warehouse_address or ""
    handover.location         = city
    handover.city             = city
    handover.state            = state
    handover.pincode          = str(pincode).strip()

    # Package totals - Use provided dimensions or calculate
    handover.weight           = round(weight, 3) if weight else round(total_weight, 3)
    handover.length           = length if length else 0
    handover.width            = width  if width  else 0
    handover.height           = height if height else 0
    handover.declared_value   = declared_value if declared_value else total_value
    handover.invoice_number   = dn.name
    handover.invoice_value    = declared_value if declared_value else total_value
   

    # FORCE PREPAID - ALL SHIPMENTS ARE PREPAID WITH 0 COD
    handover.payment_type     = "Prepaid"
    handover.cod_amount       = 0

    # Dates
    handover.handover_date    = today()
    handover.handover_time    = nowtime()

    # Add all items as packing materials
    for item_data in packing_items:
        handover.append("packing_materials", item_data)
    
    handover.description      = get_item_description(handover)

    handover.insert(ignore_permissions=True)

    return handover.name

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY for bulk dialog
# ══════════════════════════════════════════════════════════════════════════════

# @frappe.whitelist()
# def get_bulk_dn_summary(delivery_notes):
#     """
#     Returns total DNs, pending DNs, skipped DNs across multiple Delivery Notes.
#     Used to populate the bulk creation dialog summary.
#     """
#     import json
#     if isinstance(delivery_notes, str):
#         delivery_notes = json.loads(delivery_notes)

#     total_dns = len(delivery_notes)
#     skipped_dns = 0
#     total_items = 0

#     for dn_name in delivery_notes:
#         try:
#             dn = frappe.get_doc("Delivery Note", dn_name)
#             existing = _get_existing_handover_for_dn(dn_name)
#             total_items += len(dn.items)
#             if existing:
#                 skipped_dns += 1
#         except Exception:
#             pass

#     return {
#         "total_dns": total_dns,
#         "pending_dns": total_dns - skipped_dns,
#         "skipped_dns": skipped_dns,
#         "total_items": total_items,
#     }

@frappe.whitelist()
def get_bulk_dn_summary(delivery_notes):
    """
    Returns total DNs, pending DNs, skipped DNs across multiple Delivery Notes.
    Used to populate the bulk creation dialog summary.
    """
    import json
    if isinstance(delivery_notes, str):
        delivery_notes = json.loads(delivery_notes)

    total_dns = len(delivery_notes)
    skipped_dns = 0
    total_items = 0
    pending_items = 0  # Add this

    for dn_name in delivery_notes:
        try:
            dn = frappe.get_doc("Delivery Note", dn_name)
            existing = _get_existing_handover_for_dn(dn_name)
            total_items += len(dn.items)
            if existing:
                skipped_dns += 1
            else:
                pending_items += len(dn.items)  # Count pending items
        except Exception:
            pass

    return {
        "total_dns": total_dns,
        "pending_dns": total_dns - skipped_dns,
        "skipped_dns": skipped_dns,
        "total_items": total_items,
        "pending_items": pending_items,  # Add this for the UI
    }


# ══════════════════════════════════════════════════════════════════════════════
# CREATE AND SUBMIT DN — single server-side call (avoids BrokenPipeError)
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def create_and_submit_dn(sales_order, selected_items):
    """
    Creates and submits a Delivery Note from a Sales Order.
    Uses long_timeout=True to avoid BrokenPipeError on slow connections.
    selected_items: JSON list of {so_detail, qty}
    """
    import json

    if isinstance(selected_items, str):
        selected_items = json.loads(selected_items)

    selected_map = {item["so_detail"]: float(item["qty"]) for item in selected_items}

    if not selected_map:
        frappe.throw(_("No items selected."))

    # Use ERPNext make_delivery_note for correct SO→DN mapping
    from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
    dn = make_delivery_note(sales_order)

    # Filter to only selected items
    filtered_items = []
    for item in dn.items:
        if item.so_detail in selected_map:
            item.qty    = selected_map[item.so_detail]
            item.amount = item.qty * (item.rate or 0)
            filtered_items.append(item)

    if not filtered_items:
        frappe.throw(_(
            "No matching items found for Sales Order {0}. "
            "Please try again."
        ).format(sales_order))

    dn.items        = filtered_items
    dn.posting_date = frappe.utils.today()

    # Insert as draft
    dn.flags.ignore_permissions = True
    dn.insert(ignore_permissions=True)
    dn_name = dn.name

    # Submit — wrapped in try/catch, deletes draft if fails
    try:
        dn.flags.ignore_permissions = True
        dn.submit()
        frappe.db.commit()
    except Exception as exc:
        try:
            frappe.delete_doc("Delivery Note", dn_name,
                              force=1, ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass
        frappe.log_error(
            title=f"DN Submit Failed — {sales_order}",
            message=frappe.get_traceback()
        )
        frappe.throw(_("Submit failed: {0}").format(str(exc)))

    return {
        "success":       True,
        "delivery_note": dn_name,
        "sales_order":   sales_order,
        "items_count":   len(filtered_items),
    }
    
# ══════════════════════════════════════════════════════════════════════════════
# TRACKING NORMALIZER
# ══════════════════════════════════════════════════════════════════════════════

AMAZON_STATUS_MAP = {
    "ReadyForReceive":          "Handover Created",
    "PickupDone":               "Picked Up",
    "ArrivedAtCarrierFacility": "Reached Hub",
    "Departed":                 "In Transit",
    "OutForDelivery":           "Out for Delivery",
    "Delivered":                "Delivered",
    "DeliveryAttempted":        "Delivery Attempted",
    "Cancelled":                "Cancelled",
    "Lost":                     "Lost",
    "Returned":                 "Returned",
}

EKART_STATUS_MAP = {
    "Handover Created":   "Handover Created",
    "Picked Up":          "Picked Up",
    "Reached Hub":        "Reached Hub",
    "In Transit":         "In Transit",
    "Out for Delivery":   "Out for Delivery",
    "Delivered":          "Delivered",
    "Delivery Attempted": "Delivery Attempted",
    "Cancelled":          "Cancelled",
    "Returned":           "Returned",
}


def _format_amazon_date(iso_date):
    """Convert 2026-03-14T04:09:49Z → 14-Mar-2026 04:09:00"""
    from datetime import datetime
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%d-%b-%Y %H:%M:%S")
    except Exception:
        return iso_date or ""


def _normalize_amazon(raw):
    payload        = raw.get("payload", {})
    summary        = payload.get("summary", {})
    events         = payload.get("eventHistory", [])
    raw_status     = summary.get("status", "")
    current_status = AMAZON_STATUS_MAP.get(raw_status, raw_status)

    history = []
    for event in events:
        loc          = event.get("location", {})
        city         = (loc.get("city") or "").title()
        state        = (loc.get("stateOrRegion") or "").title()
        location_str = ", ".join(filter(None, [city, state])) or "—"
        raw_code     = event.get("eventCode", "")
        mapped       = AMAZON_STATUS_MAP.get(raw_code, raw_code)
        history.append({
            "date":        _format_amazon_date(event.get("eventTime", "")),
            "status":      mapped,
            "location":    location_str,
            "description": mapped,
        })

    history.reverse()  # latest first

    return {
        "shipping_partner": "Amazon",
        "tracking_number":  payload.get("trackingId", ""),
        "status":           current_status,
        "tracking_history": history,
    }


def _normalize_ekart(raw):
    history = []
    for event in raw.get("tracking_history", []):
        history.append({
            "date":        event.get("date", ""),
            "status":      EKART_STATUS_MAP.get(event.get("status", ""), event.get("status", "")),
            "location":    event.get("location", "—"),
            "description": event.get("description", ""),
        })
    return {
        "shipping_partner": "Ekart",
        "tracking_number":  raw.get("tracking_number", ""),
        "status":           EKART_STATUS_MAP.get(raw.get("status", ""), raw.get("status", "")),
        "tracking_history": history,
    }


def normalize_tracking_response(shipping_partner, raw_response):
    """Routes to correct normalizer based on shipping partner."""
    partner = (shipping_partner or "").strip().lower()
    if partner == "amazon":
        return _normalize_amazon(raw_response)
    elif partner == "ekart":
        return _normalize_ekart(raw_response)
    else:
        frappe.throw(_(f"Unsupported shipping partner: {shipping_partner}"))


@frappe.whitelist()
def update_tracking_status(delivery_note, shipping_partner, raw_response):
    """Normalizes tracking response and saves to Delivery Note tracking_status field."""
    import json
    from frappe.utils import now

    if isinstance(raw_response, str):
        raw_response = json.loads(raw_response)

    normalized = normalize_tracking_response(shipping_partner, raw_response)
    normalized["last_updated"]  = now()
    normalized["delivery_note"] = delivery_note

    frappe.db.set_value(
        "Delivery Note",
        delivery_note,
        "tracking_status",
        json.dumps(normalized),
        update_modified=False
    )
    frappe.db.commit()

    return {
        "success":    True,
        "message":    f"Tracking updated for {delivery_note}",
        "normalized": normalized,
    }


@frappe.whitelist()
def get_tracking_status(delivery_note):
    """Returns normalized tracking status from Delivery Note."""
    import json
    raw = frappe.db.get_value("Delivery Note", delivery_note, "tracking_status")
    if not raw:
        return {"success": False, "message": "No tracking data found"}
    return {"success": True, "tracking": json.loads(raw)}



@frappe.whitelist()
def validate_dns_for_delivery(delivery_notes):
    """
    For each DN, check:
      1. A non-cancelled Handover To Logistics exists with a logistics_tracking_number
      2. That HLG's carrier_status == "Delivered"
 
    Returns three buckets:
      eligible       — AWB exists AND carrier_status = "Delivered"
      no_awb         — no HLG found, or HLG exists but tracking number is blank
      not_delivered  — AWB exists but carrier_status is not "Delivered"
    """
    import json
 
    if isinstance(delivery_notes, str):
        delivery_notes = json.loads(delivery_notes)
 
    eligible      = []
    no_awb        = []
    not_delivered = []
 
    for dn_name in delivery_notes:
        try:
            dn = frappe.get_doc("Delivery Note", dn_name)
            customer = dn.customer_name or dn.customer or dn_name
 
            # Find the HLG for this DN (non-cancelled)
            hlg_data = frappe.db.get_value(
                "Handover To Logistics",
                {"delivery_note": dn_name, "docstatus": ["!=", 2]},
                ["name", "logistics_tracking_number", "carrier_status"],
                as_dict=True
            )
 
            if not hlg_data or not hlg_data.get("logistics_tracking_number"):
                no_awb.append({
                    "dn":       dn_name,
                    "customer": customer,
                    "hlg":      hlg_data.get("name") if hlg_data else None,
                })
                continue
 
            tracking_number = hlg_data.get("logistics_tracking_number")
            carrier_status  = hlg_data.get("carrier_status") or ""
 
            if carrier_status.strip().lower() == "delivered":
                eligible.append({
                    "dn":              dn_name,
                    "customer":        customer,
                    "hlg":             hlg_data.get("name"),
                    "tracking_number": tracking_number,
                    "carrier_status":  carrier_status,
                })
            else:
                not_delivered.append({
                    "dn":              dn_name,
                    "customer":        customer,
                    "hlg":             hlg_data.get("name"),
                    "tracking_number": tracking_number,
                    "carrier_status":  carrier_status,
                })
 
        except Exception as exc:
            frappe.log_error(
                title=f"validate_dns_for_delivery failed - {dn_name}",
                message=frappe.get_traceback()
            )
            no_awb.append({
                "dn":       dn_name,
                "customer": dn_name,
                "error":    str(exc),
            })
 
    return {
        "eligible":      eligible,
        "no_awb":        no_awb,
        "not_delivered": not_delivered,
    }
 
 
# ══════════════════════════════════════════════════════════════════════════════
# BULK MARK DELIVERED
# Append this function to delivery_note_utils.py
# ══════════════════════════════════════════════════════════════════════════════
 
@frappe.whitelist()
def bulk_mark_delivered(delivery_notes, delivered_date):
    """
    Bulk mark multiple Delivery Notes as delivered.
    Sets:
        custom_is_delivered   = 1
        custom_delivered_date = delivered_date
 
    Also injects a synthetic "Delivered" event into custom_status_tracking
    so the tracking timeline stays consistent.
 
    delivery_notes : JSON string or list of DN names
    delivered_date : date string "YYYY-MM-DD"
    """
    import json
 
    if isinstance(delivery_notes, str):
        delivery_notes = json.loads(delivery_notes)
 
    if not delivery_notes:
        frappe.throw(_("No Delivery Notes provided."))
 
    if not delivered_date:
        frappe.throw(_("Delivered date is required."))
 
    results = {
        "success":       [],
        "failed":        [],
        "success_count": 0,
        "failed_count":  0,
    }
 
    for dn_name in delivery_notes:
        try:
            if not frappe.db.exists("Delivery Note", dn_name):
                results["failed"].append({
                    "delivery_note": dn_name,
                    "error": "Delivery Note not found"
                })
                results["failed_count"] += 1
                continue
 
            # Mark as delivered
            frappe.db.set_value(
                "Delivery Note",
                dn_name,
                {
                    "custom_is_delivered":   1,
                    "custom_delivered_date": delivered_date,
                },
                update_modified=False
            )
 
            # Keep custom_status_tracking in sync if it exists
            raw = frappe.db.get_value("Delivery Note", dn_name, "custom_status_tracking")
            if raw:
                try:
                    tracking = json.loads(raw)
 
                    # Update top-level status
                    tracking["status"] = "Delivered"
 
                    # Inject a synthetic delivery event (avoid duplicates)
                    delivery_event = {
                        "date":        delivered_date,
                        "status":      "Delivered",
                        "location":    "N/A",
                        "description": "Marked as delivered manually"
                    }
                    history = tracking.get("tracking_history", [])
                    already_marked = any(
                        e.get("description") == "Marked as delivered manually"
                        for e in history
                    )
                    if not already_marked:
                        history.append(delivery_event)
                        tracking["tracking_history"] = history
 
                    frappe.db.set_value(
                        "Delivery Note",
                        dn_name,
                        "custom_status_tracking",
                        json.dumps(tracking),
                        update_modified=False
                    )
                except Exception:
                    pass  # Don't fail the whole record if JSON is malformed
 
            results["success"].append({"delivery_note": dn_name})
            results["success_count"] += 1
 
        except Exception as exc:
            frappe.log_error(
                title=f"bulk_mark_delivered failed - {dn_name}",
                message=frappe.get_traceback()
            )
            results["failed"].append({
                "delivery_note": dn_name,
                "error":         str(exc)
            })
            results["failed_count"] += 1
 
    frappe.db.commit()
    return results