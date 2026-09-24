import requests
import frappe
from urllib.parse import quote_plus


class SMSService:
    """
    Central SMS Service
    - Public methods = business intent (register OTP, login OTP, order placed)
    - Internal method = DLT-safe sender
    """

    # =====================================================
    # PUBLIC INTENT METHODS
    # =====================================================

    @classmethod
    def send_register_otp(cls, *, mobile: str, otp: str):
        template_id = "380462"
        dlt_content_id = "1107173978479110904"

        var1 = "Registration"
        var2 = str(otp)
        var3 = "10"

        message = (
            f"Your OTP for {var1} is {var2}. "
            f"Please do not share this OTP with anyone. "
            f"It is valid for {var3} minutes. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="REGISTER_OTP"
        )

    @classmethod
    def send_login_otp(cls, *, mobile: str, otp: str):
        template_id = "380462"
        dlt_content_id = "1107173978479110904"

        var1 = "Login"
        var2 = str(otp)
        var3 = "10"

        message = (
            f"Your OTP for {var1} is {var2}. "
            f"Please do not share this OTP with anyone. "
            f"It is valid for {var3} minutes. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )
        # return message

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="LOGIN_OTP"
        )
    
    @classmethod
    def send_student_update_otp(cls, *, mobile: str, otp: str):
        template_id = "380462"
        dlt_content_id = "1107173978479110904"

        var1 = "Student Update"
        var2 = str(otp)
        var3 = "10"

        message = (
            f"Your OTP for {var1} is {var2}. "
            f"Please do not share this OTP with anyone. "
            f"It is valid for {var3} minutes. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )
        # return message

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="LOGIN_OTP"
        )

    @classmethod
    def send_zero_order_otp(cls, *, mobile: str, otp: str):
        template_id = "380462"
        dlt_content_id = "1107173978479110904"

        var1 = "Zero Order"
        var2 = str(otp)
        var3 = "10"

        message = (
            f"Your OTP for {var1} is {var2}. "
            f"Please do not share this OTP with anyone. "
            f"It is valid for {var3} minutes. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )
        # return message

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="LOGIN_OTP"
        )

    @classmethod
    def send_order_placed_sms(cls, *, mobile: str, customer_name: str, order_no: str):
        template_id = "380461"
        dlt_content_id = "1107174047780441340"

        message = (
            f"Dear {customer_name}, Your order {order_no} has been successfully placed. "
            f"You will receive updates once it is processed. "
            f"INVENTRE EDUSERVICES PVT. LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="ORDER_PLACED"
        )

    # sms_service.py — add inside SMSService class

    @classmethod
    def send_rer_missing_confirmed(cls, *, mobile: str, customer_name: str, order_no: str):
        template_id     = "XXXXXX"           # register your DLT template
        dlt_content_id  = "XXXXXXXXXXXXXXXXX"
        return 0

        message = (
            f"Dear {customer_name}, your missing item request for order {order_no} "
            f"has been approved and a replacement order is confirmed. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="RER_MISSING_CONFIRMED"
        )

    @classmethod
    def send_rer_exchange_confirmed(cls, *, mobile: str, customer_name: str, order_no: str):
        template_id     = "XXXXXX"
        dlt_content_id  = "1107177494996128746"
        return 0

        message = (
            f"Dear {customer_name},"
            f"Exchange request accepted successfully. "
            f"Your new order is confirmed with us and will be delivered in next 7-10 working days. "
            f"Thank you -INVENTRE EDU SERVICES PVT LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="RER_EXCHANGE_CONFIRMED"
        )

    @classmethod
    def send_rer_refund_processing(cls, *, mobile: str, customer_name: str, order_no: str, refund_amount: str):
        template_id     = "XXXXXX"
        dlt_content_id  = "1107177494989068246"
        return 0

        message = (
            f"Dear {customer_name},"
            f"Exchange request accepted successfully. "
            f"Kindly log in to the website www.impressio.in, enter the Bank details to process the refund. "
            f"-INVENTRE EDU SERVICES PVT LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="RER_REFUND_PROCESSING"
        )

    @classmethod
    def send_rer_payment_required(cls, *, mobile: str, customer_name: str, order_no: str, amount: str):
        template_id     = "XXXXXX"
        dlt_content_id  = "1107177494981171274"
        return 0

        message = (
            f"Dear {customer_name},"
            f"Exchange request accepted successfully. "
            f"Kindly log in to our website www.impressio.in, pay the price difference to proceed with the new order. "
            f"-INVENTRE EDU SERVICES PVT LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="RER_PAYMENT_REQUIRED"
        )


    @classmethod
    def send_order_processing_sms(cls, *, mobile: str, customer_name: str, order_no: str):
        template_id = "444515"
        dlt_content_id = "1107177606214041837"

        var1 = str(customer_name)
        var2 = str(order_no)
        
        message = (
            f"Dear {var1}, "
            f"Your Order {var2} is currently under process. "
            f"We sincerely apologize for the delay. "
            f"Please be assured that our team is actively working to deliver your order at the earliest. "
            f"Thank you for your patience and understanding. "
            f"Note: If your order has already been delivered, Please ignore this message. "
            f"- INVENTRE EDUSERVICES PVT. LTD"
        )

        return cls._send_sms(
            mobile=mobile,
            message=message,
            template_id=template_id,
            dlt_content_id=dlt_content_id,
            purpose="ORDER_PROCESSING"
        )

    # =====================================================
    # INTERNAL DLT-SAFE SENDER (DO NOT CALL DIRECTLY)
    # =====================================================

    @classmethod
    def _send_sms(
        cls,
        *,
        mobile: str,
        message: str,
        template_id: str,
        dlt_content_id: str,
        purpose: str,
        unicode: bool = False
    ):
        """
        Sends SMS via Arihant HTTP API (DLT compliant)
        """

        cfg = frappe.conf.get("sms_gateway")
        if not cfg:
             return False, {"error": "SMS Gateway not configured"}

        payload = {
            "username": cfg["username"],                       # inventreedu.trans
            "password": cfg["password"],
            "from": cfg["sender_id"],                          # 6 alpha
            "to":  SMSService.normalize_indian_mobile(mobile),
            "unicode": "true" if unicode else "false",
            "text": message,   
            "dltContentId": dlt_content_id,                    # correct case
            "dltPrincipalEntityId": cfg["dlt_pe_id"],          # REQUIRED
        }

        if template_id:
            payload["templateId"] = template_id


        # Log sanitized request
        frappe.log_error(
            title="SMS REQUEST",
            message={
                "purpose": purpose,
                "payload": cls._sanitize(payload)
            }
        )

        try:
            res = requests.post(
                cfg["base_url"],
                data=payload,
                timeout=10
            )

            try:
                response = res.json()
            except Exception:
                response = {
                    "http_status": res.status_code,
                    "raw": res.text
                }

            frappe.log_error(
                title="SMS RESPONSE",
                message=response
            )

            cls._log_sms(payload, response, purpose, message)

            success = response.get("state") == "SUBMIT_ACCEPTED"
            return success, response

        except Exception as e:
            frappe.log_error(
                title="SMS TRANSPORT ERROR",
                message=str(e)
            )
            return False, str(e)

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    @staticmethod
    def _sanitize(payload: dict) -> dict:
        safe = payload.copy()
        if "password" in safe:
            safe["password"] = "****"
        return safe

    @staticmethod
    def _log_sms(payload, response, purpose, message):
        frappe.get_doc({
            "doctype": "SMS Log",
            "mobile": payload.get("to"),
            "purpose": purpose,
            "message": message,
            "template_id": payload.get("templateId"),
            "dlt_content_id": payload.get("dltContentId"),
            "transaction_id": response.get("transactionId"),
            "status": response.get("state"),
            "status_code": response.get("statusCode"),
            "description": response.get("description"),
            "raw_response": frappe.as_json(response)
        }).insert(ignore_permissions=True)

    @staticmethod
    def normalize_indian_mobile(mobile: str) -> str:
        m = mobile.strip().replace(" ", "").replace("-", "").replace("+", "")
        if m.startswith("91") and len(m) == 12:
            return m
        if len(m) == 10:
            return f"91{m}"
        return m  # fallback (let gateway decide)
