# File: utils.py (Non-Large Shipment)

def create_non_large_shipment(doc, token):
    """Create non-large shipment as per Ekart API v2"""
    try:
        settings = frappe.get_single("Ekart Settings")
        
        if settings.environment == "Sandbox":
            base_url = "https://api-sandbox.ekartlogistics.com"
        else:
            base_url = "https://api.ekartlogistics.com"
        
        url = f"{base_url}/v2/non-large"
        
        # Prepare payload as per API docs
        payload = {
            "external_shipment_id": doc.name,
            "customer_details": {
                "name": doc.customer_name,
                "phone": doc.customer_phone or "",
                "pincode": str(doc.pincode),
                "address_line_1": doc.address[:100] if doc.address else "",
                "address_line_2": "",
                "city": doc.location or "",
                "state": "",
                "country": "IN"
            },
            "package_details": {
                "weight": float(doc.weight or 0.5),  # in kg
                "length": float(doc.length or 10),   # in cm
                "breadth": float(doc.width or 10),   # in cm
                "height": float(doc.height or 10),   # in cm
                "declared_value": float(doc.declared_value or 0),
                "description": doc.description or "General Goods"
            },
            "order_details": {
                "order_id": doc.order_no,
                "order_date": str(doc.handover_date or now_datetime().date()),
                "invoice_value": float(doc.invoice_value or 0),
                "invoice_number": doc.invoice_number or "",
                "payment_mode": settings.default_payment_mode or "Prepaid",
                "service_type": settings.default_service_type or "Surface"
            },
            "additional_details": {
                "cod_amount": float(doc.cod_amount or 0),
                "return_pincode": str(settings.return_pincode) if hasattr(settings, 'return_pincode') else str(doc.pincode),
                "delivery_instructions": doc.delivery_instructions or ""
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Log response for debugging
        frappe.log_error(
            title="Non-Large Shipment Response",
            message=f"Status: {response.status_code}\nRequest: {payload}\nResponse: {response.text}"
        )
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            return {
                "error": True,
                "status_code": response.status_code,
                "message": response.text,
                "details": "Non-large shipment creation failed"
            }
            
    except Exception as e:
        frappe.log_error(
            title="Non-Large Shipment Error",
            message=str(e)
        )
        return {
            "error": True,
            "message": str(e)
        }