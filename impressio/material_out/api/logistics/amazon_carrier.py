
import time
import json
import re

import frappe
import requests
from frappe.utils import now_datetime, add_to_date, getdate
from .base_carrier import BaseCarrier


class AmazonCarrier(BaseCarrier):

    def __init__(self, settings):
        super().__init__(settings)
        self.settings = settings
        self.base_url = self._get_base_url()
        self.timeout = 30

        self.MAX_ADDRESS_LINE_1 = 60
        self.MAX_ADDRESS_LINE_2 = 60
        self.MAX_ADDRESS_LINE_3 = 60
        self.MAX_WEIGHT_KG = 18.0
        self.MIN_WEIGHT_KG = 0.011
        self.MAX_DIMENSION_CM = 70
        self.MAX_PREPAID_AMOUNT = 50000
        self.MAX_COD_AMOUNT = 30000
        self.MAX_FUTURE_DAYS = 7

    # ======================================================
    # HELPERS
    # ======================================================

    def _clean_address(self, value):
        """Remove newlines and extra spaces from address fields"""
        if not value:
            return None
        return " ".join(str(value).replace("\n", " ").replace("\r", " ").split()).strip() or None

    def _format_phone(self, phone):
        """Add +91 prefix to Indian phone numbers"""
        phone = (phone or "").strip()
        if not phone:
            return None
        if not phone.startswith("+"):
            phone = "+91" + phone.lstrip("0")
        return phone
    
    
    def _build_ship_to(self, customer):
        """Build shipTo address block — auto splits long addresses"""
        full_address = self._clean_address(customer.get("address")) or ""

        # Split address into 3 lines of max 60 chars each
        line1, line2, line3 = "", "", ""

        if len(full_address) <= 60:
            line1 = full_address
        elif len(full_address) <= 120:
            split = full_address[:60].rfind(",")
            if split > 20:
                line1 = full_address[:split].strip()
                line2 = full_address[split+1:].strip()[:60]
            else:
                line1 = full_address[:60].strip()
                line2 = full_address[60:120].strip()
        else:
            split1 = full_address[:60].rfind(",")
            if split1 > 20:
                line1 = full_address[:split1].strip()
                remaining = full_address[split1+1:].strip()
            else:
                line1 = full_address[:60].strip()
                remaining = full_address[60:].strip()

            split2 = remaining[:60].rfind(",")
            if split2 > 20:
                line2 = remaining[:split2].strip()
                line3 = remaining[split2+1:].strip()[:60]
            else:
                line2 = remaining[:60].strip()
                line3 = remaining[60:120].strip()

        ship_to = {
            "name": (customer.get("name") or "Recipient").strip(),
            "addressLine1": line1,
            "city": (customer.get("city") or "").strip(),
            "stateOrRegion": (customer.get("state") or "").strip(),
            "postalCode": str(customer.get("pincode", "")).strip(),
            "countryCode": "IN",
        }

        if line2:
            ship_to["addressLine2"] = line2
        if line3:
            ship_to["addressLine3"] = line3

        for val, key in [
            (customer.get("company_name"), "companyName"),
            (customer.get("email"), "email"),
        ]:
            cleaned = self._clean_address(val)
            if cleaned:
                ship_to[key] = cleaned

        phone = self._format_phone(customer.get("phone"))
        if phone:
            ship_to["phoneNumber"] = phone

        return ship_to

   
    def _build_ship_from(self):
        """Build shipFrom address block"""
        ship_from = {
            "name": self.settings.amazon_sender_name,
            "addressLine1": self._clean_address(self.settings.warehouse_address) or "",
            "city": self.settings.amazon_sender_city,
            "stateOrRegion": self.settings.amazon_sender_state,
            "postalCode": str(self.settings.warehouse_pincode).strip(),
            "countryCode": "IN",
            "phoneNumber": self._format_phone(self.settings.amazon_sender_phone),
        }
        for val, key in [
            (self.settings.get("warehouse_address_line2"), "addressLine2"),
            (self.settings.get("warehouse_address_line3"), "addressLine3"),
            (self.settings.get("company_name"), "companyName"),
            (self.settings.get("amazon_sender_email"), "email"),
        ]:
            cleaned = self._clean_address(val)
            if cleaned:
                ship_from[key] = cleaned

        return ship_from

    # ======================================================
    # BASE URL
    # ======================================================

    def _get_base_url(self):
        if getattr(self.settings, "amazon_sandbox", False):
            return "https://sandbox.sellingpartnerapi-eu.amazon.com"
        return "https://sellingpartnerapi-eu.amazon.com"

    # ======================================================
    # TOKEN MANAGEMENT
    # ======================================================

    def _get_token(self):
        token = frappe.cache().get_value("amazon_access_token")
        expiry = frappe.cache().get_value("amazon_access_token_expiry")
        if token and expiry and now_datetime() < expiry:
            return token
        return self._refresh_token()

    def _refresh_token(self):
        if getattr(self.settings, "use_mock_api", False):
            return "mock_amazon_access_token"

        url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.settings.get_password("amazon_refresh_token"),
            "client_id": self.settings.amazon_client_id,
            "client_secret": self.settings.get_password("amazon_client_secret"),
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        expiry_time = add_to_date(now_datetime(), seconds=expires_in - 60)
        frappe.cache().set_value("amazon_access_token", access_token)
        frappe.cache().set_value("amazon_access_token_expiry", expiry_time)
        return access_token

    # ======================================================
    # GENERIC REQUEST
    # ======================================================

    def _request(self, method, endpoint, payload=None):
        access_token = self._get_token()
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Expect": "",
            "x-amz-access-token": access_token,
            "x-amzn-shipping-business-id": "AmazonShipping_IN",
        }
        response = requests.request(method=method, url=url, headers=headers, json=payload, timeout=self.timeout)
        if response.status_code == 401:
            frappe.cache().delete_value("amazon_access_token")
            access_token = self._refresh_token()
            headers["x-amz-access-token"] = access_token
            response = requests.request(method=method, url=url, headers=headers, json=payload, timeout=self.timeout)
        return response

    # ======================================================
    # VALIDATION METHODS
    # ======================================================

    def _validate_address_field(self, field_name, value, max_length, is_mandatory=False):
        if is_mandatory and not value:
            return {"code": "MissingRequiredField", "message": f"{field_name} is a required field"}
        if value and len(value) > max_length:
            return {"code": "InvalidAddressField", "message": f"{field_name} exceeds maximum length of {max_length} characters"}
        return None

    def _validate_address(self, address, address_type="shipTo"):
        error = self._validate_address_field("addressLine1", address.get("addressLine1"), self.MAX_ADDRESS_LINE_1, is_mandatory=True)
        if error:
            return error
        error = self._validate_address_field("addressLine2", address.get("addressLine2"), self.MAX_ADDRESS_LINE_2)
        if error:
            return error
        error = self._validate_address_field("addressLine3", address.get("addressLine3"), self.MAX_ADDRESS_LINE_3)
        if error:
            return error
        if not address.get("name"):
            return {"code": "MissingRequiredField", "message": "name is a required field"}
        if address.get("city") and len(address.get("city", "")) > 50:
            return {"code": "InvalidCity", "message": "City name exceeds maximum length"}
        if address.get("stateOrRegion") and len(address.get("stateOrRegion", "")) > 50:
            return {"code": "InvalidState", "message": "State name exceeds maximum length"}
        postal_code = address.get("postalCode", "")
        if postal_code:
            postal_code = str(postal_code).strip()
            if not re.match(r'^\d{6}$', postal_code):
                return {"code": "InvalidPostalCode", "message": "Invalid PIN Code - must be 6 digits"}
        else:
            return {"code": "MissingRequiredField", "message": "postalCode is a required field"}
        if address.get("countryCode") != "IN":
            return {"code": "UnsupportedCountry", "message": f"Country code {address.get('countryCode')} is not supported"}
        return None

    def _validate_dimensions(self, dimensions):
        length = float(dimensions.get("length", 0))
        width = float(dimensions.get("width", 0))
        height = float(dimensions.get("height", 0))
        if length <= 0 or width <= 0 or height <= 0:
            return {"code": "InvalidPackageDimensions", "message": "Package dimensions must be positive values"}
        if length > self.MAX_DIMENSION_CM or width > self.MAX_DIMENSION_CM or height > self.MAX_DIMENSION_CM:
            return {"code": "DimensionsExceedLimit", "message": f"Dimensions exceed allowed maximum of {self.MAX_DIMENSION_CM} cm"}
        return None

    def _validate_weight(self, weight_value, weight_unit="GRAM"):
        weight_kg = float(weight_value)
        if weight_unit == "GRAM":
            weight_kg = weight_value / 1000
        elif weight_unit == "POUND":
            weight_kg = weight_value * 0.453592
        elif weight_unit == "OUNCE":
            weight_kg = weight_value * 0.0283495
        if weight_kg <= 0:
            return {"code": "InvalidPackageWeight", "message": "Package weight must be greater than 0"}
        if weight_kg < self.MIN_WEIGHT_KG:
            return {"code": "InvalidPackageWeight", "message": f"Package weight must be at least {self.MIN_WEIGHT_KG} kg"}
        if weight_kg > self.MAX_WEIGHT_KG:
            return {"code": "ExceededWeightLimit", "message": f"Package weight exceeds maximum limit of {self.MAX_WEIGHT_KG} kg"}
        return None

    def _validate_amounts(self, payment_type, declared_value, cod_amount=0):
        if payment_type == "COD":
            if cod_amount <= 0:
                return {"code": "InvalidCodAmount", "message": "COD amount must be a positive value"}
            if cod_amount > self.MAX_COD_AMOUNT:
                return {"code": "AmountExceedsLimit", "message": f"Amount exceeds COD limit of INR {self.MAX_COD_AMOUNT}"}
        else:
            if declared_value > self.MAX_PREPAID_AMOUNT:
                return {"code": "AmountExceedsLimit", "message": f"Amount exceeds prepaid limit of INR {self.MAX_PREPAID_AMOUNT}"}
        return None

    def _validate_ship_date(self, ship_date):
        if not ship_date:
            return None
        try:
            ship_datetime = getdate(ship_date.split('T')[0])
            today = getdate(now_datetime().date())
            max_future_date = add_to_date(today, days=self.MAX_FUTURE_DAYS)
            if ship_datetime < today:
                return {"code": "InvalidShipDate", "message": "Ship date cannot be in the past"}
            if ship_datetime > max_future_date:
                return {"code": "InvalidShipDate", "message": f"Ship date cannot be more than {self.MAX_FUTURE_DAYS} days in future"}
        except:
            return {"code": "InvalidDateFormat", "message": "Ship date must be in ISO 8601 format (YYYY-MM-DDThh:mm:ssZ)"}
        return None

    def _validate_gst_number(self, gst_number):
        if not gst_number:
            return None
        gst_pattern = r'^\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d[Z]{1}[A-Z\d]{1}$'
        if len(gst_number) != 15:
            return {"code": "InvalidGSTNumber", "message": "GST registration number must be exactly 15 characters"}
        if not re.match(gst_pattern, gst_number):
            return {"code": "InvalidGSTNumber", "message": "Invalid GST registration number format"}
        return None

    def _validate_hazmat(self, is_hazmat):
        if is_hazmat:
            return {"code": "HazardousItem", "message": "Hazardous items are not allowed"}
        return None

     # REPLACE WITH:
    def _validate_shipment_data(self, shipment_data):
        # Use _build_ship_to() to get the already-split address
        # so validation runs on split lines not raw long address
        ship_to = self._build_ship_to(shipment_data["customer"])
        error = self._validate_address(ship_to, "shipTo")
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        
        error = self._validate_address(ship_to, "shipTo")
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        if not self.settings.amazon_sender_name:
            frappe.throw(json.dumps({"code": "MissingRequiredField", "message": "Sender name is required"}))
        if not self.settings.warehouse_address:
            frappe.throw(json.dumps({"code": "MissingRequiredField", "message": "Sender address is required"}))
        error = self._validate_dimensions(shipment_data["package"]["dimensions"])
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        error = self._validate_weight(shipment_data["package"]["weight"], "KILOGRAM")
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        error = self._validate_amounts(
            shipment_data["order"]["payment_type"],
            float(shipment_data["package"].get("value", 0)),
            float(shipment_data["order"].get("cod_amount", 0))
        )
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        gst_number = (self.settings.amazon_gst_number or "").strip()
        error = self._validate_gst_number(gst_number)
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")
        error = self._validate_hazmat(shipment_data["package"].get("is_hazmat", False))
        if error:
            frappe.throw(json.dumps(error), title="Amazon Validation Error")

    # ======================================================
    # GET RATES
    # ======================================================

    def get_rates(self, shipment_data):
        if getattr(self.settings, "use_mock_api", False):
            return self._get_mock_rates(shipment_data)

        self._validate_shipment_data(shipment_data)

        package_value = float(shipment_data["package"].get("value") or 1)
        ship_to = self._build_ship_to(shipment_data["customer"])
        ship_from = self._build_ship_from()

        package_weight_grams = float(int(shipment_data["package"]["weight"] * 1000))
        package_description = shipment_data["package"].get("description") or "General Goods"
        item_identifier = str(shipment_data.get("external_id", "ITEM-1"))

        payload = {
            "shipTo": ship_to,
            "shipFrom": ship_from,
            "returnTo": ship_from,
            "shipDate": now_datetime().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "packages": [
                {
                    "dimensions": {
                        "length": float(shipment_data["package"]["dimensions"]["length"]),
                        "width": float(shipment_data["package"]["dimensions"]["width"]),
                        "height": float(shipment_data["package"]["dimensions"]["height"]),
                        "unit": "CENTIMETER",
                    },
                    "weight": {"unit": "GRAM", "value": package_weight_grams},
                    "insuredValue": {"unit": "INR", "value": package_value},
                    "isHazmat": False,
                    "sellerDisplayName": self.settings.get("company_name") or "Seller",
                    "packageClientReferenceId": str(shipment_data.get("order_id_for_label") or shipment_data.get("external_id", "PKG-1")),
                    "items": [
                        {
                            "itemValue": {"unit": "INR", "value": package_value},
                            "description": package_description,
                            "itemIdentifier": str(shipment_data.get("order_id_for_label") or shipment_data.get("external_id", "PKG-1")),
                            "quantity": 1,
                            "weight": {"unit": "GRAM", "value": package_weight_grams},
                            "isHazmat": False,
                            "productType": shipment_data["package"].get("product_type", "General Goods"),
                        }
                    ],
                }
            ],
            "channelDetails": {"channelType": "EXTERNAL"},
        }

        gst_number = (self.settings.amazon_gst_number or "").strip()
        if gst_number:
            payload["taxDetails"] = [{"taxType": "GST", "taxRegistrationNumber": gst_number}]

        if shipment_data["order"]["payment_type"] == "COD":
            payload["valueAddedServices"] = {
                "collectOnDelivery": {
                    "amount": {"unit": "INR", "value": float(shipment_data["order"]["cod_amount"])}
                }
            }

        frappe.log_error(
            title="Amazon getRates Request",
            message=f"Endpoint: /shipping/v2/shipments/rates\nPayload:\n{json.dumps(payload, indent=2)}",
        )

        max_attempts = 3
        last_response = None

        for attempt in range(1, max_attempts + 1):
            response = self._request("POST", "/shipping/v2/shipments/rates", payload)
            last_response = response

            if response.status_code == 200:
                break

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", 60)
                frappe.throw(json.dumps({"code": "RateLimitExceeded", "message": f"API rate limit exceeded. Please retry after {retry_after} seconds"}))

            try:
                err_body = response.json()
            except Exception:
                err_body = {}

            errors = err_body.get("errors", [])
            is_transient = any(e.get("code") == "InternalFailure" for e in errors)

            frappe.log_error(
                title=f"Amazon getRates Attempt {attempt} Failed",
                message=f"Status: {response.status_code}\nResponse: {response.text}\nPayload sent:\n{json.dumps(payload, indent=2)}",
            )

            if is_transient and attempt < max_attempts:
                time.sleep(2**attempt)
                continue

            if errors:
                error = errors[0]
                frappe.throw(json.dumps({"code": error.get("code", "UnknownError"), "message": error.get("message", "Unknown error occurred")}))

            raise Exception(f"Amazon Shipping getRates failed (HTTP {response.status_code}): {response.text}")

        data = last_response.json()
        payload_data = data.get("payload", {})
        rates = payload_data.get("rates", [])
        request_token = payload_data.get("requestToken")

        if not rates:
            raise Exception(f"Amazon Shipping returned no service options. Response: {data}")

        service = sorted(rates, key=lambda x: x["totalCharge"]["value"])[0]
        raw_service_id = service.get("serviceId")
        if isinstance(raw_service_id, list):
            raw_service_id = raw_service_id[0]

        if raw_service_id != "SWA-IN-OA":
            frappe.log_error(title="Amazon Unexpected Service ID", message=f"Expected SWA-IN-OA, got {raw_service_id}")

        return {
            "service_id": raw_service_id,
            "rate": service["totalCharge"]["value"],
            "request_token": request_token,
        }

    # ======================================================
    # CREATE SHIPMENT
    # ======================================================

    def create_shipment(self, shipment_data):
        if getattr(self.settings, "use_mock_api", False):
            return self._create_mock_shipment(shipment_data)

        self._validate_shipment_data(shipment_data)

        rate_data = self.get_rates(shipment_data)
        service_id = rate_data.get("service_id")
        request_token = rate_data.get("request_token")

        package_value = float(shipment_data["package"].get("value") or 1)
        ship_to = self._build_ship_to(shipment_data["customer"])
        sender_address = self._build_ship_from()
        weight_grams = float(int(shipment_data["package"]["weight"] * 1000))

        payload = {
            "requestToken": request_token,
            "shipTo": ship_to,
            "shipFrom": sender_address,
            "returnTo": sender_address,
            "shipDate": now_datetime().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "packages": [
                {
                    "dimensions": {
                        "length": float(shipment_data["package"]["dimensions"]["length"]),
                        "width": float(shipment_data["package"]["dimensions"]["width"]),
                        "height": float(shipment_data["package"]["dimensions"]["height"]),
                        "unit": "CENTIMETER",
                    },
                    "weight": {"unit": "GRAM", "value": weight_grams},
                    "insuredValue": {"unit": "INR", "value": package_value},
                    "isHazmat": False,
                    "sellerDisplayName": self.settings.get("company_name") or "Seller",
                    "packageClientReferenceId": str(shipment_data.get("order_id_for_label") or shipment_data["external_id"]),
                    "items": [
                        {
                            "itemValue": {"unit": "INR", "value": package_value},
                            "description": shipment_data["package"].get("description") or "Goods",
                            "itemIdentifier": str(shipment_data.get("order_id_for_label") or shipment_data["external_id"]),
                            "quantity": 1,
                            "weight": {"unit": "GRAM", "value": weight_grams},
                            "isHazmat": False,
                            "productType": shipment_data["package"].get("product_type", "General Goods"),
                        }
                    ],
                }
            ],
            "channelDetails": {"channelType": "EXTERNAL"},
            "serviceSelection": {"serviceId": [service_id]},
            "labelSpecifications": {
                "format": "PDF",
                "dpi": 203,
                "needFileJoining": False,
                "pageLayout": "DEFAULT",
                "size": {"width": 4, "length": 6, "unit": "INCH"},
                "requestedDocumentTypes": ["LABEL"],
                "requestedLabelCustomization": {
                    "requestAttributes": ["PACKAGE_CLIENT_REFERENCE_ID"]
                },
            },
        }

        gst_number = (self.settings.amazon_gst_number or "").strip()
        if gst_number:
            payload["taxDetails"] = [{"taxType": "GST", "taxRegistrationNumber": gst_number}]

        is_cod = shipment_data["order"]["payment_type"] == "COD"
        if is_cod:
            payload["labelSpecifications"]["requestedLabelCustomization"]["requestAttributes"].append("COLLECT_ON_DELIVERY_AMOUNT")
            payload["valueAddedServiceDetails"] = [
                {
                    "id": "CollectOnDelivery",
                    "amount": {"unit": "INR", "value": float(shipment_data["order"]["cod_amount"])},
                }
            ]

        frappe.log_error(
            title="Amazon oneClickShipment Request",
            message=f"Endpoint: /shipping/v2/oneClickShipment\nservice_id used: {service_id}\nPayload:\n{json.dumps(payload, indent=2)}",
        )

        last_response = None
        for attempt in range(1, 4):
            last_response = self._request("POST", "/shipping/v2/oneClickShipment", payload)

            if last_response.status_code in [200, 201]:
                break

            if last_response.status_code == 429:
                retry_after = last_response.headers.get("Retry-After", 60)
                frappe.throw(json.dumps({"code": "RateLimitExceeded", "message": f"API rate limit exceeded. Please retry after {retry_after} seconds"}))

            if last_response.status_code < 500:
                try:
                    error_data = last_response.json()
                    errors = error_data.get("errors", [])
                    if errors:
                        error = errors[0]
                        frappe.throw(json.dumps({"code": error.get("code", "UnknownError"), "message": error.get("message", "Unknown error occurred")}))
                except:
                    pass
                break

            if attempt < 3:
                time.sleep(2**attempt)

        if last_response.status_code not in [200, 201]:
            raise Exception(f"Amazon Shipping oneClickShipment failed (HTTP {last_response.status_code}): {last_response.text}")

        data = last_response.json()
        result_payload = data.get("payload", data)

        tracking_id = None
        package_doc_details = result_payload.get("packageDocumentDetails", [])
        if package_doc_details:
            tracking_id = package_doc_details[0].get("trackingId")

        return {
            "success": True,
            "carrier": "Amazon Shipping",
            "tracking_number": result_payload.get("shipmentId"),
            "amazon_tracking_id": tracking_id,
            "label_url": result_payload.get("packageDocumentDetails", [{}])[0].get("packageDocuments", [{}])[0].get("contents", ""),
            "raw_response": data,
        }

    # ======================================================
    # TRACK SHIPMENT
    # ======================================================

    # def track_shipment(self, tracking_number):
    #     tracking_id = tracking_number

    #     if tracking_number and str(tracking_number).startswith('amzn1.sid.'):
    #         try:
    #             doc_name = frappe.db.get_value("Handover To Logistics", {"logistics_tracking_number": tracking_number}, "name")
    #             if doc_name:
    #                 doc = frappe.get_doc("Handover To Logistics", doc_name)
    #                 if doc.carrier_response:
    #                     carrier_data = json.loads(doc.carrier_response)
    #                     if carrier_data.get("amazon_tracking_id"):
    #                         tracking_id = carrier_data["amazon_tracking_id"]
    #                     else:
    #                         raw_response = carrier_data.get("raw_response", {})
    #                         payload = raw_response.get("payload", {})
    #                         package_details = payload.get("packageDocumentDetails", [])
    #                         if package_details:
    #                             tracking_id = package_details[0].get("trackingId")
                                
    #         except Exception as e:
    #             frappe.log_error("Amazon Track - ID Lookup Failed", str(e))

    #     endpoint = f"/shipping/v2/tracking?carrierId=ATS&trackingId={tracking_id}"
    #     response = self._request("GET", endpoint)

    #     if response.status_code != 200:
    #         try:
    #             error_data = response.json()
    #             errors = error_data.get("errors", [])
    #             if errors:
    #                 error = errors[0]
    #                 return {
    #                     "success": False,
    #                     "tracking_number": tracking_number,
    #                     "tracking_id_used": tracking_id,
    #                     "error_code": error.get("code", "Unknown"),
    #                     "error_message": error.get("message", "Unknown error"),
    #                     "error_details": error.get("details", ""),
    #                     "amazon_response": error_data,
    #                     "current_status": "Exception",
    #                     "carrier_status": "Exception"
    #                 }
    #         except:
    #             pass
    #         return {
    #             "success": False,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "error": response.text,
    #             "status_code": response.status_code,
    #             "current_status": "Exception",
    #             "carrier_status": "Exception"
    #         }

    #     try:
    #         data = response.json()
    #         payload = data.get("payload", {})
    #         events = payload.get("eventHistory", [])
    #         tracking_history = []
    #         for event in events:
    #             tracking_history.append({
    #                 "date": event.get("eventTime", ""),
    #                 "status": event.get("eventCode", ""),
    #                 "location": event.get("location", {}).get("city", ""),
    #                 "description": event.get("eventCode", "")
    #             })
    #         current_status = payload.get("summary", {}).get("status", "Unknown")
    #         return {
    #             "success": True,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "current_status": current_status,
    #             "carrier_status": current_status,
    #             "tracking_history": tracking_history,
    #             "estimated_delivery": payload.get("promisedDeliveryDate"),
    #             "raw_response": data
    #         }
    #     except Exception as e:
    #         frappe.log_error(title="Amazon Track - Parse Error", message=f"Tracking: {tracking_number}\nError: {str(e)}\nResponse: {response.text}")
    #         return {
    #             "success": False,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "error": str(e),
    #             "raw_response": response.text,
    #             "current_status": "Exception",
    #             "carrier_status": "Exception"
    #         }
    
    # def track_shipment(self, tracking_number):
    #     """
    #     Track shipment with Amazon Shipping carrier
    #     Returns tracking history including pre-pickup events like ReadyForReceive
    #     """
    #     tracking_id = tracking_number

    #     # If tracking number is Amazon shipment ID (starts with amzn1.sid), get the actual tracking ID
    #     if tracking_number and str(tracking_number).startswith('amzn1.sid.'):
    #         try:
    #             doc_name = frappe.db.get_value(
    #                 "Handover To Logistics", 
    #                 {"logistics_tracking_number": tracking_number}, 
    #                 "name"
    #             )
    #             if doc_name:
    #                 doc = frappe.get_doc("Handover To Logistics", doc_name)
    #                 if doc.carrier_response:
    #                     carrier_data = json.loads(doc.carrier_response)
    #                     # Try to get tracking ID from different possible locations
    #                     if carrier_data.get("amazon_tracking_id"):
    #                         tracking_id = carrier_data["amazon_tracking_id"]
    #                     else:
    #                         raw_response = carrier_data.get("raw_response", {})
    #                         payload = raw_response.get("payload", {})
    #                         package_details = payload.get("packageDocumentDetails", [])
    #                         if package_details and len(package_details) > 0:
    #                             tracking_id = package_details[0].get("trackingId")
                                
    #         except Exception as e:
    #             frappe.log_error(
    #                 title="Amazon Track - ID Lookup Failed",
    #                 message=f"Tracking: {tracking_number}\nError: {str(e)}"
    #             )

    #     # Make API request to Amazon
    #     endpoint = f"/shipping/v2/tracking?carrierId=ATS&trackingId={tracking_id}"
        
    #     try:
    #         response = self._request("GET", endpoint)
    #     except Exception as e:
    #         frappe.log_error(
    #             title="Amazon Track - Request Failed",
    #             message=f"Tracking: {tracking_number}\nError: {str(e)}"
    #         )
    #         return {
    #             "success": False,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "error": str(e),
    #             "current_status": "Exception",
    #             "carrier_status": "Exception"
    #         }

    #     # Handle non-200 responses
    #     if response.status_code != 200:
    #         try:
    #             error_data = response.json()
    #             errors = error_data.get("errors", [])
    #             if errors:
    #                 error = errors[0]
    #                 return {
    #                     "success": False,
    #                     "tracking_number": tracking_number,
    #                     "tracking_id_used": tracking_id,
    #                     "error_code": error.get("code", "Unknown"),
    #                     "error_message": error.get("message", "Unknown error"),
    #                     "error_details": error.get("details", ""),
    #                     "amazon_response": error_data,
    #                     "current_status": "Exception",
    #                     "carrier_status": "Exception"
    #                 }
    #         except:
    #             pass
            
    #         return {
    #             "success": False,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "error": response.text,
    #             "status_code": response.status_code,
    #             "current_status": "Exception",
    #             "carrier_status": "Exception"
    #         }

    #     # Parse successful response
    #     try:
    #         data = response.json()
    #         payload = data.get("payload", {})
    #         events = payload.get("eventHistory", [])
            
    #         tracking_history = []
            
    #         # Process each event in the history
    #         for event in events:
    #             location = event.get("location", {})
                
    #             # Build location string from available data
    #             location_parts = []
    #             if location.get("city"):
    #                 location_parts.append(location.get("city"))
    #             if location.get("stateOrRegion"):
    #                 location_parts.append(location.get("stateOrRegion"))
    #             if location.get("postalCode"):
    #                 location_parts.append(location.get("postalCode"))
                
    #             location_str = ", ".join(location_parts) if location_parts else "N/A"
                
    #             # Format the event time for display
    #             event_time = event.get("eventTime", "")
    #             formatted_time = ""
    #             if event_time:
    #                 try:
    #                     from frappe.utils import get_datetime, format_datetime
    #                     dt = get_datetime(event_time)
    #                     # Format: 17-Mar-2026 22:33:14
    #                     formatted_time = format_datetime(dt, "dd-MMM-yyyy HH:mm:ss")
    #                 except:
    #                     formatted_time = event_time
                
    #             # Get event code and create description
    #             event_code = event.get("eventCode", "")
                
    #             # Create user-friendly description based on event code
    #             description_map = {
    #                 "ReadyForReceive": "Shipment created, ready for pickup",
    #                 "PickupDone": "Package picked up from sender",
    #                 "ArrivedAtCarrierFacility": "Arrived at carrier facility",
    #                 "Departed": "Departed from facility",
    #                 "OutForDelivery": "Out for delivery",
    #                 "Delivered": "Delivered successfully",
    #                 "DeliveredWithOTP": "Delivered with OTP verification",
    #                 "Exception": "Exception in delivery",
    #                 "Returned": "Returned to sender"
    #             }
                
    #             description = description_map.get(event_code, event_code)
                
    #             # Add to tracking history list
    #             tracking_history.append({
    #                 "date": formatted_time,
    #                 "status": event_code,
    #                 "location": location_str,
    #                 "description": description,
    #                 "raw_time": event_time  # Keep raw for sorting
    #             })
            
    #         # Sort events chronologically (oldest first for timeline view)
    #         tracking_history.sort(key=lambda x: x.get("raw_time", ""))
            
    #         # Remove raw_time from final output
    #         for event in tracking_history:
    #             if "raw_time" in event:
    #                 del event["raw_time"]
            
    #         # Get current status from summary
    #         summary = payload.get("summary", {})
    #         current_status = summary.get("status", "Unknown")
            
    #         # Get estimated delivery date
    #         estimated_delivery = payload.get("promisedDeliveryDate")
    #         if estimated_delivery:
    #             try:
    #                 from frappe.utils import get_datetime, format_date
    #                 est_dt = get_datetime(estimated_delivery)
    #                 estimated_delivery = format_date(est_dt, "dd MMM yyyy")
    #             except:
    #                 pass
            
    #         # Update the Handover To Logistics document with tracking history
    #         try:
    #             doc_name = frappe.db.get_value(
    #                 "Handover To Logistics", 
    #                 {"logistics_tracking_number": tracking_number}, 
    #                 "name"
    #             )
                
    #             if doc_name:
    #                 doc = frappe.get_doc("Handover To Logistics", doc_name)
                    
    #                 # Clear existing tracking history
    #                 doc.set("tracking_history", [])
                    
    #                 # Add all events to child table
    #                 for event in tracking_history:
    #                     row = doc.append("tracking_history", {
    #                         "event_time": event["date"],
    #                         "status": event["status"],
    #                         "location": event["location"],
    #                         "remarks": event["description"]
    #                     })
                    
    #                 # Update current status
    #                 doc.carrier_status = current_status
                    
    #                 # Save the document
    #                 doc.save(ignore_permissions=True)
    #                 frappe.db.commit()
                    
    #                 frappe.log_error(
    #                     title="Amazon Track - Document Updated",
    #                     message=f"Document {doc_name} updated with {len(tracking_history)} tracking events"
    #                 )
                    
    #         except Exception as e:
    #             frappe.log_error(
    #                 title="Amazon Track - Failed to Update Document",
    #                 message=f"Tracking: {tracking_number}\nError: {str(e)}"
    #             )
            
    #         # Prepare return data
    #         result = {
    #             "success": True,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "current_status": current_status,
    #             "carrier_status": current_status,
    #             "tracking_history": tracking_history,
    #             "estimated_delivery": estimated_delivery,
    #             "raw_response": data
    #         }
            
    #         # Log successful tracking
    #         frappe.log_error(
    #             title="Amazon Track - Success",
    #             message=f"Tracking: {tracking_number}\nStatus: {current_status}\nEvents: {len(tracking_history)}"
    #         )
            
    #         return result
            
    #     except Exception as e:
    #         frappe.log_error(
    #             title="Amazon Track - Parse Error",
    #             message=f"Tracking: {tracking_number}\nError: {str(e)}\nResponse: {response.text if response else 'No response'}"
    #         )
            
    #         return {
    #             "success": False,
    #             "tracking_number": tracking_number,
    #             "tracking_id_used": tracking_id,
    #             "error": str(e),
    #             "raw_response": response.text if response else None,
    #             "current_status": "Exception",
    #             "carrier_status": "Exception"
    #         }
    

    def track_shipment(self, tracking_number):
        """
        Track shipment with Amazon Shipping carrier
        """
        tracking_id = tracking_number

        # If tracking number is Amazon shipment ID, get the actual tracking ID
        if tracking_number and str(tracking_number).startswith('amzn1.sid.'):
            try:
                doc_name = frappe.db.get_value(
                    "Handover To Logistics", 
                    {"logistics_tracking_number": tracking_number}, 
                    "name"
                )
                if doc_name:
                    doc = frappe.get_doc("Handover To Logistics", doc_name)
                    if doc.carrier_response:
                        carrier_data = json.loads(doc.carrier_response)
                        if carrier_data.get("amazon_tracking_id"):
                            tracking_id = carrier_data["amazon_tracking_id"]
                        else:
                            raw_response = carrier_data.get("raw_response", {})
                            payload = raw_response.get("payload", {})
                            package_details = payload.get("packageDocumentDetails", [])
                            if package_details and len(package_details) > 0:
                                tracking_id = package_details[0].get("trackingId")
                                    
            except Exception as e:
                frappe.log_error(
                    title="Amazon Track - ID Lookup Failed",
                    message=f"Tracking: {tracking_number}\nError: {str(e)}"
                )

        # Make API request to Amazon
        endpoint = f"/shipping/v2/tracking?carrierId=ATS&trackingId={tracking_id}"
        
        try:
            response = self._request("GET", endpoint)
        except Exception as e:
            frappe.log_error(
                title="Amazon Track - Request Failed",
                message=f"Tracking: {tracking_number}\nError: {str(e)}"
            )
            return {
                "success": False,
                "tracking_number": tracking_number,
                "tracking_id_used": tracking_id,
                "error": str(e),
                "current_status": "Exception",
                "carrier_status": "Exception",
                "tracking_history": []
            }

        # Handle non-200 responses
        if response.status_code != 200:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error = errors[0]
                    return {
                        "success": False,
                        "tracking_number": tracking_number,
                        "tracking_id_used": tracking_id,
                        "error_code": error.get("code", "Unknown"),
                        "error_message": error.get("message", "Unknown error"),
                        "error_details": error.get("details", ""),
                        "amazon_response": error_data,
                        "current_status": "Exception",
                        "carrier_status": "Exception",
                        "tracking_history": []
                    }
            except:
                pass
            
            return {
                "success": False,
                "tracking_number": tracking_number,
                "tracking_id_used": tracking_id,
                "error": response.text,
                "status_code": response.status_code,
                "current_status": "Exception",
                "carrier_status": "Exception",
                "tracking_history": []
            }

        # Parse successful response
        try:
            data = response.json()
            payload = data.get("payload", {})
            events = payload.get("eventHistory", [])
            
            # Status mapping
            STATUS_MAPPING = {
                "ReadyForReceive": "Created",
                "Preflashed": "Created",
                "PickupScheduled": "Created",
                "PickupDone": "Picked Up",
                "PickedUp": "Picked Up",
                "ArrivedAtCarrierFacility": "In Transit",
                "Departed": "In Transit",
                "OutForDelivery": "Out for Delivery",
                "Delivered": "Delivered",
                "DeliveredWithOTP": "Delivered",
                "PickupCancelled": "Cancelled",
                "Cancelled": "Cancelled",
                "Exception": "Exception",
                "Returned": "RTO"
            }
            
            tracking_history = []
            
            # Process each event in the history
            for event in events:
                # Handle location - it could be None
                location = event.get("location")
                location_str = "N/A"
                
                # Only process if location is not None and is a dict
                if location and isinstance(location, dict):
                    location_parts = []
                    if location.get("city"):
                        location_parts.append(location.get("city"))
                    if location.get("stateOrRegion"):
                        location_parts.append(location.get("stateOrRegion"))
                    if location.get("postalCode"):
                        location_parts.append(location.get("postalCode"))
                    if location_parts:
                        location_str = ", ".join(location_parts)
                
                # Format the event time for MySQL (YYYY-MM-DD HH:MM:SS)
                event_time = event.get("eventTime", "")
                formatted_time = ""
                if event_time:
                    try:
                        from frappe.utils import get_datetime
                        dt = get_datetime(event_time)
                        formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        # Fallback: try to parse manually
                        formatted_time = event_time.replace('T', ' ').replace('Z', '').split('.')[0]
                
                # Get event code and map status
                event_code = event.get("eventCode", "")
                mapped_status = STATUS_MAPPING.get(event_code, event_code)
                
                # Create description
                description_map = {
                    "ReadyForReceive": "Shipment created, ready for pickup",
                    "Preflashed": "Shipment created",
                    "PickupScheduled": "Pickup scheduled",
                    "PickupDone": "Package picked up from sender",
                    "PickedUp": "Package picked up",
                    "ArrivedAtCarrierFacility": "Arrived at carrier facility",
                    "Departed": "Departed from facility",
                    "OutForDelivery": "Out for delivery",
                    "Delivered": "Delivered successfully",
                    "DeliveredWithOTP": "Delivered with OTP verification",
                    "PickupCancelled": "Pickup cancelled",
                    "Exception": "Exception in delivery",
                    "Returned": "Returned to sender",
                    "Cancelled": "Shipment cancelled"
                }
                
                description = description_map.get(event_code, event_code)
                
                # Add to tracking history list
                tracking_history.append({
                    "date": formatted_time,
                    "status": mapped_status,
                    "location": location_str,
                    "description": description
                })
            
            # Sort events chronologically
            tracking_history.sort(key=lambda x: x.get("date", ""))
            
            # Get current status from summary
            summary = payload.get("summary", {})
            current_status = summary.get("status", "Unknown")
            mapped_current_status = STATUS_MAPPING.get(current_status, current_status)
            
            # Get estimated delivery date
            estimated_delivery = payload.get("promisedDeliveryDate")
            if estimated_delivery:
                try:
                    from frappe.utils import get_datetime, format_date
                    est_dt = get_datetime(estimated_delivery)
                    estimated_delivery = format_date(est_dt, "dd MMM yyyy")
                except:
                    pass
            
            # Prepare return data
            result = {
                "success": True,
                "tracking_number": tracking_number,
                "tracking_id_used": tracking_id,
                "current_status": mapped_current_status,
                "carrier_status": mapped_current_status,
                "tracking_history": tracking_history,
                "estimated_delivery": estimated_delivery,
                "raw_response": data
            }
            
            # Log for debugging
            frappe.log_error(
                title="Amazon Track - Success",
                message=f"Tracking: {tracking_number}\nStatus: {mapped_current_status}\nEvents: {len(tracking_history)}"
            )
            
            return result
            
        except Exception as e:
            frappe.log_error(
                title="Amazon Track - Parse Error",
                message=f"Tracking: {tracking_number}\nError: {str(e)}\nResponse: {response.text if response else 'No response'}\nTraceback: {frappe.get_traceback()}"
            )
            
            return {
                "success": False,
                "tracking_number": tracking_number,
                "tracking_id_used": tracking_id,
                "error": str(e),
                "raw_response": response.text if response else None,
                "current_status": "Exception",
                "carrier_status": "Exception",
                "tracking_history": []
            }
    # ======================================================
    # CANCEL SHIPMENT
    # ======================================================

    def cancel_shipment(self, shipment_id):
        if getattr(self.settings, "use_mock_api", False):
            return {"success": True, "message": "Mock cancellation successful"}
        endpoint = f"/shipping/v2/shipments/{shipment_id}/cancel"
        response = self._request("PUT", endpoint)
        if response.status_code != 200:
            raise Exception(response.text)
        return {"success": True}

    # ======================================================
    # AUTH TEST
    # ======================================================

    def authenticate(self):
        if getattr(self.settings, "use_mock_api", False):
            return {"token": "mock_amazon_access_token"}
        token = self._get_token()
        return {"token": token}

    def get_service_types(self):
        return ["Standard"]

    # ======================================================
    # DOWNLOAD LABEL
    # ======================================================

    def download_label(self, shipment_id, package_client_reference_id=None):
        if getattr(self.settings, "use_mock_api", False):
            return self._get_mock_label(shipment_id)

        if not package_client_reference_id:
            doc_name = frappe.db.get_value("Handover To Logistics", {"logistics_tracking_number": shipment_id}, "name")
            if doc_name:
                package_client_reference_id = doc_name
            else:
                frappe.log_error(title="Amazon Download Label - Missing packageClientReferenceId", message=f"shipment_id: {shipment_id}")
                raise Exception("packageClientReferenceId is required for label download.")

        endpoint = f"/shipping/v2/shipments/{shipment_id}/documents"
        url = f"{endpoint}?format=PDF&packageClientReferenceId={package_client_reference_id}"
        response = self._request("GET", url)

        if response.status_code != 200:
            frappe.log_error(title="Amazon Download Label Failed", message=f"Status: {response.status_code}\nResponse: {response.text}\nShipment ID: {shipment_id}\nPackageRef: {package_client_reference_id}")
            raise Exception(f"Failed to download label: {response.text}")

        data = response.json()

        try:
            payload = data.get("payload", {})
            package_doc_detail = payload.get("packageDocumentDetail", {})
            package_documents = package_doc_detail.get("packageDocuments", [])

            if not package_documents:
                package_doc_detail = payload.get("packageDocumentDetails", [])
                if package_doc_detail:
                    package_documents = package_doc_detail[0].get("packageDocuments", [])

            if not package_documents:
                raise Exception("No package documents found in response")

            document = package_documents[0]
            label_content = document.get("contents")

            if not label_content:
                raise Exception("No label content found in response")

            import base64
            label_content = re.sub(r'\s', '', label_content)
            pdf_content = base64.b64decode(label_content)

            doc_name = frappe.db.get_value("Handover To Logistics", {"logistics_tracking_number": shipment_id}, "name")
            if not doc_name:
                doc_name = package_client_reference_id

            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"Amazon_Label_{shipment_id}.pdf",
                "content": pdf_content,
                "is_private": 0,
                "attached_to_doctype": "Handover To Logistics",
                "attached_to_name": doc_name,
            }).insert(ignore_permissions=True)

            if doc_name:
                doc = frappe.get_doc("Handover To Logistics", doc_name)
                doc.db_set("label_url", file_doc.file_url)
                doc.db_set("carrier_status", "Label Generated")

            frappe.db.commit()

            return {
                "success": True,
                "file_url": file_doc.file_url,
                "file_name": file_doc.file_name,
                "tracking_id": package_doc_detail.get("trackingId", shipment_id),
                "shipment_id": payload.get("shipmentId", shipment_id)
            }

        except Exception as e:
            frappe.log_error(title="Amazon Download Label - Processing Error", message=f"Error: {str(e)}\nResponse: {json.dumps(data)[:1000]}...")
            raise Exception(f"Failed to process label: {str(e)}")

    # ======================================================
    # MOCK MODE HELPERS
    # ======================================================

    def _get_mock_rates(self, shipment_data):
        return {"service_id": "SWA-IN-OA", "rate": 55.0}

    def _create_mock_shipment(self, shipment_data):
        import random
        shipment_id = f"amzn1.sid.mock.{random.randint(100000, 999999)}"
        return {
            "success": True,
            "carrier": "Amazon Shipping",
            "tracking_number": shipment_id,
            "amazon_tracking_id": str(random.randint(100000000000, 999999999999)),
            "label_url": "",
            "raw_response": {"status": "success", "message": "Mock shipment created successfully", "shipmentId": shipment_id, "mock_mode": True},
        }

    def _get_mock_label(self, shipment_id):
        return self._generate_mock_label_file(shipment_id, {})

    def _generate_mock_label_file(self, shipment_id, shipment_data):
        try:
            from frappe.utils.pdf import get_pdf
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ text-align: center; background-color: #FF9900; color: #131921; padding: 15px; }}
        .tracking {{ text-align: center; margin: 20px 0; padding: 15px; border: 2px dashed #333; }}
        .tracking h2 {{ font-size: 22px; margin: 0; letter-spacing: 2px; }}
    </style>
</head>
<body>
    <div class="header"><h1>AMAZON SHIPPING (MOCK)</h1></div>
    <div class="tracking"><h2>{shipment_id}</h2></div>
    <div class="watermark">THIS IS A MOCK LABEL FOR TESTING PURPOSES ONLY</div>
</body>
</html>"""
            pdf_content = get_pdf(html_content)
            file_name = f"amazon_label_{shipment_id}.pdf"
            file_doc = frappe.get_doc({"doctype": "File", "file_name": file_name, "content": pdf_content, "is_private": 0})
            file_doc.save(ignore_permissions=True)
            return {"success": True, "file_url": file_doc.file_url, "file_name": file_name}
        except Exception as e:
            frappe.log_error(title="Amazon Mock Label Generation Failed", message=str(e))
            return {"success": False, "file_url": "", "error": str(e)}
