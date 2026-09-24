import frappe
import requests
import json
import hashlib

from datetime import timedelta
from frappe.utils import now_datetime
from impressio.impressio.api.sms_service import SMSService
from impressio.impressio.api.whatsapp_service import WhatsAppService
from impressio.impressio.api.helper import get_customer_name_from_mobile

# Payment reconciliation timings
RETRY_AFTER_MINUTES = 3*24*60        # recheck same order after 3 Days
TRACKING_WINDOW_MINUTES = 30*24*60   # track orders for 30 days after submission
BATCH_SIZE = 2

@frappe.whitelist(allow_guest=True)
def send_pending_exam_sms():

    now = now_datetime()
    cutoff_30_days = now - timedelta(minutes=TRACKING_WINDOW_MINUTES)
    retry_cutoff = now - timedelta(minutes=RETRY_AFTER_MINUTES)

    orders = frappe.db.sql("""
        SELECT
            so.name,
            so.contact_mobile,
            so.contact_person,
            so.customer_name,
            so.custom_processing_sms_datetime,
            so.creation,
            so.status
        FROM `tabSales Order` so
        LEFT JOIN (
            SELECT against_sales_order AS so_name
            FROM `tabDelivery Note Item`
            WHERE docstatus = 1
            AND against_sales_order IS NOT NULL
            AND against_sales_order != ''

            UNION

            SELECT custom_custom_against_sales_order AS so_name
            FROM `tabDelivery Note Item`
            WHERE docstatus = 1
            AND custom_custom_against_sales_order IS NOT NULL
            AND custom_custom_against_sales_order != ''
        ) AS delivered ON delivered.so_name = so.name
        WHERE
            so.docstatus = 1
            AND so.contact_person IS NOT NULL AND so.contact_person != ''
            AND so.contact_mobile  IS NOT NULL AND so.contact_mobile  != ''
            AND so.creation >= %(cutoff)s
            AND (
                so.custom_processing_sms_datetime IS NULL
                OR so.custom_processing_sms_datetime < %(retry_cutoff)s
            )
            AND delivered.so_name IS NULL
        ORDER BY so.creation ASC
        LIMIT %(batch_size)s
    """, {
        "cutoff":      cutoff_30_days,
        "retry_cutoff": retry_cutoff,
        "batch_size":   BATCH_SIZE
    }, as_dict=True)

    if not orders:
        return {"message": "No pending SMS"}


    return orders


    results = {}

    for row in orders:
        try:
            so = frappe.get_doc("Sales Order", row.name)

            mobile = so.contact_mobile.strip().replace(" ", "")
            resolved_name = get_customer_name_from_mobile(mobile)
            customer_name = resolved_name if resolved_name else so.customer_name
            order_no = so.name

            if not mobile or customer_name is None:
                frappe.db.sql("""
                    UPDATE `tabSales Order`
                    SET custom_processing_sms_datetime = %(now)s
                    WHERE name = %(name)s
                """, {
                    "now": now,
                    "name": so.name
                })
                results[order_no] = {
                    "status": "FAILED",
                    "mobile": mobile,
                    "sms": "FAILED",
                    "whatsapp": "FAILED",
                    "order_status": so.status
                }
                continue

            # ─── SMS ───────────────────────────────────────────────
            try:
                sms_success, sms_resp = SMSService.send_order_processing_sms(
                    mobile=mobile,
                    customer_name=customer_name,
                    order_no=order_no
                )
            except Exception as e:
                frappe.log_error(
                    title="SMS SEND FAILED",
                    message=str(e)
                )
                sms_success = False

            # ─── WhatsApp ──────────────────────────────────────────
            try:
                wa_success, wa_resp = WhatsAppService.send_order_delay_update(
                    mobile=mobile,
                    customer_name=customer_name,
                    order_no=order_no
                )
            except Exception as e:
                frappe.log_error(
                    title="WHATSAPP SEND FAILED",
                    message=str(e)
                )
                wa_success = False
                
            # sms_success = True # mocking SMS success for testing
            # wa_success = True # mocking WA success for testing

            try:
                email = frappe.get_value("User", {"mobile_no": mobile}, "email") if mobile else None
                if email:
                    frappe.sendmail(
                        recipients=[email],
                        subject="ORDER_PROCESSING",
                        message=f"""
                            Dear {customer_name},

                            Your Order {order_no} is currently under process.

                            We sincerely apologize for the delay.

                            Please be assured that our team is actively working to deliver your order at the earliest. 

                            Thank you for your patience and understanding. 

                            Note: If your order has already been delivered, Please ignore this message

                            Regards,
                            INVENTRE EDUSERVICES PVT. LTD
                            """
                    )
            except Exception:
                frappe.log_error(
                    title="CHECKOUT EMAIL FAILED",
                    message=frappe.get_traceback()
                    )


            if sms_success or wa_success:
                frappe.db.sql("""
                    UPDATE `tabSales Order`
                    SET custom_processing_sms_datetime = %(now)s
                    WHERE name = %(name)s
                """, {
                    "now": now,
                    "name": so.name
                })

            overall_success = sms_success and wa_success

            results[order_no] = {
                "status": "SENT" if overall_success else ("PARTIAL" if (sms_success or wa_success) else "FAILED"),
                "mobile": mobile,
                "sms": "OK" if sms_success else "FAILED",
                "whatsapp": "OK" if wa_success else "FAILED",
                "order_status": so.status
            }


        except Exception:
            # 💥 even if error, update datetime
            try:
                frappe.db.sql("""
                    UPDATE `tabSales Order`
                    SET custom_processing_sms_datetime = %(now)s
                    WHERE name = %(name)s
                """, {
                    "now": now,
                    "name": so.name
                })
            except Exception:
                frappe.log_error("Failed to update retry datetime")

            frappe.log_error(
                title=f"Pending SMS Error: {row.name}",
                message=frappe.get_traceback()
            )

            results[row.name] = "ERROR"

    frappe.db.commit()

    return results