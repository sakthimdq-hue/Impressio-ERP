import frappe
import base64
import hashlib
import time
import json
import requests
import hmac
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import finalize_rer_on_replacement_so_payment, get_payment_provider_details, FRONTEND_CHECKOUT_URL, map_ccavenue_status,map_pinelabs_status,  get_billing_address_from_sale_order, get_customer_name_from_mobile, check_otp, consume_otp, success, error, validate_fields, create_otp,is_book_item, get_full_image_url
from frappe.utils import get_url
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from urllib.parse import urlencode, quote_plus, unquote_plus
from impressio.impressio.api.sms_service import SMSService  # adjust path if needed
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry



def clean_payment_mode(mode: str) -> str:
    if not mode:
        return None

    mode = mode.upper().strip()

    # remove OPT only if prefix
    if mode.startswith("OPT"):
        mode = mode[3:]

    mapping = {
        "UPI": "UPI",
        "NBK": "Net Banking",
        "CRDC": "Credit Card",
        "DBCRD": "Debit Card",
        "WLT": "Wallet",
        "EMI": "EMI",
        "COD": "COD",
    }

    if not mode:
        return None

    return mapping.get(mode, mode)

@frappe.whitelist(allow_guest=True)
def payment_modes():
    """
    Website API
    Returns payment modes enabled for website
    ONLY if at least one active Payment Provider + Gateway Configuration exists
    for current PAYMENT_ENV
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required")

    is_student_flow = bool(user.has_student)
    payment_env = frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()

    modes = frappe.get_all(
        "Mode of Payment",
        filters={
            "enabled": 1,
            "custom_enabled_for_website": 1
        },
        fields=[
            "name",
            "custom_payment_flow",
            "custom_payment_category",
            "custom_allowed_for_student",
            "custom_allowed_for_direct_customer"
        ],
        order_by="name asc"
    )

    result = []

    for mode in modes:

        # ------------------------------------------------
        # 1️⃣ User type validation
        # ------------------------------------------------
        if is_student_flow and not mode.custom_allowed_for_student:
            continue

        if not is_student_flow and not mode.custom_allowed_for_direct_customer:
            continue

        payment_flow = mode.custom_payment_flow

        # return payment_flow

        # ------------------------------------------------
        # 2️⃣ ONLINE → provider + gateway validation
        # ------------------------------------------------
        if payment_flow == "ONLINE":

            # Find active providers supporting this payment mode
            providers = frappe.get_all(
                "Payment Provider",
                filters={"is_active": 1},
                fields=["name"]
            )

            provider_found = False

            for provider in providers:

                # Check supported payment mode (child table)
                supports_mode = frappe.db.exists(
                    "Payment Provider Supported Payment Mode",
                    {
                        "parent": provider.name,
                        "mode_of_payment": mode.name,
                        "is_active": 1
                    }
                )

                if not supports_mode:
                    continue

                # Check active gateway configuration for environment
                gateway_exists = frappe.db.exists(
                    "Payment Gateway Configuration",
                    {
                        "gateway_provider": provider.name,
                        "environment": payment_env,
                        "is_active": 1
                    }
                )

                if gateway_exists:
                    provider_found = True
                    break

            if not provider_found:
                continue

        # ------------------------------------------------
        # 3️⃣ COD / OFFLINE → no provider validation
        # ------------------------------------------------

        result.append({
            "name": mode.name,
            "payment_flow": payment_flow
        })

    return {
        "payment_modes": result
    }



@frappe.whitelist(allow_guest=True)
def payment_providers():
    """
    Website API
    Returns ACTIVE payment providers + gateway configs
    for current PAYMENT_ENV
    """

    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)

    payment_env = frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()

    result = []

    # ------------------------------------------------
    # 1️⃣ Fetch active Payment Providers
    # ------------------------------------------------
    providers = frappe.get_all(
        "Payment Provider",
        filters={
            "is_active": 1,
            'name': ['not in', ['COD']]  # Exclude COD from provider list (if needed)
        },
        fields=[
            "name",
            "provider_code",
            "payment_flow"
        ],
        order_by="name asc"
    )

    for provider in providers:


        # ------------------------------------------------
        # 3️⃣ Find active gateway config for ENV
        # ------------------------------------------------
        gateway = frappe.get_all(
            "Payment Gateway Configuration",
            filters={
                "gateway_provider": provider.name,
                "environment": payment_env,
                "is_active": 1
            },
            fields=[
                "name",
                "payment_url",
                "environment"
            ],
            limit=1
        )

        if not gateway and provider.payment_flow == "ONLINE":
            continue

        # ------------------------------------------------
        # 4️⃣ Supported payment modes (optional)
        # ------------------------------------------------
        supported_modes = frappe.get_all(
            "Payment Provider Supported Payment Mode",
            filters={
                "parent": provider.name,
                "is_active": 1
            },
            pluck="mode_of_payment"
        )

        # ------------------------------------------------
        # 5️⃣ Final response object
        # ------------------------------------------------
        result.append({
            "name": provider.name,
            "payment_flow": provider.payment_flow,  # REDIRECT / FORM_POST
            "supported_modes": supported_modes
        })

    return success("Payment providers fetched", result)




def create_payment_entries_per_sales_order(
    *,
    sales_order_names,
    transaction_id,
    payment_mode=None,
    gateway_provider=None
):

    if not sales_order_names:
        return []

    created_entries = []
    original_user = frappe.session.user
    original_user = frappe.session.user

    try:
        frappe.set_user("Administrator")

        for so_name in sales_order_names:
            so = frappe.get_doc("Sales Order", so_name)

            # 🔒 Idempotency guard
            if frappe.db.exists(
                "Payment Entry Reference",
                {
                    "reference_doctype": "Sales Order",
                    "reference_name": so.name
                }
            ):
                continue

            # 🚀 AUTO-FETCH Payment Entry
            pe = get_payment_entry(
                dt="Sales Order",
                dn=so.name
            )

            # 🔹 Custom gateway details
            pe.reference_no = transaction_id
            pe.reference_date = frappe.utils.today()

            mode = clean_payment_mode(payment_mode)

            if mode:
                try:
                    # create if missing
                    if not frappe.db.exists("Mode of Payment", mode):
                        mop = frappe.new_doc("Mode of Payment")
                        mop.mode_of_payment = mode
                        mop.enabled = 1
                        mop.type = "Bank"   # important for accounting settlement
                        mop.insert(ignore_permissions=True)

                except frappe.DuplicateEntryError:
                    # another worker already created it → perfectly fine
                    pass

                except Exception:
                    # never break payment posting because of configuration
                    frappe.log_error(
                        title="Mode of Payment Auto-Creation Failed",
                        message=frappe.get_traceback()
                    )

                # finally assign (even if it already existed)
                if frappe.db.exists("Mode of Payment", mode):
                    pe.mode_of_payment = mode
                

            if gateway_provider:
                pe.custom_gateway_provider = gateway_provider

            pe.flags.ignore_permissions = True
            pe.insert()
            pe.submit()

            created_entries.append(pe.name)
    except Exception:
        frappe.log_error(
            title="CCAVENUE | PAYMENT ENTRY CREATION FAILED",
            message=frappe.get_traceback()
        )
    finally:
        frappe.set_user(original_user)

    return created_entries


# ------------------------------------------------------------------
# MAIN HANDLER
# ------------------------------------------------------------------
def handle_payment(sales_order_names, provider, user, gateway=None, delivery_cost = 0, use_existing_reference=False):
    """
    Handles SINGLE payment for MULTIPLE Sales Orders
    using resolved Payment Provider (priority-based)
    """

    
    if isinstance(sales_order_names, str):
        sales_order_names = [sales_order_names]

    sales_orders = [frappe.get_doc("Sales Order", so) for so in sales_order_names]
    total_amount = sum(so.grand_total for so in sales_orders)

    total_amount = total_amount + delivery_cost

    # -------------------------------
    # ZERO AMOUNT FLOW
    # -------------------------------
    if total_amount <= 0:

        # pick guardian mobile
        mobile = user.get("mobile")

        if not mobile:
            return error("Mobile number required for zero-value order confirmation")

        success_otp, msg = create_otp(
            mobile=mobile,
            purpose="ZERO_ORDER",
            extra_data={
                "doctype": "Sales Order",
                "names": sales_order_names
            },
            user=user.name
        )

        if not success_otp:
            return error(msg)

        return success("OTP sent for order confirmation", {
            "orders": sales_order_names,
            "payment_flow": "ZERO_ORDER"
        })


    
    # ------------------------------------------------
    # COD FLOW (provider independent)
    # ------------------------------------------------
    if provider.payment_flow == "COD":
        for so in sales_orders:
            so.custom_payment_status = "COD"
            so.flags.ignore_permissions = True
            so.save()
            so.submit()

        redirect_url = (
            f"{FRONTEND_CHECKOUT_URL}"
            f"?orders={','.join(sales_order_names)}"
            f"&status=success"
            f"&payment_flow=COD"
        )

        return success("Order confirmed", {
            "orders": sales_order_names,
            "payment_flow": "COD",
            "payment_provider": "COD",
            "redirect": {
                "url": redirect_url,
                "method": "GET"
            },
            "form": None
        })
    

    # ------------------------------------------------
    # ONLINE FLOW (provider-based routing)
    # ------------------------------------------------
    if provider.payment_flow == "ONLINE":

        if not provider.name or not gateway:
            frappe.throw("Payment provider not available")

        providerName = provider.provider_code.upper()
        

        # -------------------------------
        # PINELABS → REDIRECT
        # -------------------------------
        if providerName == "PINELABS":
            payment_url = initiate_pinelabs_payment(
                sales_orders,
                total_amount,
                gateway
            )

            return success("Redirect to payment", {
                "orders": sales_order_names,
                "payment_flow": "REDIRECT",
                "payment_provider": "PINELABS",
                "redirect": {
                    "url": payment_url,
                    "method": "GET"
                },
                "form": None
            })

        # -------------------------------
        # CC AVENUE → FORM POST
        # -------------------------------
        elif providerName == "CCAVENUE":
            meta = initiate_ccavenue_payment(
                sales_orders,
                total_amount,
                gateway,
                use_existing_reference=use_existing_reference 
            )


            return success("Redirect to payment", {
                "orders": sales_order_names,
                "payment_flow": "FORM_POST",
                "payment_provider": "CCAVENUE",
                "redirect": None,
                "form": {
                    "action": meta["payment_url"],
                    "method": "POST",
                    "fields": {
                        "encRequest": meta["encRequest"],
                        "access_code": meta["access_code"]
                    }
                }
            })

        else:
            frappe.throw(f"Unsupported payment provider: {provider}")



# ------------------------------------------------------------------
# CREATE PINELABS ORDER
# ------------------------------------------------------------------
def pinelabs_get_access_token(config):
    url = f"{config.base_url}/api/auth/v1/token"

    payload = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "grant_type": "client_credentials"
    }

    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
        "Request-ID": frappe.generate_hash(length=32),
        "Request-Timestamp": frappe.utils.now_datetime().isoformat()
    }

    res = requests.post(url, json=payload, headers=headers, timeout=30)

    if res.status_code != 200:
        frappe.log_error("PineLabs Auth Failed", res.text)
        frappe.throw("Unable to authenticate with Pine Labs")

    return res.json()["access_token"]


def initiate_pinelabs_payment(sales_orders, total_amount, config):
    access_token = pinelabs_get_access_token(config)

    url = f"{config.base_url}/api/checkout/v1/orders"

    merchant_ref = (
            f"SO{int(time.time())}{frappe.generate_hash(length=6)}"
        )[:30]

    payload = {
        "merchant_order_reference": merchant_ref,
        "order_amount": {
            "value": int(total_amount * 100),
            "currency": "INR"
        },
        "pre_auth": False,
        "allowed_payment_methods": ["CARD", "UPI", "NETBANKING"],

        # customer browser redirect
        "callback_url": config.return_url,

        # webhook (REAL payment confirmation)
        "webhook_url": config.webhook_url,

        "failure_callback_url": config.cancel_url,

        "purchase_details": {
            "customer": {
                "email_id": sales_orders[0].contact_email,
                "first_name": sales_orders[0].customer_name,
                "mobile_number": sales_orders[0].contact_mobile,
                "country_code": "91"
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json",
        "Request-ID": frappe.generate_hash(length=32),
        "Request-Timestamp": frappe.utils.now_datetime().isoformat()
    }

    res = requests.post(url, json=payload, headers=headers, timeout=30)


    if res.status_code not in (200, 201):
        frappe.log_error("PineLabs Order Failed", res.text)
        frappe.throw("Pine Labs order creation failed")

    data = res.json()

    # 🔒 Store gateway refs
    for so in sales_orders:
        so.custom_gateway_provider = "PINELABS"
        so.custom_internal_payment_reference = merchant_ref
        so.custom_gateway_order_id = data["order_id"]
        so.custom_payment_status = "PENDING"
        so.save(ignore_permissions=True)

    return data["redirect_url"]


def verify_pinelabs_webhook(raw_body: str, headers: dict, client_secret: str) -> bool:
    """
    PineLabs Hosted Checkout Webhook Signature Verification
    """

    webhook_id = headers.get("webhook-id")
    webhook_timestamp = headers.get("webhook-timestamp")
    received_signature = headers.get("webhook-signature")

    if not webhook_id or not webhook_timestamp or not received_signature:
        frappe.log_error("PINELABS: Missing headers", str(headers))
        return False

    # -----------------------------
    # 1️⃣ Prevent replay attack
    # -----------------------------
    try:
        timestamp = int(webhook_timestamp)
    except Exception:
        return False

    now = int(time.time())

    # allow 5 minutes tolerance
    if abs(now - timestamp) > 300:
        frappe.log_error("PINELABS: Timestamp expired", webhook_timestamp)
        return False

    # -----------------------------
    # 2️⃣ Remove version prefix
    # header format: v1,BASE64SIGNATURE
    # -----------------------------
    try:
        received_signature = received_signature.split(",")[1]
    except Exception:
        return False

    # -----------------------------
    # 3️⃣ Create signed content
    # -----------------------------
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body}"

    # secret in dashboard is BASE64 encoded
    decoded_secret = base64.b64decode(client_secret)

    # -----------------------------
    # 4️⃣ Generate HMAC SHA256
    # -----------------------------
    computed_hmac = hmac.new(
        decoded_secret,
        signed_content.encode("utf-8"),
        hashlib.sha256
    ).digest()

    computed_signature = base64.b64encode(computed_hmac).decode()

    # constant time compare
    return hmac.compare_digest(computed_signature, received_signature)


def pinelabs_verify_payment(order_id, config):
    """
    Confirms payment directly with PineLabs server
    This is the REAL source of truth.
    """

    access_token = pinelabs_get_access_token(config)

    url = f"{config.base_url}/api/checkout/v1/orders/{order_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json",
        "Request-ID": frappe.generate_hash(length=32),
        "Request-Timestamp": frappe.utils.now_datetime().isoformat()
    }

    res = requests.get(url, headers=headers, timeout=30)

    if res.status_code != 200:
        frappe.log_error("PINELABS STATUS API FAILED", res.text)
        return None

    return res.json()

# ------------------------------------------------------------------
# PINELABS WEBHOOK
# ------------------------------------------------------------------
@frappe.whitelist(allow_guest=True)
def pinelabs_webhook():
    """
    PineLabs Webhook Handler

    IMPORTANT:
    Webhook does NOT contain payment truth.
    It is only a notification event.

    Real payment confirmation must ALWAYS be fetched
    from PineLabs Order Status API.
    """

    # --------------------------------------------------
    # 1️⃣ Capture RAW request (NEVER PARSE BEFORE VERIFY)
    # --------------------------------------------------
    raw_body = frappe.request.data.decode("utf-8") if frappe.request.data else ""
    headers = dict(frappe.request.headers or {})

    frappe.log_error(title="PINELABS WEBHOOK RECEIVED", message=raw_body)

    # --------------------------------------------------
    # 2️⃣ Load configuration
    # --------------------------------------------------
    payment_env = frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()

    provider = frappe.get_value(
        "Payment Provider",
        {"provider_code": "PINELABS", "is_active": 1},
        "name"
    )

    if not provider:
        frappe.log_error(title="PINELABS WEBHOOK: PROVIDER NOT FOUND", message="")
        return "ok"

    config = frappe.get_doc(
        "Payment Gateway Configuration",
        {
            "gateway_provider": provider,
            "environment": payment_env,
            "is_active": 1
        }
    )

    # --------------------------------------------------
    # 3️⃣ Verify webhook signature (CRITICAL)
    # --------------------------------------------------
    try:
        is_valid = verify_pinelabs_webhook(
            raw_body,
            headers,
            config.client_secret
        )
    except Exception:
        frappe.log_error("PINELABS WEBHOOK SIGNATURE ERROR", frappe.get_traceback())
        return "ok"

    if not is_valid:
        frappe.log_error("PINELABS WEBHOOK INVALID SIGNATURE", raw_body)
        return "ok"

    # --------------------------------------------------
    # 4️⃣ Now parse JSON (SAFE AFTER VERIFY)
    # --------------------------------------------------
    try:
        payload = frappe.parse_json(raw_body)
    except Exception:
        frappe.log_error("PINELABS WEBHOOK JSON PARSE FAILED", raw_body)
        return "ok"

    order_id = payload.get("order_id")

    if not order_id:
        frappe.log_error("PINELABS WEBHOOK MISSING ORDER_ID", raw_body)
        return "ok"

    frappe.log_error("PINELABS WEBHOOK ORDER RECEIVED", order_id)

    # --------------------------------------------------
    # 5️⃣ Fetch REAL payment status from PineLabs
    # --------------------------------------------------
    try:
        order_data = pinelabs_fetch_order(order_id, config)
    except Exception:
        frappe.log_error("PINELABS STATUS FETCH FAILED", frappe.get_traceback())
        return "ok"

    if not order_data:
        frappe.log_error("PINELABS WEBHOOK STATUS EMPTY", order_id)
        return "ok"

    # --------------------------------------------------
    # 6️⃣ FINALIZE PAYMENT (IDEMPOTENT)
    # --------------------------------------------------
    try:
        finalize_pinelabs_payment(order_data)
    except Exception:
        frappe.log_error("PINELABS FINALIZE FAILED", frappe.get_traceback())
        return "ok"

    # --------------------------------------------------
    # 7️⃣ IMPORTANT: Always return 200 OK
    # --------------------------------------------------
    return "ok"


def get_pinelabs_config():
    ctx = get_payment_provider_details(None, "PINELABS")
    if not ctx:
        frappe.throw("PineLabs not configured")
    return ctx["gateway"]


def verify_pinelabs_return_signature(params: dict, secret_key: str | None) -> bool:
    """
    Verify PineLabs return URL signature safely with full debug logging
    """

    received_signature = (params.get("signature") or "").strip()
    order_id = params.get("order_id", "")
    status = params.get("status", "")

    # ------------------------------
    # Missing signature
    # ------------------------------
    if not received_signature:
        frappe.log_error(
            title="PINELABS RETURN ERROR: Missing Signature",
            message=frappe.as_json(params)
        )
        return False

    # ------------------------------
    # Missing secret key (REAL ISSUE NOW)
    # ------------------------------
    if not secret_key:
        frappe.log_error(
            title="PINELABS RETURN CONFIG ERROR",
            message="""
            Return secret key is empty.
            You have not configured the PineLabs Return Secret in Payment Gateway Configuration.
            PineLabs return signature cannot be verified.
            """
        )
        return False

    # ------------------------------
    # Build message string
    # ------------------------------
    data = {
        "order_id": order_id,
        "status": status
    }

    message = "&".join(f"{k}={data[k]}" for k in sorted(data.keys()))

    # ------------------------------
    # Convert HEX secret
    # ------------------------------
    try:
        secret_bytes = bytes.fromhex(secret_key.strip())
    except ValueError:
        frappe.log_error(
            title="PINELABS RETURN SECRET FORMAT ERROR",
            message=f"""
            Secret is not HEX encoded.

            Secret received length: {len(secret_key)}
            Secret preview: {secret_key[:6]}...{secret_key[-6:] if len(secret_key) > 12 else secret_key}
            """
        )
        return False

    # ------------------------------
    # Generate signature
    # ------------------------------
    computed_signature = hmac.new(
        secret_bytes,
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    is_valid = hmac.compare_digest(computed_signature, received_signature)

    # ------------------------------
    # Deep debug log
    # ------------------------------
    frappe.log_error(
        title="PINELABS RETURN SIGNATURE DEBUG",
        message=frappe.as_json({
            "order_id": order_id,
            "status": status,
            "string_to_hash": message,
            "received_signature": received_signature,
            "computed_signature": computed_signature,
            "secret_present": True,
            "secret_length": len(secret_key),
            "match": is_valid
        })
    )

    return is_valid


def pinelabs_fetch_order(order_id, config):
    """
    Fetch final payment details from PineLabs.
    This is the REAL payment confirmation — not the return URL.
    """

    access_token = pinelabs_get_access_token(config)

    url = f"{config.base_url}/api/pay/v1/orders/{order_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json",
        "Request-ID": frappe.generate_hash(length=32),
        "Request-Timestamp": frappe.utils.now_datetime().isoformat()
    }

    try:
        res = requests.get(url, headers=headers, timeout=30)
    except Exception:
        frappe.log_error("PINELABS STATUS API CONNECTION FAILED", frappe.get_traceback())
        return None

    frappe.log_error(title="PINELABS STATUS API RESPONSE", message=res.text)

    if res.status_code != 200:
        frappe.log_error("PINELABS STATUS API NON-200", res.text)
        return None

    return res.json().get("data")



def finalize_pinelabs_payment(order_data):
    """
    Final accounting confirmation for PineLabs payment.
    Idempotent and audit-safe.
    """

    order_id = order_data.get("order_id")
    payments = order_data.get("payments") or []

    if not payments:
        frappe.log_error("PINELABS FINALIZE: NO PAYMENTS FOUND", order_id)
        return

    payment = payments[0]

    # ---- Real payment verification ----
    payment_status = map_pinelabs_status(payment.get("status"))
    if payment_status != "SUCCESS":
        frappe.log_error("PINELABS FINALIZE: PAYMENT NOT SUCCESS", frappe.as_json(payment))
        return

    payment_id = payment.get("id")
    payment_method = payment.get("payment_method")
    created_at = payment.get("created_at")

    acquirer = payment.get("acquirer_data") or {}
    rrn = acquirer.get("rrn") or acquirer.get("acquirer_reference")

    # paise → rupees
    amount = (order_data.get("order_amount", {}).get("value") or 0) / 100
    currency = order_data.get("order_amount", {}).get("currency")

    sales_orders = frappe.get_all(
        "Sales Order",
        filters={"custom_gateway_order_id": order_id},
        pluck="name"
    )

    if not sales_orders:
        frappe.log_error("PINELABS FINALIZE: SALES ORDER NOT FOUND", order_id)
        return

    finalized = []

    for so_name in sales_orders:
        so = frappe.get_doc("Sales Order", so_name)

        # 🔒 Idempotency protection
        if so.custom_payment_status == "SUCCESS":
            continue

        so.custom_gateway_provider = "PINELABS"
        so.custom_gateway_tracking_id = payment_id
        so.custom_payment_mode = payment_method
        so.custom_gateway_response_message = payment.get("status")

        so.custom_payment_status = "SUCCESS"
        so.payment_status = "PAID"

        so.custom_payment_date = created_at
        so.custom_paid_amount = amount
        so.custom_paid_currency = currency

        so.flags.ignore_permissions = True

        if so.docstatus == 0:
            so.submit()
        else:
            so.save()

        finalized.append(so.name)

    if not finalized:
        return

    # ---- Payment Entry (Bank Reference!) ----
    create_payment_entries_per_sales_order(
        sales_order_names=finalized,
        transaction_id=rrn or payment_id,
        payment_mode="Online",
        gateway_provider="PINELABS"
    )

    # ---- SMS only after accounting ----
    try:
        send_checkout_notification(finalized)
    except Exception:
        frappe.log_error("PINELABS SMS FAILED", frappe.get_traceback())

    frappe.db.commit()



@frappe.whitelist(allow_guest=True)
def pinelabs_return():

    params = dict(frappe.form_dict)

    frappe.log_error(
        title="PINELABS RETURN RECEIVED",
        message=frappe.as_json({
            "params": params,
            "headers": dict(frappe.request.headers or {}),
            "ip": frappe.request.remote_addr,
            "method": frappe.request.method
        })
    )

    config = get_pinelabs_config()
    secret = getattr(config, "client_secret", None)

    # -------------------------------------------------
    # 1️⃣ Verify return signature (browser redirect)
    # -------------------------------------------------
    if not verify_pinelabs_return_signature(params, secret):
        frappe.log_error("PINELABS RETURN SIGNATURE FAILED", frappe.as_json(params))
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{FRONTEND_CHECKOUT_URL}?status=failed&gateway=PINELABS"
        return

    order_id = params.get("order_id")

    if not order_id:
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{FRONTEND_CHECKOUT_URL}?status=failed&gateway=PINELABS"
        return

    frappe.log_error("PINELABS RETURN VERIFIED", f"Order {order_id}")

    # -------------------------------------------------
    # 2️⃣ Fetch actual payment result from PineLabs
    # -------------------------------------------------
    order_data = pinelabs_fetch_order(order_id, config)

    if not order_data:
        status = "pending"
    else:
        payments = order_data.get("payments") or [{}]
        pine_status = payments[0].get("status")
        status = map_pinelabs_status(pine_status).lower()

    # -------------------------------------------------
    # 3️⃣ Finalize accounting ONLY if success
    # -------------------------------------------------
    if order_data and status == "success":
        finalize_pinelabs_payment(order_data)

    # -------------------------------------------------
    # 4️⃣ Find related Sales Orders
    # -------------------------------------------------
    sales_order_names = frappe.get_all(
        "Sales Order",
        filters={"custom_gateway_order_id": order_id},
        pluck="name"
    )

    redirect_url = finalize_checkout_and_build_redirect(sales_order_names)

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = redirect_url



@frappe.whitelist(allow_guest=True)
def pinelabs_cancel_return():
    """
    Pine Labs Cancel / Failure Redirect
    USER-FACING endpoint (NOT payment confirmation)

    This endpoint MUST NEVER finalize payment state.
    Only soft-mark abandonment.
    """

    params = dict(frappe.form_dict)
    order_id = params.get("order_id")
    status = (params.get("status") or "CANCELLED").upper()

    # ------------------------------------------------
    # 1️⃣ Log entire event (CRITICAL FOR AUDIT)
    # ------------------------------------------------
    frappe.log_error(
        title="PINELABS CANCEL RETURN RECEIVED",
        message=frappe.as_json({
            "params": params,
            "headers": dict(frappe.request.headers or {}),
            "ip": frappe.request.remote_addr,
            "method": frappe.request.method
        })
    )

    # ------------------------------------------------
    # Safety: missing order id → just redirect UI
    # ------------------------------------------------
    if not order_id:
        frappe.log_error("PINELABS CANCEL: Missing order_id", frappe.as_json(params))
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{FRONTEND_CHECKOUT_URL}?status=failed&gateway=PINELABS"
        return

    # ------------------------------------------------
    # 2️⃣ Find related Sales Orders
    # ------------------------------------------------
    sales_orders = frappe.get_all(
        "Sales Order",
        filters={"custom_gateway_order_id": order_id},
        pluck="name"
    )

    if not sales_orders:
        frappe.log_error("PINELABS CANCEL: No Sales Orders", order_id)
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{FRONTEND_CHECKOUT_URL}?status=failed&gateway=PINELABS"
        return

    # ------------------------------------------------
    # 3️⃣ SOFT ABANDON MARK (IMPORTANT)
    # DO NOT mark FAILED or CANCELLED permanently
    # Webhook or Status API may still confirm payment
    # ------------------------------------------------
    for so_name in sales_orders:
        try:
            so = frappe.get_doc("Sales Order", so_name)

            # Already paid → do nothing
            if so.custom_payment_status == "SUCCESS":
                continue

            # Only mark abandoned if still pending
            if so.custom_payment_status == "PENDING":
                so.custom_payment_status = "ABANDONED"
                so.flags.ignore_permissions = True
                so.save()

        except Exception:
            frappe.log_error(
                title="PINELABS CANCEL UPDATE FAILED",
                message=frappe.get_traceback()
            )

    # ------------------------------------------------
    # 4️⃣ Redirect UI (User experience only)
    # ------------------------------------------------
    redirect_url = (
        f"{FRONTEND_CHECKOUT_URL}"
        f"?orders={','.join(sales_orders)}"
        f"&status=failed"
        f"&payment_flow=ONLINE"
        f"&gateway=PINELABS"
    )

    frappe.log_error("PINELABS CANCEL REDIRECT", redirect_url)

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = redirect_url


def ccavenue_encrypt(payload, working_key):
    if not payload or not working_key:
        return None

    # MD5 key
    key = hashlib.md5(working_key.encode("utf-8")).digest()

    # EXACT IV used by reference
    iv = bytes(range(16))  # \x00\x01...\x0f

    # URL encode
    plain_text = urlencode(payload)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(
        pad(plain_text.encode("utf-8"), AES.block_size)
    )

    # 🔥 HEX — NOT base64
    return encrypted.hex()
 


def ccavenue_decrypt(enc_text, working_key):
    key = hashlib.md5(working_key.encode("utf-8")).digest()
    iv = bytes(range(16))

    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(
        cipher.decrypt(bytes.fromhex(enc_text)),
        AES.block_size
    )

    return decrypted.decode("utf-8")


def initiate_ccavenue_payment(sales_orders, total_amount, config, use_existing_reference=False):
    """
    CC Avenue Non-Seamless Billing Page
    """

    if not config:
        frappe.throw("Missing Payment Gateway Configuration")

    if not config.merchant_id or not config.working_key or not config.access_code:
        frappe.throw("CC Avenue keys are missing")

    if not sales_orders or total_amount <= 0:
        frappe.throw("Invalid order or amount")

    # ------------------------------------------------
    # 1️⃣ Order ID
    # ------------------------------------------------

    # AFTER
    if use_existing_reference:
        merchant_ref = sales_orders[0].custom_internal_payment_reference
    else:
        merchant_ref = (
            f"SO{int(time.time())}{frappe.generate_hash(length=6)}"
        )[:30]
    
    if not merchant_ref:
        merchant_ref = (
            f"SO{int(time.time())}{frappe.generate_hash(length=6)}"
        )[:30]

    # ------------------------------------------------
    # 1.1️⃣ Store PENDING state on ALL Sales Orders
    # ------------------------------------------------
    for so in sales_orders:
        if not use_existing_reference:
            so.custom_payment_mode = "UNKNOWN"

        so.custom_gateway_order_id = merchant_ref # Merchant Order ID (same for all related SOs)
        so.custom_internal_payment_reference = merchant_ref  # internal reference for reconciliation (can be same as merchant_ref or different)
        so.custom_payment_flow = "ONLINE"
        so.custom_gateway_provider = "CCAVENUE"
        so.custom_payment_status = "PENDING"
        so.custom_payment_attempt_count += 1
        so.custom_refund_status = "NOT_REQUESTED"
        so.flags.ignore_permissions = True
        so.save()

        so.flags.ignore_permissions = True
        so.save()

    amount_str = f"{total_amount:.2f}"

    success_url = config.return_url.strip()
    cancel_url = (
        config.cancel_url.strip()
        if getattr(config, "cancel_url", None)
        else success_url
    )

    # ------------------------------------------------
    # 2️⃣ Load Sales Order + Billing Address
    # ------------------------------------------------
    first_so = sales_orders[0]

    if hasattr(first_so, "name"):
        so_name = first_so.name
    else:
        so_name = first_so.get("name")

    so = frappe.get_doc("Sales Order", so_name)

    # ------------------------------------------------
    # 3️⃣ CLEAN CC AVENUE PAYLOAD
    # ------------------------------------------------
    # ------------------------------------------------
    # Generate TID (Transaction ID)
    # ------------------------------------------------

    tid = tid = str(int(time.time() * 1000))[:17]

    payload = [
        ("merchant_id", str(config.merchant_id).strip()),
        ("order_id", merchant_ref),
        ("tid", tid)
    ]

    payload.extend([
        ("currency", "INR"),
        ("amount", amount_str),
        ("redirect_url", success_url),
        ("cancel_url", cancel_url),
        ("language", "EN"),
    ])



    # Billing details
    billing = get_billing_address_from_sale_order(so_name)

    payload.extend([
        ("billing_name", billing["billing_name"]),
        ("billing_address", billing["billing_address"]),
        ("billing_city", billing["billing_city"]),
        ("billing_state", billing["billing_state"]),
        ("billing_zip", billing["billing_zip"]),
        ("billing_country", billing["billing_country"]),
        ("billing_tel", billing["billing_tel"]),
        ("billing_email", billing["billing_email"]),
    ])

    # Build internal payment reference (you already have this)
    payment_reference = merchant_ref  # or any generated ref you use internally

    payload.extend([
        # 🔹 ALL Sales Order IDs (comma-separated)
        ("merchant_param1", ",".join(
            so.name if hasattr(so, "name") else so.get("name")
            for so in sales_orders
        )),

        # 🔹 Internal payment reference (VERY IMPORTANT)
        ("merchant_param2", payment_reference),

        # 🔹 Environment (PRODUCTION / LIVE)
        ("merchant_param3", frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()),

        # 🔹 User / customer identifier
        # ("merchant_param4", user.get("name")),

        # 🔹 Reserved / versioning / source
        ("merchant_param5", "WEB"),
    ])


    # ------------------------------------------------
    # 4️⃣ Encrypt
    # ------------------------------------------------
    enc_request = ccavenue_encrypt(payload, config.working_key)

    if not enc_request:
        frappe.throw("CC Avenue encryption failed")

    # ------------------------------------------------
    # 5️⃣ Final response
    # ------------------------------------------------
    return {
        "payment_url": config.payment_url.strip(),
        "encRequest": enc_request,
        "access_code": config.access_code.strip(),
        "order_id": merchant_ref,
    }


@frappe.whitelist(allow_guest=True)
def ccavenue_return():
    """
    CC Avenue return handler
    - Receives encResp (POST)
    - Decrypts response
    - Updates Sales Orders using merchant order_id
    - Redirects to frontend
    """
    
    # ------------------------------------------------
    # 1️⃣ Get encrypted response
    # ------------------------------------------------
    enc_resp = frappe.form_dict.get("encResp")
    if not enc_resp:
        frappe.log_error(title="Empty encResp received", message="No encrypted response received from CCAvenue")
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = (
            f"{FRONTEND_CHECKOUT_URL}?"
            f"status=failed"
            f"&payment_flow=ONLINE"
            f"&gateway=CCAVENUE"
        )

    # ------------------------------------------------
    # 2️⃣ Load active CC Avenue gateway config
    # ------------------------------------------------
    payment_env = frappe.conf.get("PAYMENT_ENV", "PRODUCTION").upper()

    provider = frappe.get_value(
        "Payment Provider",
        {"provider_code": "CCAVENUE", "is_active": 1},
        "name"
    )
    if not provider:
        frappe.throw("Active CCAVENUE Payment Provider not found")

    config = frappe.get_all(
        "Payment Gateway Configuration",
        filters={
            "gateway_provider": provider,
            "environment": payment_env,
            "is_active": 1
        },
        fields=["working_key"],
        limit=1
    )
    if not config:
        frappe.throw(f"Active CCAVENUE config not found for {payment_env}")

    working_key = config[0].working_key

    # ------------------------------------------------
    # 3️⃣ Decrypt response
    # ------------------------------------------------
    try:
        decrypted = ccavenue_decrypt(enc_resp, working_key)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "CCAVENUE DECRYPT FAILED"
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = (
            f"{FRONTEND_CHECKOUT_URL}?"
            f"status=failed"
            f"&payment_flow=ONLINE"
            f"&gateway=CCAVENUE"
        )
        return
    
    
    response = {}
    for item in decrypted.split("&"):
        if "=" in item:
            k, v = item.split("=", 1)
            response[k] = unquote_plus(v)

    # ------------------------------------------------
    # 4️⃣ Extract gateway fields
    # ------------------------------------------------
    merchant_order_id = response.get("order_id")
    tracking_id = response.get("tracking_id")
    payment_mode = response.get("payment_mode", "UNKNOWN")
    status_message = response.get("status_message", "")
    order_status = response.get("order_status", "").strip().upper()

    paid_amount = float(response.get("amount") or "UNKNOWN")
    currency = response.get("currency") or "UNKNOWN"
    trans_date = response.get("trans_date") or ""


    if not merchant_order_id:
        frappe.throw("Missing order_id in CC Avenue response")


    # ------------------------------------------------
    # 5️⃣ Fetch Sales Orders (AUTHORITATIVE)
    # ------------------------------------------------
    sales_order_names = frappe.get_all(
        "Sales Order",
        filters={"custom_gateway_order_id": merchant_order_id},
        pluck="name"
    )

    # ------------------------------------------------
    # 6️⃣ Map CC Avenue status (USE SAME MAPPER AS SCHEDULER)
    # ------------------------------------------------
    
    erp_status = map_ccavenue_status(order_status)

    if erp_status == "SUCCESS":
        custom_payment_status = "SUCCESS"
        payment_status = "PAID"

    elif erp_status == "FAILED":
        custom_payment_status = "FAILED"
        payment_status = "FAILED"

    else:
        # IMPORTANT: do NOT mark failed on redirect uncertainty
        custom_payment_status = "PENDING"
        payment_status = "UNPAID"

    
    if not sales_order_names:
        frappe.log_error(
            title="CCAVENUE RETURN: NO SALES ORDERS FOUND",
            message=response
        )
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = (
            f"{FRONTEND_CHECKOUT_URL}"
            f"?orders="
            f"&status={'success' if custom_payment_status == 'SUCCESS' else 'failed'}"
            f"&payment_flow=ONLINE"
            f"&gateway=CCAVENUE"
        )

    # ------------------------------------------------
    # 7️⃣ Update Sales Orders (idempotent)
    # ------------------------------------------------

    for so_name in sales_order_names:
        so = frappe.get_doc("Sales Order", so_name)

        # 🔒 Skip if already finalized
        if so.custom_payment_status == "SUCCESS":
            continue

        so.custom_gateway_provider = "CCAVENUE"
        so.custom_gateway_tracking_id = tracking_id
        so.custom_gateway_response_message = status_message
        so.custom_payment_mode = payment_mode
        so.custom_payment_status = custom_payment_status
        so.payment_status = payment_status
        #  Extra fields

        so.custom_payment_date = trans_date
        so.custom_paid_currency = currency
        so.custom_paid_amount = paid_amount

        so.flags.ignore_permissions = True

        # Draft order → can submit
        if custom_payment_status == "SUCCESS" and so.docstatus == 0:            
            so.submit()
        else:
            so.save()

    # ------------------------------------------------
    # 🔐 LOG COMPLETE CC AVENUE RESPONSE (SAFE)
    # ------------------------------------------------
    try:
        frappe.log_error(
            title=f"CCAVENUE | ${tracking_id}",
            message=frappe.as_json({
                # 1️⃣ Raw POST data
                "raw_form_dict": dict(frappe.form_dict),

                # 2️⃣ Encrypted payload
                "encResp": enc_resp,

                # 3️⃣ Decrypted raw string
                "decrypted_raw": decrypted,

                # 4️⃣ Parsed response (key-value)
                "parsed_response": response,

                # 5️⃣ Meta
                "payment_env": payment_env,
                "timestamp": frappe.utils.now(),
            }, indent=2)
        )
    except Exception:
        # Never allow logging failure to break payment flow
        pass
    
    # ------------------------------------------------
    # 8️⃣ Redirect to frontend
    # ------------------------------------------------
    redirect_url = finalize_checkout_and_build_redirect(sales_order_names)

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = redirect_url


def send_checkout_notification(
    sales_order_names,
    sms_send=True,
    email_send=True):    
    """
    Unified checkout notification.

    Sends:
        - One SMS for entire checkout
        - One Email for entire checkout

    Idempotent per payment attempt using:
        custom_internal_payment_reference

    Safe against:
        - webhook retry
        - return URL refresh
        - double callback
    """

    if not sales_order_names:
        return False

    if isinstance(sales_order_names, str):
        sales_order_names = [sales_order_names]

    # Use first order as notification owner
    first_so = frappe.get_doc("Sales Order", sales_order_names[0])

    payment_ref = first_so.custom_internal_payment_reference if first_so.custom_internal_payment_reference else first_so.custom_gateway_order_id

    # ------------------------------------------------
    # IDEMPOTENCY LOCK
    # ------------------------------------------------
    if not payment_ref:
        return False

    if first_so.custom_checkout_notification_sent == payment_ref:
        # already notified for this payment attempt
        return False

    mobile = first_so.contact_mobile

    user = frappe.get_value(
        "User",
        {"mobile_no": mobile},
        ["name", "full_name"],
        as_dict=True
    ) if mobile else None

    email = user.email if user else None
    order_ref = ",".join(sales_order_names)

    # Resolve name
    customer_name = user.full_name if user and user.full_name else "Customer"

    try:
        resolved_name = get_customer_name_from_mobile(mobile)
        if resolved_name:
            customer_name = resolved_name
    except Exception:
        pass

    # ------------------------------------------------
    # SMS
    # ------------------------------------------------
    if sms_send and mobile:
        try:
            SMSService.send_order_placed_sms(
                mobile=mobile,
                customer_name=customer_name,
                order_no=order_ref
            )
        except Exception:
            frappe.log_error(
                title="CHECKOUT SMS FAILED",
                message=frappe.get_traceback()
            )

    # ------------------------------------------------
    # EMAIL (single email for all orders)
    # ------------------------------------------------
    if email_send and email:
        try:
            frappe.sendmail(
                recipients=[email],
                subject="Payment Received - Order Confirmation",
                message=f"""
                    Dear {customer_name},

                    We have successfully received your payment.

                    Your Orders:
                    {order_ref}

                    Thank you for shopping with us.

                    Regards,
                    INVENTRE EDUSERVICES PVT. LTD
                    """
            )
        except Exception:
            frappe.log_error(
                title="CHECKOUT EMAIL FAILED",
                message=frappe.get_traceback()
            )

    # ------------------------------------------------
    # MARK NOTIFICATION COMPLETE (LOCK)
    # ------------------------------------------------
    try:
        first_so.custom_checkout_notification_sent = payment_ref
        first_so.flags.ignore_permissions = True
        first_so.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="CHECKOUT NOTIFICATION LOCK FAILED",
            message=frappe.get_traceback()
        )

    return True


def finalize_checkout_and_build_redirect(sales_order_names):
    """
    Common post-payment finisher.

    Responsibilities:
        1) Create Payment Entry (ONLINE payments only)
        2) Send SMS + Email notification (only once)
        3) Decide overall checkout status
        4) Return frontend redirect URL

    IMPORTANT:
        - Assumes Sales Orders are already updated with payment fields
        - Does NOT verify payment
        - Does NOT modify payment status
        - Does NOT submit orders
    """

    if not sales_order_names:
        return f"{FRONTEND_CHECKOUT_URL}?status=failed"

    if isinstance(sales_order_names, str):
        sales_order_names = [sales_order_names]

    sales_orders = [frappe.get_doc("Sales Order", so) for so in sales_order_names]

    # --------------------------------------------------
    # STEP 1 — Determine overall status
    # --------------------------------------------------
    statuses = [so.custom_payment_status for so in sales_orders]

    if all(s == "SUCCESS" or s == "COD" for s in statuses):
        overall_status = "success"

    elif any(s == "PENDING" for s in statuses):
        overall_status = "pending"

    elif any(s == "SUCCESS" for s in statuses):
        # mixed case (rare but possible multi-order scenario)
        overall_status = "success"

    else:
        overall_status = "failed"

    # --------------------------------------------------
    # STEP 2 — Identify gateway & payment flow
    # (use first order as representative)
    # --------------------------------------------------
    first_so = sales_orders[0]
    gateway = first_so.custom_gateway_provider or "UNKNOWN"

    if gateway in ("PINELABS", "CCAVENUE"):
        payment_flow = "ONLINE"
    elif gateway == "COD":
        payment_flow = "COD"
    elif gateway == "ZERO":
        payment_flow = "ZERO_ORDER"
    else:
        payment_flow = "UNKNOWN"

    # --------------------------------------------------
    # STEP 3 — Create Payment Entries (ONLINE SUCCESS only)
    # --------------------------------------------------
    if overall_status == "success" and payment_flow == "ONLINE":

        try:
            create_payment_entries_per_sales_order(
                sales_order_names=sales_order_names,
                transaction_id=first_so.custom_gateway_tracking_id,
                payment_mode=first_so.custom_payment_mode or "Online",
                gateway_provider=gateway
            )
        except Exception:
            frappe.log_error(
                title="CHECKOUT FINALIZER | PAYMENT ENTRY FAILED",
                message=frappe.get_traceback()
            )

        # After payment entries block, inside `if overall_status == "success" and payment_flow == "ONLINE":`
        for so_name in sales_order_names:
            try:
                finalize_rer_on_replacement_so_payment(so_name)
            except Exception:
                frappe.log_error(
                    title="CHECKOUT FINALIZER | FINALIZE RER FAILED",
                    message=frappe.get_traceback()
                )


    # --------------------------------------------------
    # STEP 4 — Send Notifications (only once)
    # --------------------------------------------------
    if overall_status == "success":
        try:
            # SMS & Email notification
            send_checkout_notification(sales_order_names)

        except Exception:
            frappe.log_error(
                title="CHECKOUT FINALIZER | SMS/EMAIL FAILED",
                message=frappe.get_traceback()
            )

    # --------------------------------------------------
    # STEP 5 — Build Redirect URL
    # --------------------------------------------------
    orders_param = ",".join(sales_order_names)

    redirect_url = (
        f"{FRONTEND_CHECKOUT_URL}"
        f"?orders={orders_param}"
        f"&status={overall_status}"
        f"&payment_flow={payment_flow}"
        f"&gateway={gateway}"
    )

    return redirect_url