# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/base_carrier.py
"""
Abstract Base Class for all Logistics Carriers
"""

from abc import ABC, abstractmethod

class BaseCarrier(ABC):
    """Abstract base class for all carrier implementations"""
    
    def __init__(self, settings):
        self.settings = settings
        self.carrier_name = ""
    
    @abstractmethod
    def authenticate(self):
        """Authenticate with carrier API"""
        pass
    
    @abstractmethod
    def create_shipment(self, shipment_data):
        """Create shipment with carrier"""
        pass
    
    @abstractmethod
    def track_shipment(self, tracking_number):
        """Track shipment"""
        pass
    
    @abstractmethod
    def download_label(self, tracking_number):
        """Download shipping label"""
        pass
    
    @abstractmethod
    def cancel_shipment(self, tracking_number):
        """Cancel shipment"""
        pass
    
    @abstractmethod
    def get_service_types(self):
        """Get available service types for this carrier"""
        pass
    
    def validate_address(self, pincode):
        """Validate if address is serviceable"""
        return {
            "serviceable": True,
            "message": "Serviceability check not implemented"
        }
    
    def get_rates(self, shipment_data):
        """Get shipping rates"""
        return {
            "success": False,
            "message": "Rates API not implemented",
            "rates": []
        }