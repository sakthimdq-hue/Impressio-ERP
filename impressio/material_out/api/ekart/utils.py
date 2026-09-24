"""
Ekart Logistics Integration API
File: inventre/material_out/api/ekart/utils.py
"""

import frappe
import requests
import json
import hmac
import hashlib
from frappe import _
from frappe.utils import now_datetime, get_url, cstr, flt
from frappe.utils.file_manager import save_file
from datetime import datetime, timedelta
import random

# ===================================================================
# AUTHENTICATION FUNCTIONS
# ===================================================================

@frappe.whitelist(allow_guest=True)
def get_auth_token():
    """Get authentication token from Ekart API"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        # MOCK MODE - Return dummy token for testing
        if settings.get("use_mock_api"):
            frappe.logger().info("Using mock authentication for Ekart API")
            return "mock_auth_token_for_testing_12345"
        
        # Get base URL based on environment
        if settings.environment == "Sandbox":
            base_url = "https://api-sandbox.ekartlogistics.com"
        else:
            base_url = "https://api.ekartlogistics.com"
        
        # Check for username/password in site config
        username = frappe.conf.get("ekart_username")
        password = frappe.conf.get("ekart_password")
        
        if username and password:
            # Use OAuth password grant
            url = f"{base_url}/login/v1/oauth/token"
            payload = {
                "username": username,
                "password": password,
                "grant_type": "password"
            }
        elif settings.client_id and settings.client_secret:
            # Use client credentials
            url = f"{base_url}/v1/auth/token"
            payload = {
                "client_id": settings.client_id,
                "client_secret": settings.client_secret
            }
        else:
            frappe.throw(_("Ekart credentials not configured. Please check Ekart Settings."))
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        token = data.get("access_token")
        
        if token:
            # Cache the token
            settings.auth_token = token
            settings.token_expiry = now_datetime() + timedelta(seconds=data.get("expires_in", 3600))
            settings.save(ignore_permissions=True)
            frappe.db.commit()
            
            return token
        
        frappe.throw(_("Failed to get authentication token from Ekart"))
        
    except requests.exceptions.RequestException as e:
        frappe.log_error(
            title="Ekart Authentication Failed",
            message=f"Error: {str(e)}\nURL: {url if 'url' in locals() else 'N/A'}"
        )
        frappe.throw(_("Failed to connect to Ekart API. Please check your internet connection and credentials."))
    except Exception as e:
        frappe.log_error(
            title="Ekart Authentication Error",
            message=str(e)
        )
        frappe.throw(_("Authentication error: {0}").format(str(e)))

def get_cached_auth_token():
    """Get cached token or fetch new one if expired"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        # If mock API is enabled, return mock token
        if settings.get("use_mock_api"):
            return "mock_auth_token_for_testing_12345"
        
        # Check if token is valid
        if settings.auth_token and settings.token_expiry:
            expiry = frappe.utils.get_datetime(settings.token_expiry)
            if expiry > now_datetime():
                return settings.auth_token
        
        # Get new token
        return get_auth_token()
        
    except Exception as e:
        frappe.log_error(title="Token Cache Error", message=str(e))
        return None

# ===================================================================
# SHIPMENT CREATION FUNCTIONS
# ===================================================================

@frappe.whitelist()
def create_shipment_for_doc(docname):
    """
    Main function to create Ekart shipment
    Called from UI button
    """
    try:
        # Get document
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        # Validate document state
        if doc.docstatus != 0:
            frappe.throw(_("Shipment can only be created in Draft state"))
        
        if doc.ekart_tracking_number:
            frappe.throw(_("Tracking number already exists"))
        
        # Validate required fields
        required_fields = ['customer_name', 'address', 'pincode', 'order_no', 'weight']
        missing_fields = []
        for field in required_fields:
            if not doc.get(field):
                missing_fields.append(frappe.unscrub(field))
        
        if missing_fields:
            frappe.throw(_("Please fill in: {0}").format(", ".join(missing_fields)))
        
        # Get Ekart settings
        settings = frappe.get_single("Ekart Settings")
        
        # Use Mock API for testing
        if settings.get("use_mock_api"):
            return create_mock_shipment(doc)
        
        # Determine if large shipment
        is_large = is_large_shipment(doc)
        
        # Get authentication token
        token = get_cached_auth_token()
        if not token:
            frappe.throw(_("Failed to authenticate with Ekart API"))
        
        # Create shipment based on type
        if is_large:
            result = create_large_shipment_real(doc, token, settings)
        else:
            result = create_non_large_shipment_real(doc, token, settings)
        
        # Process result
        if result.get("error"):
            frappe.throw(_("Failed to create shipment: {0}").format(result.get("message", "Unknown error")))
        
        # Extract tracking info
        tracking_id = (result.get("tracking_id") or 
                      result.get("shipment_id") or 
                      result.get("awb_number"))
        
        if not tracking_id:
            frappe.throw(_("No tracking ID received from Ekart"))
        
        # Update document
        doc.ekart_tracking_number = tracking_id
        doc.ekart_awb_number = result.get("awb_number", tracking_id)
        doc.ekart_shipment_status = "Created"
        doc.ekart_manifest_id = result.get("manifest_id", "")
        doc.save(ignore_permissions=True)
        
        frappe.db.commit()
        
        # Create notification
        frappe.msgprint(
            _("Shipment created successfully! Tracking ID: {0}").format(tracking_id),
            indicator="green",
            alert=True
        )
        
        return {
            "status": "success",
            "tracking_id": tracking_id,
            "message": _("Shipment created successfully")
        }
        
    except frappe.exceptions.ValidationError:
        raise
    except Exception as e:
        frappe.log_error(
            title="Shipment Creation Failed",
            message=f"Doc: {docname}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
        )
        frappe.throw(_("Failed to create shipment: {0}").format(str(e)))

def is_large_shipment(doc):
    """Determine if shipment is large based on Ekart criteria"""
    large_threshold = {
        'length': 120,  # cm
        'width': 120,   # cm
        'height': 120,  # cm
        'weight': 30    # kg
    }
    
    try:
        length = float(doc.length or 0)
        width = float(doc.width or 0)
        height = float(doc.height or 0)
        weight = float(doc.weight or 0)
        
        if (length > large_threshold['length'] or 
            width > large_threshold['width'] or 
            height > large_threshold['height'] or 
            weight > large_threshold['weight']):
            return True
    except:
        pass
        
    return False

def create_non_large_shipment_real(doc, token, settings):
    """Create non-large shipment using real API"""
    try:
        # Get base URL
        if settings.environment == "Sandbox":
            base_url = "https://api-sandbox.ekartlogistics.com"
        else:
            base_url = "https://api.ekartlogistics.com"
        
        url = f"{base_url}/v2/non-large"
        
        # Prepare payload
        payload = {
            "external_shipment_id": doc.name,
            "customer_details": {
                "name": doc.customer_name,
                "phone": doc.customer_phone or "0000000000",
                "pincode": str(doc.pincode),
                "address_line_1": (doc.address or "")[:100],
                "address_line_2": "",
                "city": doc.location or "",
                "state": doc.state or "",
                "country": "IN"
            },
            "package_details": {
                "weight": float(doc.weight or 0.5),
                "length": float(doc.length or 10),
                "breadth": float(doc.width or 10),
                "height": float(doc.height or 10),
                "declared_value": float(doc.declared_value or 0),
                "description": doc.description or "General Goods"
            },
            "order_details": {
                "order_id": doc.order_no,
                "order_date": str(doc.handover_date or now_datetime().date()),
                "invoice_value": float(doc.invoice_value or 0),
                "invoice_number": doc.invoice_number or "",
                "payment_mode": "Prepaid" if doc.payment_type == "Prepaid" else "COD",
                "service_type": "Surface"
            },
            "additional_details": {
                "cod_amount": float(doc.cod_amount or 0),
                "delivery_instructions": doc.delivery_instructions or "",
                "return_pincode": str(settings.warehouse_pincode) if settings.warehouse_pincode else str(doc.pincode)
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Log for debugging
        frappe.log_error(
            title="Ekart Non-Large Shipment API Call",
            message=f"URL: {url}\nStatus: {response.status_code}\nResponse: {response.text}"
        )
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            return {
                "error": True,
                "message": f"HTTP {response.status_code}: {response.text}",
                "status_code": response.status_code
            }
            
    except requests.exceptions.Timeout:
        return {"error": True, "message": "API request timeout"}
    except requests.exceptions.ConnectionError:
        return {"error": True, "message": "Connection error. Please check your internet connection."}
    except Exception as e:
        frappe.log_error(
            title="Non-Large Shipment Error",
            message=str(e)
        )
        return {
            "error": True,
            "message": str(e)
        }

def create_large_shipment_real(doc, token, settings):
    """Create large shipment using real API"""
    try:
        # Get base URL
        if settings.environment == "Sandbox":
            base_url = "https://api-sandbox.ekartlogistics.com"
        else:
            base_url = "https://api.ekartlogistics.com"
        
        url = f"{base_url}/v1/large"
        
        # Prepare payload
        payload = {
            "external_shipment_id": doc.name,
            "customer_details": {
                "name": doc.customer_name,
                "phone": doc.customer_phone or "0000000000",
                "pincode": str(doc.pincode),
                "address_line_1": (doc.address or "")[:100],
                "address_line_2": "",
                "city": doc.location or "",
                "state": doc.state or "",
                "country": "IN"
            },
            "package_details": {
                "weight": float(doc.weight or 30.1),
                "length": float(doc.length or 50),
                "breadth": float(doc.width or 50),
                "height": float(doc.height or 50),
                "declared_value": float(doc.declared_value or 0),
                "description": doc.description or "Large Goods"
            },
            "order_details": {
                "order_id": doc.order_no,
                "order_date": str(doc.handover_date or now_datetime().date()),
                "invoice_value": float(doc.invoice_value or 0),
                "invoice_number": doc.invoice_number or "",
                "payment_mode": "Prepaid" if doc.payment_type == "Prepaid" else "COD"
            },
            "additional_details": {
                "cod_amount": float(doc.cod_amount or 0),
                "delivery_instructions": doc.delivery_instructions or "",
                "pickup_preferences": {
                    "preferred_pickup_date": str(doc.handover_date or now_datetime().date()),
                    "preferred_pickup_time": "10:00-18:00"
                }
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Log for debugging
        frappe.log_error(
            title="Ekart Large Shipment API Call",
            message=f"URL: {url}\nStatus: {response.status_code}\nResponse: {response.text}"
        )
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            return {
                "error": True,
                "message": f"HTTP {response.status_code}: {response.text}",
                "status_code": response.status_code
            }
            
    except requests.exceptions.Timeout:
        return {"error": True, "message": "API request timeout"}
    except requests.exceptions.ConnectionError:
        return {"error": True, "message": "Connection error. Please check your internet connection."}
    except Exception as e:
        frappe.log_error(
            title="Large Shipment Error",
            message=str(e)
        )
        return {
            "error": True,
            "message": str(e)
        }

def create_mock_shipment(doc):
    """Create mock shipment for testing"""
    import random
    
    is_large = is_large_shipment(doc)
    prefix = "EKLG" if is_large else "EKNL"
    tracking_id = f"{prefix}{random.randint(10000000, 99999999)}"
    
    # UPDATE THE DOCUMENT - THIS WAS MISSING!
    doc.ekart_tracking_number = tracking_id
    doc.ekart_awb_number = tracking_id
    doc.ekart_shipment_status = "Created"
    doc.ekart_manifest_id = f"MANIFEST{random.randint(1000, 9999)}"
    
    # SAVE THE DOCUMENT - IMPORTANT!
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    result = {
        "shipment_id": tracking_id,
        "tracking_id": tracking_id,
        "awb_number": tracking_id,
        "status": "SHIPMENT_CREATED",
        "manifest_id": doc.ekart_manifest_id,
        "label_url": f"https://mock.ekart.com/labels/{tracking_id}.pdf"
    }
    
    # Show success message
    frappe.msgprint(
        f"✅ Mock shipment created successfully! Tracking ID: {tracking_id}",
        indicator="green",
        alert=True
    )
    
    return result
# ===================================================================
# BULK OPERATIONS
# ===================================================================

@frappe.whitelist()
def bulk_create_shipments(docnames):
    """Bulk create shipments from list view"""
    try:
        docnames = json.loads(docnames)
        results = {
            "success": [], 
            "failed": [], 
            "success_count": 0, 
            "failed_count": 0
        }
        
        for docname in docnames:
            try:
                result = create_shipment_for_doc(docname)
                if result.get("status") == "success":
                    results["success"].append({
                        "docname": docname,
                        "tracking_id": result.get("tracking_id")
                    })
                    results["success_count"] += 1
                else:
                    results["failed"].append({
                        "docname": docname,
                        "error": result.get("message", "Unknown error")
                    })
                    results["failed_count"] += 1
            except Exception as e:
                results["failed"].append({
                    "docname": docname,
                    "error": str(e)
                })
                results["failed_count"] += 1
        
        # Show summary
        if results["success_count"] > 0:
            frappe.msgprint(
                _("Successfully created {0} shipments").format(results["success_count"]),
                indicator="green",
                alert=True
            )
        
        if results["failed_count"] > 0:
            frappe.msgprint(
                _("Failed to create {0} shipments").format(results["failed_count"]),
                indicator="orange",
                alert=True
            )
        
        return results
        
    except Exception as e:
        frappe.log_error(title="Bulk Creation Failed", message=str(e))
        frappe.throw(_("Bulk creation failed: {0}").format(str(e)))

# ===================================================================
# TRACKING FUNCTIONS
# ===================================================================

@frappe.whitelist()
def track_shipment(docname):
    """Track shipment status"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        if not doc.ekart_tracking_number:
            frappe.throw(_("No tracking number available"))
        
        settings = frappe.get_single("Ekart Settings")
        
        if settings.get("use_mock_api"):
            # Mock tracking
            statuses = ["Created", "Picked Up", "In Transit", "Out for Delivery", "Delivered"]
            current_index = statuses.index(doc.ekart_shipment_status) if doc.ekart_shipment_status in statuses else 0
            new_index = min(current_index + 1, len(statuses) - 1)
            new_status = statuses[new_index]
            
            doc.ekart_shipment_status = new_status
            doc.append("ekart_tracking_history", {
                "event_time": now_datetime(),
                "event_type": new_status.upper().replace(" ", "_"),
                "status": new_status,
                "location": "Mock Location",
                "remarks": "Mock tracking update"
            })
        else:
            # Real API tracking
            token = get_cached_auth_token()
            
            if not token:
                frappe.throw(_("Failed to authenticate with Ekart"))
            
            # Get base URL
            if settings.environment == "Sandbox":
                base_url = "https://api-sandbox.ekartlogistics.com"
            else:
                base_url = "https://api.ekartlogistics.com"
            
            url = f"{base_url}/v1/track/{doc.ekart_tracking_number}"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Update status
                current_status = data.get("current_status", {}).get("status", "Unknown")
                status_mapping = {
                    "SHIPMENT_CREATED": "Created",
                    "PICKED_UP": "Picked Up",
                    "IN_TRANSIT": "In Transit",
                    "OUT_FOR_DELIVERY": "Out for Delivery",
                    "DELIVERED": "Delivered",
                    "RTO": "RTO",
                    "EXCEPTION": "Exception",
                    "CANCELLED": "Cancelled"
                }
                
                doc.ekart_shipment_status = status_mapping.get(current_status, "Unknown")
                
                # Update tracking history
                if data.get("tracking_history"):
                    # Clear existing history
                    doc.set("ekart_tracking_history", [])
                    
                    for event in data["tracking_history"]:
                        doc.append("ekart_tracking_history", {
                            "event_time": event.get("event_time"),
                            "event_type": event.get("event_type"),
                            "status": event.get("status"),
                            "location": event.get("location", ""),
                            "remarks": event.get("remarks", "")
                        })
            else:
                frappe.throw(_("Failed to track shipment: {0}").format(response.text))
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        frappe.msgprint(
            _("Tracking updated for {0}").format(doc.ekart_tracking_number),
            indicator="green"
        )
        
        return {"status": "success", "message": _("Tracking updated")}
        
    except Exception as e:
        frappe.log_error(title="Tracking Failed", message=str(e))
        frappe.throw(_("Failed to track shipment: {0}").format(str(e)))

# ===================================================================
# LABEL DOWNLOAD FUNCTIONS
# ===================================================================

@frappe.whitelist()
def download_label(docname):
    """Download shipping label"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        if not doc.ekart_tracking_number:
            frappe.throw(_("No tracking number available"))
        
        settings = frappe.get_single("Ekart Settings")
        
        if settings.get("use_mock_api"):
            # Generate mock label content
            label_content = f"""
            SHIPPING LABEL
            ================
            Tracking Number: {doc.ekart_tracking_number}
            Customer: {doc.customer_name}
            Address: {doc.address}
            Pincode: {doc.pincode}
            
            From:
            Warehouse: {settings.warehouse_address or 'Default Warehouse'}
            Pincode: {settings.warehouse_pincode}
            
            Package Details:
            Weight: {doc.weight} kg
            Dimensions: {doc.length or 0} x {doc.width or 0} x {doc.height or 0} cm
            
            Generated: {now_datetime()}
            """
            
            file_name = f"ekart_label_{doc.ekart_tracking_number}.txt"
            file_doc = save_file(
                file_name,
                label_content.encode(),
                "Handover To Logistics",
                doc.name,
                is_private=0
            )
        else:
            # Download real label
            token = get_cached_auth_token()
            
            if not token:
                frappe.throw(_("Failed to authenticate with Ekart"))
            
            # Get base URL
            if settings.environment == "Sandbox":
                base_url = "https://api-sandbox.ekartlogistics.com"
            else:
                base_url = "https://api.ekartlogistics.com"
            
            url = f"{base_url}/v1/labels/{doc.ekart_tracking_number}"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/pdf"
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            file_name = f"ekart_label_{doc.ekart_tracking_number}.pdf"
            file_doc = save_file(
                file_name,
                response.content,
                "Handover To Logistics",
                doc.name,
                is_private=0,
                content_type="application/pdf"
            )
        
        doc.ekart_label = file_doc.file_url
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {
            "status": "success",
            "file_url": file_doc.file_url,
            "file_name": file_name
        }
        
    except Exception as e:
        frappe.log_error(title="Label Download Failed", message=str(e))
        frappe.throw(_("Failed to download label: {0}").format(str(e)))

# ===================================================================
# WEBHOOK HANDLING
# ===================================================================

@frappe.whitelist(allow_guest=True)
def handle_ekart_webhook():
    """Handle Ekart webhook events"""
    try:
        # Get request data
        data = frappe.request.get_data(as_text=True)
        frappe.log_error(
            title="Ekart Webhook Received",
            message=f"Webhook Data: {data}"
        )
        
        # Parse JSON
        try:
            webhook_data = json.loads(data)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Invalid JSON"}, 400
        
        # Verify webhook signature (if configured)
        settings = frappe.get_single("Ekart Settings")
        signature = frappe.request.headers.get("X-Ekart-Signature")
        
        if settings.webhook_secret and signature:
            expected_signature = hmac.new(
                settings.webhook_secret.encode(),
                data.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                return {"status": "error", "message": "Invalid signature"}, 401
        
        # Process webhook event
        event_type = webhook_data.get("event_type")
        tracking_id = webhook_data.get("tracking_id")
        
        if not tracking_id:
            return {"status": "error", "message": "No tracking ID provided"}, 400
        
        # Find document by tracking number
        docs = frappe.get_all(
            "Handover To Logistics",
            filters={"ekart_tracking_number": tracking_id},
            fields=["name"]
        )
        
        if not docs:
            return {"status": "error", "message": "Document not found"}, 404
        
        docname = docs[0].name
        doc = frappe.get_doc("Handover To Logistics", docname)
        
        # Map event type to status
        status_mapping = {
            "SHIPMENT_CREATED": "Created",
            "PICKED_UP": "Picked Up",
            "IN_TRANSIT": "In Transit",
            "OUT_FOR_DELIVERY": "Out for Delivery",
            "DELIVERED": "Delivered",
            "RTO": "RTO",
            "EXCEPTION": "Exception",
            "CANCELLED": "Cancelled"
        }
        
        new_status = status_mapping.get(event_type, "Unknown")
        
        # Update document
        doc.ekart_shipment_status = new_status
        
        # Add to tracking history
        doc.append("ekart_tracking_history", {
            "event_time": now_datetime(),
            "event_type": event_type,
            "status": new_status,
            "location": webhook_data.get("location", ""),
            "remarks": webhook_data.get("remarks", webhook_data.get("description", ""))
        })
        
        # Set dates for specific events
        if event_type == "PICKED_UP":
            doc.ekart_pickup_date = now_datetime()
        elif event_type == "DELIVERED":
            doc.ekart_delivery_date = now_datetime()
            doc.status = "Delivered"
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {"status": "success", "message": "Webhook processed"}
        
    except Exception as e:
        frappe.log_error(
            title="Ekart Webhook Error",
            message=f"Error: {str(e)}\nData: {frappe.request.get_data() if frappe.request else 'No request'}"
        )
        return {"status": "error", "message": str(e)}, 500

# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

@frappe.whitelist()
def get_shipment_stats():
    """Get shipment statistics for dashboard"""
    try:
        stats = frappe.db.sql("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN ekart_tracking_number IS NOT NULL THEN 1 ELSE 0 END) as with_tracking,
                SUM(CASE WHEN ekart_tracking_number IS NULL THEN 1 ELSE 0 END) as without_tracking,
                SUM(CASE WHEN ekart_shipment_status = 'Delivered' THEN 1 ELSE 0 END) as delivered,
                SUM(CASE WHEN ekart_shipment_status = 'In Transit' THEN 1 ELSE 0 END) as in_transit,
                SUM(CASE WHEN ekart_shipment_status = 'RTO' THEN 1 ELSE 0 END) as rto
            FROM `tabHandover To Logistics`
            WHERE docstatus = 0
        """, as_dict=True)
        
        if stats:
            return stats[0]
        return {}
        
    except Exception as e:
        frappe.log_error(title="Shipment Stats Error", message=str(e))
        return {}

@frappe.whitelist()
def check_pincode_serviceability(pincode, is_large=False):
    """Check if pincode is serviceable by Ekart"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        if settings.get("use_mock_api"):
            # Mock serviceability check
            # In real implementation, call Ekart's serviceability API
            return {
                "serviceable": True,
                "message": "Mock serviceability check",
                "estimated_days": 3 if not is_large else 5
            }
        
        return {
            "serviceable": True,
            "message": "Serviceability check not implemented for real API",
            "estimated_days": None
        }
        
    except Exception as e:
        frappe.log_error(title="Serviceability Check Error", message=str(e))
        return {"serviceable": False, "message": str(e)}

@frappe.whitelist()
def test_ekart_connection():
    """Test connection to Ekart API"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        if settings.get("use_mock_api"):
            return {
                "status": "success",
                "message": "Mock API is enabled",
                "details": "Using mock mode for testing"
            }
        
        token = get_cached_auth_token()
        
        if token:
            return {
                "status": "success",
                "message": "Connected to Ekart API successfully",
                "token_obtained": True
            }
        else:
            return {
                "status": "error",
                "message": "Failed to connect to Ekart API"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ===================================================================
# TEST FUNCTION (Add this at the end of your utils.py)
# ===================================================================

@frappe.whitelist()
def test_connection():
    """Test if the API is working"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        return {
            "status": "success",
            "message": "Ekart API is working",
            "settings": {
                "environment": settings.environment,
                "use_mock_api": settings.use_mock_api,
                "warehouse_pincode": settings.warehouse_pincode
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist()
def setup_ekart_settings():
    """Create Ekart Settings if it doesn't exist"""
    try:
        # Check if Ekart Settings exists
        if not frappe.db.exists("DocType", "Ekart Settings"):
            return {
                "status": "error",
                "message": "Ekart Settings doctype not found. Please create it first."
            }
        
        # Check if single instance exists
        if not frappe.db.exists("Ekart Settings", "Ekart Settings"):
            # Create default settings
            settings = frappe.new_doc("Ekart Settings")
            settings.environment = "Sandbox"
            settings.use_mock_api = True
            settings.warehouse_pincode = "560001"
            settings.warehouse_address = "Default Warehouse Address"
            settings.warehouse_city = "Bangalore"
            settings.warehouse_state = "Karnataka"
            settings.warehouse_country = "India"
            settings.warehouse_phone = "9999999999"
            settings.save()
            
            return {
                "status": "success",
                "message": "Ekart Settings created successfully!"
            }
        else:
            return {
                "status": "success",
                "message": "Ekart Settings already exists"
            }
            
    except Exception as e:
        frappe.log_error(title="Setup Ekart Settings Failed", message=str(e))
        return {
            "status": "error",
            "message": str(e)
        }

# ===================================================================
# SIMPLE DEBUG FUNCTIONS
# ===================================================================

@frappe.whitelist()
def debug_info():
    """Get debug information about the Ekart setup"""
    try:
        info = {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "frappe_version": frappe.__version__,
            "requests_version": requests.__version__ if 'requests' in sys.modules else "Not loaded",
            "ekart_settings_exists": frappe.db.exists("DocType", "Ekart Settings"),
            "ekart_settings_instance_exists": frappe.db.exists("Ekart Settings", "Ekart Settings") if frappe.db.exists("DocType", "Ekart Settings") else False,
            "handover_doctype_exists": frappe.db.exists("DocType", "Handover To Logistics"),
            "ekart_tracking_history_exists": frappe.db.exists("DocType", "Ekart Tracking History")
        }
        
        # Try to get settings
        try:
            settings = frappe.get_single("Ekart Settings")
            info["ekart_settings"] = {
                "environment": settings.environment,
                "use_mock_api": settings.use_mock_api,
                "warehouse_pincode": settings.warehouse_pincode
            }
        except:
            info["ekart_settings"] = "Not accessible"
        
        return {
            "status": "success",
            "info": info
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }

@frappe.whitelist()
def test_create_shipment_simple(docname):
    """Simplified test function to create a shipment"""
    try:
        # Just create a mock tracking number
        import random
        tracking_id = f"TEST{random.randint(100000, 999999)}"
        
        doc = frappe.get_doc("Handover To Logistics", docname)
        doc.ekart_tracking_number = tracking_id
        doc.ekart_shipment_status = "Created"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {
            "status": "success",
            "tracking_id": tracking_id,
            "message": f"Test shipment created: {tracking_id}"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }


# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/ekart/utils.py

# Replace the get_ekart_settings() function with this:

def get_ekart_settings():
    """Get Ekart settings with proper error handling"""
    try:
        # First check if doctype exists
        if not frappe.db.exists("DocType", "Ekart Settings"):
            return create_default_settings_object()
        
        # Try to get single instance
        try:
            return frappe.get_single("Ekart Settings")
        except frappe.exceptions.DoesNotExistError:
            # Document doesn't exist, create it
            return create_ekart_settings_instance()
        except Exception:
            # Other error, use defaults
            return create_default_settings_object()
            
    except Exception:
        # Any other error, use defaults
        return create_default_settings_object()

def create_ekart_settings_instance():
    """Create Ekart Settings instance if it doesn't exist"""
    try:
        settings = frappe.new_doc("Ekart Settings")
        settings.environment = "Sandbox"
        settings.use_mock_api = True
        settings.warehouse_pincode = "560001"
        settings.warehouse_address = "Default Warehouse"
        settings.warehouse_city = "Bangalore"
        settings.warehouse_state = "Karnataka"
        settings.warehouse_country = "India"
        settings.warehouse_phone = "9999999999"
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        
        frappe.log_error("Created missing Ekart Settings instance", "Ekart")
        return settings
        
    except Exception as e:
        frappe.log_error(f"Failed to create Ekart Settings: {str(e)}", "Ekart")
        return create_default_settings_object()

def create_default_settings_object():
    """Create default settings object"""
    class DefaultSettings:
        def __init__(self):
            self.environment = "Sandbox"
            self.use_mock_api = True
            self.warehouse_pincode = "560001"
            self.auth_token = None
            self.token_expiry = None
            self.api_base_url = "https://api-sandbox.ekartlogistics.com"
            self.client_id = ""
            self.client_secret = ""
            self.webhook_secret = ""
            self.webhook_url = ""
            self.warehouse_address = "Default Warehouse"
            self.warehouse_city = "Bangalore"
            self.warehouse_state = "Karnataka"
            self.warehouse_country = "India"
            self.warehouse_phone = "9999999999"
        
        def get(self, key, default=None):
            return getattr(self, key, default)
        
        def save(self, *args, **kwargs):
            pass
    
    return DefaultSettings()