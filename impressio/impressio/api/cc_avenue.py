
import frappe
import requests
import json
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from impressio.impressio.api.helper import get_payment_provider_details, map_ccavenue_status
from impressio.impressio.api.payments import finalize_checkout_and_build_redirect, clean_payment_mode

from datetime import timedelta
from frappe.utils import now_datetime

# Payment reconciliation timings
RETRY_AFTER_MINUTES = 3*60        # recheck same order after 3 Hours
PAYMENT_EXPIRY_MINUTES = 72*60
LOOKBACK_WINDOW_MINUTES = 45*24*60  # 30 days
MAX_RETRY = 26


BLOCK_SIZE = AES.block_size
IV = bytes(range(16))  # 00..0f


def encrypt(plain_text: str, working_key: str) -> str:
    plain_text = plain_text.strip()
    key = hashlib.md5(working_key.strip().encode("utf-8")).digest()
    cipher = AES.new(key, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(pad(plain_text.encode("utf-8"), BLOCK_SIZE))
    return encrypted.hex()


def decrypt(enc_text: str, working_key: str) -> str:
    key = hashlib.md5(working_key.strip().encode("utf-8")).digest()
    cipher = AES.new(key, AES.MODE_CBC, IV)
    decrypted = unpad(cipher.decrypt(bytes.fromhex(enc_text)), BLOCK_SIZE)
    return decrypted.decode("utf-8")



def get_active_ccavenue_config():
    ctx = get_payment_provider_details(None, "CCAVENUE")
    if not ctx:
        frappe.throw("CCAvenue not configured")
    return ctx["gateway"]




def check_ccavenue_status(order_id: str):

    config = get_active_ccavenue_config()

    # ---------- STRING REQUEST ----------
    plain = f"|{order_id}|"

    frappe.log_error(
        title="CCAvenue Status Request",
        message=f"Order: {order_id}\nPlain: {plain}"
    )

    enc_request = encrypt(plain, config.working_key)
 
    if not config.status_checking_url:
        return None

    try:
        response = requests.post(
            config.status_checking_url,
            data={
                "enc_request": enc_request,
                "access_code": config.access_code,
                "command": "orderStatusTracker",
                "request_type": "STRING",
                "response_type": "JSON",  # 🔥 IMPORTANT CHANGE
            },
            timeout=30
        )
    except Exception as e:
        frappe.log_error(str(e), "CCAvenue Connection Failed")
        return None

    frappe.log_error(title=f"Order {order_id} status received", message=f"CCAvenue Status: {response.text}")

    # ----------------------------------------------------
    # Parse wrapper (status & enc_response)
    # ----------------------------------------------------
    parts = {}
    for item in response.text.split("&"):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k] = v

    if parts.get("status") != "0":
        frappe.log_error(response.text, "CCAvenue API Failure")
        return None

    enc_response = parts.get("enc_response")
    if not enc_response:
        frappe.log_error(response.text, "CCAvenue Missing enc_response")
        return None

    # ----------------------------------------------------
    # Decrypt JSON payload
    # ----------------------------------------------------
    try:
        decrypted = decrypt(enc_response, config.working_key)
        frappe.log_error(title=f"Decrypted CCAvenue Response: {order_id}",message=decrypted)
    except Exception:
        frappe.log_error(message=f"Failed to decrypt CCAvenue response: {enc_response}", title="CCAvenue Decrypt Failed")
        return None

    try:        
        parsed = json.loads(decrypted)
    except Exception:
        frappe.log_error(message=f"Failed to parse CCAvenue JSON: {decrypted}", title="CCAvenue JSON Parse Failed")
        return None  

    if not parsed or "Order_Status_Result" not in parsed:
        frappe.log_error(message=f"Empty or malformed CCAvenue response: {parsed}", title="CCAvenue Empty Status Response")
        return None

    parsed = parsed["Order_Status_Result"]

    ccavenue_json = normalize_ccavenue_json(parsed)
    frappe.log_error(title=f"CCAvenue Response JSON: {order_id}",message=ccavenue_json)

    return ccavenue_json


def normalize_ccavenue_json(data: dict):


    return {
        "order_no": data.get("order_no"),
        "order_status": (data.get("order_status") or "").upper(),
        "reference_no": data.get("reference_no"),  # tracking id
        "bank_ref_no": data.get("order_bank_ref_no"),
        "bank_message": data.get("order_bank_response"),

        "amount": float(data.get("order_amt") or 0),
        "currency": data.get("order_currncy"),
        "payment_mode": data.get("order_option_type","UNKNOWN"),
        "device_type": data.get("order_device_type"),
        "order_date": data.get("order_date_time"),
        "status_date": data.get("order_status_date_time"),

        # billing
        "billing_name": data.get("order_bill_name"),
        "billing_email": data.get("order_bill_email"),
        "billing_city": data.get("order_bill_city"),
        "billing_state": data.get("order_bill_state"),
        "billing_country": data.get("order_bill_country"),
        "billing_tel": data.get("order_bill_tel"),

        # risk
        "fraud_status": data.get("order_fraud_status"),

        # network
        "ip": data.get("order_ip"),
        "gateway": data.get("order_gtw_id"),
    }


def finalize_ccavenue_payment(so, data):

    if not data:
        return "NO DATA"

    # if so.custom_payment_finalized:
    #     return "ALREADY FINALIZED"

    status = data["order_status"]
    gateway_status = data["order_status"]
    erp_status = map_ccavenue_status(gateway_status)

    paymentMode = clean_payment_mode(data["payment_mode"])

    # ---------------- SUCCESS ----------------
    if erp_status == "SUCCESS":

        so.custom_payment_status = "SUCCESS"
        so.payment_status = "PAID"
        so.custom_payment_finalized = 1

        so.custom_gateway_tracking_id = data["reference_no"]
        so.custom_gateway_bank_ref = data["bank_ref_no"]
        so.custom_gateway_response_message = data["bank_message"]
        so.custom_payment_mode = paymentMode

        so.custom_paid_amount = data["amount"]
        so.custom_paid_currency = data["currency"]
        so.custom_payment_date = data["status_date"]

        if so.docstatus == 0:
            try:
                so.submit()
            except Exception:
                frappe.log_error(
                    title=f"SO SUBMIT FAILED AFTER PAYMENT {so.name}",
                    message=frappe.get_traceback()
                )
                so.custom_order_submit_error = 1

        # so.flags.ignore_validate = True
        # so.flags.ignore_links = True
        so.save(ignore_permissions=True)
        frappe.db.commit()
        
        finalize_checkout_and_build_redirect([so.name])

        return "SUCCESS (FINALIZED)"

    # ---------------- FAILURE ----------------
    elif erp_status == "FAILED":
        so.custom_payment_status = "FAILED"
        so.payment_status = "FAILED"
        so.custom_payment_finalized = 1

        so.custom_gateway_tracking_id = data["reference_no"]
        so.custom_gateway_bank_ref = data["bank_ref_no"]
        so.custom_gateway_response_message = data["bank_message"]
        so.custom_payment_mode = paymentMode

        so.custom_paid_amount = data["amount"]
        so.custom_paid_currency = data["currency"]
        so.custom_payment_date = data["status_date"]

        # so.flags.ignore_validate = True
        # so.flags.ignore_links = True
        so.save(ignore_permissions=True)
        frappe.db.commit()

        return "FAILED (FINALIZED)"

    # ---------------- PENDING ----------------
    else:
        so.custom_payment_status = erp_status if erp_status else status.upper()
        # so.flags.ignore_validate = True
        # so.flags.ignore_links = True
        so.save(ignore_permissions=True)
        frappe.db.commit()
        return f"WAITING ({gateway_status})"


@frappe.whitelist(allow_guest=True)
def reconcile_pending_orders():

    now = now_datetime()
    retry_cutoff = now - timedelta(minutes=RETRY_AFTER_MINUTES)
    creation_cutoff = now - timedelta(minutes=LOOKBACK_WINDOW_MINUTES)
    

    orders = frappe.get_all(
        "Sales Order",
        filters={
            "custom_order_submit_error": 0,
            "custom_gateway_provider": "CCAVENUE",
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
        order_by="creation asc",
        limit=50
    )

    if not orders:
        return {"message": "No pending CCAvenue orders"}

    results = {}

    for row in orders:
        try:
            so = frappe.get_doc("Sales Order", row.name)
            retry = so.custom_payment_status_retry_count or 0

            expiry_time = so.creation + timedelta(minutes=PAYMENT_EXPIRY_MINUTES)

            if now >= expiry_time:

                # LAST verification attempt
                data = check_ccavenue_status(so.custom_gateway_order_id)

                if data:
                    final_try = finalize_ccavenue_payment(so, data)

                    if "SUCCESS" in final_try:
                        results[so.name] = {
                            "status": "LATE_SUCCESS",
                            "action": "FINALIZED_AFTER_72H"
                        }
                        continue

                # truly expired
                so.custom_payment_status = "EXPIRED"
                so.payment_status = "EXPIRED"
                so.custom_payment_finalized = 1
                so.custom_gateway_response_message = "Expired after 72h payment confirmation"
                so.custom_payment_status_last_checked = now
                # so.flags.ignore_validate = True
                # so.flags.ignore_links = True
                so.save(ignore_permissions=True)

                results[so.name] = {
                    "status": "EXPIRED",
                    "action": "Expired after 72h payment confirmation"
                    }

                continue   # ⭐⭐⭐ THIS IS CRITICAL

            # if retry >= MAX_RETRY:
            #     results[so.name] = {
            #         "status": "SKIPPED",
            #         "reason": "Max retries reached"
            #     }
            #     continue

            # ---- call ccavenue ----
            data = check_ccavenue_status(so.custom_gateway_order_id)

            # update retry tracking
            so.custom_payment_status_retry_count = retry + 1
            so.custom_payment_status_last_checked = now
            # so.flags.ignore_validate = True
            # so.flags.ignore_links = True
            so.save(ignore_permissions=True)
            

            if not data:
                results[so.name] = {
                    "status": "API_FAILED",
                    "retry": retry
                }
                continue

            # finalize
            result = finalize_ccavenue_payment(so, data)

            results[so.name] = {
                "ccavenue_status": data.get("order_status"),
                "action": result,
                "retry_count": retry + 1,
                "reference_no": data.get("reference_no"),
            }

        except Exception:
            frappe.log_error(
                title=f"CCAvenue Reconcile Fatal: {row.name}",
                message=frappe.get_traceback()
            )
            try:
                # mark order as system-finalized failure
                so = frappe.get_doc("Sales Order", row.name)

                so.custom_payment_status = "FAILED"
                so.payment_status = "FAILED"
                so.custom_payment_finalized = 1
                so.custom_order_submit_error = 1
                so.custom_payment_status_last_checked = now
                so.custom_payment_status_retry_count = MAX_RETRY
                so.custom_gateway_response_message = "System reconciliation exception"

                # so.flags.ignore_validate = True
                # so.flags.ignore_links = True
                so.save(ignore_permissions=True)
                frappe.db.commit()

                results[row.name] = {
                    "status": "EXCEPTION_FINALIZED",
                    "action": "AUTO_CLOSED_BY_SYSTEM"
                }

            except Exception:
                # ultra fallback — never allow loop
                frappe.db.sql("""
                    UPDATE `tabSales Order`
                    SET
                        custom_payment_finalized = 1,
                        custom_order_submit_error = 1,
                        custom_payment_status_last_checked = %s,
                        custom_payment_status_retry_count = %s,
                        custom_gateway_response_message = 'System reconciliation exception-fallback'
                    WHERE name = %s
                """, (now, MAX_RETRY, row.name))

                frappe.db.commit()

                results[row.name] = {
                    "status": "FORCE_CLOSED_DB"
                }

    frappe.db.commit()

    return results


@frappe.whitelist(allow_guest=True)
def track_ccavenue_orders(sales_orders):

    # Accept JSON string or list
    if isinstance(sales_orders, str):
        try:
            sales_orders = json.loads(sales_orders)
        except Exception:
            return {"error": "Invalid JSON array"}

    if not isinstance(sales_orders, list) or not sales_orders:
        return {"error": "sales_orders must be a non-empty list"}

    now = now_datetime()
    retry_cutoff = now - timedelta(minutes=RETRY_AFTER_MINUTES)
    creation_cutoff = now - timedelta(minutes=LOOKBACK_WINDOW_MINUTES)

    results = {}

    for sales_order_name in sales_orders:

        try:
            so = frappe.get_doc("Sales Order", sales_order_name)

            retry = so.custom_payment_status_retry_count or 0            

            if so.custom_gateway_provider != "CCAVENUE":
                results[sales_order_name] = {"error": "Not a CCAvenue order"}
                continue

            if not so.custom_gateway_order_id:
                results[sales_order_name] = {"error": "Gateway Order ID missing"}
                continue

            # ---- Call CCAvenue ----
            data = check_ccavenue_status(so.custom_gateway_order_id)
            expiry_time = so.creation + timedelta(minutes=PAYMENT_EXPIRY_MINUTES)

            if now >= expiry_time:

                # LAST verification attempt
                if data:
                    final_try = finalize_ccavenue_payment(so, data)

                    if "SUCCESS" in final_try:
                        results[so.name] = {
                            "status": "LATE_SUCCESS",
                            "action": "FINALIZED_AFTER_72H"
                        }
                        continue
                    
                # truly expired
                so.custom_payment_status = "EXPIRED"
                so.payment_status = "EXPIRED"
                so.custom_payment_finalized = 1
                so.custom_gateway_response_message = "Expired after 72h payment confirmation"
                so.custom_payment_status_last_checked = now
                # so.flags.ignore_validate = True
                # so.flags.ignore_links = True
                so.save(ignore_permissions=True)

                results[so.name] = {
                    "status": "EXPIRED",
                    "action": "Expired after 72h payment confirmation"
                    }

                continue   # ⭐⭐⭐ THIS IS CRITICAL

            if not data:
                results[sales_order_name] = {"status": "API_FAILED"}
                continue

            # ---- Finalize ----
            result = finalize_ccavenue_payment(so, data)

            results[sales_order_name] = {
                "erp_payment_status": so.custom_payment_status,
                "gateway_status": data.get("order_status"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "action_taken": result,
                "retry_count": so.custom_payment_status_retry_count,
                "last_checked": so.custom_payment_status_last_checked
            }

        except Exception:
            frappe.log_error(
                title=f"Track CCAvenue Error: {sales_order_name}",
                message=frappe.get_traceback()
            )
            frappe.log_error(
                title=f"Track CCAvenue Response: {sales_order_name}",
                message=data
            )

            results[sales_order_name] = {
                "status": "EXCEPTION",
            }

    return results


@frappe.whitelist(allow_guest=True)
def get_broken_ccavenue_orders(limit=50):
    """
    Fetch Sales Orders where:
    - Payment SUCCESS
    - CCAvenue
    - Submitted (docstatus=1)
    - But status is still 'Draft' (broken case)
    """

    try:
        limit = int(limit)
    except Exception:
        limit = 50

    orders = frappe.db.sql("""
        SELECT 
            name,
            custom_payment_finalized,
            custom_gateway_provider,
            custom_payment_status,
            custom_gateway_tracking_id,
            status,
            docstatus
        FROM `tabSales Order`
        WHERE
            custom_payment_finalized = 1
            AND custom_gateway_provider = 'CCAVENUE'
            AND custom_payment_status = 'SUCCESS'
            AND IFNULL(custom_gateway_tracking_id, '') != ''
            AND status = 'Draft'
            AND docstatus = 1
        ORDER BY modified DESC
        LIMIT %s
    """, (limit,), as_dict=True)

    return {
        "count": len(orders),
        "orders": orders
    }


@frappe.whitelist(allow_guest=True)
def check_and_fix_ccavenue_status(limit=50, auto_fix=0):

    try:
        limit = int(limit)
    except Exception:
        limit = 50

    auto_fix = int(auto_fix)

    orders = frappe.db.sql("""
        SELECT name, status
        FROM `tabSales Order`
        WHERE
            custom_payment_finalized = 1
            AND custom_gateway_provider = 'CCAVENUE'
            AND custom_payment_status = 'SUCCESS'
            AND IFNULL(custom_gateway_tracking_id, '') != ''
            AND status = 'Draft'
            AND docstatus = 1
        LIMIT %s
    """, (limit,), as_dict=True)

    exists = len(orders) > 0

    fixed = []
    failed = []

    if exists and auto_fix:
        for row in orders:
            so_name = row["name"]
            before_status = row["status"]

            try:
                so = frappe.get_doc("Sales Order", so_name)

                # recalc status
                so.set_status(update=True)
                after_status = so.status

                so.save(ignore_permissions=True)

                fixed.append({
                    "name": so_name,
                    "before_status": before_status,
                    "after_status": after_status
                })

            except Exception:
                frappe.log_error(
                    title=f"STATUS FIX FAILED: {so_name}",
                    message=frappe.get_traceback()
                )

                failed.append({
                    "name": so_name,
                    "before_status": before_status
                })

        frappe.db.commit()

    return {
        "exists": exists,
        "count": len(orders),
        "orders": [o["name"] for o in orders],
        "fixed_count": len(fixed),
        "fixed_orders": fixed,
        "failed_count": len(failed),
        "failed_orders": failed
    }