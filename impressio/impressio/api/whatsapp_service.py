import requests
import frappe


class WhatsAppService:
    """
    WhatsApp Service — Tata Tele Business (Omni)
    Server  : https://wb.omni.tatatelebusiness.com
    Endpoint: POST /whatsapp-cloud/messages
    Auth    : Authorization header (Bearer token from TTBS dashboard)
    """

    # =====================================================
    # PUBLIC INTENT METHODS
    # =====================================================

    @classmethod
    def send_order_delay_update(cls, *, mobile: str, customer_name: str, order_no: str):
        """
        Template : order_delay_update
        {{1}}    : customer_name
        {{2}}    : order_no
        """
        return cls._send_template(
            mobile=mobile,
            template_name="order_delay_update",
            language_code="en",
            body_params=[customer_name, order_no],
            purpose="ORDER_DELAY_UPDATE",
            sales_order=order_no
        )

    # =====================================================
    # INTERNAL TTBS SENDER — DO NOT CALL DIRECTLY
    # =====================================================

    @classmethod
    def _send_template(
        cls,
        *,
        mobile: str,
        template_name: str,
        language_code: str,
        body_params: list,
        purpose: str,
        header_params: list = None,
        sales_order: str = None
    ):
        cfg = frappe.conf.get("whatsapp_gateway")
        if not cfg:
            return False, {"error": "WhatsApp Gateway not configured"}

        to_number = WhatsAppService.format_mobile(mobile)

        # Build components
        components = []

        if header_params:
            components.append({
                "type": "header",
                "parameters": [
                    {"type": "text", "text": str(v)} for v in header_params
                ]
            })

        if body_params:
            components.append({
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(v)} for v in body_params
                ]
            })

        payload = {
            "to": to_number,                 # e.g. +919090909090
            "type": "template",
            "source": "external",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code    # "en"
                },
                "components": components
            }
        }

        headers = {
            "Content-Type":  "application/json",
            "Authorization": cfg["auth_token"],   # TTBS gives token directly, no "Bearer " prefix needed
        }

        frappe.log_error(
            title="WA REQUEST",
            message={
                "purpose":  purpose,
                "to":       to_number,
                "template": template_name,
                "params":   body_params
            }
        )

        try:
            res = requests.post(
                cfg["base_url"],     # https://wb.omni.tatatelebusiness.com/whatsapp-cloud/messages
                json=payload,
                headers=headers,
                timeout=10
            )

            try:
                response = res.json()
            except Exception:
                response = {
                    "http_status": res.status_code,
                    "raw": res.text
                }

            frappe.log_error(title="WA RESPONSE", message=response)

            cls._log_whatsapp(to_number, template_name, body_params, response, purpose, sales_order)

            # ✅ Success = response has "id" field  (per TTBS docs: {"id": "bf07a16a-..."})
            # ❌ Failure = response has "error" or "status": "ERROR"
            success = bool(response.get("id"))
            return success, response

        except Exception as e:
            frappe.log_error(title="WA TRANSPORT ERROR", message=str(e))
            return False, str(e)

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    @staticmethod
    def _log_whatsapp(to, template_name, body_params, response, purpose, sales_order=None):
        frappe.get_doc({
            "doctype":       "WhatsApp Log",
            "mobile":        to,
            "sales_order":   sales_order if sales_order is not None else None,  # assuming order_no is always the 2nd param
            "purpose":       purpose,
            "template_name": template_name,
            "body_params":   frappe.as_json(body_params),
            "message_id":    response.get("id"),
            "status":        "SUCCESS" if response.get("id") else response.get("error", "FAILED"),
            "raw_response":  frappe.as_json(response)
        }).insert(ignore_permissions=True)

    @staticmethod
    def format_mobile(mobile: str) -> str:
        """
        TTBS requires international format with + prefix.
        e.g. 9188701851128 or 88701851128 → +919190909090
        """
        m = mobile.strip().replace(" ", "").replace("-", "").replace("+", "")
        if m.startswith("91") and len(m) == 12:
            return f"+{m}"
        if len(m) == 10:
            return f"+91{m}"
        return f"+{m}"   # fallback