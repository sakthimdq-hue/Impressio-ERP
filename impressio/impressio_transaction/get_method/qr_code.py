import frappe
import json

@frappe.whitelist()
def get_parameter(): 
    doc = frappe.get_doc("App Settings")

    parameter_data = []
    for child_data in doc.get('readings'):
        if child_data.parameter:
            parameter_data.append({
                'parameter': child_data.parameter,
                
            })

    return parameter_data