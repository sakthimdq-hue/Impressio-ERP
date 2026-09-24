"""
Sales Invoice Overrides
This exports the CustomSalesInvoice class for Frappe's override system
"""

# Import the CustomSalesInvoice class from the sales_invoice.py file
from impressio.overrides.sales_invoice.sales_invoice import CustomSalesInvoice

# Make it available when importing the package
__all__ = ['CustomSalesInvoice']