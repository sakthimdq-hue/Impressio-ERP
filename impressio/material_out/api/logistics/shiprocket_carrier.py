# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/shiprocket_carrier.py
"""
Shiprocket Carrier Implementation
"""

import frappe
import requests
import json
from frappe import _
from frappe.utils import now_datetime
from .base_carrier import BaseCarrier

class ShiprocketCarrier(BaseCarrier):
    """Shiprocket carrier implementation"""
    
    def __init__(self, settings):
        super().__init__(settings)
        self.carrier_name = "Shiprocket"
        self.settings = settings
        self.base_url = "https://apiv2.shiprocket.in/v1"
    
    def authenticate(self):
        """Authenticate with Shiprocket"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return {"token": "mock_shiprocket_token", "expires_in": None}
            
            if getattr(self.settings, 'shiprocket_token', None):
                return {"token": self.settings.shiprocket_token, "expires_in": None}
            
            if not all([
                getattr(self.settings, 'shiprocket_email', None),
                getattr(self.settings, 'shiprocket_password', None)
            ]):
                raise Exception("Shiprocket credentials not configured")
            
            url = f"{self.base_url}/external/auth/login"
            
            payload = {
                "email": self.settings.shiprocket_email,
                "password": self.settings.shiprocket_password
            }
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            token = data.get("token")
            
            if not token:
                raise Exception("No token received from Shiprocket")
            
            return {"token": token, "expires_in": None}
            
        except Exception as e:
            frappe.log_error(
                title="Shiprocket Authentication Failed",
                message=f"Error: {str(e)}"
            )
            raise Exception(f"Shiprocket authentication failed: {str(e)}")
    
    def get_service_types(self):
        """Get available Shiprocket couriers"""
        return [
            "Shiprocket Surface",
            "Shiprocket Air",
            "Delhivery Surface", 
            "Delhivery Air",
            "BlueDart",
            "DTDC",
            "XpressBees",
            "Ecom Express"
        ]
    
    def create_shipment(self, shipment_data):
        """Create shipment with Shiprocket

        Includes CBM and shipment category data for tracking purposes.
        """
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return self._create_mock_shipment(shipment_data)

            auth_data = self.authenticate()
            token = auth_data.get("token")

            # Log shipment category for debugging
            frappe.log_error(
                title="Shiprocket Shipment Category",
                message=f"External ID: {shipment_data.get('external_id')}\n"
                        f"Category: {shipment_data.get('shipment_category')}\n"
                        f"CBM: {shipment_data.get('package', {}).get('cbm', 0)}\n"
                        f"Max Dimension: {shipment_data.get('package', {}).get('max_dimension', 0)}"
            )

            url = f"{self.base_url}/external/orders/create/adhoc"

            payload = {
                "order_id": shipment_data["external_id"],
                "order_date": str(now_datetime().date()),
                "pickup_location": "Primary",
                "channel_id": getattr(self.settings, 'shiprocket_channel_id', ''),
                "billing_customer_name": shipment_data["customer"]["name"],
                "billing_last_name": "",
                "billing_address": shipment_data["customer"]["address"][:100],
                "billing_address_2": "",
                "billing_city": shipment_data["customer"].get("city", "City"),
                "billing_pincode": str(shipment_data["customer"]["pincode"]),
                "billing_state": shipment_data["customer"].get("state", "State"),
                "billing_country": "India",
                "billing_email": "customer@example.com",
                "billing_phone": shipment_data["customer"]["phone"],
                "shipping_is_billing": True,
                "order_items": [
                    {
                        "name": shipment_data["package"].get("description", "Product"),
                        "sku": "SKU001",
                        "units": 1,
                        "selling_price": shipment_data["package"].get("value", 0),
                        "discount": "",
                        "tax": "",
                        "hsn": 441122
                    }
                ],
                "payment_method": "Prepaid" if shipment_data["order"].get("payment_type") == "Prepaid" else "COD",
                "sub_total": shipment_data["package"].get("value", 0),
                "length": shipment_data["package"]["dimensions"].get("length", 10),
                "breadth": shipment_data["package"]["dimensions"].get("width", 10),
                "height": shipment_data["package"]["dimensions"].get("height", 10),
                "weight": shipment_data["package"]["weight"]
            }
            
            if shipment_data["order"].get("payment_type") == "COD":
                payload["cod_amount"] = shipment_data["order"].get("cod_amount", 0)
        
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            frappe.log_error(
                title="Shiprocket Order Creation",
                message=f"URL: {url}\nStatus: {response.status_code}\nResponse: {response.text}"
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                return self._parse_shiprocket_response(data)
            else:
                raise Exception(f"Order creation failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            frappe.log_error(
                title="Shiprocket Shipment Creation Failed",
                message=f"Error: {str(e)}\nData: {json.dumps(shipment_data, indent=2)}"
            )
            raise Exception(f"Failed to create Shiprocket shipment: {str(e)}")
    
    def _parse_shiprocket_response(self, data):
        """Parse Shiprocket response"""
        order_id = data.get("order_id")
        awb_code = data.get("awb_code")
        
        return {
            "success": True,
            "carrier": "Shiprocket",
            "tracking_number": awb_code or f"SR{order_id}",
            "order_id": order_id,
            "shipment_id": data.get("shipment_id"),
            "awb_number": awb_code,
            "label_url": data.get("label_url"),
            "manifest_url": data.get("manifest_url"),
            "pickup_scheduled": data.get("pickup_scheduled_date"),
            "raw_response": data
        }
    
    def _create_mock_shipment(self, shipment_data):
        """Create mock Shiprocket shipment with actual downloadable label"""
        import random

        order_id = random.randint(100000, 999999)
        awb_code = f"SR{random.randint(1000000000, 9999999999)}"

        frappe.logger().info(f"Using mock API for Shiprocket shipment creation - External ID: {shipment_data.get('external_id')}")

        # Generate actual label file
        label_result = self._generate_mock_label_file(awb_code, shipment_data)

        return {
            "success": True,
            "carrier": "Shiprocket",
            "tracking_number": awb_code,
            "order_id": order_id,
            "shipment_id": order_id,
            "awb_number": awb_code,
            "label_url": label_result.get("file_url", ""),
            "manifest_url": "",
            "courier_name": shipment_data.get("service_type", "Shiprocket Surface"),
            "raw_response": {
                "status": "success",
                "message": "Mock shipment created successfully",
                "awb_code": awb_code,
                "order_id": order_id,
                "mock_mode": True
            }
        }

    def _generate_mock_label_file(self, awb_code, shipment_data):
        """Generate a PDF label file for mock shipments"""
        try:
            from frappe.utils.pdf import get_pdf

            customer = shipment_data.get("customer", {})
            package = shipment_data.get("package", {})
            order = shipment_data.get("order", {})
            dimensions = package.get("dimensions", {})
            service_type = shipment_data.get("service_type", "Shiprocket Surface")

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ text-align: center; background-color: #7B2D8E; color: white; padding: 15px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header h2 {{ margin: 5px 0 0 0; font-size: 14px; font-weight: normal; }}
        .tracking {{ text-align: center; margin: 20px 0; padding: 15px; border: 2px dashed #333; }}
        .tracking h2 {{ font-size: 28px; margin: 0; letter-spacing: 2px; }}
        .tracking p {{ margin: 5px 0; color: #666; }}
        .section {{ margin: 15px 0; padding: 10px; border: 1px solid #ddd; }}
        .section-title {{ background-color: #f5f5f5; padding: 5px 10px; margin: -10px -10px 10px -10px; font-weight: bold; }}
        .row {{ display: flex; margin: 5px 0; }}
        .label {{ font-weight: bold; width: 120px; }}
        .value {{ flex: 1; }}
        .barcode {{ text-align: center; margin: 20px 0; padding: 20px; background: #f9f9f9; border: 1px solid #ddd; }}
        .barcode-placeholder {{ font-family: monospace; font-size: 24px; letter-spacing: 3px; }}
        .watermark {{ text-align: center; background-color: #ffeb3b; color: #333; padding: 10px; margin-top: 20px; font-weight: bold; }}
        .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 11px; }}
        .courier-badge {{ display: inline-block; padding: 5px 15px; background-color: #7B2D8E; color: white; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SHIPROCKET</h1>
        <h2>SHIPPING LABEL</h2>
    </div>

    <div class="tracking">
        <p>AWB NUMBER</p>
        <h2>{awb_code}</h2>
        <p><span class="courier-badge">{service_type}</span></p>
    </div>

    <div class="barcode">
        <div class="barcode-placeholder">||| {awb_code} |||</div>
        <p style="font-size: 10px; color: #999;">Barcode Placeholder</p>
    </div>

    <div class="section">
        <div class="section-title">RECIPIENT</div>
        <div class="row"><span class="label">Name:</span><span class="value">{customer.get('name', 'N/A')}</span></div>
        <div class="row"><span class="label">Phone:</span><span class="value">{customer.get('phone', 'N/A')}</span></div>
        <div class="row"><span class="label">Address:</span><span class="value">{customer.get('address', 'N/A')[:80]}</span></div>
        <div class="row"><span class="label">City:</span><span class="value">{customer.get('city', 'N/A')}</span></div>
        <div class="row"><span class="label">State:</span><span class="value">{customer.get('state', 'N/A')}</span></div>
        <div class="row"><span class="label">Pincode:</span><span class="value" style="font-weight: bold; font-size: 18px;">{customer.get('pincode', 'N/A')}</span></div>
    </div>

    <div class="section">
        <div class="section-title">PACKAGE DETAILS</div>
        <div class="row"><span class="label">Weight:</span><span class="value">{package.get('weight', 0)} kg</span></div>
        <div class="row"><span class="label">Dimensions:</span><span class="value">{dimensions.get('length', 0)} x {dimensions.get('width', 0)} x {dimensions.get('height', 0)} cm</span></div>
    </div>

    <div class="section">
        <div class="section-title">ORDER DETAILS</div>
        <div class="row"><span class="label">Order ID:</span><span class="value">{order.get('id', 'N/A')}</span></div>
        <div class="row"><span class="label">Payment:</span><span class="value">{order.get('payment_type', 'Prepaid')}</span></div>
        <div class="row"><span class="label">COD Amount:</span><span class="value">₹{order.get('cod_amount', 0)}</span></div>
    </div>

    <div class="watermark">
        ⚠️ THIS IS A MOCK LABEL FOR TESTING PURPOSES ONLY ⚠️
    </div>

    <div class="footer">
        Generated: {now_datetime().strftime('%Y-%m-%d %H:%M:%S')} | Shiprocket Mock API
    </div>
</body>
</html>
"""

            pdf_content = get_pdf(html_content)

            file_name = f"shiprocket_label_{awb_code}.pdf"
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file_name,
                "content": pdf_content,
                "is_private": 0
            })
            file_doc.save(ignore_permissions=True)

            return {
                "success": True,
                "file_url": file_doc.file_url,
                "file_name": file_name
            }

        except Exception as e:
            frappe.log_error(title="Shiprocket Mock Label Generation Failed", message=str(e))
            return {
                "success": False,
                "file_url": "",
                "error": str(e)
            }
    
    def track_shipment(self, tracking_number):
        """Track Shiprocket shipment"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return self._get_mock_tracking(tracking_number)
            
            auth_data = self.authenticate()
            token = auth_data.get("token")
            
            url = f"{self.base_url}/external/courier/track/awb/{tracking_number}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_tracking_response(data)
            else:
                raise Exception(f"Tracking failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            frappe.log_error(title="Shiprocket Tracking Failed", message=str(e))
            return {
                "success": False,
                "error": str(e),
                "carrier": "Shiprocket"
            }
    
    def _parse_tracking_response(self, data):
        """Parse tracking response"""
        tracking_data = data.get("tracking_data", {})
        shipment_status = tracking_data.get("shipment_status", "Unknown")
        
        status_mapping = {
            "NEW": "Created",
            "PICKUP GENERATED": "Pickup Generated",
            "MANIFEST GENERATED": "Manifest Generated",
            "PICKED UP": "Picked Up",
            "IN TRANSIT": "In Transit",
            "OUT FOR DELIVERY": "Out for Delivery",
            "DELIVERED": "Delivered",
            "RTO": "RTO",
            "CANCELLED": "Cancelled"
        }
        
        track_history = tracking_data.get("track_history", [])
        
        return {
            "success": True,
            "carrier": "Shiprocket",
            "tracking_number": tracking_data.get("awb_code"),
            "current_status": status_mapping.get(shipment_status, shipment_status),
            "status_code": shipment_status,
            "tracking_history": track_history,
            "estimated_delivery": tracking_data.get("etd"),
            "raw_response": data
        }
    
    def _get_mock_tracking(self, tracking_number):
        """Get mock tracking data"""
        import random
        
        statuses = ["NEW", "PICKUP GENERATED", "PICKED UP", "IN TRANSIT", "OUT FOR DELIVERY", "DELIVERED"]
        current_status = random.choice(statuses)
        
        status_mapping = {
            "NEW": "Created",
            "PICKUP GENERATED": "Pickup Generated",
            "PICKED UP": "Picked Up",
            "IN TRANSIT": "In Transit",
            "OUT FOR DELIVERY": "Out for Delivery",
            "DELIVERED": "Delivered"
        }
        
        return {
            "success": True,
            "carrier": "Shiprocket",
            "tracking_number": tracking_number,
            "current_status": status_mapping.get(current_status, current_status),
            "status_code": current_status,
            "estimated_delivery": str(now_datetime().date()),
            "tracking_history": [
                {
                    "Date": str(now_datetime()),
                    "Status": current_status,
                    "Activity": f"Mock {current_status} activity",
                    "Location": "Mock Location"
                }
            ]
        }
    
    def download_label(self, tracking_number):
        """Download Shiprocket label"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return self._get_mock_label(tracking_number)
            
            auth_data = self.authenticate()
            token = auth_data.get("token")
            
            # For mock, we'll just create a simple label
            # Real implementation would call Shiprocket's label API
            
            label_content = f"SHIPROCKET SHIPPING LABEL\nAWB: {tracking_number}\nDate: {now_datetime()}\nCarrier: Shiprocket"
            
            file_name = f"shiprocket_label_{tracking_number}.txt"
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": file_name,
                "content": label_content,
                "is_private": 0
            }).insert()
            
            return {
                "success": True,
                "file_url": file_doc.file_url,
                "file_name": file_name
            }
                
        except Exception as e:
            frappe.log_error(title="Shiprocket Label Download Failed", message=str(e))
            raise Exception(f"Failed to download Shiprocket label: {str(e)}")
    
    def _get_mock_label(self, tracking_number):
        """Generate mock label"""
        label_content = f"SHIPROCKET SHIPPING LABEL\nAWB: {tracking_number}\nDate: {now_datetime()}"
        
        file_name = f"shiprocket_label_{tracking_number}.txt"
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "content": label_content,
            "is_private": 0
        }).insert()
        
        return {
            "success": True,
            "file_url": file_doc.file_url,
            "file_name": file_name
        }
    
    def cancel_shipment(self, tracking_number):
        """Cancel Shiprocket shipment"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return {"success": True, "message": "Mock cancellation successful"}
            
            auth_data = self.authenticate()
            token = auth_data.get("token")
            
            # Get shipment ID first (you need to map tracking number to shipment ID)
            shipment_id = self._get_shipment_id_from_awb(tracking_number, token)
            
            url = f"{self.base_url}/external/orders/cancel/shipment/{shipment_id}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Shipment cancelled successfully",
                    "raw_response": response.json()
                }
            else:
                raise Exception(f"Cancellation failed: {response.status_code}")
                
        except Exception as e:
            frappe.log_error(title="Shiprocket Cancellation Failed", message=str(e))
            raise Exception(f"Cancellation failed: {str(e)}")
    
    def _get_shipment_id_from_awb(self, awb_number, token):
        """Get shipment ID from AWB number"""
        # In real implementation, you'd need to map AWB to shipment ID
        # For now, return a placeholder
        return 123456
    
    def validate_address(self, pincode):
        """Validate address serviceability"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return {
                    "serviceable": True,
                    "pincode": pincode,
                    "message": "Mock serviceability check",
                    "estimated_days": 4,
                    "carrier": "Shiprocket"
                }
            
            auth_data = self.authenticate()
            token = auth_data.get("token")
            
            url = f"{self.base_url}/external/courier/serviceability"
            params = {
                "pickup_postcode": getattr(self.settings, 'warehouse_pincode', '560001'),
                "delivery_postcode": pincode,
                "weight": 0.5,
                "cod": 0
            }
            
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                available_couriers = data.get("available_courier_companies", [])
                
                return {
                    "serviceable": len(available_couriers) > 0,
                    "pincode": pincode,
                    "message": f"{len(available_couriers)} couriers available" if available_couriers else "No couriers available",
                    "available_couriers": available_couriers,
                    "carrier": "Shiprocket"
                }
            else:
                return {
                    "serviceable": False,
                    "pincode": pincode,
                    "message": f"API Error: {response.status_code}",
                    "carrier": "Shiprocket"
                }
                
        except Exception as e:
            frappe.log_error(title="Shiprocket Serviceability Failed", message=str(e))
            return {
                "serviceable": False,
                "pincode": pincode,
                "message": str(e),
                "carrier": "Shiprocket"
            }
    
    def get_rates(self, shipment_data):
        """Get Shiprocket shipping rates"""
        try:
            if getattr(self.settings, 'use_mock_api', False):
                return self._get_mock_rates(shipment_data)
            
            auth_data = self.authenticate()
            token = auth_data.get("token")
            
            url = f"{self.base_url}/external/courier/serviceability"
            params = {
                "pickup_postcode": getattr(self.settings, 'warehouse_pincode', '560001'),
                "delivery_postcode": str(shipment_data["customer"]["pincode"]),
                "weight": shipment_data["package"]["weight"],
                "cod": 1 if shipment_data["order"].get("payment_type") == "COD" else 0,
                "cod_amount": shipment_data["order"].get("cod_amount", 0)
            }
            
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_rates_response(data)
            else:
                raise Exception(f"Rates API Error: {response.status_code}")
                
        except Exception as e:
            frappe.log_error(title="Shiprocket Rates Failed", message=str(e))
            return {
                "success": False,
                "error": str(e),
                "rates": []
            }
    
    def _parse_rates_response(self, data):
        """Parse rates response"""
        rates = []
        available_couriers = data.get("available_courier_companies", [])
        
        for courier in available_couriers:
            rates.append({
                "service_type": courier.get("courier_name", ""),
                "charge": courier.get("rate", 0),
                "estimated_days": courier.get("etd", ""),
                "carrier": "Shiprocket"
            })
        
        return {
            "success": True,
            "rates": rates,
            "currency": "INR"
        }
    
    def _get_mock_rates(self, shipment_data):
        """Get mock rates"""
        import random
        
        weight = shipment_data["package"]["weight"]
        base_rate = weight * 18
        
        couriers = [
            {"name": "Shiprocket Surface", "multiplier": 0.8, "days": 5},
            {"name": "Shiprocket Air", "multiplier": 1.2, "days": 2},
            {"name": "Delhivery Surface", "multiplier": 0.9, "days": 4},
            {"name": "Delhivery Air", "multiplier": 1.3, "days": 1},
            {"name": "BlueDart", "multiplier": 1.5, "days": 2},
            {"name": "DTDC", "multiplier": 0.7, "days": 6}
        ]
        
        rates = []
        for courier in couriers[:3]:
            rates.append({
                "service_type": courier["name"],
                "charge": base_rate * courier["multiplier"],
                "estimated_days": courier["days"],
                "carrier": "Shiprocket"
            })
        
        return {
            "success": True,
            "rates": rates,
            "currency": "INR"
        }