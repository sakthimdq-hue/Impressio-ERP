import json
import os
import re
import frappe
from frappe import _
import requests


def safe_flt(val, default=0.0):
	"""Safely converts numeric or string value to float, stripping currency symbols and formatting"""
	if val is None or val == "":
		return default
	if isinstance(val, (int, float)):
		return float(val)
	try:
		cleaned = str(val).replace("₹", "").replace("$", "").replace(",", "").strip()
		return float(cleaned) if cleaned else default
	except (ValueError, TypeError):
		return default


DEFAULT_PRODUCTS_API_URL = "https://impressiouat.mdqapps.online/api/external/products?api_key=ed4e1357e99a5b4a76151409d56744f8d9a03a5ac3d8f5b14285ea088b8971c9"
DEFAULT_QUOTATIONS_API_URL = "https://impressiouat.mdqapps.online/api/external/quotation?api_key=ed4e1357e99a5b4a76151409d56744f8d9a03a5ac3d8f5b14285ea088b8971c9"
DEFAULT_STUDENTS_API_URL = "https://impressiouat.mdqapps.online/api/external/students?api_key=ed4e1357e99a5b4a76151409d56744f8d9a03a5ac3d8f5b14285ea088b8971c9"
DEFAULT_ORDERS_API_URL = "https://impressiodemouat.mdqapps.online/api/external/orders?api_key=gde76gg34g347g34g6643g6734g6643"


def normalize_and_flatten_products(product_list, parent_bundle=None, parent_sub_bundle=None):
	"""
	Recursively flattens a list of products that may contain nested bundle_items.
	Assigns custom_parent_bundle and custom_parent_sub_bundle.
	Deduplicates products by item_code while keeping bundle hierarchies.
	"""
	if not product_list:
		return []

	extracted = []
	seen_codes = set()

	def _traverse(it, p_bundle, p_sub_bundle):
		if not isinstance(it, dict):
			return

		raw_code = (
			it.get("item_code")
			or it.get("code")
			or it.get("sku")
			or it.get("name")
			or (f"PROD-{it.get('product_id')}" if it.get("product_id") else (f"PROD-{it.get('id')}" if it.get("id") else ""))
		)
		raw_name = (
			it.get("website_display_name")
			or it.get("product_name")
			or it.get("name")
			or raw_code
		)
		category = (
			it.get("category_name")
			or it.get("category")
			or it.get("item_group")
			or "Garments"
		)
		tier = it.get("group_type_name") or it.get("tier") or ""

		# Calculate selling rate / MSP
		rate = safe_flt(
			it.get("standard_rate")
			if it.get("standard_rate") is not None
			else (
				it.get("calc_msp")
				if it.get("calc_msp") is not None
				else (
					it.get("incl_gst")
					if it.get("incl_gst") is not None
					else (
						it.get("landed_pricing_mrp")
						if it.get("landed_pricing_mrp") is not None
						else (it.get("msp") if it.get("msp") is not None else it.get("received_cost", 0.0))
					)
				)
			)
		)

		raw_gst = safe_flt(it.get("gst_rate") if it.get("gst_rate") is not None else it.get("gst_percent", 0.0))
		gst_pct = raw_gst * 100 if (0.0 < raw_gst < 1.0) else raw_gst

		img_url = it.get("image_url")
		if not img_url and it.get("image_urls") and isinstance(it.get("image_urls"), list) and len(it.get("image_urls")) > 0:
			img_url = it.get("image_urls")[0]

		is_bundle = 1 if it.get("is_bundle") else 0
		bundle_items = it.get("bundle_items") or []

		item_dict = {
			**it,
			"item_code": raw_code,
			"item_name": raw_name,
			"product_name": it.get("product_name") or raw_name,
			"website_display_name": it.get("website_display_name") or raw_name,
			"item_group": category,
			"category": category,
			"tier": tier,
			"standard_rate": rate,
			"calc_msp": rate,
			"gst_rate": round(gst_pct, 2),
			"gst_percent": round(gst_pct, 2),
			"image_url": img_url,
			"is_bundle": is_bundle,
			"bundle_items": bundle_items,
			"description": it.get("description") or raw_name,
			"custom_parent_bundle": p_bundle or "",
			"custom_parent_sub_bundle": p_sub_bundle or "",
			"custom_school_name": it.get("school_name") or "",
			"custom_grade": it.get("grade_name") or "",
		}

		if raw_code and raw_code not in seen_codes:
			seen_codes.add(raw_code)
			extracted.append(item_dict)
		elif raw_code:
			# Update parent info if already seen
			for ex in extracted:
				if ex.get("item_code") == raw_code:
					if p_bundle and not ex.get("custom_parent_bundle"):
						ex["custom_parent_bundle"] = p_bundle
					if p_sub_bundle and not ex.get("custom_parent_sub_bundle"):
						ex["custom_parent_sub_bundle"] = p_sub_bundle
					break

		# If bundle, recurse into bundle_items dynamically for any depth (N levels)
		if is_bundle and bundle_items:
			next_root = p_bundle if p_bundle else raw_code
			next_parent = raw_code

			for sub_it in bundle_items:
				if isinstance(sub_it, dict):
					sub_copy = dict(sub_it)
					if not sub_copy.get("school_name") and it.get("school_name"):
						sub_copy["school_name"] = it.get("school_name")
					if not sub_copy.get("grade_name") and it.get("grade_name"):
						sub_copy["grade_name"] = it.get("grade_name")
					_traverse(sub_copy, next_root, next_parent)

	for p in product_list:
		_traverse(p, parent_bundle, parent_sub_bundle)

	return extracted


def create_or_update_product_bundle(parent_item_code, bundle_items_list):
	"""
	Creates or updates ERPNext Product Bundle and BOM draft mapping for parent_item_code.
	ERPNext Product Bundle strictly requires parent item to be a non-stock item (is_stock_item == 0).
	For stock items (which Impressio kits/bundles are), BOM (Bill of Materials) is used.
	"""
	if not parent_item_code or not bundle_items_list:
		return

	is_stock = frappe.db.get_value("Item", parent_item_code, "is_stock_item")

	# 1. ERPNext Product Bundle (Only allowed for non-stock items in ERPNext)
	if not is_stock:
		try:
			if frappe.db.exists("Product Bundle", parent_item_code):
				pb = frappe.get_doc("Product Bundle", parent_item_code)
				pb.items = []
			else:
				pb = frappe.new_doc("Product Bundle")
				pb.new_item_code = parent_item_code

			for bi in bundle_items_list:
				if not isinstance(bi, dict):
					continue
				sub_code = (
					bi.get("item_code")
					or bi.get("code")
					or bi.get("sku")
					or bi.get("name")
					or (f"PROD-{bi.get('product_id')}" if bi.get("product_id") else (f"PROD-{bi.get('id')}" if bi.get("id") else ""))
				)
				sub_qty = safe_flt(bi.get("quantity") or 1, default=1.0)
				if sub_code and frappe.db.exists("Item", sub_code):
					pb.append("items", {
						"item_code": sub_code,
						"qty": sub_qty,
						"description": bi.get("description") or bi.get("product_name") or bi.get("name") or sub_code
					})

			if pb.items:
				pb.flags.ignore_permissions = True
				pb.flags.ignore_links = True
				pb.save()
		except Exception:
			pass

	# 2. Impressio BOM (Used for Stock Items and resolve_bom_tree in sales_helper)
	orig_mute = getattr(frappe.flags, "mute_messages", False)
	frappe.flags.mute_messages = True
	try:
		existing_bom = frappe.get_value("BOM", {"item": parent_item_code, "is_active": 1, "docstatus": ["!=", 2]}, "name")
		if existing_bom:
			bom = frappe.get_doc("BOM", existing_bom)
			bom.items = []
		else:
			bom = frappe.new_doc("BOM")
			bom.item = parent_item_code
			bom.quantity = 1
			bom.is_active = 1

		for bi in bundle_items_list:
			if not isinstance(bi, dict):
				continue
			sub_code = (
				bi.get("item_code")
				or bi.get("code")
				or bi.get("sku")
				or bi.get("name")
				or (f"PROD-{bi.get('product_id')}" if bi.get("product_id") else (f"PROD-{bi.get('id')}" if bi.get("id") else ""))
			)
			sub_qty = safe_flt(bi.get("quantity") or 1, default=1.0)
			if sub_code and frappe.db.exists("Item", sub_code):
				sub_rate = safe_flt(
					bi.get("received_cost")
					or bi.get("landed_pricing_cost_actual")
					or bi.get("calc_msp")
					or bi.get("rate")
					or 0.0
				)
				bom.append("items", {
					"item_code": sub_code,
					"qty": sub_qty,
					"rate": sub_rate,
				})

		if bom.items:
			bom.flags.ignore_permissions = True
			bom.flags.ignore_links = True
			bom.save()
	except Exception:
		pass
	finally:
		frappe.flags.mute_messages = orig_mute


@frappe.whitelist()
def fetch_pricing_from_api(api_url=None):
	"""
	Fetches live pricing/products JSON data from an external API endpoint.
	Handles:
	- products endpoint: {"data": {"products": [...]}}
	- direct list: [...]
	- items wrapper: {"items": [...]} or {"data": [...]}
	- orders wrapper: {"orders": [{"items": [...]}]}
	Never falls back to default json; raises error if keys changed.
	"""
	if not api_url:
		api_url = DEFAULT_PRODUCTS_API_URL

	api_url = str(api_url).strip()

	try:
		headers = {
			"User-Agent": "ERPNext-Impressio/1.0",
			"Accept": "application/json",
		}
		response = requests.get(api_url, timeout=25, headers=headers)
		response.raise_for_status()
		data = response.json()

		if isinstance(data, list):
			items = data
		elif isinstance(data, dict):
			if "data" in data and isinstance(data["data"], dict) and "products" in data["data"]:
				items = data["data"]["products"]
			elif "products" in data and isinstance(data["products"], list):
				items = data["products"]
			elif "items" in data and isinstance(data["items"], list):
				items = data["items"]
			elif "data" in data and isinstance(data["data"], list):
				items = data["data"]
			elif "result" in data and isinstance(data["result"], list):
				items = data["result"]
			elif "orders" in data and isinstance(data["orders"], list):
				order_items = []
				for ord in data["orders"]:
					if isinstance(ord, dict) and "items" in ord and isinstance(ord["items"], list):
						for it in ord["items"]:
							it_copy = dict(it)
							if not it_copy.get("product_name") and it_copy.get("website_display_name"):
								it_copy["product_name"] = it_copy["website_display_name"]
							order_items.append(it_copy)
				items = order_items
			elif "order" in data and isinstance(data["order"], dict):
				items = data["order"].get("items", [])
			elif "success" in data and not data.get("success"):
				frappe.throw(_("API Error: {0}").format(data.get("message") or "Request was not successful"))
			else:
				keys_str = ", ".join(data.keys())
				frappe.throw(_("API response format changed: Expected 'products', 'items', or 'orders', but received keys: {0}").format(keys_str))
		else:
			frappe.throw(_("Invalid API response format: Expected JSON object or array, received {0}").format(type(data).__name__))

		if not items:
			frappe.throw(_("No items found in the API response."))

		# Normalize fields and recursively unpack all nested bundle items
		normalized_items = normalize_and_flatten_products(items)

		return {
			"success": True,
			"count": len(normalized_items),
			"items": normalized_items,
			"api_url": api_url,
		}
	except requests.exceptions.RequestException as e:
		frappe.throw(_("Failed to fetch data from API: {0}").format(str(e)))
	except Exception as e:
		frappe.throw(_("Error parsing API response: {0}").format(str(e)))


@frappe.whitelist()
def import_pricing_from_api(api_url=None, items_data=None):
	"""
	Fetches items from the provided API URL (or uses pre-fetched items_data) and imports them into ERPNext.
	"""
	if not items_data and api_url:
		fetch_res = fetch_pricing_from_api(api_url)
		items_data = fetch_res.get("items", [])

	if not items_data and not api_url:
		fetch_res = fetch_pricing_from_api(DEFAULT_PRODUCTS_API_URL)
		items_data = fetch_res.get("items", [])

	return import_pricing_items(items_data=items_data)


@frappe.whitelist()
def read_uploaded_json_file(file_url):
	"""Reads and parses an uploaded JSON file from public/private files or File doc (kept for backward compatibility)"""
	if not file_url:
		return []

	clean_url = file_url.lstrip("/")
	paths_to_try = [
		frappe.get_site_path("public", clean_url),
		frappe.get_site_path(clean_url),
		os.path.join(frappe.get_site_path(), "public", "files", os.path.basename(file_url)),
		os.path.join(frappe.get_site_path(), "private", "files", os.path.basename(file_url)),
	]

	for p in paths_to_try:
		if os.path.exists(p):
			try:
				with open(p, "r", encoding="utf-8") as f:
					data = json.load(f)
					if isinstance(data, list):
						return data
					elif isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
						return data["items"]
			except Exception as e:
				frappe.log_error(title="Failed to parse JSON file", message=str(e))

	frappe.throw(_("Could not read uploaded JSON file: {0}").format(file_url))


@frappe.whitelist()
def import_pricing_items(items_data=None):
	"""
	Imports or updates items from pricing JSON data with resilient handling for missing/flexible fields.
	"""
	if not items_data:
		frappe.throw(_("No items data provided for import. Please check the API endpoint."))

	if isinstance(items_data, str):
		try:
			items_list = json.loads(items_data)
		except Exception as e:
			frappe.throw(_("Invalid JSON data: {0}").format(str(e)))
	elif isinstance(items_data, list):
		items_list = items_data
	elif isinstance(items_data, dict):
		if "items" in items_data and isinstance(items_data["items"], list):
			items_list = items_data["items"]
		elif "data" in items_data and isinstance(items_data["data"], list):
			items_list = items_data["data"]
		else:
			items_list = [items_data]
	else:
		frappe.throw(_("Invalid format for items data. Expected JSON string or array."))

	if not items_list:
		frappe.throw(_("Items list is empty."))

	# Flatten any nested bundle items if items_list contains raw unflattened items
	items_list = normalize_and_flatten_products(items_list)

	# 0. Ensure custom_parent_bundle and custom_parent_sub_bundle are Link fields in DB
	ensure_custom_fields_as_link()

	# 1. Ensure root Item Group and categories exist
	ensure_item_groups_and_uom(items_list)

	# 2. Import items
	created_count = 0
	updated_count = 0
	errors = []

	meta = frappe.get_meta("Item")

	for item in items_list:
		if not isinstance(item, dict):
			continue

		try:
			# Resilient item code identification
			raw_code = (
				item.get("item_code")
				or item.get("code")
				or item.get("sku")
				or item.get("item")
				or item.get("name")
				or ""
			)
			raw_name = (
				item.get("item_name")
				or item.get("website_display_name")
				or item.get("product_name")
				or item.get("name")
				or raw_code
			)

			tier = item.get("tier") or ""

			if not raw_code:
				if raw_name:
					# Generate standard code from name + tier
					base_slug = re.sub(r"[^A-Za-z0-9]+", "-", str(raw_name).strip()).strip("-").upper()
					tier_slug = f"-{tier.upper()}" if tier and tier.upper() not in base_slug else ""
					item_code = f"{base_slug}{tier_slug}"
				else:
					continue
			else:
				item_code = str(raw_code).strip()

			item_name = str(raw_name or item_code).strip()
			item_group = str(item.get("item_group") or item.get("group") or item.get("category") or "Garments").strip()
			stock_uom = str(item.get("stock_uom") or item.get("uom") or item.get("unit") or "Nos").strip()

			# Selling standard rate (MSP) cascade
			standard_rate = safe_flt(
				item.get("standard_rate")
				if item.get("standard_rate") is not None
				else (
					item.get("msp")
					if item.get("msp") is not None
					else (
						item.get("calc_msp")
						if item.get("calc_msp") is not None
						else (
							item.get("price_incl_gst")
							if item.get("price_incl_gst") is not None
							else (item.get("mrp") if item.get("mrp") is not None else item.get("rate", 0))
						)
					)
				)
			)

			# Cost / Valuation rate cascade
			raw_cost = (
				item.get("valuation_rate")
				if item.get("valuation_rate") is not None
				else (
					item.get("received_cost")
					if item.get("received_cost") is not None
					else (
						item.get("landed_pricing_cost_actual")
						if item.get("landed_pricing_cost_actual") is not None
						else (
							item.get("effective_base_cost")
							if item.get("effective_base_cost") is not None
							else (
								item.get("build_cost")
								if item.get("build_cost") is not None
								else (item.get("landed_cost") if item.get("landed_cost") is not None else item.get("cost", 0))
							)
						)
					)
				)
			)
			valuation_rate = safe_flt(raw_cost)

			landed_cost = safe_flt(
				item.get("landed_cost")
				if item.get("landed_cost") is not None
				else (
					item.get("landed_pricing_cost_actual")
					if item.get("landed_pricing_cost_actual") is not None
					else item.get("received_cost")
				)
			)
			build_cost = safe_flt(
				item.get("build_cost")
				if item.get("build_cost") is not None
				else (
					item.get("effective_base_cost")
					if item.get("effective_base_cost") is not None
					else item.get("received_cost")
				)
			)
			operational_cost = safe_flt(item.get("operational_cost") or item.get("otc_per_unit") or item.get("op_cost"))
			gst_rate = safe_flt(item.get("gst_rate"))
			mrp = safe_flt(item.get("mrp") if item.get("mrp") is not None else item.get("landed_pricing_mrp"))

			# Description fallback
			description = item.get("description")
			if not description:
				desc_parts = [item_name]
				if tier:
					desc_parts.append(f"({tier} Tier)")
				if landed_cost:
					desc_parts.append(f"Landed: ₹{landed_cost}")
				if build_cost:
					desc_parts.append(f"Build: ₹{build_cost}")
				if standard_rate:
					desc_parts.append(f"MSP: ₹{standard_rate}")
				if gst_rate:
					desc_parts.append(f"GST: {gst_rate}%")
				description = " | ".join(desc_parts)

			# Stock & Sales flags
			is_stock_item = 1 if item.get("is_stock_item") is None else (1 if item.get("is_stock_item") else 0)
			is_sales_item = 1 if item.get("is_sales_item") is None else (1 if item.get("is_sales_item") else 0)
			is_purchase_item = 1 if item.get("is_purchase_item") is None else (1 if item.get("is_purchase_item") else 0)

			# GST HSN Code
			gst_hsn = item.get("gst_hsn_code") or get_valid_hsn_for_item(item_group)

			item_values = {
				"item_name": item_name,
				"item_group": item_group,
				"stock_uom": stock_uom,
				"standard_rate": standard_rate,
				"valuation_rate": valuation_rate,
				"description": description,
				"is_stock_item": is_stock_item,
				"is_sales_item": is_sales_item,
				"is_purchase_item": is_purchase_item,
			}

			# Check standard / custom fields on Item DocType dynamically
			if meta.has_field("gst_hsn_code") and gst_hsn:
				item_values["gst_hsn_code"] = gst_hsn

			if meta.has_field("tier") and tier:
				item_values["tier"] = tier
			elif meta.has_field("custom_tier") and tier:
				item_values["custom_tier"] = tier

			if meta.has_field("custom_parent_bundle") and item.get("custom_parent_bundle"):
				item_values["custom_parent_bundle"] = item.get("custom_parent_bundle")

			if meta.has_field("custom_parent_sub_bundle") and item.get("custom_parent_sub_bundle"):
				item_values["custom_parent_sub_bundle"] = item.get("custom_parent_sub_bundle")

			if meta.has_field("custom_school_name") and item.get("custom_school_name"):
				resolved_school = ensure_school(item.get("custom_school_name"))
				if resolved_school:
					item_values["custom_school_name"] = resolved_school

			if meta.has_field("custom_grade") and item.get("custom_grade"):
				resolved_grade = ensure_grade(item.get("custom_grade"))
				if resolved_grade:
					item_values["custom_grade"] = resolved_grade

			if meta.has_field("custom_landed_cost") and landed_cost:
				item_values["custom_landed_cost"] = landed_cost

			if meta.has_field("custom_build_cost") and build_cost:
				item_values["custom_build_cost"] = build_cost

			if meta.has_field("custom_operational_cost") and operational_cost:
				item_values["custom_operational_cost"] = operational_cost

			if meta.has_field("custom_gst_rate") and gst_rate:
				item_values["custom_gst_rate"] = gst_rate

			if meta.has_field("custom_mrp") and mrp is not None:
				item_values["custom_mrp"] = mrp

			if frappe.db.exists("Item", item_code):
				# Update existing item
				doc = frappe.get_doc("Item", item_code)
				doc.update(item_values)
				doc.flags.ignore_permissions = True
				doc.flags.ignore_links = True
				doc.save()
				updated_count += 1
			else:
				# Create new item
				doc = frappe.get_doc({
					"doctype": "Item",
					"item_code": item_code,
					**item_values
				})
				doc.flags.ignore_permissions = True
				doc.flags.ignore_links = True
				doc.insert()
				created_count += 1

			# Update / Create Item Price for Standard Selling if price list exists
			if standard_rate > 0:
				update_item_price(item_code, standard_rate, stock_uom)

		except Exception as e:
			frappe.log_error(title=f"Error importing item {item.get('item_code')}", message=frappe.get_traceback())
			errors.append(f"{item.get('item_code') or 'Unknown'}: {str(e)}")

	frappe.db.commit()

	# 3. Create or update Product Bundle & BOM mappings for all bundles once items exist
	for item in items_list:
		if not isinstance(item, dict):
			continue
		if item.get("is_bundle") and item.get("bundle_items"):
			b_code = (
				item.get("item_code")
				or item.get("code")
				or item.get("sku")
				or item.get("item")
				or item.get("name")
				or ""
			)
			if b_code:
				try:
					create_or_update_product_bundle(str(b_code).strip(), item.get("bundle_items"))
				except Exception as be:
					frappe.log_error(title=f"Error creating bundle mapping for {b_code}", message=str(be))

	frappe.db.commit()

	return {
		"success": True,
		"total": len(items_list),
		"created": created_count,
		"updated": updated_count,
		"errors": errors,
		"message": _("Successfully imported {0} items ({1} created, {2} updated).").format(
			created_count + updated_count, created_count, updated_count
		),
	}


def ensure_custom_fields_as_link():
	"""Ensures custom_parent_bundle and custom_parent_sub_bundle are configured as Link to Item in DB."""
	try:
		changed = False
		for fieldname in ["custom_parent_bundle", "custom_parent_sub_bundle"]:
			cf_name = f"Item-{fieldname}"
			if frappe.db.exists("Custom Field", cf_name):
				fieldtype = frappe.db.get_value("Custom Field", cf_name, "fieldtype")
				options = frappe.db.get_value("Custom Field", cf_name, "options")
				if fieldtype != "Link" or options != "Item":
					frappe.db.set_value("Custom Field", cf_name, "fieldtype", "Link")
					frappe.db.set_value("Custom Field", cf_name, "options", "Item")
					changed = True
		if changed:
			frappe.clear_cache(doctype="Item")
	except Exception:
		pass


def ensure_school(school_name, school_code=None):
	"""Resolves or auto-creates School DocType record, returning the primary key (name)."""
	if not school_name:
		return ""
	school_name = str(school_name).strip()

	try:
		if not frappe.db.exists("DocType", "School"):
			return school_name

		# 1. Exact match by primary key (name)
		if frappe.db.exists("School", school_name):
			return school_name

		# 2. Match by school_name field
		name = frappe.db.get_value("School", {"school_name": school_name}, "name")
		if name:
			return name

		# 3. Partial / LIKE match on name
		name = frappe.db.get_value("School", {"name": ["like", f"%{school_name}%"]}, "name")
		if name:
			return name

		# 4. Auto-create if not exists
		if not school_code:
			words = [w for w in re.split(r"[^A-Za-z0-9]+", school_name) if w]
			if len(words) >= 2:
				school_code = "".join(w[0] for w in words).upper()
			else:
				school_code = school_name[:4].upper()

		base_code = school_code
		c = 1
		while frappe.db.exists("School", {"school_code": school_code}):
			school_code = f"{base_code}{c}"
			c += 1

		new_school = frappe.get_doc({
			"doctype": "School",
			"school_code": school_code,
			"school_name": school_name,
			"status": "Active",
		})
		new_school.flags.ignore_permissions = True
		new_school.flags.ignore_links = True
		new_school.insert()
		return new_school.name
	except Exception as e:
		frappe.log_error(title=f"Could not auto-create School {school_name}", message=str(e))
		return ""


def ensure_grade(grade_name):
	"""Resolves or auto-creates Grade DocType record, returning the primary key (name)."""
	if not grade_name:
		return ""
	grade_name = str(grade_name).strip()

	try:
		if not frappe.db.exists("DocType", "Grade"):
			return grade_name

		# 1. Exact match by primary key (name)
		if frappe.db.exists("Grade", grade_name):
			return grade_name

		# 2. Match by grade_name field
		name = frappe.db.get_value("Grade", {"grade_name": grade_name}, "name")
		if name:
			return name

		# 3. Partial match
		name = frappe.db.get_value("Grade", {"name": ["like", f"%{grade_name}%"]}, "name")
		if name:
			return name

		# 4. Auto-create if not exists
		new_grade = frappe.get_doc({
			"doctype": "Grade",
			"grade_name": grade_name,
			"grade_code": grade_name,
			"status": "Active",
		})
		new_grade.flags.ignore_permissions = True
		new_grade.flags.ignore_links = True
		new_grade.insert()
		return new_grade.name
	except Exception as e:
		frappe.log_error(title=f"Could not auto-create Grade {grade_name}", message=str(e))
		return ""


def ensure_item_groups_and_uom(items_list):
	"""Ensures UOM 'Nos' and required Item Groups exist"""
	# 1. Ensure UOM 'Nos'
	if not frappe.db.exists("UOM", "Nos"):
		try:
			uom_doc = frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"})
			uom_doc.insert(ignore_permissions=True)
		except Exception:
			pass

	# 2. Find root item group
	root_group = "All Item Groups"
	if not frappe.db.exists("Item Group", root_group):
		groups = frappe.get_all("Item Group", filters={"is_group": 1}, limit=1)
		if groups:
			root_group = groups[0].name
		else:
			try:
				root = frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": "All Item Groups",
						"is_group": 1,
					}
				)
				root.insert(ignore_permissions=True)
				root_group = "All Item Groups"
			except Exception:
				pass

	# 3. Create missing item groups
	item_groups = set(
		(item.get("item_group") or item.get("group") or item.get("category") or "Garments").strip()
		for item in items_list
		if isinstance(item, dict) and (item.get("item_group") or item.get("group") or item.get("category"))
	)
	for ig in item_groups:
		if ig and not frappe.db.exists("Item Group", ig):
			try:
				ig_doc = frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": ig,
						"parent_item_group": root_group,
						"is_group": 0,
					}
				)
				ig_doc.insert(ignore_permissions=True)
			except Exception:
				pass


def update_item_price(item_code, price_rate, uom="Nos", price_list=None):
	"""Creates or updates standard selling item price safely without throwing duplicate errors"""
	price_rate = safe_flt(price_rate)
	if price_rate <= 0:
		return

	if not price_list:
		price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"

	if not frappe.db.exists("Price List", price_list):
		return

	existing_price = frappe.db.get_value(
		"Item Price", {"item_code": item_code, "price_list": price_list}, "name"
	)
	if existing_price:
		frappe.db.set_value("Item Price", existing_price, "price_list_rate", price_rate)
		return

	try:
		ip_doc = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item_code,
				"price_list": price_list,
				"price_list_rate": price_rate,
				"uom": uom or "Nos",
				"selling": 1,
			}
		)
		ip_doc.flags.ignore_permissions = True
		ip_doc.flags.ignore_mandatory = True
		ip_doc.insert()
	except Exception:
		frappe.clear_messages()



DEFAULT_HSN_MAP = {
	"Garments": "620300",
	"Accessories": "611599",
	"Notebooks": "482010",
	"Textbooks": "490110",
	"Stationery": "960810",
	"Print Accessories": "491199",
}


def get_valid_hsn_for_item(item_group):
	"""Returns a valid HSN Code from the GST HSN Code doctype"""
	prefix = DEFAULT_HSN_MAP.get(item_group, "6203")

	if frappe.db.exists("GST HSN Code", prefix):
		return prefix

	# Search for matching HSN code starting with prefix
	matching = frappe.db.get_value("GST HSN Code", {"name": ["like", f"{prefix[:4]}%"]}, "name")
	if matching:
		return matching

	# Fallback to any existing HSN code in database
	fallback = frappe.db.get_value("GST HSN Code", {}, "name")
	return fallback or "620300"


@frappe.whitelist()
def create_quotation_from_api(quotation_to="Customer", party_name=None, items_data=None, api_url=None, company=None):
	"""
	Creates a new Quotation from API pricing items.
	"""
	if not items_data and api_url:
		fetch_res = fetch_pricing_from_api(api_url)
		items_data = fetch_res.get("items", [])

	if isinstance(items_data, str):
		try:
			items_data = json.loads(items_data)
		except Exception as e:
			frappe.throw(_("Invalid items data: {0}").format(str(e)))

	if not items_data:
		frappe.throw(_("No items selected for Quotation."))

	# 1. Ensure all items are in Item Master
	import_pricing_items(items_data)

	# 2. Get default party if not provided
	if not party_name:
		parties = frappe.get_all(quotation_to, limit=1, fields=["name"])
		if parties:
			party_name = parties[0].name
		else:
			frappe.throw(_("Please select a valid {0} first.").format(quotation_to))

	# 3. Get default company
	if not company:
		company = (
			frappe.defaults.get_user_default("company")
			or frappe.db.get_single_value("Global Defaults", "default_company")
			or (frappe.get_all("Company", limit=1)[0].name if frappe.get_all("Company", limit=1) else None)
		)

	quotation = frappe.new_doc("Quotation")
	quotation.quotation_to = quotation_to
	quotation.party_name = party_name
	if company:
		quotation.company = company
		company_addr = get_or_create_company_address(company)
		if company_addr:
			quotation.company_address = company_addr
			comp_gstin = frappe.db.get_value("Address", company_addr, "gstin")
			if comp_gstin:
				quotation.company_gstin = comp_gstin

	if quotation_to == "Customer" and party_name:
		customer_addr = get_or_create_customer_address(party_name)
		if customer_addr:
			quotation.customer_address = customer_addr
			cust_gstin = frappe.db.get_value("Address", customer_addr, "gstin")
			if cust_gstin:
				quotation.billing_address_gstin = cust_gstin

	quotation.transaction_date = frappe.utils.today()
	quotation.valid_till = frappe.utils.add_days(frappe.utils.today(), 30)
	quotation.order_type = "Sales"

	for it in items_data:
		if not isinstance(it, dict):
			continue

		raw_code = it.get("item_code") or it.get("code") or it.get("sku") or ""
		raw_name = it.get("item_name") or it.get("product_name") or raw_code
		tier = it.get("tier") or ""

		if not raw_code:
			if raw_name:
				base_slug = re.sub(r"[^A-Za-z0-9]+", "-", str(raw_name).strip()).strip("-").upper()
				tier_slug = f"-{tier.upper()}" if tier and tier.upper() not in base_slug else ""
				item_code = f"{base_slug}{tier_slug}"
			else:
				continue
		else:
			item_code = str(raw_code).strip()

		item_name = str(raw_name or item_code).strip()
		qty = safe_flt(it.get("qty") or 1, default=1.0)
		rate = safe_flt(
			it.get("rate")
			if it.get("rate") is not None
			else (
				it.get("standard_rate")
				if it.get("standard_rate") is not None
				else (
					it.get("msp")
					if it.get("msp") is not None
					else (
						it.get("calc_msp")
						if it.get("calc_msp") is not None
						else (it.get("price_incl_gst") if it.get("price_incl_gst") is not None else 0)
					)
				)
			)
		)
		stock_uom = str(it.get("stock_uom") or it.get("uom") or "Nos").strip()
		description = it.get("description") or item_name

		quotation.append("items", {
			"item_code": item_code,
			"item_name": item_name,
			"qty": qty,
			"rate": rate,
			"price_list_rate": rate,
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"description": description,
		})

	quotation.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"success": True,
		"quotation_name": quotation.name,
		"items_count": len(items_data),
		"message": _("Quotation {0} created with {1} items.").format(quotation.name, len(items_data)),
	}


@frappe.whitelist()
def fetch_quotations_from_api(api_url=None):
	"""
	Fetches live quotations list from the external API endpoint.
	Checks against ERPNext database to mark which quotations are already imported.
	"""
	if not api_url:
		api_url = DEFAULT_QUOTATIONS_API_URL

	api_url = str(api_url).strip()

	try:
		headers = {
			"User-Agent": "ERPNext-Impressio/1.0",
			"Accept": "application/json",
		}
		response = requests.get(api_url, timeout=25, headers=headers)
		response.raise_for_status()
		data = response.json()

		quotations = []
		if isinstance(data, dict):
			if "data" in data and isinstance(data["data"], dict) and "quotations" in data["data"]:
				quotations = data["data"]["quotations"]
			elif "quotations" in data and isinstance(data["quotations"], list):
				quotations = data["quotations"]
			elif "data" in data and isinstance(data["data"], list):
				quotations = data["data"]
			elif "items" in data and isinstance(data["items"], list):
				quotations = data["items"]
		elif isinstance(data, list):
			quotations = data

		# Enrich with ERPNext import status
		imported_count = 0
		for q in quotations:
			qid = q.get("id")
			qnum = q.get("quote_number")
			existing = None
			if qid:
				existing = frappe.db.get_value("Quotation", {"custom_external_quote_id": qid}, ["name", "status", "docstatus"], as_dict=True)
			if not existing and qnum:
				existing = frappe.db.get_value("Quotation", {"custom_quote_number": qnum}, ["name", "status", "docstatus"], as_dict=True)

			if existing:
				q["is_imported"] = True
				q["erpnext_quotation"] = existing.name
				q["erpnext_status"] = existing.status
				imported_count += 1
			else:
				q["is_imported"] = False
				q["erpnext_quotation"] = None
				q["erpnext_status"] = None

		return {
			"success": True,
			"total": len(quotations),
			"imported_count": imported_count,
			"new_count": len(quotations) - imported_count,
			"quotations": quotations,
			"api_url": api_url,
		}
	except requests.exceptions.RequestException as e:
		frappe.throw(_("Failed to fetch quotations from API: {0}").format(str(e)))
	except Exception as e:
		frappe.throw(_("Error parsing quotations API response: {0}").format(str(e)))


@frappe.whitelist()
def fetch_quotation_details(quote_id, api_url=None):
	"""
	Fetches full details including line items for a specific quotation ID.
	"""
	if not quote_id:
		frappe.throw(_("Quote ID is required."))

	if not api_url:
		api_url = DEFAULT_QUOTATIONS_API_URL

	api_url = str(api_url).strip()

	# Construct detail URL by inserting /{quote_id} before query params
	if "?" in api_url:
		base, qs = api_url.split("?", 1)
		detail_url = f"{base.rstrip('/')}/{quote_id}?{qs}"
	else:
		detail_url = f"{api_url.rstrip('/')}/{quote_id}"

	try:
		headers = {
			"User-Agent": "ERPNext-Impressio/1.0",
			"Accept": "application/json",
		}
		response = requests.get(detail_url, timeout=25, headers=headers)
		response.raise_for_status()
		data = response.json()

		quote_data = data.get("data", {}) if isinstance(data, dict) else {}
		return {
			"success": True,
			"data": quote_data,
		}
	except Exception as e:
		frappe.throw(_("Failed to fetch quotation details for ID {0}: {1}").format(quote_id, str(e)))


def get_or_create_customer(quote_data):
	"""
	Finds existing Customer or creates new Customer in ERPNext from external quotation data.
	Also creates Address if address details are present.
	"""
	customer_name = (
		quote_data.get("customer_name")
		or quote_data.get("school_name")
		or "External Customer"
	).strip()

	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if existing:
		return existing

	# Create new customer
	default_cg = (
		frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		or frappe.db.get_value("Customer Group", {}, "name")
		or "All Customer Groups"
	)
	default_terr = (
		frappe.db.get_value("Territory", {"is_group": 0}, "name")
		or frappe.db.get_value("Territory", {}, "name")
		or "All Territories"
	)

	cust = frappe.new_doc("Customer")
	cust.customer_name = customer_name
	cust.customer_group = default_cg
	cust.territory = default_terr
	cust.customer_type = "Company"
	if quote_data.get("customer_phone"):
		cust.mobile_no = str(quote_data.get("customer_phone")).strip()
	if quote_data.get("customer_email"):
		cust.email_id = str(quote_data.get("customer_email")).strip()

	cust.flags.ignore_permissions = True
	cust.insert()

	# Create Address linked to Customer if address details exist
	address_line1 = quote_data.get("customer_address")
	city = quote_data.get("city")
	state = quote_data.get("state")
	pincode = quote_data.get("pincode")
	if address_line1 or city or state or pincode:
		try:
			addr = frappe.new_doc("Address")
			addr.address_title = customer_name
			addr.address_type = "Billing"
			addr.address_line1 = address_line1 or (city or "Main Address")
			addr.city = city or "Bengaluru"
			addr.state = state or "Karnataka"
			addr.pincode = str(pincode or "")
			addr.country = quote_data.get("country") or "India"
			if quote_data.get("customer_phone"):
				addr.phone = str(quote_data.get("customer_phone")).strip()
			if quote_data.get("customer_email"):
				addr.email_id = str(quote_data.get("customer_email")).strip()
			addr.append("links", {
				"link_doctype": "Customer",
				"link_name": cust.name,
			})
			addr.flags.ignore_permissions = True
			addr.insert()
		except Exception:
			pass

	return cust.name


def get_state_info_from_gstin(gstin):
	"""
	Returns (state_name, city_name) based on the first 2 digits of an Indian GSTIN.
	This ensures India Compliance's validate_state passes without error.
	"""
	state_code_map = {
		"01": ("Jammu and Kashmir", "Srinagar"),
		"02": ("Himachal Pradesh", "Shimla"),
		"03": ("Punjab", "Chandigarh"),
		"04": ("Chandigarh", "Chandigarh"),
		"05": ("Uttarakhand", "Dehradun"),
		"06": ("Haryana", "Gurugram"),
		"07": ("Delhi", "New Delhi"),
		"08": ("Rajasthan", "Jaipur"),
		"09": ("Uttar Pradesh", "Noida"),
		"10": ("Bihar", "Patna"),
		"11": ("Sikkim", "Gangtok"),
		"12": ("Arunachal Pradesh", "Itanagar"),
		"13": ("Nagaland", "Kohima"),
		"14": ("Manipur", "Imphal"),
		"15": ("Mizoram", "Aizawl"),
		"16": ("Tripura", "Agartala"),
		"17": ("Meghalaya", "Shillong"),
		"18": ("Assam", "Guwahati"),
		"19": ("West Bengal", "Kolkata"),
		"20": ("Jharkhand", "Ranchi"),
		"21": ("Odisha", "Bhubaneswar"),
		"22": ("Chhattisgarh", "Raipur"),
		"23": ("Madhya Pradesh", "Bhopal"),
		"24": ("Gujarat", "Ahmedabad"),
		"26": ("Dadra and Nagar Haveli and Daman and Diu", "Daman"),
		"27": ("Maharashtra", "Mumbai"),
		"29": ("Karnataka", "Bengaluru"),
		"30": ("Goa", "Panaji"),
		"31": ("Lakshadweep Islands", "Kavaratti"),
		"32": ("Kerala", "Kochi"),
		"33": ("Tamil Nadu", "Chennai"),
		"34": ("Puducherry", "Puducherry"),
		"35": ("Andaman and Nicobar Islands", "Port Blair"),
		"36": ("Telangana", "Hyderabad"),
		"37": ("Andhra Pradesh", "Vijayawada"),
		"38": ("Ladakh", "Leh"),
	}
	if gstin and len(str(gstin).strip()) >= 2:
		code = str(gstin).strip()[:2]
		if code in state_code_map:
			return state_code_map[code]
	return "Tamil Nadu", "Chennai"


def get_or_create_customer_address(customer_name, quote_data=None):
	"""
	Returns the customer's billing address name, creating/linking if needed.
	"""
	if not customer_name:
		return None

	from frappe.contacts.doctype.address.address import get_default_address

	addr_name = get_default_address("Customer", customer_name)
	if not addr_name:
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Address"},
			"parent",
		)

	if not addr_name and quote_data:
		try:
			cust_gstin = quote_data.get("gstin") or quote_data.get("customer_gstin")
			cust_state = quote_data.get("state")
			cust_city = quote_data.get("city")
			if cust_gstin:
				state_from_gstin, city_from_gstin = get_state_info_from_gstin(cust_gstin)
				cust_state = cust_state or state_from_gstin
				cust_city = cust_city or city_from_gstin

			addr = frappe.new_doc("Address")
			addr.address_title = customer_name
			addr.address_type = "Billing"
			addr.is_primary_address = 1
			addr.address_line1 = quote_data.get("customer_address") or cust_city or "Main Address"
			addr.city = cust_city or "Bengaluru"
			addr.state = cust_state or "Karnataka"
			addr.pincode = str(quote_data.get("pincode") or "")
			addr.country = quote_data.get("country") or "India"
			if cust_gstin:
				addr.gstin = str(cust_gstin).strip()
			if quote_data.get("customer_phone"):
				addr.phone = str(quote_data.get("customer_phone")).strip()
			if quote_data.get("customer_email"):
				addr.email_id = str(quote_data.get("customer_email")).strip()
			addr.append("links", {
				"link_doctype": "Customer",
				"link_name": customer_name,
			})
			addr.flags.ignore_permissions = True
			addr.insert(ignore_permissions=True)
			addr_name = addr.name
		except Exception:
			frappe.log_error(title="Failed to auto-create customer address", message=frappe.get_traceback())
			addr_name = None

	return addr_name


def get_or_create_company_address(company):
	"""
	Returns the company's billing address name, creating a default one if none exists.
	This ensures India Compliance GST validations pass without throwing 'Please set Company Address Name'
	or 'Company Address Name does not belong to the Company ...'.
	"""
	if not company:
		return None

	from frappe.contacts.doctype.address.address import get_default_address

	# 1. Standard default address for Company
	addr_name = get_default_address("Company", company)

	# 2. Check Dynamic Link for this company
	if not addr_name:
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
			"parent",
		)

	# 3. If found and exists, return it
	if addr_name and frappe.db.exists("Address", addr_name):
		return addr_name

	# 4. Check if an address with company title already exists and ensure Dynamic Link is attached
	existing_addr = frappe.db.get_value("Address", {"address_title": company}, "name")
	if existing_addr:
		if not frappe.db.exists("Dynamic Link", {"link_doctype": "Company", "link_name": company, "parent": existing_addr}):
			try:
				dlink = frappe.new_doc("Dynamic Link")
				dlink.parent = existing_addr
				dlink.parenttype = "Address"
				dlink.parentfield = "links"
				dlink.link_doctype = "Company"
				dlink.link_name = company
				dlink.flags.ignore_permissions = True
				dlink.insert(ignore_permissions=True)
			except Exception:
				pass
		return existing_addr

	# 5. Create default company address with matching State and GSTIN
	try:
		comp_doc = frappe.get_doc("Company", company) if frappe.db.exists("Company", company) else None
		gstin = None
		if comp_doc:
			gstin = getattr(comp_doc, "gstin", None) or getattr(comp_doc, "tax_id", None)

		state_name, city_name = get_state_info_from_gstin(gstin)

		addr = frappe.new_doc("Address")
		addr.address_title = company
		addr.address_type = "Billing"
		addr.is_your_company_address = 1
		addr.is_primary_address = 1
		addr.address_line1 = "Registered Office"
		addr.city = city_name
		addr.state = state_name
		addr.country = (comp_doc.country if comp_doc and getattr(comp_doc, "country", None) else "India")

		if gstin:
			addr.gstin = str(gstin).strip()

		addr.append("links", {
			"link_doctype": "Company",
			"link_name": company,
		})
		addr.flags.ignore_permissions = True
		addr.flags.ignore_mandatory = True
		addr.insert(ignore_permissions=True)
		addr_name = addr.name
	except Exception:
		frappe.log_error(title="Failed to auto-create company address", message=frappe.get_traceback())
		addr_name = None

	return addr_name



def get_or_create_item_for_quote_product(prod):
	"""
	Finds existing Item or creates new Item in ERPNext from quote product data.
	"""
	prod_name = str(prod.get("product_name") or prod.get("name") or "Product").strip()
	prod_id = prod.get("product_id") or prod.get("id")
	category = prod.get("product_category_name") or prod.get("category_name") or "Garments"
	rate = safe_flt(
		prod.get("unit_price")
		if prod.get("unit_price") is not None
		else (
			prod.get("product_mrp")
			if prod.get("product_mrp") is not None
			else prod.get("final_unit_price", 0.0)
		)
	)

	# 1. Look for existing item by name
	existing_by_name = frappe.db.get_value("Item", {"item_name": prod_name}, "name")
	if existing_by_name:
		return existing_by_name

	# 2. Check by slug
	base_slug = re.sub(r"[^A-Za-z0-9]+", "-", prod_name).strip("-").upper()
	if not base_slug:
		base_slug = f"PROD-{prod_id}" if prod_id else "ITEM"
	if len(base_slug) > 100:
		base_slug = base_slug[:100].rstrip("-")

	if frappe.db.exists("Item", base_slug):
		return base_slug

	# 3. Create Item
	ensure_item_groups_and_uom([{"item_group": category}])
	gst_hsn = get_valid_hsn_for_item(category)

	item = frappe.new_doc("Item")
	item.item_code = base_slug
	item.item_name = prod_name
	item.item_group = category if frappe.db.exists("Item Group", category) else "All Item Groups"
	item.stock_uom = "Nos"
	item.is_stock_item = 1
	item.is_sales_item = 1
	item.standard_rate = rate
	item.description = prod.get("product_description") or prod_name

	meta = frappe.get_meta("Item")
	if meta.has_field("gst_hsn_code") and gst_hsn:
		item.gst_hsn_code = gst_hsn

	item.flags.ignore_permissions = True
	item.insert()

	# Create or update Item Price safely without duplicate errors
	update_item_price(item.name, rate, uom="Nos")

	return item.name


def get_or_create_placeholder_item():
	"""Ensures a fallback generic item exists for quotations with 0 line items"""
	code = "QUOTATION-CUSTOM-ITEM"
	if frappe.db.exists("Item", code):
		return code
	ensure_item_groups_and_uom([{"item_group": "Garments"}])
	gst_hsn = get_valid_hsn_for_item("Garments")
	item = frappe.new_doc("Item")
	item.item_code = code
	item.item_name = "Quotation Custom Item"
	item.item_group = "Garments"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.description = "Custom items as per external quotation"
	meta = frappe.get_meta("Item")
	if meta.has_field("gst_hsn_code") and gst_hsn:
		item.gst_hsn_code = gst_hsn
	item.flags.ignore_permissions = True
	item.insert()
	return code


def create_or_update_erpnext_quotation(quote_data, company=None):
	"""
	Creates or updates a Quotation document in ERPNext from external quotation data dictionary.
	Returns (quotation.name, is_new: bool).
	"""
	if not company:
		company = (
			frappe.defaults.get_user_default("company")
			or frappe.db.get_single_value("Global Defaults", "default_company")
			or frappe.db.get_value("Company", {}, "name")
			or "Impressio"
		)

	customer_name = get_or_create_customer(quote_data)
	qid = quote_data.get("id")
	qnumber = quote_data.get("quote_number")

	existing_name = None
	if qid:
		existing_name = frappe.db.get_value("Quotation", {"custom_external_quote_id": qid}, "name")
	if not existing_name and qnumber:
		existing_name = frappe.db.get_value("Quotation", {"custom_quote_number": qnumber}, "name")

	if existing_name:
		quotation = frappe.get_doc("Quotation", existing_name)
		is_new = False
	else:
		quotation = frappe.new_doc("Quotation")
		is_new = True

	quotation.quotation_to = "Customer"
	quotation.party_name = customer_name
	quotation.company = company
	quotation.transaction_date = quote_data.get("date") or frappe.utils.today()
	quotation.valid_till = frappe.utils.add_days(quotation.transaction_date, 30)
	quotation.order_type = "Sales"

	# Set Company Address & GSTIN for India Compliance
	company_addr = get_or_create_company_address(company)
	if company_addr:
		quotation.company_address = company_addr
		comp_gstin = frappe.db.get_value("Address", company_addr, "gstin")
		if comp_gstin:
			quotation.company_gstin = comp_gstin

	# Set Customer Address & GSTIN
	customer_addr = get_or_create_customer_address(customer_name, quote_data)
	if customer_addr:
		quotation.customer_address = customer_addr
		cust_gstin = frappe.db.get_value("Address", customer_addr, "gstin")
		if cust_gstin:
			quotation.billing_address_gstin = cust_gstin


	# Set custom fields
	quotation.custom_quote_number = qnumber
	quotation.custom_external_quote_id = qid
	quotation.custom_school_name = quote_data.get("school_name") or quote_data.get("customer_name")
	quotation.custom_academic_year = quote_data.get("academic_year")
	quotation.custom_external_status = quote_data.get("status")
	quotation.custom_created_by_name = quote_data.get("created_by_name")
	quotation.custom_agent_name = quote_data.get("agent_name")
	quotation.custom_agent_id = str(quote_data.get("agent_id") or "")
	quotation.custom_customer_phone = quote_data.get("customer_phone")
	quotation.custom_customer_email = quote_data.get("customer_email")
	quotation.custom_city = quote_data.get("city")
	quotation.custom_state = quote_data.get("state")
	quotation.custom_pincode = quote_data.get("pincode")
	quotation.custom_agent_commission_percent = safe_flt(quote_data.get("agent_commission_percent"))
	quotation.custom_agent_commission_amount = safe_flt(quote_data.get("agent_commission_amount"))
	quotation.custom_school_commission_amount = safe_flt(quote_data.get("school_commission_amount"))
	quotation.custom_total_before_gst = safe_flt(quote_data.get("total_before_gst"))
	quotation.custom_total_gst_amount = safe_flt(quote_data.get("total_gst_amount") or quote_data.get("total_gst"))
	quotation.custom_api_grand_total = safe_flt(quote_data.get("grand_total"))
	if quote_data.get("notes"):
		quotation.notes = quote_data.get("notes")

	raw_items = quote_data.get("items", [])
	quotation.items = []

	if raw_items:
		for it in raw_items:
			item_code = get_or_create_item_for_quote_product(it)
			qty = safe_flt(it.get("quantity") or 1, default=1.0)
			rate = safe_flt(
				it.get("unit_price")
				if it.get("unit_price") is not None
				else (
					it.get("product_mrp")
					if it.get("product_mrp") is not None
					else (it.get("final_unit_price") or 0.0)
				)
			)

			category = it.get("product_category_name") or it.get("category_name") or it.get("category") or "Accessories"
			gst_hsn = (
				it.get("gst_hsn_code")
				or it.get("product_hsn_code")
				or get_valid_hsn_for_item(category)
				or frappe.db.get_value("Item", item_code, "gst_hsn_code")
				or "620300"
			)

			final_mrp = safe_flt(it.get("final_mrp_per_unit"))
			if final_mrp <= 0:
				final_mrp = safe_flt(it.get("final_unit_price") or it.get("product_incl_gst") or it.get("product_mrp"))

			quotation.append("items", {
				"item_code": item_code,
				"item_name": it.get("product_name") or item_code,
				"qty": qty,
				"rate": rate,
				"price_list_rate": rate,
				"uom": "Nos",
				"stock_uom": "Nos",
				"gst_hsn_code": gst_hsn,
				"description": it.get("product_description") or it.get("product_name") or item_code,
				"custom_product_id": it.get("product_id") or it.get("id"),
				"custom_category_name": category,
				"custom_tier_group": it.get("product_group_type_name") or it.get("group_name") or it.get("tier") or it.get("group"),
				"custom_addon_1": it.get("addon1_name") or it.get("addon_1"),
				"custom_addon_2": it.get("addon2_name") or it.get("addon_2"),
				"custom_addon_3": it.get("addon3_name") or it.get("addon_3"),
				"custom_unit_price_msp": safe_flt(it.get("product_msp") or it.get("unit_price_msp")),
				"custom_addon_cost": safe_flt(it.get("addon_cost") or it.get("product_addon_cost") or it.get("addon_cost_per_unit")),
				"custom_surcharge": safe_flt(it.get("surcharge_amount") or it.get("surcharge") or it.get("surcharge_per_unit")),
				"custom_subtotal_before_gst": safe_flt(it.get("subtotal_total") or it.get("total_before_gst") or it.get("subtotal_before_gst")),
				"custom_gst_rate": safe_flt(it.get("gst_percent") or it.get("product_gst_rate") or it.get("gst_rate")),
				"custom_gst_amount": safe_flt(it.get("gst_amount_total") or it.get("gst_amount") or it.get("product_gst_amount")),
				"custom_final_mrp_per_unit": final_mrp,
				"custom_agent_commission_amount": safe_flt(it.get("agent_commission_amount") or it.get("product_comm_amount")),
				"custom_school_commission_amount": safe_flt(it.get("school_commission_amount")),
			})
	else:
		# Fallback item if no line items in the external quotation
		placeholder_code = get_or_create_placeholder_item()
		rate = safe_flt(quote_data.get("grand_total") or quote_data.get("total_before_gst") or 0.0)
		gst_hsn = get_valid_hsn_for_item("Garments")
		quotation.append("items", {
			"item_code": placeholder_code,
			"item_name": f"Quotation {qnumber or qid}",
			"qty": 1.0,
			"rate": rate,
			"price_list_rate": rate,
			"uom": "Nos",
			"stock_uom": "Nos",
			"gst_hsn_code": gst_hsn,
			"description": quote_data.get("notes") or f"Quotation {qnumber or qid}",
		})

	quotation.flags.ignore_permissions = True
	quotation.save()
	frappe.db.commit()

	return quotation.name, is_new


@frappe.whitelist()
def import_quotations_from_api(quote_ids=None, api_url=None, company=None):
	"""
	Imports one or more external quotations by their IDs.
	"""
	if not quote_ids:
		frappe.throw(_("No quote IDs provided for import."))

	if isinstance(quote_ids, str):
		try:
			quote_ids = json.loads(quote_ids)
		except Exception:
			quote_ids = [s.strip() for s in quote_ids.split(",") if s.strip()]

	if not isinstance(quote_ids, list):
		quote_ids = [quote_ids]

	imported = []
	updated = []
	errors = []

	for qid in quote_ids:
		try:
			detail_res = fetch_quotation_details(qid, api_url=api_url)
			quote_data = detail_res.get("data", {})
			if not quote_data:
				errors.append(f"No data returned for Quote ID {qid}")
				continue

			qtn_name, is_new = create_or_update_erpnext_quotation(quote_data, company=company)
			item_info = {
				"id": qid,
				"quotation_name": qtn_name,
				"quote_number": quote_data.get("quote_number"),
				"customer_name": quote_data.get("customer_name"),
				"grand_total": quote_data.get("grand_total"),
			}
			if is_new:
				imported.append(item_info)
			else:
				updated.append(item_info)
		except Exception as e:
			frappe.log_error(title=f"Failed to import Quote {qid}", message=frappe.get_traceback())
			errors.append(f"Quote {qid}: {str(e)}")

	total_success = len(imported) + len(updated)
	first_name = (imported[0]["quotation_name"] if imported else (updated[0]["quotation_name"] if updated else None))

	frappe.clear_messages()
	return {
		"success": total_success > 0,
		"imported_count": len(imported),
		"updated_count": len(updated),
		"imported": imported,
		"updated": updated,
		"errors": errors,
		"quotation_name": first_name,
		"message": _("Imported {0} new and updated {1} quotation(s).").format(len(imported), len(updated)),
	}


@frappe.whitelist()
def sync_all_quotations_from_api(api_url=None, company=None):
	"""
	Directly fetches all live quotations from the external API and imports them into ERPNext.
	Invoked instantly when clicking 'Create Quotation from API'.
	"""
	fetch_res = fetch_quotations_from_api(api_url=api_url)
	quotations = fetch_res.get("quotations", [])

	if not quotations:
		frappe.throw(_("No quotations returned from the API endpoint."))

	quote_ids = [q["id"] for q in quotations if q.get("id")]
	return import_quotations_from_api(quote_ids=quote_ids, api_url=api_url, company=company)


@frappe.whitelist()
def sync_all_products_from_api(api_url=None):
	"""
	Directly fetches all live products from the external API and imports them into Item Master.
	Invoked instantly when clicking 'Import Products from API'.
	"""
	return import_pricing_from_api(api_url=api_url)


def ensure_school(school_code, school_name=None, city=None, state=None):
	"""Ensures a School document exists for the given school_code"""
	if not school_code:
		return None
	school_code = str(school_code).strip()
	school = frappe.db.get_value("School", {"school_code": school_code}, "name")
	if not school:
		try:
			doc = frappe.new_doc("School")
			doc.school_code = school_code
			doc.school_name = school_name or school_code
			doc.city = city
			doc.state = state
			doc.status = "Active"
			doc.country = "India"
			doc.flags.ignore_permissions = True
			doc.insert()
			frappe.db.commit()
			return doc.name
		except Exception:
			frappe.clear_messages()
	return school or school_code


def ensure_grade(grade_name):
	"""Ensures a Grade document exists"""
	if not grade_name:
		return None
	grade_name = str(grade_name).strip()
	if not frappe.db.exists("Grade", grade_name):
		try:
			doc = frappe.new_doc("Grade")
			doc.grade_name = grade_name
			doc.status = "Active"
			doc.flags.ignore_permissions = True
			doc.insert()
			frappe.db.commit()
		except Exception:
			frappe.clear_messages()
	return grade_name


def ensure_customer_group(name="Student"):
	"""Ensures Student customer group exists"""
	if not frappe.db.exists("Customer Group", name):
		try:
			cg = frappe.new_doc("Customer Group")
			cg.customer_group_name = name
			cg.parent_customer_group = "All Customer Groups"
			cg.is_group = 0
			cg.flags.ignore_permissions = True
			cg.insert()
			frappe.db.commit()
		except Exception:
			frappe.clear_messages()
	return name


def get_or_create_student_guardian(guardian_name, mobile, email=None, relation=None):
	"""Gets or creates a Guardian document"""
	if not guardian_name and not mobile:
		return None

	clean_mobile = re.sub(r"\D", "", str(mobile or ""))
	if len(clean_mobile) == 12 and clean_mobile.startswith("91"):
		clean_mobile = clean_mobile[2:]
	if len(clean_mobile) != 10:
		clean_mobile = None

	guardian_doc_name = None
	if clean_mobile:
		guardian_doc_name = frappe.db.get_value("Guardians", {"mobile_number": clean_mobile}, "name")
	if not guardian_doc_name and guardian_name:
		guardian_doc_name = frappe.db.get_value("Guardians", {"guardian_name": guardian_name}, "name")

	if not guardian_doc_name:
		try:
			g = frappe.new_doc("Guardians")
			g.guardian_name = guardian_name or f"Guardian {clean_mobile}"
			g.mobile_number = clean_mobile
			g.email_address = email
			g.relation = relation or "Father"
			g.flags.ignore_permissions = True
			g.insert()
			guardian_doc_name = g.name
		except Exception:
			pass

	return guardian_doc_name


@frappe.whitelist()
def fetch_students_from_api(api_url=None, page=1, limit=50, fetch_all=True):
	"""
	Fetches students list from external Students API endpoint.
	If fetch_all is True (or 1 / 'true'), it automatically paginates through
	all pages (page 1 to total_pages) to retrieve the complete list (e.g. 1338 students).
	"""
	if not api_url:
		api_url = DEFAULT_STUDENTS_API_URL

	api_url = str(api_url).strip()

	should_fetch_all = True
	if fetch_all is not None:
		if isinstance(fetch_all, bool):
			should_fetch_all = fetch_all
		elif str(fetch_all).strip().lower() in ["0", "false", "no"]:
			should_fetch_all = False

	session = requests.Session()
	session.headers.update({
		"User-Agent": "ERPNext-Impressio/1.0",
		"Accept": "application/json",
	})

	initial_page = int(page) if page else 1
	per_page_limit = int(limit) if limit else 50

	params = {
		"page": initial_page,
		"limit": per_page_limit,
	}

	response = session.get(api_url, params=params, timeout=30)
	response.raise_for_status()
	data = response.json()

	def extract_page_data(d):
		page_students = []
		page_pagination = {}
		if isinstance(d, dict):
			res_data = d.get("data", {})
			if isinstance(res_data, dict):
				page_students = res_data.get("students", [])
				page_pagination = res_data.get("pagination", {})
			elif isinstance(res_data, list):
				page_students = res_data
			elif "students" in d:
				page_students = d.get("students", [])

			if not page_pagination and "pagination" in d and isinstance(d.get("pagination"), dict):
				page_pagination = d.get("pagination", {})
		return page_students, page_pagination

	students, pagination = extract_page_data(data)

	total_count = pagination.get("total", len(students))
	total_pages = pagination.get("total_pages", 1)

	if should_fetch_all and total_pages > initial_page:
		for current_p in range(initial_page + 1, total_pages + 1):
			try:
				p_params = {
					"page": current_p,
					"limit": per_page_limit,
				}
				p_resp = session.get(api_url, params=p_params, timeout=30)
				if p_resp.status_code == 200:
					p_data = p_resp.json()
					p_students, _ = extract_page_data(p_data)
					if p_students:
						students.extend(p_students)
					else:
						break
				else:
					frappe.log_error(title="Students API Fetch Error", message=f"Page {current_p} returned {p_resp.status_code}")
					break
			except Exception as err:
				frappe.log_error(title="Students API Fetch Page Exception", message=f"Failed fetching page {current_p}: {str(err)}")
				break

	return {
		"success": True,
		"students": students,
		"pagination": pagination,
		"total": total_count if should_fetch_all else pagination.get("total", len(students)),
		"count": len(students),
		"page": initial_page,
		"limit": per_page_limit,
		"total_pages": total_pages,
	}


def create_or_update_erpnext_student(student_data):
	"""
	Creates or updates a Students record in ERPNext from API student dict.
	Returns (student_name, is_new: bool).
	"""
	sid = student_data.get("id")
	admission_no = student_data.get("admission_no") or f"STU-{sid}"
	school_code = student_data.get("school_code") or "CPS"
	school_name = student_data.get("school_name")
	school_city = student_data.get("school_city")
	school_state = student_data.get("school_state")

	ensure_school(school_code, school_name, school_city, school_state)
	grade_name = student_data.get("grade_name")
	if grade_name:
		ensure_grade(grade_name)
	ensure_customer_group("Student")

	# Check existing
	existing_name = None
	if sid:
		existing_name = frappe.db.get_value("Students", {"custom_external_student_id": sid}, "name")
	if not existing_name and school_code and admission_no:
		existing_name = frappe.db.get_value("Students", {"school_code": school_code, "enrollment_number": admission_no}, "name")
	if not existing_name and admission_no:
		existing_name = frappe.db.get_value("Students", {"enrollment_number": admission_no}, "name")

	if existing_name:
		doc = frappe.get_doc("Students", existing_name)
		is_new = False
	else:
		doc = frappe.new_doc("Students")
		is_new = True

	# Name parsing
	full_name = (student_data.get("name") or "").strip()
	parts = full_name.split()
	first_name = parts[0] if parts else f"Student {sid}"
	middle_name = " ".join(parts[1:-1]) if len(parts) > 2 else ""
	last_name = parts[-1] if len(parts) > 1 else ""

	doc.first_name = first_name
	doc.middle_name = middle_name
	doc.last_name = last_name
	doc.school_code = school_code
	doc.enrollment_number = admission_no
	if grade_name and frappe.db.exists("Grade", grade_name):
		doc.grade = grade_name
	doc.section = student_data.get("section_name") or ""
	doc.enabled = 1 if student_data.get("is_active", 1) else 0

	# Gender
	raw_gender = (student_data.get("gender") or "Other").strip().capitalize()
	if raw_gender not in ["Male", "Female"]:
		raw_gender = "Other"
	doc.gender = raw_gender

	# DOB
	if student_data.get("dob"):
		doc.date_of_birth = student_data.get("dob")

	# Mobile & Email (mandatory in Students doctype)
	mobile = student_data.get("parent_contact") or ""
	clean_mobile = re.sub(r"\D", "", str(mobile))
	if len(clean_mobile) == 12 and clean_mobile.startswith("91"):
		clean_mobile = clean_mobile[2:]
	doc.student_mobile_number = clean_mobile

	email = student_data.get("parent_email") or ""
	if not email or "@" not in email:
		clean_ad = re.sub(r"[^a-zA-Z0-9]", "", admission_no).lower()
		clean_sc = re.sub(r"[^a-zA-Z0-9]", "", school_code).lower()
		email = f"{clean_ad}@{clean_sc}.impressio.in"
	doc.student_email_id = email

	doc.house_color = student_data.get("house_color") or ""
	doc.customer_group = "Student"
	if student_data.get("created_at"):
		doc.joining_date = str(student_data.get("created_at"))[:10]

	# Custom fields
	doc.custom_external_student_id = sid
	doc.custom_school_id = student_data.get("school_id")
	doc.custom_school_name = school_name
	doc.custom_school_city = school_city
	doc.custom_school_state = school_state
	doc.custom_student_code = student_data.get("student_code")
	doc.custom_academic_year = student_data.get("academic_year")
	doc.custom_grade_id = student_data.get("grade_id")
	doc.custom_section_id = student_data.get("section_id")
	doc.custom_house_id = student_data.get("house_id")
	doc.custom_house_name = student_data.get("house_name")
	doc.custom_customer_mapping_status = student_data.get("customer_mapping_status")
	doc.custom_customer_mapped_on = student_data.get("customer_mapped_on")
	doc.custom_subject_names = student_data.get("subject_names")
	doc.custom_full_address = student_data.get("address")

	# Guardians child table
	parent_name = student_data.get("parent_name")
	relation = student_data.get("relationship") or "Father"
	if relation not in ["Mother", "Father", "Others"]:
		relation = "Others"

	if parent_name or clean_mobile:
		guardian_ref = get_or_create_student_guardian(parent_name, clean_mobile, email=student_data.get("parent_email"), relation=relation)
		if guardian_ref:
			doc.guardians = []
			doc.append("guardians", {
				"guardian": guardian_ref,
				"guardian_name": parent_name or guardian_ref,
				"relation": relation,
				"email": student_data.get("parent_email") or "",
				"phone_no": clean_mobile or "",
			})

	# Address child table
	addr_text = student_data.get("address")
	if addr_text:
		lines = [line.strip() for line in addr_text.split("\n") if line.strip()]
		line1 = lines[0] if lines else addr_text
		line2 = ", ".join(lines[1:]) if len(lines) > 1 else ""
		pin_match = re.search(r"\b\d{6}\b", addr_text)
		pincode = int(pin_match.group()) if pin_match else 600001

		doc.student_billing_addresses = []
		doc.append("student_billing_addresses", {
			"address_title": f"{first_name} Home",
			"address_type": "Permanent",
			"address_line_1": line1,
			"address_line_2": line2,
			"city": school_city or "Chennai",
			"state": school_state or "Tamil Nadu",
			"country": "India",
			"pincode": pincode,
			"preferred": 1,
			"disabled": 0,
		})

	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()

	return doc.name, is_new


@frappe.whitelist()
def import_students_from_api(students_data=None, api_url=None):
	"""
	Imports one or more students from provided list or fetches next batch.
	"""
	if not students_data:
		fetch_res = fetch_students_from_api(api_url=api_url, fetch_all=True)
		students_data = fetch_res.get("students", [])

	if isinstance(students_data, str):
		try:
			students_data = json.loads(students_data)
		except Exception:
			pass

	if not isinstance(students_data, list):
		students_data = [students_data]

	imported = []
	updated = []
	errors = []

	for st in students_data:
		try:
			name, is_new = create_or_update_erpnext_student(st)
			info = {
				"id": st.get("id"),
				"name": name,
				"student_name": st.get("name"),
				"admission_no": st.get("admission_no"),
				"school_name": st.get("school_name"),
			}
			if is_new:
				imported.append(info)
			else:
				updated.append(info)
		except Exception as e:
			frappe.log_error(title=f"Student import error {st.get('admission_no')}", message=str(e))
			errors.append(f"{st.get('name')} ({st.get('admission_no')}): {str(e)}")

	frappe.clear_messages()
	return {
		"success": (len(imported) + len(updated)) > 0,
		"imported_count": len(imported),
		"updated_count": len(updated),
		"imported": imported,
		"updated": updated,
		"errors": errors,
		"message": _("Imported {0} new and updated {1} student(s).").format(len(imported), len(updated)),
	}


@frappe.whitelist()
def sync_all_students_from_api(api_url=None, page=None, limit=50, fetch_all=True):
	"""
	Directly fetches students from API and imports them.
	"""
	fetch_res = fetch_students_from_api(api_url=api_url, page=page, limit=limit, fetch_all=fetch_all)
	students = fetch_res.get("students", [])
	if not students:
		frappe.throw(_("No students returned from the API endpoint."))
	return import_students_from_api(students_data=students, api_url=api_url)


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS API INTEGRATION (Impressio External Orders)
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def fetch_orders_from_api(api_url=None, page=1):
	"""
	Fetches live orders from the external orders API endpoint.
	Validates response and raises clear errors if keys or format changed.
	NEVER falls back to default/sample JSON.
	"""
	if not api_url:
		api_url = DEFAULT_ORDERS_API_URL

	api_url = str(api_url).strip()

	try:
		headers = {
			"User-Agent": "ERPNext-Impressio/1.0",
			"Accept": "application/json",
		}
		params = {}
		if page:
			params["page"] = int(page)

		response = requests.get(api_url, params=params, timeout=25, headers=headers)
		response.raise_for_status()
		data = response.json()
	except requests.exceptions.RequestException as e:
		frappe.throw(_("Failed to fetch orders from API: {0}").format(str(e)))
	except Exception as e:
		frappe.throw(_("Error parsing Orders API response: {0}").format(str(e)))

	if not isinstance(data, dict):
		frappe.throw(_("Invalid Orders API response format: Expected JSON object, received {0}").format(type(data).__name__))

	# Check success flag if present
	if "success" in data and not data.get("success"):
		frappe.throw(_("Orders API returned error: {0}").format(data.get("message") or data.get("error") or "Request failed"))

	# Check for 'orders' key
	if "orders" not in data:
		found_keys = list(data.keys())
		frappe.throw(_("Orders API key changed or missing: Expected 'orders' key in response, but received keys: {0}").format(", ".join(found_keys)))

	orders = data.get("orders")
	if not isinstance(orders, list):
		frappe.throw(_("Orders API format changed: Expected 'orders' to be a list, received {0}").format(type(orders).__name__))

	# Validate first order structure if orders exist
	if orders:
		sample_order = orders[0]
		if not isinstance(sample_order, dict):
			frappe.throw(_("Orders API format changed: Order element is not a JSON object."))

		required_order_keys = ["id", "orderId", "items"]
		missing_keys = [k for k in required_order_keys if k not in sample_order]
		if missing_keys:
			frappe.throw(_("Orders API format changed: Missing required key(s) in order: {0}. Available keys: {1}").format(
				", ".join(missing_keys), ", ".join(sample_order.keys())
			))

	# Enrich orders with ERPNext Sales Order import status
	imported_count = 0
	for o in orders:
		oid = o.get("id")
		order_number = o.get("orderId")
		existing = None
		if order_number:
			existing = frappe.db.get_value("Sales Order", {"custom_gateway_order_id": order_number}, ["name", "status", "docstatus"], as_dict=True)
			if not existing:
				existing = frappe.db.get_value("Sales Order", {"po_no": order_number}, ["name", "status", "docstatus"], as_dict=True)
		if not existing and oid:
			if frappe.db.has_column("Sales Order", "custom_external_order_id"):
				existing = frappe.db.get_value("Sales Order", {"custom_external_order_id": oid}, ["name", "status", "docstatus"], as_dict=True)

		if existing:
			o["is_imported"] = True
			o["erpnext_sales_order"] = existing.name
			o["erpnext_status"] = existing.status
			imported_count += 1
		else:
			o["is_imported"] = False
			o["erpnext_sales_order"] = None
			o["erpnext_status"] = None

	return {
		"success": True,
		"total": data.get("total", len(orders)),
		"imported_count": imported_count,
		"new_count": len(orders) - imported_count,
		"orders": orders,
		"api_url": api_url,
		"page": data.get("page", 1),
		"totalPages": data.get("totalPages", 1),
	}


@frappe.whitelist()
def fetch_order_details(order_id, api_url=None):
	"""
	Fetches details for a single order from the API endpoint.
	e.g. /orders/44?api_key=...
	"""
	if not order_id:
		frappe.throw(_("Order ID is required."))

	if not api_url:
		api_url = DEFAULT_ORDERS_API_URL

	api_url = str(api_url).strip()
	if "?" in api_url:
		base, qs = api_url.split("?", 1)
		detail_url = f"{base.rstrip('/')}/{order_id}?{qs}"
	else:
		detail_url = f"{api_url.rstrip('/')}/{order_id}"

	try:
		headers = {
			"User-Agent": "ERPNext-Impressio/1.0",
			"Accept": "application/json",
		}
		response = requests.get(detail_url, timeout=25, headers=headers)
		response.raise_for_status()
		data = response.json()

		if not isinstance(data, dict):
			frappe.throw(_("Invalid response format from Order Details API."))

		if "success" in data and not data.get("success"):
			frappe.throw(_("Order API returned error: {0}").format(data.get("message") or "Order not found"))

		order_data = data.get("order") or data.get("data")
		if not order_data:
			found_keys = list(data.keys())
			frappe.throw(_("Order details key changed: Expected 'order' key in response, received: {0}").format(", ".join(found_keys)))

		return {
			"success": True,
			"order": order_data,
		}
	except requests.exceptions.RequestException as e:
		frappe.throw(_("Failed to fetch order details for ID {0}: {1}").format(order_id, str(e)))


def get_or_create_order_customer(order_data):
	"""
	Finds existing Customer or creates new Customer in ERPNext from order data.
	Also creates Address linked to Customer.
	"""
	addr_dict = order_data.get("address") or {}
	customer_name = (
		order_data.get("orderedBy")
		or addr_dict.get("fullName")
		or order_data.get("studentName")
		or "Website Customer"
	).strip()

	mobile = addr_dict.get("mobile")
	clean_mobile = re.sub(r"\D", "", str(mobile or ""))
	if len(clean_mobile) == 12 and clean_mobile.startswith("91"):
		clean_mobile = clean_mobile[2:]
	if len(clean_mobile) != 10:
		clean_mobile = None

	# 1. Search existing Customer by name or mobile
	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if not existing and clean_mobile:
		existing = frappe.db.get_value("Customer", {"mobile_no": clean_mobile}, "name")
	if existing:
		return existing

	# 2. Create new customer
	default_cg = (
		frappe.db.get_value("Customer Group", {"customer_group_name": "Student"}, "name")
		or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		or "All Customer Groups"
	)
	default_terr = (
		frappe.db.get_value("Territory", {"is_group": 0}, "name")
		or "All Territories"
	)

	cust = frappe.new_doc("Customer")
	cust.customer_name = customer_name
	cust.customer_group = default_cg
	cust.territory = default_terr
	cust.customer_type = "Individual"
	if clean_mobile:
		cust.mobile_no = clean_mobile

	cust.flags.ignore_permissions = True
	cust.insert()

	# 3. Create Address linked to Customer if address details exist
	house = (addr_dict.get("house") or "").strip()
	area = (addr_dict.get("area") or "").strip()
	city = (addr_dict.get("city") or "Madurai").strip()
	state = (addr_dict.get("state") or "Tamil Nadu").strip()
	pincode = (addr_dict.get("pincode") or "").strip()

	lines = [x for x in [house, area] if x and x != "NA"]
	address_line1 = ", ".join(lines) if lines else (city or "Main Address")

	try:
		addr = frappe.new_doc("Address")
		addr.address_title = customer_name
		addr.address_type = "Billing"
		addr.address_line1 = address_line1
		addr.city = city
		addr.state = state
		addr.pincode = str(pincode)
		addr.country = "India"
		if clean_mobile:
			addr.phone = clean_mobile
		addr.append("links", {
			"link_doctype": "Customer",
			"link_name": cust.name,
		})
		addr.flags.ignore_permissions = True
		addr.insert()
	except Exception:
		pass

	return cust.name


def get_or_create_item_for_order_product(prod):
	"""
	Finds existing Item or creates new Item in ERPNext from order product data.
	"""
	prod_name = str(prod.get("website_display_name") or prod.get("product_name") or prod.get("name") or "Product").strip()
	prod_id = prod.get("product_id") or prod.get("id")
	category = prod.get("category_name") or prod.get("category") or "Garments"
	rate = safe_flt(prod.get("calc_msp") or prod.get("standard_rate") or prod.get("unit_price") or 0.0)

	# 1. Look for existing item by name
	existing_by_name = frappe.db.get_value("Item", {"item_name": prod_name}, "name")
	if existing_by_name:
		return existing_by_name

	# 2. Check by slug
	base_slug = re.sub(r"[^A-Za-z0-9]+", "-", prod_name).strip("-").upper()
	if not base_slug:
		base_slug = f"PROD-{prod_id}" if prod_id else "ITEM"
	if len(base_slug) > 100:
		base_slug = base_slug[:100].rstrip("-")

	if frappe.db.exists("Item", base_slug):
		return base_slug

	# 3. Create Item
	ensure_item_groups_and_uom([{"item_group": category}])
	gst_hsn = get_valid_hsn_for_item(category)

	item = frappe.new_doc("Item")
	item.item_code = base_slug
	item.item_name = prod_name
	item.item_group = category if frappe.db.exists("Item Group", category) else "All Item Groups"
	item.stock_uom = "Nos"
	item.is_stock_item = 1
	item.is_sales_item = 1
	item.standard_rate = rate
	item.description = prod.get("description") or prod_name

	image_urls = prod.get("image_urls")
	if image_urls and isinstance(image_urls, list) and len(image_urls) > 0:
		item.image = image_urls[0]

	meta = frappe.get_meta("Item")
	if meta.has_field("gst_hsn_code") and gst_hsn:
		item.gst_hsn_code = gst_hsn

	item.flags.ignore_permissions = True
	item.insert()

	update_item_price(item.name, rate, uom="Nos")
	return item.name


def create_or_update_erpnext_sales_order(order_data, company=None):
	"""
	Creates or updates a Sales Order document in ERPNext from external order data.
	Returns (sales_order.name, is_new: bool).
	"""
	if not isinstance(order_data, dict):
		frappe.throw(_("Invalid order data format: Expected JSON object."))

	oid = order_data.get("id")
	order_id_code = order_data.get("orderId")
	if not oid and not order_id_code:
		keys_str = ", ".join(order_data.keys())
		frappe.throw(_("Order missing 'orderId' or 'id' key. Received keys: {0}").format(keys_str))

	if "items" not in order_data or not isinstance(order_data.get("items"), list):
		keys_str = ", ".join(order_data.keys())
		frappe.throw(_("Order {0} missing 'items' array. Received keys: {1}").format(order_id_code or oid, keys_str))

	if not company:
		company = (
			frappe.defaults.get_user_default("company")
			or frappe.db.get_single_value("Global Defaults", "default_company")
			or "Impressio"
		)

	customer_name = get_or_create_order_customer(order_data)

	# Check for existing Sales Order
	existing_name = None
	if order_id_code:
		existing_name = frappe.db.get_value("Sales Order", {"custom_gateway_order_id": order_id_code}, "name")
		if not existing_name:
			existing_name = frappe.db.get_value("Sales Order", {"po_no": order_id_code}, "name")
	if not existing_name and oid and frappe.db.has_column("Sales Order", "custom_external_order_id"):
		existing_name = frappe.db.get_value("Sales Order", {"custom_external_order_id": oid}, "name")

	if existing_name:
		so = frappe.get_doc("Sales Order", existing_name)
		is_new = False
		# If already submitted, skip item modification to prevent validation errors
		if so.docstatus == 1:
			return so.name, False
	else:
		so = frappe.new_doc("Sales Order")
		is_new = True

	so.customer = customer_name
	so.company = company

	# Set Company Address & GSTIN for India Compliance
	company_addr = get_or_create_company_address(company)
	if company_addr:
		so.company_address = company_addr
		comp_gstin = frappe.db.get_value("Address", company_addr, "gstin")
		if comp_gstin:
			so.company_gstin = comp_gstin

	# Set Customer Address
	customer_addr = get_or_create_customer_address(customer_name)
	if customer_addr:
		so.customer_address = customer_addr

	created_at = order_data.get("createdAt")
	so.transaction_date = str(created_at)[:10] if created_at else frappe.utils.today()
	# transaction_date + 7 use pannuvom — data accurate-ah irukum
	# (delivery_date past-la irundhalum ERPNext error throw pannaaது — only payment terms due_date validate aagum)
	so.delivery_date = frappe.utils.add_days(so.transaction_date, 7)
	so.order_type = "Shopping Cart"
	so.currency = frappe.get_cached_value("Company", company, "default_currency") or "INR"
	so.selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
	# Clear payment terms to avoid 'Due Date before Posting Date' validation error
	so.payment_terms_template = ""
	so.payment_schedule = []

	# Warehouse
	default_wh = "Stores - IESPL"
	if not frappe.db.exists("Warehouse", default_wh):
		whs = frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, limit=1)
		default_wh = whs[0].name if whs else None
	if default_wh:
		so.set_warehouse = default_wh

	# PO / Gateway / Tracking fields
	so.po_no = order_id_code
	so.custom_gateway_order_id = order_id_code
	payment_method = order_data.get("paymentMethod") or "CC Avenue"
	so.custom_gateway_provider = payment_method
	so.custom_payment_mode = payment_method
	ext_status = str(order_data.get("status") or "").strip().lower()
	if ext_status in ["confirmed", "completed", "paid", "success"]:
		so.custom_payment_status = "SUCCESS"
		so.custom_payment_finalized = 1
	else:
		so.custom_payment_status = ext_status.capitalize() if ext_status else "Draft"

	total_amount = safe_flt(order_data.get("total"))
	so.custom_paid_amount = str(total_amount)
	tracking_id = order_data.get("trackingId")
	if tracking_id:
		so.custom_gateway_tracking_id = tracking_id

	addr_dict = order_data.get("address") or {}
	if addr_dict.get("pincode"):
		so.custom_pin_code = str(addr_dict.get("pincode")).strip()
	if addr_dict.get("mobile"):
		so.contact_mobile = str(addr_dict.get("mobile")).strip()

	# Custom external fields if present
	if hasattr(so, "custom_external_order_id") and oid:
		so.custom_external_order_id = oid
	if hasattr(so, "custom_student_name"):
		so.custom_student_name = order_data.get("studentName")
	if hasattr(so, "custom_student_id"):
		so.custom_student_id = order_data.get("studentId")
	if hasattr(so, "custom_ordered_by"):
		so.custom_ordered_by = order_data.get("orderedBy")
	if hasattr(so, "custom_external_order_status"):
		so.custom_external_order_status = order_data.get("status")

	# Student link resolution
	student_id = order_data.get("studentId")
	student_name = order_data.get("studentName")
	student_doc_name = None
	if student_id:
		student_doc_name = frappe.db.get_value("Students", {"enrollment_number": student_id}, "name")
		if not student_doc_name:
			# Match by suffix (e.g. 0363 in GV-0363)
			clean_suffix = re.sub(r"\D", "", student_id)
			if clean_suffix:
				matching = frappe.db.get_value("Students", {"enrollment_number": ["like", f"%{clean_suffix}%"]}, "name")
				if matching:
					student_doc_name = matching
	if not student_doc_name and student_name:
		student_doc_name = frappe.db.get_value("Students", {"first_name": student_name.split()[0], "last_name": student_name.split()[-1] if len(student_name.split()) > 1 else ""}, "name")

	if student_doc_name:
		st_info = frappe.db.get_value("Students", student_doc_name, ["school_code", "grade"], as_dict=True)
		so.student = student_doc_name
		if st_info:
			sc_code = st_info.get("school_code")
			school_link = frappe.db.get_value("School", {"school_code": sc_code}, "name") if sc_code else None
			if not school_link and sc_code and frappe.db.exists("School", sc_code):
				school_link = sc_code
			so.custom_student_school = school_link
			so.custom_student_grade = ensure_grade(st_info.get("grade"))

	# Extract order items
	raw_items = order_data.get("items", [])

	# Fallback school & grade from order items if not set from student
	if not so.get("custom_student_school") and raw_items:
		for rit in raw_items:
			sc_name = rit.get("school_name")
			if sc_name:
				s_link = frappe.db.get_value("School", {"school_name": sc_name}, "name") or frappe.db.get_value("School", {"school_code": sc_name}, "name")
				if s_link:
					so.custom_student_school = s_link
					break

	if not so.get("custom_student_grade") and raw_items:
		for rit in raw_items:
			gr_name = rit.get("grade_name")
			if gr_name:
				so.custom_student_grade = ensure_grade(gr_name)
				break

	# Items and Sub-items
	so.items = []
	if hasattr(so, "custom_sub_items"):
		so.custom_sub_items = []

	for it in raw_items:
		item_code = get_or_create_item_for_order_product(it)
		qty = safe_flt(it.get("quantity") or 1, default=1.0)
		rate = safe_flt(it.get("calc_msp") or it.get("unit_price") or it.get("standard_rate") or 0.0)
		item_title = it.get("website_display_name") or it.get("product_name") or item_code
		category = it.get("category_name") or it.get("category") or "Garments"
		gst_hsn = get_valid_hsn_for_item(category)

		item_row = {
			"item_code": item_code,
			"item_name": item_title,
			"qty": qty,
			"rate": rate,
			"price_list_rate": rate,
			"uom": "Nos",
			"stock_uom": "Nos",
			"warehouse": default_wh,
			"gst_hsn_code": gst_hsn,
			"description": it.get("description") or item_title,
		}
		if frappe.db.has_column("Sales Order Item", "custom_selected_size"):
			item_row["custom_selected_size"] = it.get("selectedSize") or it.get("size")
		if frappe.db.has_column("Sales Order Item", "custom_product_id"):
			item_row["custom_product_id"] = it.get("product_id") or it.get("id")

		so.append("items", item_row)

		# Sub-items resolution
		is_bundle = 1 if it.get("is_bundle") else 0
		bundle_items = it.get("bundle_items") or []

		if hasattr(so, "custom_sub_items"):
			if is_bundle and bundle_items:
				for sub in bundle_items:
					sub_code = get_or_create_item_for_order_product(sub)
					sub_qty = safe_flt(sub.get("quantity") or 1, default=1.0) * qty
					so.append("custom_sub_items", {
						"parent_item_code": item_code,
						"item_code": sub_code,
						"qty": sub_qty,
					})
			else:
				so.append("custom_sub_items", {
					"parent_item_code": item_code,
					"item_code": item_code,
					"qty": qty,
				})

	# Shipping charges in Taxes table
	shipping_charge = safe_flt(order_data.get("shipping"))
	if hasattr(so, "custom_shipping_charges"):
		so.custom_shipping_charges = shipping_charge

	if shipping_charge > 0:
		freight_account = frappe.db.get_value("Account", {"account_name": ["like", "%Freight%"], "company": company, "is_group": 0}, "name")
		cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name") or "Main - I"
		if freight_account:
			so.taxes = []
			so.append("taxes", {
				"charge_type": "Actual",
				"account_head": freight_account,
				"cost_center": cost_center,
				"description": "Shipping Charges",
				"tax_amount": shipping_charge,
			})

	# Clear address fields to avoid "Billing Address does not belong to Customer" error
	# Address mismatch aaguthu when customer changes or duplicate customers exist
	so.customer_address = ""
	so.shipping_address_name = ""
	so.contact_person = ""

	so.flags.ignore_permissions = True
	so.flags.ignore_mandatory = True
	so.save()
	frappe.db.commit()

	return so.name, is_new


@frappe.whitelist()
def import_orders_from_api(orders_data=None, order_ids=None, api_url=None, company=None):
	"""
	Imports orders into ERPNext as Sales Orders.
	Accepts either:
	- orders_data: list of order dicts
	- order_ids: list of order IDs to filter and import from the live API
	- api_url: custom API URL if needed
	"""
	if not orders_data:
		fetch_res = fetch_orders_from_api(api_url=api_url)
		all_orders = fetch_res.get("orders", [])

		if order_ids:
			if isinstance(order_ids, str):
				try:
					order_ids = json.loads(order_ids)
				except Exception:
					order_ids = [s.strip() for s in order_ids.split(",") if s.strip()]

			order_ids_set = set(str(x) for x in order_ids)
			orders_data = [
				o for o in all_orders
				if str(o.get("id")) in order_ids_set or str(o.get("orderId")) in order_ids_set
			]
		else:
			orders_data = all_orders

	if isinstance(orders_data, str):
		try:
			orders_data = json.loads(orders_data)
		except Exception as e:
			frappe.throw(_("Invalid orders data JSON: {0}").format(str(e)))

	if not isinstance(orders_data, list):
		orders_data = [orders_data]

	if not orders_data:
		frappe.throw(_("No orders to import."))

	imported = []
	updated = []
	errors = []

	for order in orders_data:
		oid = order.get("orderId") or order.get("id")
		try:
			so_name, is_new = create_or_update_erpnext_sales_order(order, company=company)
			item_info = {
				"id": order.get("id"),
				"orderId": order.get("orderId"),
				"sales_order_name": so_name,
				"customer": order.get("orderedBy") or (order.get("address") or {}).get("fullName"),
				"total": order.get("total"),
			}
			if is_new:
				imported.append(item_info)
			else:
				updated.append(item_info)
		except Exception as e:
			frappe.log_error(title=f"Failed to import Order {oid}", message=frappe.get_traceback())
			errors.append(f"Order {oid}: {str(e)}")

	total_success = len(imported) + len(updated)
	first_name = (imported[0]["sales_order_name"] if imported else (updated[0]["sales_order_name"] if updated else None))

	frappe.clear_messages()
	return {
		"success": total_success > 0,
		"imported_count": len(imported),
		"updated_count": len(updated),
		"imported": imported,
		"updated": updated,
		"errors": errors,
		"sales_order_name": first_name,
		"message": _("Imported {0} new and updated {1} Sales Order(s).").format(len(imported), len(updated)),
	}


@frappe.whitelist()
def sync_all_orders_from_api(api_url=None, company=None):
	"""
	Directly fetches all live orders from external API and imports them as Sales Orders into ERPNext.
	"""
	return import_orders_from_api(api_url=api_url, company=company)




