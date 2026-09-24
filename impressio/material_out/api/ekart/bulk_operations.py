import frappe
import json

@frappe.whitelist()
def bulk_create_ekart_shipments(handover_names):
    """Bulk create Ekart shipments from list view"""
    handover_names = json.loads(handover_names)
    results = {"success": [], "failed": []}
    
    for name in handover_names:
        try:
            doc = frappe.get_doc("Handover To Logistics", name)
            if doc.docstatus == 1 and not doc.ekart_tracking_number:
                doc.create_ekart_shipment()
                results["success"].append(name)
            else:
                results["failed"].append(f"{name}: Not submitted or already has tracking")
        except Exception as e:
            results["failed"].append(f"{name}: {str(e)}")
    
    # Show summary
    if results["success"]:
        frappe.msgprint(f"✅ Created shipments for: {', '.join(results['success'])}")
    if results["failed"]:
        frappe.msgprint(f"❌ Failed: {', '.join(results['failed'])}")
    
    return results