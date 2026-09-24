import time
import json
import random
import subprocess
import tempfile
import os

import frappe
from frappe.utils import now_datetime, add_to_date
from .base_carrier import BaseCarrier


class EkartCarrier(BaseCarrier):

    def __init__(self, settings):
        super().__init__(settings)
        self.settings = settings

        _timeout = getattr(settings, "ekart_timeout", None)
        self.timeout = int(_timeout) if _timeout and int(_timeout) > 0 else 30
        self.debug_mode = bool(getattr(settings, "ekart_debug_mode", False))

        self.client_code_large = "IEL"
        self.client_code_non_large = "IES"

        self._token_ies = None
        self._token_iel = None
        self._token_expiry_ies = None
        self._token_expiry_iel = None
        self._retry_count = 0

    # ======================================================
    # BASE URLS
    # ======================================================

    def _get_base_urls(self):
        is_sandbox = getattr(self.settings, "ekart_environment", "Sandbox") == "Sandbox"
        if is_sandbox:
            return {
                "token":           "https://staging.ekartlogistics.com/auth/token",
                "create_shipment": "https://staging.ekartlogistics.com/v2/shipments/create",
                "track_shipment":  "https://staging.ekartlogistics.com/v2/shipments/track",
                "create_large":    "https://staging.ekartlogistics.com/shipments/large/create",
                "track_large":     "https://staging.ekartlogistics.com/shipments/large/track",
                "cancel_large":    "https://staging.ekartlogistics.com/shipments/large/rto/create",
                "cancel_non_large":"https://staging.ekartlogistics.com/v2/shipments/cancel",
            }
        else:
            return {
                "token":           "https://api.ekartlogistics.com/auth/token",
                "create_shipment": "https://api.ekartlogistics.com/v2/shipments/create",
                "track_shipment":  "https://api.ekartlogistics.com/v2/shipments/track",
                "create_large":    "https://api.ekartlogistics.com/shipments/large/create",
                "track_large":     "https://api.ekartlogistics.com/shipments/large/track",
                "cancel_large":    "https://api.ekartlogistics.com/shipments/large/rto/create",
                "cancel_non_large":"https://api.ekartlogistics.com/v2/shipments/cancel",
            }

    # ======================================================
    # AUTH
    # ======================================================

    def _get_basic_auth_header(self, is_large=False):
        is_sandbox = getattr(self.settings, "ekart_environment", "Sandbox") == "Sandbox"
        if is_sandbox:
            auth = (
                self.settings.get_password("ekart_auth_large_staging")
                if is_large
                else self.settings.get_password("ekart_auth_non_large_staging")
            )
        else:
            auth = (
                self.settings.get_password("ekart_auth_large_production")
                if is_large
                else self.settings.get_password("ekart_auth_non_large_production")
            )
        if not auth:
            raise Exception("Ekart Auth Code missing in Logistics Settings")
        return auth if auth.startswith("Basic ") else f"Basic {auth}"

    # ======================================================
    # HTTP REQUEST — uses curl subprocess
    # ======================================================

    def _http_request(self, method, url, headers, body=None):
        cmd = ["curl", "-s", "-w", "\n__STATUS__%{http_code}", "-X", method.upper()]

        for key, value in headers.items():
            cmd += ["-H", f"{key}: {value}"]

        tmp_file = None
        if body:
            body_str = body if isinstance(body, str) else body.decode("utf-8")
            tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            tmp_file.write(body_str)
            tmp_file.close()
            cmd += ["--data-binary", f"@{tmp_file.name}"]

        cmd.append(url)

        if self.debug_mode:
            frappe.log_error(
                title="Ekart curl Command",
                message=" ".join(str(c) for c in cmd)
            )

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            output = result.stdout

            if "__STATUS__" in output:
                parts = output.rsplit("__STATUS__", 1)
                response_text = parts[0].strip()
                status_code = int(parts[1].strip())
            else:
                response_text = output
                status_code = 200

            if self.debug_mode:
                frappe.log_error(
                    title="Ekart curl Response",
                    message=f"Status: {status_code}\n{response_text}"
                )

            return status_code, response_text

        except subprocess.TimeoutExpired:
            raise Exception(f"Ekart API timeout after {self.timeout}s")
        except Exception as e:
            raise Exception(f"Ekart curl error: {str(e)}")
        finally:
            if tmp_file and os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)

    # ======================================================
    # TOKEN MANAGEMENT
    # ======================================================

    def _fetch_token(self, is_large=False):
        urls = self._get_base_urls()
        merchant_code = self.client_code_large if is_large else self.client_code_non_large

        headers = {
            "Authorization": self._get_basic_auth_header(is_large),
            "HTTP_X_MERCHANT_CODE": merchant_code,
            "Content-Type": "application/json"
        }

        if self.debug_mode:
            frappe.log_error(
                title="Ekart Token Fetch",
                message=f"URL: {urls['token']}\nMerchant: {merchant_code}\nis_large: {is_large}"
            )

        status_code, response_text = self._http_request(
            method="POST", url=urls["token"], headers=headers, body=b""
        )

        if self.debug_mode:
            frappe.log_error(
                title="Ekart Token Response",
                message=f"Status: {status_code}\n{response_text}"
            )

        if status_code != 200:
            raise Exception(f"Token fetch failed ({status_code}): {response_text}")

        token_data = json.loads(response_text)
        auth_header = token_data.get("Authorization", "")
        token_string = auth_header.replace("Bearer ", "").strip()

        if not token_string:
            raise Exception(f"No token in response: {token_data}")

        expiry = add_to_date(None, minutes=40)
        if is_large:
            self._token_iel = token_string
            self._token_expiry_iel = expiry
        else:
            self._token_ies = token_string
            self._token_expiry_ies = expiry

        frappe.log_error(
            title=f"Ekart Token Fetched ({'IEL' if is_large else 'IES'})",
            message=f"Merchant: {merchant_code}\nToken preview: {token_string[:30]}..."
        )
        return token_string

    def _get_token(self, is_large=False):
        if is_large:
            if self._token_iel and self._token_expiry_iel and now_datetime() < self._token_expiry_iel:
                return self._token_iel
        else:
            if self._token_ies and self._token_expiry_ies and now_datetime() < self._token_expiry_ies:
                return self._token_ies
        return self._fetch_token(is_large)

    # ======================================================
    # GENERIC REQUEST
    # ======================================================

    def _request(self, method, url, payload=None, is_large=False):
        merchant_code = self.client_code_large if is_large else self.client_code_non_large
        token = self._get_token(is_large)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "HTTP_X_MERCHANT_CODE": merchant_code,
        }

        body = json.dumps(payload).encode("utf-8") if payload else b""

        if self.debug_mode:
            frappe.log_error(
                title="Ekart API Request",
                message=f"URL: {url}\nMethod: {method}\nis_large: {is_large}\nMerchant: {merchant_code}\nPayload:\n{json.dumps(payload, indent=2) if payload else None}"
            )

        status_code, response_text = self._http_request(
            method=method, url=url, headers=headers, body=body
        )

        if self.debug_mode:
            frappe.log_error(
                title="Ekart API Response",
                message=f"Status: {status_code}\n{response_text}"
            )

        if status_code == 401 and self._retry_count == 0:
            self._retry_count = 1
            if is_large:
                self._token_iel = None
                frappe.log_error("Ekart IEL Token Expired", "Refreshing IEL token and retrying...")
            else:
                self._token_ies = None
                frappe.log_error("Ekart IES Token Expired", "Refreshing IES token and retrying...")
            return self._request(method, url, payload, is_large)

        self._retry_count = 0

        if status_code >= 400:
            raise Exception(f"Ekart API error ({status_code}): {response_text}")

        return json.loads(response_text)

    # ======================================================
    # HELPERS
    # ======================================================

    def _is_large_shipment(self, weight):
        """Check if shipment is large based on weight threshold (default 4kg)"""
        threshold = getattr(self.settings, "ekart_large_weight_threshold", 4) or 4
        return float(weight) > float(threshold)

    def _generate_global_tracking_id(self):
        """Generates IELN tracking — used for global_shipment in large shipments"""
        timestamp = str(int(time.time()))[-6:]
        rand = str(random.randint(1000, 9999))
        unique = (timestamp + rand)[:10].zfill(10)
        return f"{self.client_code_large}N{unique}"

    def _generate_piece_tracking_id(self, sequence=1):
        """Generates IELP tracking — used for pieces in large shipments"""
        timestamp = str(int(time.time()))[-6:]
        rand = str(random.randint(100, 999))
        unique = (timestamp + rand + str(sequence))[:10].zfill(10)
        return f"{self.client_code_large}P{unique}"

    def _generate_non_large_tracking_id(self, payment_type):
        """Generates IES tracking for non-large shipments"""
        type_code = "C" if payment_type == "COD" else "P"
        timestamp = str(int(time.time()))[-6:]
        rand = str(random.randint(1000, 9999))
        unique = (timestamp + rand)[:10].zfill(10)
        return f"{self.client_code_non_large}{type_code}{unique}"

    # ======================================================
    # CREATE SHIPMENT — MAIN ENTRY
    # ======================================================

    # def create_shipment(self, shipment_data):
    #     weight = float(shipment_data["package"]["weight"])
        
    #     # Check for multiple packages
    #     packages = shipment_data.get("packages", [])
    #     if not packages:
    #         packages = [shipment_data["package"]]
        
    #     is_multi_piece = len(packages) > 1
        
    #     urls = self._get_base_urls()

    #     frappe.log_error(
    #         title="Ekart Create Shipment",
    #         message=f"is_multi_piece: {is_multi_piece}\nNum packages: {len(packages)}\nWeight: {weight}kg"
    #     )

    #     if is_multi_piece:
    #         # ONLY multi-piece shipments use Large API (IEL)
    #         piece_tracking_ids = []
    #         for i, package in enumerate(packages, 1):
    #             piece_tracking_ids.append(self._generate_piece_tracking_id(i))
            
    #         global_tracking_id = self._generate_global_tracking_id()
            
    #         payload = self._build_large_payload_multi_piece(
    #             shipment_data, 
    #             piece_tracking_ids, 
    #             global_tracking_id,
    #             packages
    #         )
            
    #         url = urls["create_large"]
    #         frappe.log_error(title="Ekart Large Payload (Multi-Piece)", message=json.dumps(payload, indent=2))
    #         response = self._request("POST", url, payload, is_large=True)
    #         return self._parse_large_response_multi_piece(response, piece_tracking_ids, global_tracking_id)
        
    #     else:
    #         # ALL single-piece shipments use Non-Large API (IES)
    #         tracking_id = self._generate_non_large_tracking_id(
    #             shipment_data["order"]["payment_type"]
    #         )
            
    #         payload = self._build_non_large_payload(shipment_data, tracking_id)
    #         url = urls["create_shipment"]
            
    #         frappe.log_error(title="Ekart Non-Large Payload", message=json.dumps(payload, indent=2))
    #         response = self._request("POST", url, payload, is_large=False)
    #         return self._parse_non_large_response(response, tracking_id)
    
    
        
    def create_shipment(self, shipment_data):
        """
        Create shipment with Ekart using Large API (IEL).
        
        Routes based on shipment type:
        - Multi-piece or weight > threshold → Large API (IEL)
        - Single-piece and light → Non-Large API (IES)
        
        Args:
            shipment_data: Dict with customer, package, order info
        
        Returns:
            dict: Success/failure response with tracking number
        """
        try:
            weight = float(shipment_data["package"]["weight"])
            
            # Check for multiple packages
            packages = shipment_data.get("packages", [])
            if not packages:
                packages = [shipment_data["package"]]
            
            is_multi_piece = len(packages) > 1
            is_large_weight = self._is_large_shipment(weight)
            
            urls = self._get_base_urls()
 
            frappe.log_error(
                title="Ekart Create Shipment",
                message=f"is_multi_piece: {is_multi_piece}\nNum packages: {len(packages)}\nWeight: {weight}kg\nis_large_weight: {is_large_weight}"
            )
 
            # ========== ROUTE: Multi-piece OR heavy single-piece → Large API (IEL) ==========
            if is_multi_piece or is_large_weight:
                
                if is_multi_piece:
                    # Multi-piece: Use Large API with MPS structure
                    piece_tracking_ids = []
                    for i, package in enumerate(packages, 1):
                        piece_tracking_ids.append(self._generate_piece_tracking_id(i))
                    
                    global_tracking_id = self._generate_global_tracking_id()
                    
                    payload = self._build_large_payload_multi_piece(
                        shipment_data, 
                        piece_tracking_ids, 
                        global_tracking_id,
                        packages
                    )
                    
                    url = urls["create_large"]
                    frappe.log_error(
                        title="Ekart Large Payload (Multi-Piece)",
                        message=json.dumps(payload, indent=2)
                    )
                    response = self._request("POST", url, payload, is_large=True)
                    return self._parse_large_response_multi_piece(
                        response, 
                        piece_tracking_ids, 
                        global_tracking_id
                    )
                
                else:
                    # Single-piece but heavy: Use Large API
                    piece_tracking_id = self._generate_piece_tracking_id(1)
                    global_tracking_id = self._generate_global_tracking_id()
                    
                    payload = self._build_large_payload_single_piece_simple(
                        shipment_data,
                        global_tracking_id,
                        piece_tracking_id,
                        packages[0]
                    )
                    
                    url = urls["create_large"]
                    frappe.log_error(
                        title="Ekart Large Payload (Single-Piece Heavy)",
                        message=json.dumps(payload, indent=2)
                    )
                    response = self._request("POST", url, payload, is_large=True)
                    return self._parse_large_response_single_piece_simple(
                        response,
                        global_tracking_id,
                        piece_tracking_id
                    )
            
            # ========== ROUTE: Single-piece AND light → Non-Large API (IES) ==========
            else:
                tracking_id = self._generate_non_large_tracking_id(
                    shipment_data["order"]["payment_type"]
                )
                
                payload = self._build_non_large_payload(shipment_data, tracking_id)
                url = urls["create_shipment"]
                
                frappe.log_error(
                    title="Ekart Non-Large Payload",
                    message=json.dumps(payload, indent=2)
                )
                response = self._request("POST", url, payload, is_large=False)
                return self._parse_non_large_response(response, tracking_id)
 
        except Exception as e:
            # ← PROPER EXCEPTION HANDLING WITH CORRECT INDENTATION
            frappe.log_error(
                title="Ekart Create Shipment - Exception",
                message=f"Error: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )
            return {
                "success": False,
                "error_message": str(e),
                "error_details": frappe.get_traceback()
     }
 
    # ======================================================
    # BUILD PAYLOAD — NON-LARGE
    # ======================================================

    def _build_non_large_payload(self, shipment_data, tracking_id):
        is_cod = shipment_data["order"]["payment_type"] == "COD"
        customer = shipment_data["customer"]
        package = shipment_data["package"]

        dimensions = package.get("dimensions", {})
        length = float(dimensions.get("length", 0))
        width  = float(dimensions.get("width", 0))
        height = float(dimensions.get("height", 0))
        weight = float(package.get("weight", 0.5))

        if length <= 0: length = 10
        if width  <= 0: width  = 10
        if height <= 0: height = 10
        if weight <= 0: weight = 0.5

        order_id   = str(shipment_data.get("external_id", f"ORD{int(time.time())}"))
        invoice_id = shipment_data.get("order", {}).get("invoice_number") or f"INV{order_id}"
        goods_category = getattr(self.settings, "ekart_goods_category", "ESSENTIAL") or "ESSENTIAL"

        return {
            "client_name": self.client_code_non_large,
            "goods_category": goods_category,
            "services": [
                {
                    "service_code": getattr(self.settings, "ekart_default_service", "REGULAR") or "REGULAR",
                    "service_details": [
                        {
                            "service_leg": "FORWARD",
                            "service_data": {
                                "service_types": [
                                    {"name": "regional_handover", "value": "true"},
                                    {"name": "delayed_dispatch",  "value": "false"}
                                ],
                                "vendor_name": "Ekart",
                                "amount_to_collect": str(shipment_data["order"].get("cod_amount", 0)) if is_cod else "0",
                                "dispatch_date": "",
                                "customer_promise_date": "",
                                "delivery_type": "SMALL",
                                "source": {"address": {
                                    "first_name": self.settings.ekart_sender_name,
                                    "address_line1": self.settings.ekart_sender_address,
                                    "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                    "pincode": str(self.settings.ekart_sender_pincode),
                                    "city": self.settings.ekart_sender_city,
                                    "state": self.settings.ekart_sender_state,
                                    "primary_contact_number": self.settings.ekart_sender_phone,
                                    "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                }},
                                "destination": {"address": {
                                    "first_name": customer.get("name", ""),
                                    "address_line1": customer.get("address", ""),
                                    "address_line2": customer.get("address_line2", "") or "",
                                    "pincode": str(customer.get("pincode", "")),
                                    "city": customer.get("city", ""),
                                    "state": customer.get("state", ""),
                                    "primary_contact_number": customer.get("phone", ""),
                                    "email_id": customer.get("email", "") or ""
                                }},
                                "return_location": {"address": {
                                    "first_name": f"{self.settings.ekart_sender_name} RTO",
                                    "address_line1": self.settings.ekart_sender_address,
                                    "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                    "pincode": str(self.settings.ekart_sender_pincode),
                                    "city": self.settings.ekart_sender_city,
                                    "state": self.settings.ekart_sender_state,
                                    "primary_contact_number": self.settings.ekart_sender_phone,
                                    "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                }}
                            },
                            "shipment": {
                                "client_reference_id": tracking_id,
                                "tracking_id": tracking_id,
                                "shipment_value": str(int(float(package.get("value", 0)))),
                                "shipment_dimensions": {
                                    "length":  {"value": str(int(length))},
                                    "breadth": {"value": str(int(width))},
                                    "height":  {"value": str(int(height))},
                                    "weight":  {"value": str(weight)}
                                },
                                "return_label_desc_1": "",
                                "return_label_desc_2": "",
                                "shipment_items": [
                                    {
                                        "product_id": package.get("sku") or order_id,
                                        "category": package.get("category", "GENERAL"),
                                        "product_title": (package.get("description", "Goods") or "Goods")[:100],
                                        "quantity": str(int(package.get("quantity", 1))),
                                        "cost": {
                                            "total_sale_value": float(package.get("value", 0)),
                                            "total_tax_value": 0,
                                            "tax_breakup": {"cgst": "0", "sgst": "0", "igst": "0"}
                                        },
                                        "seller_details": {
                                            "seller_reg_name": self.settings.ekart_seller_name or self.settings.ekart_sender_name,
                                            "gstin_id": getattr(self.settings, "ekart_gstin", "") or "",
                                            "brand_communication_name": self.settings.ekart_brand_name or self.settings.ekart_sender_name
                                        },
                                        "hsn": getattr(self.settings, "ekart_hsn", "") or "",
                                        "ern": "",
                                        "discount": 0,
                                        "item_attributes": [
                                            {"name": "order_id",        "value": order_id},
                                            {"name": "invoice_id",      "value": invoice_id},
                                            {"name": "item_dimensions", "value": f"{int(length)}:{int(width)}:{int(height)}:{weight}"},
                                            {"name": "brand_name",      "value": self.settings.ekart_brand_name or self.settings.ekart_sender_name},
                                            {"name": "eway_bill_number","value": ""}
                                        ],
                                        "handling_attributes": [
                                            {"name": "isFragile",   "value": "false"},
                                            {"name": "isDangerous", "value": "false"}
                                        ]
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    # ======================================================
    # BUILD PAYLOAD — LARGE SINGLE-PIECE (SIMPLIFIED - NO MPS)
    # ======================================================

    def _build_large_payload_single_piece_simple(self, shipment_data, global_tracking_id, piece_tracking_id, package):
        is_cod = shipment_data["order"]["payment_type"] == "COD"
        customer = shipment_data["customer"]
        
        dimensions = package.get("dimensions", {})
        length = float(dimensions.get("length", 0))
        width = float(dimensions.get("width", 0))
        height = float(dimensions.get("height", 0))
        
        if length <= 0: length = 30
        if width <= 0: width = 20
        if height <= 0: height = 20
        
        weight = float(package.get("weight", 0))
        if weight <= 0: 
            threshold = getattr(self.settings, "ekart_large_weight_threshold", 4)
            weight = threshold + 0.1
        
        weight_grams = int(weight * 1000)
        
        total_sale_value = float(package.get("value", 0))
        total_tax_value = float(package.get("tax", 0))
        
        order_id = str(shipment_data.get("external_id", f"ORD{int(time.time())}"))
        invoice_id = shipment_data.get("order", {}).get("invoice_number") or f"INV{order_id}"
        
        return {
            "services": [
                {
                    "service_code": getattr(self.settings, "ekart_default_service", "REGULAR") or "REGULAR",
                    "service_details": [
                        {
                            "service_leg": "FORWARD",
                            "service_data": {
                                "vendor_name": "Ekart",
                                "amount_to_collect": str(shipment_data["order"].get("cod_amount", 0)) if is_cod else "0",
                                "delivery_type": "LARGE",
                                "offering_tier": getattr(self.settings, "ekart_offering_tier_large", "P4") or "P4",
                                "source": {
                                    "address": {
                                        "first_name": self.settings.ekart_sender_name,
                                        "address_line1": self.settings.ekart_sender_address,
                                        "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                        "pincode": str(self.settings.ekart_sender_pincode),
                                        "city": self.settings.ekart_sender_city,
                                        "state": self.settings.ekart_sender_state,
                                        "primary_contact_number": self.settings.ekart_sender_phone,
                                        "landmark": getattr(self.settings, "ekart_sender_landmark", "") or "",
                                        "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                    }
                                },
                                "destination": {
                                    "address": {
                                        "first_name": customer.get("name", ""),
                                        "address_line1": customer.get("address", ""),
                                        "address_line2": customer.get("address_line2", "") or "",
                                        "pincode": str(customer.get("pincode", "")),
                                        "city": customer.get("city", ""),
                                        "state": customer.get("state", ""),
                                        "primary_contact_number": customer.get("phone", ""),
                                        "landmark": customer.get("landmark", "") or "",
                                        "email_id": customer.get("email", "") or "",
                                        "alternate_contact_number": customer.get("alternate_phone", "") or ""
                                    }
                                },
                                "return_location": {
                                    "address": {
                                        "first_name": f"{self.settings.ekart_sender_name} RTO",
                                        "address_line1": self.settings.ekart_sender_address,
                                        "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                        "pincode": str(self.settings.ekart_sender_pincode),
                                        "city": self.settings.ekart_sender_city,
                                        "state": self.settings.ekart_sender_state,
                                        "primary_contact_number": self.settings.ekart_sender_phone,
                                        "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                    }
                                }
                            },
                            "global_shipment": {
                                "client_reference_id": "",
                                "tracking_id": "",
                                "shipment_value": str(int(total_sale_value)),
                                "cost": {
                                    "total_tax_value": str(total_tax_value),
                                    "total_sale_value": str(int(total_sale_value)),
                                    "tax_breakup": {
                                        "cgst": "0",
                                        "sgst": "0",
                                        "igst": str(total_tax_value)
                                    }
                                },
                                "attributes": [
                                    {"name": "order_id", "value": order_id},
                                    {"name": "invoice_id", "value": invoice_id},
                                    {"name": "eway_bill_number", "value": shipment_data.get("eway_bill_number", "")}
                                ],
                                "hsn": getattr(self.settings, "ekart_hsn", "") or "",
                                "ern": shipment_data.get("ern", ""),
                                "total_weight": str(weight_grams),
                                "seller_details": {
                                    "seller_reg_name": self.settings.ekart_seller_name or self.settings.ekart_sender_name,
                                    "gstin_id": getattr(self.settings, "ekart_gstin", "") or ""
                                }
                            },
                            "shipments": [
                                {
                                    "tracking_id": piece_tracking_id,
                                    "shipment_items": [
                                        {
                                            "product_id": package.get("sku") or order_id,
                                            "product_title": (package.get("description", "Item") or "Item")[:100],
                                            "category": package.get("category", "GENERAL"),
                                            "handling_attributes": [
                                                {"name": "isDangerous", "value": "false"},
                                                {"name": "isFragile", "value": "false"}
                                            ]
                                        }
                                    ],
                                    "shipment_dimensions": {
                                        "length": {"value": str(int(length))},
                                        "height": {"value": str(int(height))},
                                        "weight": {"value": str(weight_grams)},
                                        "breadth": {"value": str(int(width))}
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }
   # ======================================================
    # BUILD PAYLOAD — LARGE MULTI-PIECE (MPS STRUCTURE)
    # ======================================================

   

    def _build_large_payload_multi_piece(self, shipment_data, piece_tracking_ids, global_tracking_id, packages):
        is_cod = shipment_data["order"]["payment_type"] == "COD"
        customer = shipment_data["customer"]
        
        main_package = packages[0]
        dimensions = main_package.get("dimensions", {})
        length = float(dimensions.get("length", 0))
        width = float(dimensions.get("width", 0))
        height = float(dimensions.get("height", 0))
        
        if length <= 0: length = 30
        if width <= 0: width = 20
        if height <= 0: height = 20
        
        total_weight_grams = 0
        total_sale_value = 0
        total_tax_value = 0
        
        for package in packages:
            weight = float(package.get("weight", 0))
            if weight <= 0: 
                threshold = getattr(self.settings, "ekart_large_weight_threshold", 4)
                weight = threshold + 0.1
            total_weight_grams += int(weight * 1000)
            total_sale_value += float(package.get("value", 0))
            total_tax_value += float(package.get("tax", 0))
        
        order_id = str(shipment_data.get("external_id", f"ORD{int(time.time())}"))
        invoice_id = shipment_data.get("order", {}).get("invoice_number") or f"INV{order_id}"
        
        shipments = []
        for idx, (package, piece_tracking_id) in enumerate(zip(packages, piece_tracking_ids)):
            package_dimensions = package.get("dimensions", dimensions)
            pkg_length = float(package_dimensions.get("length", length))
            pkg_width = float(package_dimensions.get("width", width))
            pkg_height = float(package_dimensions.get("height", height))
            pkg_weight = float(package.get("weight", 0))
            if pkg_weight <= 0:
                threshold = getattr(self.settings, "ekart_large_weight_threshold", 4)
                pkg_weight = threshold + 0.1
            pkg_weight_grams = int(pkg_weight * 1000)
            
            shipments.append({
                "tracking_id": piece_tracking_id,
                "shipment_items": [
                    {
                        "product_id": package.get("sku") or f"{order_id}-{idx+1}",
                        "product_title": (package.get("description", f"Item {idx+1}") or f"Item {idx+1}")[:100],
                        "category": package.get("category", "GENERAL"),
                        "handling_attributes": [
                            {"name": "isDangerous", "value": "false"},
                            {"name": "isFragile", "value": "false"}
                        ]
                    }
                ],
                "shipment_dimensions": {
                    "length": {"value": str(int(pkg_length))},
                    "height": {"value": str(int(pkg_height))},
                    "weight": {"value": str(pkg_weight_grams)},
                    "breadth": {"value": str(int(pkg_width))}
                }
            })
        
        return {
            "services": [
                {
                    "service_code": getattr(self.settings, "ekart_default_service", "REGULAR") or "REGULAR",
                    "service_details": [
                        {
                            "service_leg": "FORWARD",
                            "service_data": {
                                "vendor_name": "Ekart",
                                "amount_to_collect": str(shipment_data["order"].get("cod_amount", 0)) if is_cod else "0",
                                "delivery_type": "LARGE",
                                "offering_tier": getattr(self.settings, "ekart_offering_tier_large", "P4") or "P4",
                                "source": {
                                    "address": {
                                        "first_name": self.settings.ekart_sender_name,
                                        "address_line1": self.settings.ekart_sender_address,
                                        "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                        "pincode": str(self.settings.ekart_sender_pincode),
                                        "city": self.settings.ekart_sender_city,
                                        "state": self.settings.ekart_sender_state,
                                        "primary_contact_number": self.settings.ekart_sender_phone,
                                        "landmark": getattr(self.settings, "ekart_sender_landmark", "") or "",
                                        "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                    }
                                },
                                "destination": {
                                    "address": {
                                        "first_name": customer.get("name", ""),
                                        "address_line1": customer.get("address", ""),
                                        "address_line2": customer.get("address_line2", "") or "",
                                        "pincode": str(customer.get("pincode", "")),
                                        "city": customer.get("city", ""),
                                        "state": customer.get("state", ""),
                                        "primary_contact_number": customer.get("phone", ""),
                                        "landmark": customer.get("landmark", "") or "",
                                        "email_id": customer.get("email", "") or "",
                                        "alternate_contact_number": customer.get("alternate_phone", "") or ""
                                    }
                                },
                                "return_location": {
                                    "address": {
                                        "first_name": f"{self.settings.ekart_sender_name} RTO",
                                        "address_line1": self.settings.ekart_sender_address,
                                        "address_line2": getattr(self.settings, "ekart_sender_address2", "") or "",
                                        "pincode": str(self.settings.ekart_sender_pincode),
                                        "city": self.settings.ekart_sender_city,
                                        "state": self.settings.ekart_sender_state,
                                        "primary_contact_number": self.settings.ekart_sender_phone,
                                        "email_id": getattr(self.settings, "ekart_sender_email", "") or ""
                                    }
                                }
                            },
                            "global_shipment": {
                                "client_reference_id": "",
                                "tracking_id": "",
                                "shipment_value": str(int(total_sale_value)),
                                "cost": {
                                    "total_tax_value": str(total_tax_value),
                                    "total_sale_value": str(int(total_sale_value)),
                                    "tax_breakup": {
                                        "cgst": "0",
                                        "sgst": "0",
                                        "igst": str(total_tax_value)
                                    }
                                },
                                "attributes": [
                                    {"name": "order_id", "value": order_id},
                                    {"name": "invoice_id", "value": invoice_id},
                                    {"name": "eway_bill_number", "value": shipment_data.get("eway_bill_number", "")}
                                ],
                                "hsn": getattr(self.settings, "ekart_hsn", "") or "",
                                "ern": shipment_data.get("ern", ""),
                                "total_weight": str(total_weight_grams),
                                "seller_details": {
                                    "seller_reg_name": self.settings.ekart_seller_name or self.settings.ekart_sender_name,
                                    "gstin_id": getattr(self.settings, "ekart_gstin", "") or ""
                                }
                            },
                            "shipments": shipments
                        }
                    ]
                }
            ]
        }

   
    # ======================================================
    # PARSE RESPONSES
    # ======================================================

    def _parse_non_large_response(self, response, tracking_id):
        raw = response.get("response", {})
        response_data = raw[0] if isinstance(raw, list) and raw else raw
        status = response_data.get("status")

        if status != "REQUEST_RECEIVED":
            messages = response_data.get("message", [])
            error_msg = ", ".join(messages) if isinstance(messages, list) else str(messages)
            frappe.log_error(
                "Ekart Non-Large Failed",
                f"Status: {status}\nMsg: {error_msg}\nFull: {json.dumps(response, indent=2)}"
            )
            return {"success": False, "error": error_msg, "raw_response": response}

        return {
            "success": True,
            "carrier": "Ekart",
            "tracking_number": tracking_id,
            "awb_number": response_data.get("awbNumber"),
            "shipment_id": response_data.get("shipmentId"),
            "label_url": response_data.get("labelUrl"),
            "payment_link": response_data.get("shipment_payment_link"),
            "raw_response": response,
        }

    def _parse_large_response_multi_piece(self, response, piece_tracking_ids, global_tracking_id):
        """Parse response for multi-piece large shipments"""
        frappe.log_error("Ekart Large Multi-Piece Response", json.dumps(response, indent=2))
        
        if isinstance(response, dict):
            response_list = response.get("response", [])
            if isinstance(response_list, list) and response_list:
                first = response_list[0]
                if first.get("status") == "REQUEST_REJECTED":
                    messages = first.get("message", [])
                    error_msg = ", ".join(messages) if isinstance(messages, list) else str(messages)
                    return {"success": False, "error": error_msg, "raw_response": response}
        
        return {
            "success": True,
            "carrier": "Ekart",
            "tracking_number": global_tracking_id,
            "piece_tracking_ids": piece_tracking_ids,
            "awb_number": response.get("awbNumber"),
            "shipment_id": response.get("shipmentId"),
            "label_url": response.get("labelUrl"),
            "raw_response": response,
        }

    def _parse_large_response_single_piece_simple(self, response, tracking_id, piece_tracking_id):
        """Parse response for single-piece large shipments (non-MPS)"""
        frappe.log_error("Ekart Large Single-Piece Response", json.dumps(response, indent=2))
        
        if isinstance(response, dict):
            response_list = response.get("response", [])
            if isinstance(response_list, list) and response_list:
                first = response_list[0]
                if first.get("status") == "REQUEST_REJECTED":
                    messages = first.get("message", [])
                    error_msg = ", ".join(messages) if isinstance(messages, list) else str(messages)
                    return {"success": False, "error": error_msg, "raw_response": response}
        
        return {
            "success": True,
            "carrier": "Ekart",
            "tracking_number": tracking_id,
            "piece_tracking_id": piece_tracking_id,
            "awb_number": response.get("awbNumber"),
            "shipment_id": response.get("shipmentId"),
            "label_url": response.get("labelUrl"),
            "raw_response": response,
        }

    # ======================================================
    # TRACK SHIPMENT (unchanged)
    # ======================================================

    def track_shipment(self, tracking_number):
        """Track shipment with Ekart"""
        is_large = tracking_number.startswith("IEL")
        urls = self._get_base_urls()

        if is_large:
            url = urls["track_large"]
            payload = {"tracking_ids": [tracking_number]}
        else:
            url = urls["track_shipment"]
            payload = {"tracking_ids": tracking_number}

        try:
            response = self._request("POST", url, payload, is_large)
            
            tracking_history = []
            current_status = "Unknown"
            awb_number = None
            
            if response and isinstance(response, dict):
                tracking_data = response
                
                if "response" in response and isinstance(response["response"], list):
                    tracking_data = response["response"][0] if response["response"] else {}
                
                for tracking_id, data in tracking_data.items():
                    if tracking_id == tracking_number or tracking_id.startswith('IES') or tracking_id.startswith('IEL'):
                        awb_number = data.get("awb_number") or data.get("awbNumber")
                        history = data.get("history", [])
                        
                        for event in history:
                            event_date = event.get("event_date", "")
                            formatted_date = ""
                            if event_date:
                                try:
                                    from frappe.utils import get_datetime
                                    dt = get_datetime(event_date)
                                    formatted_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                                except:
                                    formatted_date = event_date
                            
                            raw_status = event.get("status", "")
                            status_mapping = {
                                "shipment_created": "Created",
                                "pickup_scheduled": "Pickup Scheduled",
                                "pickup_done": "Picked Up",
                                "in_transit": "In Transit",
                                "out_for_delivery": "Out for Delivery",
                                "delivered": "Delivered",
                                "rto_initiated": "RTO",
                                "cancelled": "Cancelled"
                            }
                            mapped_status = status_mapping.get(raw_status, raw_status.replace("_", " ").title())
                            location = event.get("city") or "N/A"
                            description = event.get("public_description") or event.get("description") or raw_status
                            if description and "null" in description.lower():
                                description = raw_status.replace("_", " ").title()
                            
                            tracking_history.append({
                                "date": formatted_date,
                                "status": mapped_status,
                                "location": location,
                                "description": description
                            })
                        
                        if history:
                            latest = history[-1]
                            current_status = status_mapping.get(latest.get("status", ""), "Unknown")
                        break
            
            tracking_history.sort(key=lambda x: x.get("date", ""))
            
            return {
                "success": True,
                "tracking_number": tracking_number,
                "awb_number": awb_number,
                "tracking_history": tracking_history,
                "current_status": current_status,
                "carrier_status": current_status,
                "raw_response": response
            }
            
        except Exception as e:
            frappe.log_error(
                title="Ekart Tracking Error",
                message=f"Tracking: {tracking_number}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
            )
            return {
                "success": False,
                "error": str(e),
                "tracking_number": tracking_number,
                "tracking_history": [],
                "current_status": "Exception",
                "carrier_status": "Exception"
            }
    
    # ======================================================
    # CANCEL SHIPMENT (unchanged)
    # ======================================================

    def cancel_shipment(self, tracking_number):
        """Cancel shipment with Ekart (RTO for large shipments)"""
        is_large = tracking_number.startswith("IEL")
        
        if not is_large:
            return {
                "success": False,
                "error_message": "Ekart non-large shipments (IES) cannot be cancelled via API. Please contact Ekart support or cancel through the Ekart portal.",
                "error_details": "API endpoint does not exist for IES cancellations",
                "suggestion": "Use 'Cancel & Recreate' option to clear tracking and create a new shipment instead."
            }
        
        urls = self._get_base_urls()
        
        try:
            url = urls["cancel_large"]
            payload = {
                "request_id": "",
                "request_details": [{"tracking_id": tracking_number, "reason": ""}]
            }
            
            response = self._request("PUT", url, payload, is_large=True)
            
            if isinstance(response, dict):
                response_data = response.get("response", [])
                if isinstance(response_data, list) and response_data:
                    first = response_data[0]
                    if first.get("status") == "REQUEST_RECEIVED":
                        return {"success": True, "message": "RTO initiated successfully", "raw_response": response}
                    else:
                        error_msg = first.get("message", ["Unknown error"])[0] if first.get("message") else "Cancellation failed"
                        return {"success": False, "error_message": error_msg, "error_details": json.dumps(response)}
            
            return {"success": True, "raw_response": response}
                
        except Exception as e:
            return {"success": False, "error_message": str(e), "error_details": str(e)}

    # ======================================================
    # OTHER METHODS (unchanged)
    # ======================================================

    def authenticate(self):
        try:
            token = self._get_token(is_large=False)
            return {"success": True, "token": token, "message": "Authentication successful"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def download_label(self, tracking_number=None, shipment_id=None, package_client_reference_id=None):
        tracking_id = tracking_number or shipment_id
        
        if not tracking_id:
            return {"success": False, "message": "No tracking number provided"}
        
        try:
            doc_name = frappe.db.get_value(
                "Handover To Logistics",
                {"logistics_tracking_number": tracking_id},
                "name"
            )
            
            if not doc_name:
                return {"success": False, "message": f"No shipment found with tracking number: {tracking_id}"}
            
            doc = frappe.get_doc("Handover To Logistics", doc_name)
            
            if doc.carrier_response:
                carrier_data = json.loads(doc.carrier_response)
                label_url = carrier_data.get("label_url")
                
                if label_url:
                    return {"success": True, "file_url": label_url, "message": "Label URL retrieved from stored response"}
                
                track_result = self.track_shipment(tracking_id)
                
                if track_result.get("success") and track_result.get("raw_response"):
                    raw_response = track_result.get("raw_response", {})
                    for track_id, data in raw_response.items():
                        if track_id == tracking_id or track_id.startswith('IES'):
                            label_url = data.get("label_url") or data.get("labelUrl") or data.get("shipping_label")
                            if label_url:
                                doc.db_set("carrier_response", json.dumps({**carrier_data, "label_url": label_url}, indent=2))
                                return {"success": True, "file_url": label_url, "message": "Label URL retrieved from tracking response"}
                
                return {
                    "success": False,
                    "message": "Label not yet available. Please wait and try again later.",
                    "status": carrier_data.get("raw_response", {}).get("response", [{}])[0].get("status", "Unknown"),
                    "suggestion": "Ekart may generate the label after the shipment is processed. Try tracking the shipment again in a few minutes."
                }
            else:
                return {"success": False, "message": "No carrier_response found for this shipment"}
                
        except Exception as e:
            frappe.log_error(title="Ekart Download Label Error", message=f"Tracking: {tracking_id}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}")
            return {"success": False, "error": str(e), "message": f"Failed to retrieve label: {str(e)}"}

    def get_service_types(self):
        return ["REGULAR", "ECONOMY", "NDD"]
    
    def _map_ekart_status(self, ekart_status):
        status_mapping = {
            "shipment_created": "Created",
            "pickup_scheduled": "Created",
            "pickup_done": "Picked Up",
            "in_transit": "In Transit",
            "out_for_delivery": "Out for Delivery",
            "delivered": "Delivered",
            "rto_initiated": "RTO",
            "rto_delivered": "RTO",
            "cancelled": "Cancelled",
            "exception": "Exception"
        }
        
        if ekart_status.lower() in status_mapping:
            return status_mapping[ekart_status.lower()]
        
        for key, value in status_mapping.items():
            if key in ekart_status.lower():
                return value
        
        return ekart_status.replace("_", " ").title()