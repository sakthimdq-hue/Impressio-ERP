# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PhysicalInspectionForUnloading(Document):
	def on_update(self):
		self.update_status()
	def update_status(self):
		accepted_count = 0
		rejected_count = 0

		for row in self.readings:
			if row.accepted == 1:
				accepted_count += 1
			if row.rejected == 1:
				rejected_count += 1

		if accepted_count > rejected_count:
			self.status = "Accepted"
		elif accepted_count < rejected_count:
			self.status = "Rejected"
		else:
			self.status = "Partially Accepted"

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_available_gate_entries(doctype, txt, searchfield, start, page_len, filters=None):
    filters = filters or {}
    current_doc = filters.get("current_doc") or ""

    used_gate_entries = frappe.db.sql_list("""
        SELECT gate_entry
        FROM `tabPhysical Inspection For Unloading`
        WHERE gate_entry IS NOT NULL
        AND name != %s
    """, current_doc)

    conditions = []
    params = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    }

    if used_gate_entries:
        conditions.append("name NOT IN %(used_gate_entries)s")
        params["used_gate_entries"] = tuple(used_gate_entries)

    condition_sql = f"AND {' AND '.join(conditions)}" if conditions else ""

    return frappe.db.sql(f"""
        SELECT name
        FROM `tabGate Entry`
        WHERE name LIKE %(txt)s
        {condition_sql}
        ORDER BY modified DESC
        LIMIT %(start)s, %(page_len)s
    """, params)
