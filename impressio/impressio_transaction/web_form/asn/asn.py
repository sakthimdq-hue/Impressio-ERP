import frappe
import json
from frappe import _

def get_context(context):
	pass

@frappe.whitelist()
def get_allowed_suppliers_with_pos(doctype, txt, searchfield, start, page_len, filters=None):
    """Return suppliers and their POs where the logged-in user exists in Portal Users."""
    
    user = frappe.session.user
    
    # Get allowed suppliers
    suppliers = frappe.db.sql("""
        SELECT s.name, s.supplier_name
        FROM `tabSupplier` s
        INNER JOIN `tabPortal User` pu ON pu.parent = s.name
        WHERE pu.user = %(user)s
        AND (s.name LIKE %(txt)s OR s.supplier_name LIKE %(txt)s)
        ORDER BY s.name
        LIMIT %(start)s, %(page_len)s
    """, {
        "user": user, 
        "txt": f"%{txt}%",
        "start": int(start),
        "page_len": int(page_len)
    }, as_dict=True)
    
    # Get POs for these suppliers
    supplier_names = [s['name'] for s in suppliers]
    purchase_orders = []
    
    if supplier_names:
        purchase_orders = frappe.db.sql("""
            SELECT name, supplier, transaction_date
            FROM `tabPurchase Order`
            WHERE supplier IN %(suppliers)s
            AND docstatus = 1
            AND status NOT IN ('Completed', 'Cancelled', 'Closed')
            ORDER BY transaction_date DESC
        """, {
            'suppliers': supplier_names
        }, as_dict=True)
    
    return {
        'suppliers': suppliers,
        'purchase_orders': purchase_orders
    }