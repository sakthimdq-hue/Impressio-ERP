# File: inventre/tasks.py

import frappe
from datetime import timedelta
from frappe.utils import now_datetime

# ── Tracking config ──────────────────────────────────────────────
TRACKING_WINDOW_DAYS = 30   # ignore shipments older than 30 days
RETRY_AFTER_HOURS    = 2    # recheck same shipment after 2 hours
BATCH_SIZE           = 50   # max API calls per run
# ────────────────────────────────────────────────────────────────

def auto_track_all_shipments():
    from impressio.material_out.api.logistics.utils import track_shipment, get_unified_tracking_data

    now          = now_datetime()
    cutoff_date  = now - timedelta(days=TRACKING_WINDOW_DAYS)
    retry_cutoff = now - timedelta(hours=RETRY_AFTER_HOURS)

    active_handovers = frappe.db.sql("""
        SELECT
            name,
            delivery_note,
            logistics_tracking_number,
            carrier_status,
            logistics_partner,
            last_tracked
        FROM `tabHandover To Logistics`
        WHERE
            docstatus IN (0, 1)
            AND carrier_status NOT IN (
                'Delivered', 'Cancelled', 'RTO Delivered', 'Label Generated'
            )
            AND logistics_tracking_number IS NOT NULL
            AND logistics_tracking_number != ''
            AND creation >= %(cutoff)s
            AND (
                last_tracked IS NULL
                OR last_tracked < %(retry_cutoff)s
            )
        ORDER BY last_tracked ASC
        LIMIT %(batch_size)s
    """, {
        "cutoff":       cutoff_date,
        "retry_cutoff": retry_cutoff,
        "batch_size":   BATCH_SIZE
    }, as_dict=True)

    if not active_handovers:
        print("[AutoTrack] No active shipments to track.")
        return

    print(f"[AutoTrack] Tracking {len(active_handovers)} active shipment(s)...")

    success = 0
    failed  = 0

    for hlg in active_handovers:
        try:
            # Step 1: Hit carrier API → update HLG carrier_status
            result = track_shipment(docname=hlg['name'])
            current_status = result.get('current_status') if result else None

            # Step 2: Update DN → custom_status_tracking, custom_is_delivered
            dn_name = hlg.get('delivery_note')
            if dn_name:
                hlg_doc = frappe.get_doc("Handover To Logistics", hlg['name'])
                get_unified_tracking_data(hlg_doc)
                print(f"[AutoTrack] ✓ {hlg['name']} → {current_status} | DN {dn_name} updated")
            else:
                print(f"[AutoTrack] ✓ {hlg['name']} → {current_status} | No DN linked")

            # Step 3: Update last tracked timestamp
            frappe.db.set_value(
                "Handover To Logistics",
                hlg['name'],
                "last_tracked",
                now
            )

            success += 1

        except Exception as e:
            failed += 1
            print(f"[AutoTrack] ERROR {hlg['name']}: {str(e)}")
            frappe.log_error(
                title=f"AutoTrack Failed — {hlg['name']}",
                message=frappe.get_traceback()
            )

    frappe.db.commit()
    print(f"[AutoTrack] Done. ✓ {success} updated, ✗ {failed} failed.")