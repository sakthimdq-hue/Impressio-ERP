# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/carrier_factory.py
"""
Factory pattern to instantiate carrier objects
"""

import frappe

def get_carrier_instance(carrier_name):
    """Factory method to get carrier instance"""
    
    # Get settings
    try:
        settings = frappe.get_single("Logistics Settings")
    except:
        # Create default settings if not exists
        settings = create_default_settings()
    
    # Check if carrier is enabled
    if carrier_name == "Ekart" and not getattr(settings, 'enable_ekart', False):
        frappe.throw(f"Ekart is not enabled in Logistics Settings")
    
    if carrier_name == "Amazon Shipping" and not getattr(settings, 'enable_amazon', False):
        frappe.throw(f"Amazon Shipping is not enabled in Logistics Settings")
    
    if carrier_name == "Shiprocket" and not getattr(settings, 'enable_shiprocket', False):
        frappe.throw(f"Shiprocket is not enabled in Logistics Settings")
    
    # Instantiate carrier
    if carrier_name == "Ekart":
        from .ekart_carrier import EkartCarrier
        return EkartCarrier(settings)
    
    elif carrier_name == "Amazon Shipping":
        from .amazon_carrier import AmazonCarrier
        return AmazonCarrier(settings)
    
    elif carrier_name == "Shiprocket":
        from .shiprocket_carrier import ShiprocketCarrier
        return ShiprocketCarrier(settings)
    
    else:
        frappe.throw(f"Carrier '{carrier_name}' is not implemented")

def create_default_settings():
    """Create default settings object if doctype doesn't exist"""
    class DefaultSettings:
        def __init__(self):
            self.enable_ekart = True
            self.ekart_environment = "Sandbox"
            self.use_mock_api = True
            self.warehouse_pincode = "560001"
            self.enable_amazon = False
            self.enable_shiprocket = False
            
        def get(self, key, default=None):
            return getattr(self, key, default)
    
    return DefaultSettings()