import frappe
from datetime import timedelta
from frappe.utils import now_datetime

from impressio.impressio.api.helper import get_payment_provider_details, map_pinelabs_status
from impressio.impressio.api.payments import pinelabs_fetch_order, finalize_pinelabs_payment


# ------------------------------------------------
# CONFIG
# ------------------------------------------------
RETRY_AFTER_MINUTES = 3 * 60      # 3 hours
PAYMENT_EXPIRY_MINUTES = 72 * 60  # 72 hours
LOOKBACK_WINDOW_MINUTES = 45 * 24 * 60  # 30 days
MAX_RETRY = 26

# ------------------------------------------------
# MAIN RECONCILE FUNCTION
# ------------------------------------------------
@frappe.whitelist(allow_guest=True)
def reconcile_pending_orders():


    now = now_datetime()
    retry_cutoff = now - timedelta(minutes=RETRY_AFTER_MINUTES)
    creation_cutoff = now - timedelta(minutes=LOOKBACK_WINDOW_MINUTES)
    
    # ------------------------------------------------
    # FETCH PENDING PINELABS ORDERS
    # ------------------------------------------------

    orders = frappe.get_all(
        "Sales Order",
        filters={
            "custom_order_submit_error": 0,
            "custom_gateway_provider": "PINELABS",
            "custom_payment_finalized": 0,
            "docstatus": ["in", [0]],  # ← CRITICAL FIX
            "creation": [">=", creation_cutoff],
            # "custom_payment_status": ["in", ["INITIATED", "VERIFYING", "AWAITED", "AWAIT", "SHIPPED", "PENDING"]],
        },
        or_filters=[
            ["custom_payment_status_last_checked", "is", "not set"],
            ["custom_payment_status_last_checked", "<=", retry_cutoff],
        ],
        fields=[
            "name",
            "creation",
            "custom_payment_status",
            "custom_gateway_order_id",
            "custom_payment_finalized",
            "custom_order_submit_error",
            "custom_payment_status_last_checked",
            "custom_payment_status_retry_count",

        ],
        order_by="creation DESC",
        limit=50
    )

    if not orders:
        return {"message": "No pending PineLabs orders"}

    results = {}

    # return orders

    # ------------------------------------------------
    # LOAD CONFIG ONCE
    # ------------------------------------------------
    ctx = get_payment_provider_details(None, "PINELABS")
    if not ctx:
        return {"error": "PineLabs config missing"}

    config = ctx["gateway"]

    # ------------------------------------------------
    # GROUP BY ORDER_ID (IMPORTANT)
    # ------------------------------------------------
    order_map = {}

    for row in orders:
        order_id = row.custom_gateway_order_id
        if not order_id:
            continue

        order_map.setdefault(order_id, []).append(row.name)

    # ------------------------------------------------
    # PROCESS EACH ORDER_ID
    # ------------------------------------------------
    for order_id, so_names in order_map.items():

        try:
            order_data = pinelabs_fetch_order(order_id, config)

            # return order_data

            if not order_data:
                for so_name in so_names:
                    so = frappe.get_doc("Sales Order", so_name)

                    so.custom_payment_status_last_checked = now
                    so.custom_payment_status_retry_count = (so.custom_payment_status_retry_count or 0) + 1

                    so.save(ignore_permissions=True)

                results[order_id] = {
                    "status": "API_FAILED"
                }
                continue

            pine_status = order_data.get("status")
            mapped_status = map_pinelabs_status(pine_status)

            # return mapped_status

            # ------------------------------------------------
            # SUCCESS → finalize once (handles all SOs)
            # ------------------------------------------------
            if mapped_status == "SUCCESS":
                finalize_pinelabs_payment(order_data)

                results[order_id] = {
                    "status": "SUCCESS",
                    "action": "FINALIZED"
                }
                continue

            # ------------------------------------------------
            # FAILED → mark all SOs
            # ------------------------------------------------
            elif mapped_status == "FAILED":

                for so_name in so_names:
                    so = frappe.get_doc("Sales Order", so_name)

                    so.custom_payment_status = "FAILED"
                    so.payment_status = "FAILED"
                    so.custom_payment_finalized = 1
                    so.custom_gateway_response_message = "Marked failed via reconcile"

                    so.custom_payment_status_last_checked = now
                    so.custom_payment_status_retry_count = (so.custom_payment_status_retry_count or 0) + 1

                    so.save(ignore_permissions=True)

                results[order_id] = {
                    "status": "FAILED",
                    "action": "MARKED_FAILED"
                }
                continue

            # ------------------------------------------------
            # PENDING → update retry tracking
            # ------------------------------------------------
            else:
                for so_name in so_names:
                    so = frappe.get_doc("Sales Order", so_name)

                    # expiry check
                    expiry_time = so.creation + timedelta(minutes=PAYMENT_EXPIRY_MINUTES)

                    if now >= expiry_time:
                        so.custom_payment_status = "EXPIRED"
                        so.payment_status = "EXPIRED"
                        so.custom_payment_finalized = 1
                        so.custom_gateway_response_message = "Expired after 72h"

                        results[so_name] = {
                            "status": "EXPIRED"
                        }

                    else:
                        so.custom_payment_status = "PENDING"

                        results[so_name] = {
                            "status": "PENDING"
                        }

                    so.custom_payment_status_last_checked = now
                    so.custom_payment_status_retry_count = (so.custom_payment_status_retry_count or 0) + 1

                    so.save(ignore_permissions=True)

        except Exception:
            frappe.log_error(
                title=f"PineLabs Reconcile Fatal: {order_id}",
                message=frappe.get_traceback()
            )

            try:
                # mark ALL related SOs as system-finalized failure
                for so_name in so_names:
                    so = frappe.get_doc("Sales Order", so_name)

                    so.custom_payment_status = "FAILED"
                    so.payment_status = "FAILED"
                    so.custom_payment_finalized = 1
                    so.custom_order_submit_error = 1
                    so.custom_payment_status_last_checked = now
                    so.custom_payment_status_retry_count = MAX_RETRY
                    so.custom_gateway_response_message = "System reconciliation exception"

                    so.save(ignore_permissions=True)

                frappe.db.commit()

                for so_name in so_names:
                    results[so_name] = {
                        "status": "EXCEPTION_FINALIZED",
                        "action": "AUTO_CLOSED_BY_SYSTEM"
                    }

            except Exception:
                # ultra fallback — never allow loop break
                for so_name in so_names:
                    frappe.db.sql("""
                        UPDATE `tabSales Order`
                        SET
                            custom_payment_finalized = 1,
                            custom_order_submit_error = 1,
                            custom_payment_status_last_checked = %s,
                            custom_payment_status_retry_count = %s,
                            custom_gateway_response_message = 'System reconciliation exception-fallback'
                        WHERE name = %s
                    """, (now, MAX_RETRY, so_name))

                frappe.db.commit()

                for so_name in so_names:
                    results[so_name] = {
                        "status": "FORCE_CLOSED_DB"
                    }

    frappe.db.commit()

    return results