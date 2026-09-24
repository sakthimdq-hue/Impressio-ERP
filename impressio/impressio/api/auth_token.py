import secrets
import frappe
from frappe.utils import now_datetime, add_days

TOKEN_EXPIRY_DAYS = 7


# ------------------------------------------------
# CREATE TOKEN
# ------------------------------------------------
def generate_token(user, device=None):
    token = secrets.token_urlsafe(32)

    frappe.get_doc({
        "doctype": "Website Auth Token",
        "user": user,                 # User.name
        "token": token,
        "enabled": 1,
        "expires_at": add_days(now_datetime(), TOKEN_EXPIRY_DAYS),
        "device": device,
        "ip_address": frappe.local.request_ip if frappe.local else None,
    }).insert(ignore_permissions=True)

    return token


# ------------------------------------------------
# READ TOKEN FROM REQUEST (Bearer FIRST)
# ------------------------------------------------
def get_request_token():
    """
    Resolve auth token without triggering Frappe's auth middleware.
    """

    # 1️⃣ Custom header (PRIMARY)
    token = frappe.get_request_header("X-Auth-Token")
    if token:
        return token.strip()

    # 2️⃣ Cookie fallback (browser only)
    try:
        if hasattr(frappe, "request") and frappe.request:
            return frappe.request.cookies.get("auth_token")
    except Exception:
        pass

    return None



# ------------------------------------------------
# VALIDATE TOKEN
# ------------------------------------------------
def validate_token(token):
    if not token:
        return None

    return frappe.get_value(
        "Website Auth Token",
        {
            "token": token,
            "enabled": 1,
            "expires_at": [">", now_datetime()]
        },
        "user"    # returns User.name (string)
    )


# ------------------------------------------------
# REVOKE TOKEN (LOGOUT)
# ------------------------------------------------
def revoke_token(token):
    if not token:
        return

    frappe.db.delete("Website Auth Token", {"token": token})
    frappe.db.commit()


def revoke_all_tokens(user):
    if not user:
        return

    frappe.db.delete("Website Auth Token", {"user": user})
    frappe.db.commit()