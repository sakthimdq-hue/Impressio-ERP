import frappe
from frappe.utils import nowdate
from collections import defaultdict
from frappe import _


# =====================================================
# SCHEMA HELPERS
# =====================================================

def _has_sub_items_table():
	try:
		return frappe.db.table_exists("Sale Order Sub Items")
	except Exception:
		return False


def _has_custom_dn_so_column():
	try:
		return frappe.db.has_column("Delivery Note Item", "custom_custom_against_sales_order")
	except Exception:
		return False


def _get_so_items_data(so_names):
	"""
	Returns items for given SOs.
	If 'Sale Order Sub Items' table exists and has rows for an SO, uses those.
	Otherwise, falls back cleanly to standard 'Sales Order Item'.
	"""
	if isinstance(so_names, str):
		so_names = [so_names]

	if not so_names:
		return {}

	sub_item_map = {}
	if _has_sub_items_table():
		try:
			sub_rows = frappe.db.sql("""
				SELECT
					parent,
					name,
					item_code,
					parent_item_code,
					qty
				FROM `tabSale Order Sub Items`
				WHERE parent IN %(names)s
				ORDER BY parent, idx ASC
			""", {"names": tuple(so_names)}, as_dict=True)
			for r in sub_rows:
				sub_item_map.setdefault(r.parent, []).append(r)
		except Exception:
			sub_item_map = {}

	# Standard Sales Order Items
	std_rows = frappe.db.sql("""
		SELECT
			parent,
			name,
			item_code,
			item_code AS parent_item_code,
			qty
		FROM `tabSales Order Item`
		WHERE parent IN %(names)s
		ORDER BY parent, idx ASC
	""", {"names": tuple(so_names)}, as_dict=True)

	std_item_map = {}
	for r in std_rows:
		std_item_map.setdefault(r.parent, []).append(r)

	result_map = {}
	for so_name in so_names:
		if so_name in sub_item_map and len(sub_item_map[so_name]) > 0:
			result_map[so_name] = sub_item_map[so_name]
		else:
			result_map[so_name] = std_item_map.get(so_name, [])

	return result_map


# =====================================================
# BULK DELIVERY NOTE CREATION
# =====================================================

@frappe.whitelist()
def create_bulk_delivery_notes(sales_orders, selected_items=None):
	if isinstance(sales_orders, str):
		sales_orders = frappe.parse_json(sales_orders)

	if isinstance(selected_items, str):
		selected_items = frappe.parse_json(selected_items)

	selected_items = selected_items or {}
	results = []

	for so_name in sales_orders:
		try:
			# 1. Load the Sales Order
			so = frappe.get_doc("Sales Order", so_name)

			if so.docstatus != 1:
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": "Sales Order is not submitted"
				})
				continue

			if so.status not in ("To Deliver and Bill", "To Deliver"):
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": f"Status is '{so.status}' — skipped"
				})
				continue

			# 2. Collect sub items or standard items
			sub_items = _get_so_items_data([so_name]).get(so_name, [])

			if not sub_items:
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": "No items found for Sales Order"
				})
				continue

			# 3. Calculate pending qty per item
			pending_map = get_pending_qty_map(so_name, sub_items)

			all_delivered = all(
				pending_map.get(row.get("item_code") or row.item_code, {}).get("pending_qty", 0) <= 0
				for row in sub_items
			)

			if all_delivered:
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": "All items already fully delivered"
				})
				continue

			# 4. Build qty_map from selected_items
			so_selected = selected_items.get(so_name)

			qty_map = {}
			if so_selected is not None:
				for entry in so_selected:
					if isinstance(entry, dict):
						qty_map[entry["item_code"]] = entry["qty"]
					else:
						qty_map[entry] = None

			# 5. STOCK VALIDATION
			warehouse = so.set_warehouse
			stock_errors = []
			validated_items = []

			for row in sub_items:
				item_code = row.get("item_code") or row.item_code
				if so_selected is not None and item_code not in qty_map:
					continue

				pending_qty = pending_map.get(item_code, {}).get("pending_qty", 0)

				if so_selected is not None and item_code in qty_map:
					user_qty = qty_map[item_code]
					if user_qty is not None:
						pending_qty = min(int(user_qty), pending_qty)

				if pending_qty <= 0:
					continue

				available_stock = get_available_stock(item_code, warehouse)

				if available_stock < pending_qty:
					stock_errors.append(
						f"{item_code}: Need {pending_qty}, but only {available_stock} available in stock"
					)
				else:
					validated_items.append({
						"row": row,
						"pending_qty": pending_qty,
						"available_stock": available_stock
					})

			if stock_errors:
				results.append({
					"sales_order": so_name,
					"status": "error",
					"dn_name": "",
					"message": f"Stock insufficient: {'; '.join(stock_errors)}"
				})
				continue

			if not validated_items:
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": "No items with sufficient stock to deliver"
				})
				continue

			# 6. Lookup SO Item row names for so_detail field
			so_item_name_map = {
				r.item_code: r.name
				for r in frappe.db.get_all(
					"Sales Order Item",
					filters={"parent": so_name},
					fields=["name", "item_code"]
				)
			}

			has_custom_against_so = _has_custom_dn_so_column()
			dn_items = []

			for validated in validated_items:
				row = validated["row"]
				pending_qty = validated["pending_qty"]
				item_code = row.get("item_code") or row.item_code
				parent_item_code = row.get("parent_item_code") or row.parent_item_code or item_code

				is_parent = (parent_item_code == item_code)

				dn_item = {
					"doctype": "Delivery Note Item",
					"item_code": item_code,
					"qty": pending_qty,
				}

				if is_parent:
					dn_item["against_sales_order"] = so_name
					dn_item["so_detail"] = so_item_name_map.get(item_code, "")
				elif has_custom_against_so:
					dn_item["custom_custom_against_sales_order"] = so_name

				dn_items.append(dn_item)

			if not dn_items:
				results.append({
					"sales_order": so_name,
					"status": "skipped",
					"dn_name": "",
					"message": "No pending items to deliver"
				})
				continue

			# 7. Create & submit the Delivery Note
			dn = frappe.get_doc({
				"doctype": "Delivery Note",
				"customer": so.customer,
				"posting_date": nowdate(),
				"company": so.company,
				"currency": so.currency,
				"selling_price_list": so.selling_price_list,
				"set_warehouse": warehouse or "",
			})

			for di in dn_items:
				row = dn.append("items", {
					"item_code": di["item_code"],
					"qty": di["qty"],
					"against_sales_order": di.get("against_sales_order", ""),
					"so_detail": di.get("so_detail", ""),
				})
				if di.get("custom_custom_against_sales_order") and hasattr(row, "custom_custom_against_sales_order"):
					row.custom_custom_against_sales_order = di["custom_custom_against_sales_order"]

			dn.insert(ignore_permissions=True)
			dn.submit()

			try:
				_update_so_display_status(so_name)
			except Exception:
				frappe.log_error(
					title=f"Display Status Update Failed: {so_name}",
					message=frappe.get_traceback()
				)

			results.append({
				"sales_order": so_name,
				"status": "success",
				"dn_name": dn.name,
				"message": f"{len(dn_items)} item(s) delivered (stock verified)"
			})

		except Exception as e:
			frappe.log_error(
				title=f"Bulk DN Creation Failed: {so_name}",
				message=frappe.get_traceback()
			)
			results.append({
				"sales_order": so_name,
				"status": "error",
				"dn_name": "",
				"message": str(e)
			})

	return {"results": results}


# =====================================================
# DISPLAY STATUS HELPERS
# =====================================================

def _get_sub_item_counts_for_status(so_name):
	"""
	Returns { total: int, delivered: int } for items of a single SO.
	"""
	items_data = _get_so_items_data([so_name]).get(so_name, [])
	if not items_data:
		return {"total": 0, "delivered": 0}

	ordered_map = {}
	for r in items_data:
		ic = r.get("item_code") or r.item_code
		qty = r.get("qty") or r.qty or 0
		ordered_map[ic] = ordered_map.get(ic, 0) + qty

	item_codes = list(ordered_map.keys())

	std = frappe.db.sql("""
		SELECT dni.item_code, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1
		  AND dni.against_sales_order = %(so)s
		  AND dni.item_code IN %(items)s
		GROUP BY dni.item_code
	""", {"so": so_name, "items": tuple(item_codes)}, as_dict=True)

	custom = []
	if _has_custom_dn_so_column():
		try:
			custom = frappe.db.sql("""
				SELECT dni.item_code, SUM(dni.qty) AS qty
				FROM `tabDelivery Note Item` dni
				JOIN `tabDelivery Note` dn ON dn.name = dni.parent
				WHERE dn.docstatus = 1
				  AND dni.custom_custom_against_sales_order = %(so)s
				  AND dni.item_code IN %(items)s
				GROUP BY dni.item_code
			""", {"so": so_name, "items": tuple(item_codes)}, as_dict=True)
		except Exception:
			custom = []

	delivered_map = {}
	for row in std + custom:
		delivered_map[row.item_code] = delivered_map.get(row.item_code, 0) + (row.qty or 0)

	total = len(ordered_map)
	delivered = sum(
		1 for ic, oq in ordered_map.items()
		if delivered_map.get(ic, 0) >= oq
	)

	return {"total": total, "delivered": delivered}


def _update_so_display_status(so_name):
	so = frappe.db.get_value(
		"Sales Order", so_name,
		["status", "docstatus"], as_dict=True
	)

	if not so:
		return

	if so.docstatus == 0:
		new_status = "Not Yet Delivered"
	elif so.status == "Cancelled":
		new_status = "Cancelled"
	elif so.docstatus == 1:
		if _has_custom_dn_so_column():
			query = """
				SELECT COUNT(DISTINCT dn.name) AS cnt
				FROM `tabDelivery Note` dn
				JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
				WHERE dn.docstatus = 1
				  AND (
					  dni.against_sales_order = %(so)s
					  OR dni.custom_custom_against_sales_order = %(so)s
				  )
			"""
		else:
			query = """
				SELECT COUNT(DISTINCT dn.name) AS cnt
				FROM `tabDelivery Note` dn
				JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
				WHERE dn.docstatus = 1
				  AND dni.against_sales_order = %(so)s
			"""
		has_delivery = frappe.db.sql(query, {"so": so_name}, as_dict=True)[0].cnt or 0
		new_status = "Shipment Created" if has_delivery > 0 else "Not Yet Delivered"
	else:
		return

	if frappe.db.has_column("Sales Order", "custom_display_status"):
		frappe.db.set_value(
			"Sales Order", so_name,
			"custom_display_status", new_status,
			update_modified=False
		)


# =====================================================
# HELPER: GET AVAILABLE STOCK
# =====================================================

def get_available_stock(item_code, warehouse):
	"""Get available stock for an item in a warehouse"""
	try:
		if not warehouse:
			return 0

		bin_data = frappe.db.get_value(
			"Bin",
			{"item_code": item_code, "warehouse": warehouse},
			"actual_qty"
		)

		return max(0, bin_data or 0)
	except Exception as e:
		frappe.log_error(f"Error getting stock for {item_code}: {str(e)}")
		return 0


# =====================================================
# GET SO DELIVERY STATUS
# =====================================================

@frappe.whitelist()
def get_so_delivery_status(sales_orders):
	if isinstance(sales_orders, str):
		sales_orders = frappe.parse_json(sales_orders)

	result = []
	if not sales_orders:
		return result

	so_meta_rows = frappe.db.sql("""
		SELECT name, customer, status, docstatus, set_warehouse
		FROM `tabSales Order`
		WHERE name IN %(names)s
	""", {"names": tuple(sales_orders)}, as_dict=True)

	so_meta_map = {r.name: r for r in so_meta_rows}

	valid_so_names = [
		r.name for r in so_meta_rows
		if r.docstatus == 1
		and r.status in ("To Deliver and Bill", "To Deliver")
	]

	so_subitem_map = _get_so_items_data(valid_so_names)

	for so_name in sales_orders:
		sub_items = so_subitem_map.get(so_name, [])
		so_meta = so_meta_map.get(so_name, {})

		if so_meta.get("docstatus") != 1 or so_meta.get("status") not in ("To Deliver and Bill", "To Deliver"):
			result.append({
				"so_name": so_name,
				"customer": so_meta.get("customer", ""),
				"status": so_meta.get("status", ""),
				"items": [],
				"warning": f"Status '{so_meta.get('status')}' — not eligible for delivery"
			})
			continue

		if not sub_items:
			result.append({
				"so_name": so_name,
				"customer": so_meta.get("customer", ""),
				"status": so_meta.get("status", ""),
				"items": [],
				"warning": "No items found"
			})
			continue

		pending_map = get_pending_qty_map(so_name, sub_items)
		items_out_map = {}

		for row in sub_items:
			item_code = row.get("item_code") or row.item_code
			parent_item_code = row.get("parent_item_code") or row.parent_item_code or item_code
			p = pending_map.get(item_code, {})
			is_parent = (parent_item_code == item_code)

			available_stock = get_available_stock(
				item_code,
				so_meta.get("set_warehouse", "")
			)

			if item_code in items_out_map:
				continue

			items_out_map[item_code] = {
				"item_code": item_code,
				"parent_item_code": parent_item_code,
				"is_parent": is_parent,
				"ordered_qty": p.get("ordered_qty", row.get("qty") or 0),
				"delivered_qty": p.get("delivered_qty", 0),
				"pending_qty": p.get("pending_qty", row.get("qty") or 0),
				"stock_qty": available_stock,
				"warehouse": so_meta.get("set_warehouse", "")
			}

		items_out = list(items_out_map.values())

		result.append({
			"so_name": so_name,
			"customer": so_meta.get("customer", ""),
			"status": so_meta.get("status", ""),
			"items": items_out,
			"warning": ""
		})

	return result


# =====================================================
# PENDING QTY MAP
# =====================================================

def get_pending_qty_map(so_name, sub_items):
	item_codes = list({(row.get("item_code") or row.item_code) for row in sub_items})

	if not item_codes:
		return {}

	delivered_standard = frappe.db.sql("""
		SELECT
			dni.item_code,
			SUM(dni.qty) AS delivered_qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1
		  AND dni.against_sales_order = %(so)s
		  AND dni.item_code IN %(items)s
		GROUP BY dni.item_code
	""", {"so": so_name, "items": tuple(item_codes)}, as_dict=True)

	delivered_custom = []
	if _has_custom_dn_so_column():
		try:
			delivered_custom = frappe.db.sql("""
				SELECT
					dni.item_code,
					SUM(dni.qty) AS delivered_qty
				FROM `tabDelivery Note Item` dni
				JOIN `tabDelivery Note` dn ON dn.name = dni.parent
				WHERE dn.docstatus = 1
				  AND dni.custom_custom_against_sales_order = %(so)s
				  AND dni.item_code IN %(items)s
				GROUP BY dni.item_code
			""", {"so": so_name, "items": tuple(item_codes)}, as_dict=True)
		except Exception:
			delivered_custom = []

	delivered_map = {}
	for row in delivered_standard:
		delivered_map[row.item_code] = delivered_map.get(row.item_code, 0) + (row.delivered_qty or 0)

	for row in delivered_custom:
		delivered_map[row.item_code] = delivered_map.get(row.item_code, 0) + (row.delivered_qty or 0)

	pending_map = {}
	for row in sub_items:
		item_code = row.get("item_code") or row.item_code
		ordered_qty = row.get("qty") or row.qty or 0

		if item_code in pending_map:
			pending_map[item_code]["ordered_qty"] += ordered_qty
		else:
			pending_map[item_code] = {
				"ordered_qty": ordered_qty,
				"delivered_qty": 0,
				"pending_qty": 0
			}

	for item_code, p in pending_map.items():
		delivered = delivered_map.get(item_code, 0)
		p["delivered_qty"] = delivered
		p["pending_qty"] = max(p["ordered_qty"] - delivered, 0)

	return pending_map


# =====================================================
# BULK PICK LIST
# =====================================================

@frappe.whitelist()
def create_bulk_pick_list(sales_orders, selected_items):
	if isinstance(sales_orders, str):
		sales_orders = frappe.parse_json(sales_orders)
	if isinstance(selected_items, str):
		selected_items = frappe.parse_json(selected_items)

	selected_items = selected_items or {}

	consolidated = defaultdict(lambda: {
		"qty": 0,
		"warehouse": None,
		"uom": None,
		"so_list": [],
		"so_detail": defaultdict(list),
	})

	so_items_data_map = _get_so_items_data(sales_orders)

	for so_name in sales_orders:
		so_selected = selected_items.get(so_name, [])
		if not so_selected:
			continue

		sel_map = {}
		for entry in so_selected:
			if isinstance(entry, dict):
				sel_map[entry["item_code"]] = float(entry.get("qty", 0))

		if not sel_map:
			continue

		so_warehouse = frappe.db.get_value("Sales Order", so_name, "set_warehouse") or ""

		so_items = frappe.db.get_all(
			"Sales Order Item",
			filters={"parent": so_name},
			fields=["name", "item_code", "warehouse", "uom", "stock_uom"],
		)
		so_item_map = {r.item_code: r for r in so_items}

		sub_items = so_items_data_map.get(so_name, [])
		sub_item_map = {(r.get("item_code") or r.item_code): r for r in sub_items}

		for item_code, qty in sel_map.items():
			if qty <= 0:
				continue

			warehouse = so_warehouse
			uom = "Nos"

			if item_code in so_item_map:
				row = so_item_map[item_code]
				warehouse = row.warehouse or so_warehouse
				uom = row.uom or row.stock_uom or "Nos"
			elif item_code in sub_item_map:
				warehouse = so_warehouse

			c = consolidated[item_code]
			c["qty"] += qty
			c["warehouse"] = c["warehouse"] or warehouse
			c["uom"] = c["uom"] or uom
			c["so_list"].append(so_name)

	if not consolidated:
		frappe.throw(_("No items found to create Pick List. Please select at least one item."))

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)

	pick_list = frappe.new_doc("Pick List")
	pick_list.purpose = "Delivery"
	pick_list.company = company
	pick_list.posting_date = nowdate()

	pick_list.custom_remarks = (
		"Bulk Pick List for: " + ", ".join(sales_orders[:10])
		+ (" ..." if len(sales_orders) > 10 else "")
	)

	items_summary = []

	for item_code, data in consolidated.items():
		qty = data["qty"]
		warehouse = data["warehouse"] or ""
		uom = data["uom"] or "Nos"
		so_list = list(dict.fromkeys(data["so_list"]))

		item_name = frappe.db.get_value("Item", item_code, "item_name") or item_code

		uom_conversion = frappe.db.get_value(
			"UOM Conversion Detail",
			{"parent": item_code, "uom": uom},
			"conversion_factor"
		) or 1.0

		pick_list.append("locations", {
			"item_code": item_code,
			"item_name": item_name,
			"qty": qty,
			"picked_qty": 0,
			"stock_qty": qty * uom_conversion,
			"uom": uom,
			"stock_uom": uom,
			"conversion_factor": uom_conversion,
			"warehouse": warehouse,
			"sales_order": so_list[0] if so_list else "",
		})

		items_summary.append({
			"item_code": item_code,
			"item_name": item_name,
			"total_qty": qty,
			"warehouse": warehouse,
			"uom": uom,
			"so_count": len(so_list),
			"so_list": so_list,
		})

	items_summary.sort(key=lambda x: x["total_qty"], reverse=True)

	try:
		pick_list.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Bulk Pick List Creation Failed",
			message=frappe.get_traceback()
		)
		frappe.throw(_("Failed to create Pick List. Check error logs for details."))

	return {
		"pick_list_name": pick_list.name,
		"total_items": len(items_summary),
		"total_qty": sum(i["total_qty"] for i in items_summary),
		"total_orders": len(sales_orders),
		"items": items_summary,
	}


# =====================================================
# SUB ITEM DELIVERY COUNTS (for list view JS)
# =====================================================

@frappe.whitelist()
def get_sub_item_delivery_counts(sales_orders):
	if isinstance(sales_orders, str):
		sales_orders = frappe.parse_json(sales_orders)

	if not sales_orders:
		return {}

	so_item_data = _get_so_items_data(sales_orders)
	so_item_map = {}
	all_items = set()

	for so_name, items in so_item_data.items():
		so_item_map.setdefault(so_name, {})
		for row in items:
			item_code = row.get("item_code") or row.item_code
			qty = row.get("qty") or row.qty or 0
			so_item_map[so_name][item_code] = (
				so_item_map[so_name].get(item_code, 0) + qty
			)
			all_items.add(item_code)

	all_items = list(all_items)
	if not all_items:
		return {so: {"total": 0, "delivered": 0} for so in sales_orders}

	std = frappe.db.sql("""
		SELECT dni.against_sales_order AS so, dni.item_code, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1
		  AND dni.against_sales_order IN %(sos)s
		  AND dni.item_code IN %(items)s
		GROUP BY dni.against_sales_order, dni.item_code
	""", {"sos": tuple(sales_orders), "items": tuple(all_items)}, as_dict=True)

	custom = []
	if _has_custom_dn_so_column():
		try:
			custom = frappe.db.sql("""
				SELECT dni.custom_custom_against_sales_order AS so, dni.item_code, SUM(dni.qty) AS qty
				FROM `tabDelivery Note Item` dni
				JOIN `tabDelivery Note` dn ON dn.name = dni.parent
				WHERE dn.docstatus = 1
				  AND dni.custom_custom_against_sales_order IN %(sos)s
				  AND dni.item_code IN %(items)s
				GROUP BY dni.custom_custom_against_sales_order, dni.item_code
			""", {"sos": tuple(sales_orders), "items": tuple(all_items)}, as_dict=True)
		except Exception:
			custom = []

	delivered_map = {}
	for row in std + custom:
		if not row.so:
			continue
		delivered_map.setdefault(row.so, {})
		delivered_map[row.so][row.item_code] = (
			delivered_map[row.so].get(row.item_code, 0) + (row.qty or 0)
		)

	result = {}
	for so in sales_orders:
		items = so_item_map.get(so, {})
		total = len(items)
		delivered = sum(
			1 for ic, oq in items.items()
			if delivered_map.get(so, {}).get(ic, 0) >= oq
		)
		result[so] = {"total": total, "delivered": delivered}

	return result


def on_delivery_note_submit(doc, method):
	"""Auto-update display status when DN is submitted or cancelled."""
	so_names = set()

	for item in doc.items:
		if item.get("against_sales_order"):
			so_names.add(item.against_sales_order)
		if item.get("custom_custom_against_sales_order"):
			so_names.add(item.custom_custom_against_sales_order)

	for so_name in so_names:
		try:
			_update_so_display_status(so_name)
		except Exception:
			frappe.log_error(
				title=f"Display Status Update Failed: {so_name}",
				message=frappe.get_traceback()
			)


def on_sales_order_cancel(doc, method):
	"""Set display status to Cancelled when SO is cancelled."""
	try:
		if frappe.db.has_column("Sales Order", "custom_display_status"):
			frappe.db.set_value(
				"Sales Order", doc.name,
				"custom_display_status", "Cancelled",
				update_modified=False
			)
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"Display Status Clear Failed: {doc.name}",
			message=frappe.get_traceback()
		)


def on_sales_order_submit(doc, method):
	"""Initialize display status when SO is submitted."""
	try:
		if doc.status not in ("To Deliver and Bill", "To Deliver"):
			return

		if frappe.db.has_column("Sales Order", "custom_display_status"):
			frappe.db.set_value(
				"Sales Order", doc.name,
				"custom_display_status", "Not Yet Delivered",
				update_modified=False
			)
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"SO Submit Hook Failed: {doc.name}",
			message=frappe.get_traceback()
		)


def on_sales_order_save(doc, method):
	_update_so_display_status(doc.name)