import frappe
import json
from frappe import _


@frappe.whitelist()
def bulk_update_bom_status(boms, action):
	"""
	boms   : JSON stringified list of BOM names  e.g. '["BOM-001", "BOM-002"]'
	action : "enable" | "disable"
	"""
	if isinstance(boms, str):
		boms = json.loads(boms)

	if action not in ("enable", "disable"):
		frappe.throw(_("Invalid action."))

	if not frappe.has_permission("BOM", "write"):
		frappe.throw(_("Not permitted to update BOMs."), frappe.PermissionError)

	is_active     = 1 if action == "enable" else 0
	success_count = 0
	failed_count  = 0
	failed_items  = []

	for bom_name in boms:
		try:
			frappe.db.set_value(
				"BOM",
				bom_name,
				{"is_active": is_active},
				update_modified=True,
			)
			success_count += 1
		except Exception as e:
			failed_count += 1
			failed_items.append(bom_name)
			frappe.log_error(
				title=f"BOM bulk {'enable' if action == 'enable' else 'disable'} failed: {bom_name}",
				message=str(e),
			)

	frappe.db.commit()

	return {
		"success_count": success_count,
		"failed_count":  failed_count,
		"failed_items":  failed_items,
	}