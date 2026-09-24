import frappe


# =====================================================
# BOM RESOLVER  (bulk, in-memory — zero recursive DB calls)
# =====================================================

def build_bom_cache(item_codes):
    """
    Given a set of item_codes, load ALL active BOMs and their items
    in exactly 2 queries, then return a dict ready for in-memory traversal.

    Returns:
        bom_items_map  →  { item_code: [ {item_code, qty}, ... ] }
                          (only items that have an active BOM are present)
    """

    if not item_codes:
        return {}

    # --- 1. find the active BOM name for every item in one shot ------------

    boms = frappe.db.sql("""
        SELECT name, item
        FROM `tabBOM`
        WHERE item IN %(items)s
          AND is_active = 1
          AND docstatus != 2
          AND custom_display = 1
    """, {"items": tuple(item_codes)}, as_dict=True)

    if not boms:
        return {}

    # keep only the first active BOM per item (mirrors original get_value logic)
    item_to_bom = {}
    for b in boms:
        if b.item not in item_to_bom:
            item_to_bom[b.item] = b.name

    bom_names = list(item_to_bom.values())

    # --- 2. load every BOM Item row for all those BOMs in one query ---------

    bom_items = frappe.db.sql("""
        SELECT parent, item_code, qty
        FROM `tabBOM Item`
        WHERE parent IN %(boms)s
        ORDER BY parent, idx ASC
    """, {"boms": tuple(bom_names)}, as_dict=True)

    # bom_name  →  [ {item_code, qty} ]
    bom_name_to_children = {}
    for bi in bom_items:
        bom_name_to_children.setdefault(bi.parent, []).append({
            "item_code": bi.item_code,
            "qty": bi.qty
        })

    # item_code → children list  (None means leaf / no BOM)
    bom_items_map = {}
    for item_code, bom_name in item_to_bom.items():
        bom_items_map[item_code] = bom_name_to_children.get(bom_name, [])

    # --- 3. discover child items that may themselves have BOMs --------------
    #        keep expanding until no new items are found

    all_child_codes = set()
    for children in bom_items_map.values():
        for c in children:
            all_child_codes.add(c["item_code"])

    unresolved = all_child_codes - set(bom_items_map.keys())

    while unresolved:

        sub_boms = frappe.db.sql("""
            SELECT name, item
            FROM `tabBOM`
            WHERE item IN %(items)s
              AND is_active = 1
              AND docstatus != 2
              AND custom_display = 1
        """, {"items": tuple(unresolved)}, as_dict=True)

        if not sub_boms:
            break

        new_item_to_bom = {}
        for b in sub_boms:
            if b.item not in new_item_to_bom:
                new_item_to_bom[b.item] = b.name

        new_bom_names = list(new_item_to_bom.values())

        sub_bom_items = frappe.db.sql("""
            SELECT parent, item_code, qty
            FROM `tabBOM Item`
            WHERE parent IN %(boms)s
            ORDER BY parent, idx ASC
        """, {"boms": tuple(new_bom_names)}, as_dict=True)

        new_bom_children = {}
        for bi in sub_bom_items:
            new_bom_children.setdefault(bi.parent, []).append({
                "item_code": bi.item_code,
                "qty": bi.qty
            })

        newly_found = set()
        for item_code, bom_name in new_item_to_bom.items():
            bom_items_map[item_code] = new_bom_children.get(bom_name, [])
            for c in bom_items_map[item_code]:
                if c["item_code"] not in bom_items_map:
                    newly_found.add(c["item_code"])

        unresolved = newly_found

    return bom_items_map


def resolve_bom_tree_from_cache(item_code, bom_cache):
    """
    Pure in-memory BOM tree resolution using pre-built cache.
    Identical output shape to the original resolve_bom_tree().
    """

    children = bom_cache.get(item_code)

    if children is None:
        return []

    result = []

    for bi in children:

        node = {
            "item_code": bi["item_code"],
            "qty": bi["qty"]
        }

        sub_children = resolve_bom_tree_from_cache(bi["item_code"], bom_cache)

        if sub_children:
            node["items"] = sub_children

        result.append(node)

    return result


# =====================================================
# FLATTEN BOM TREE  (unchanged logic)
# =====================================================

def flatten_bom(items, multiplier=1):

    final_items = []

    for it in items:

        qty = it["qty"] * multiplier

        if "items" in it:
            final_items.extend(flatten_bom(it["items"], qty))
        else:
            final_items.append({
                "item_code": it["item_code"],
                "qty": qty
            })

    return final_items


# =====================================================
# BULK SO ITEM LOADER
# =====================================================

def load_all_so_data(so_names):
    """
    Load Sales Order Items + Magic Box Sub Items for ALL orders
    in 2 queries. Also returns magic-box flag per SO.

    Returns:
        so_flags        →  { so_name: custom_magic_box (0/1) }
        so_items_map    →  { so_name: [ {item_code, qty} ] }   (normal SOs)
        so_subitem_map  →  { so_name: [ {item_code, qty} ] }   (magic box SOs)
    """

    if not so_names:
        return {}, {}, {}

    # magic box flags already on the orders — passed in from caller
    # (avoid re-querying; caller should pass so dicts)

    # --- normal SO items ---
    so_items_rows = frappe.db.sql("""
        SELECT parent, item_code, qty
        FROM `tabSales Order Item`
        WHERE parent IN %(names)s
    """, {"names": tuple(so_names)}, as_dict=True)

    so_items_map = {}
    for r in so_items_rows:
        so_items_map.setdefault(r.parent, []).append({
            "item_code": r.item_code,
            "qty": r.qty
        })

    # --- magic box sub-items ---
    so_subitem_rows = []
    try:
        if frappe.db.table_exists("Sale Order Sub Items"):
            so_subitem_rows = frappe.db.sql("""
                SELECT parent, item_code, qty
                FROM `tabSale Order Sub Items`
                WHERE parent IN %(names)s
            """, {"names": tuple(so_names)}, as_dict=True)
    except Exception:
        so_subitem_rows = []

    so_subitem_map = {}
    for r in so_subitem_rows:
        so_subitem_map.setdefault(r.parent, []).append({
            "item_code": r.item_code,
            "qty": r.qty
        })

    return so_items_map, so_subitem_map


# =====================================================
# RESOLVE SO ITEMS  (uses pre-loaded caches — no DB calls)
# =====================================================

def resolve_so_items_from_cache(so_name, is_magic_box,
                                so_items_map, so_subitem_map,
                                item_group_map, bom_cache):
    """
    Identical output to original resolve_sales_order_items()
    but uses pre-loaded in-memory caches — zero DB calls.
    """

    final_items = []

    # ---- Magic Box ----
    if is_magic_box:
        return list(so_subitem_map.get(so_name, []))

    # ---- Normal SO ----
    for item in so_items_map.get(so_name, []):

        item_group = item_group_map.get(item["item_code"])

        if item_group == "Books Bundle":

            bom_tree = resolve_bom_tree_from_cache(item["item_code"], bom_cache)
            flat_items = flatten_bom(bom_tree, item["qty"])
            final_items.extend(flat_items)

        else:

            final_items.append({
                "item_code": item["item_code"],
                "qty": item["qty"]
            })

    return final_items


# =====================================================
# SHARED STOCK / ASN HELPERS
# =====================================================

def fetch_stock_map(warehouses):

    if warehouses:
        bins = frappe.db.sql("""
            SELECT item_code, SUM(actual_qty) AS qty
            FROM `tabBin`
            WHERE warehouse IN %(warehouses)s
            GROUP BY item_code
        """, {"warehouses": tuple(warehouses)}, as_dict=True)
    else:
        bins = frappe.db.sql("""
            SELECT item_code, SUM(actual_qty) AS qty
            FROM `tabBin`
            GROUP BY item_code
        """, as_dict=True)

    return {b.item_code: (b.qty or 0) for b in bins}


def fetch_asn_map(warehouses):

    asn_map = {}

    try:

        if not frappe.db.table_exists("ASN Child Table"):
            return asn_map

        if warehouses:
            rows = frappe.db.sql("""
                SELECT
                    c.product_code AS item_code,
                    SUM(c.pending_qty) AS qty
                FROM `tabASN Child Table` c
                JOIN `tabASN Creation` a ON a.name = c.parent
                JOIN `tabPurchase Order` po ON po.name = c.po_no
                WHERE c.status != 'Delivered'
                  AND a.docstatus < 2
                  AND po.set_warehouse IN %(warehouses)s
                GROUP BY c.product_code
            """, {"warehouses": tuple(warehouses)}, as_dict=True)
        else:
            rows = frappe.db.sql("""
                SELECT
                    c.product_code AS item_code,
                    SUM(c.pending_qty) AS qty
                FROM `tabASN Child Table` c
                JOIN `tabASN Creation` a ON a.name = c.parent
                WHERE c.status != 'Delivered'
                  AND a.docstatus < 2
                GROUP BY c.product_code
            """, as_dict=True)

        asn_map = {r.item_code: (r.qty or 0) for r in rows}   # BUG FIX: was `asn_rows`

    except Exception as e:
        frappe.log_error(
            title="Error fetching ASN data for sales dashboard",
            message=str(e)
        )

    return asn_map


# =====================================================
# MAIN DASHBOARD
# =====================================================

@frappe.whitelist()
def get_sales_dashboard(page=1, page_size=10, warehouses=None):

    page = int(page)
    page_size = int(page_size)

    if isinstance(warehouses, str):
        warehouses = frappe.parse_json(warehouses)

    data = {}

    # -------------------------------------------------
    # STEP 1 : SALES ORDERS
    # -------------------------------------------------

    orders = frappe.db.get_all(
        "Sales Order",
        filters={
            "docstatus": 1,
            "status": ["in", ["To Deliver and Bill"]]
        },
        fields=[
            "name",
            "customer",
            "grand_total",
            "transaction_date",
            "status",
            "creation",
            "custom_magic_box"
        ],
        order_by="transaction_date asc, creation asc"
    )

    data["total_orders"] = len(orders)
    data["total_amount"] = sum(o.grand_total or 0 for o in orders)

    so_names = [o.name for o in orders]

    if not so_names:
        data.update({
            "fulfillable_orders": 0,
            "unfulfillable_orders": 0,
            "orders": [],
            "asn_map": {},
            "total_rows": 0
        })
        return data


    # -------------------------------------------------
    # STEP 2 : BULK-LOAD ALL SO ITEM DATA  (2 queries)
    # -------------------------------------------------

    so_items_map, so_subitem_map = load_all_so_data(so_names)


    # -------------------------------------------------
    # STEP 3 : BULK-LOAD ITEM GROUPS  (1 query)
    # -------------------------------------------------

    all_raw_item_codes = set()

    for rows in so_items_map.values():
        for r in rows:
            all_raw_item_codes.add(r["item_code"])

    for rows in so_subitem_map.values():
        for r in rows:
            all_raw_item_codes.add(r["item_code"])

    item_group_rows = frappe.db.sql("""
        SELECT name, item_group
        FROM `tabItem`
        WHERE name IN %(items)s
    """, {"items": tuple(all_raw_item_codes)}, as_dict=True)

    item_group_map = {i.name: i.item_group for i in item_group_rows}


    # -------------------------------------------------
    # STEP 4 : BULK-LOAD BOM CACHE  (2–4 queries total)
    # -------------------------------------------------

    bundle_items = {
        code for code in all_raw_item_codes
        if item_group_map.get(code) == "Books Bundle"
    }

    bom_cache = build_bom_cache(bundle_items)


    # -------------------------------------------------
    # STEP 5 : RESOLVE ALL SO ITEMS ONCE, COLLECT ITEM CODES
    # -------------------------------------------------

    so_flag_map = {o.name: o.custom_magic_box for o in orders}

    resolved_so_items = {}   # so_name → [ {item_code, qty} ]
    all_item_codes = set()

    for so in orders:
        items = resolve_so_items_from_cache(
            so.name,
            so_flag_map[so.name],
            so_items_map,
            so_subitem_map,
            item_group_map,
            bom_cache
        )
        resolved_so_items[so.name] = items
        for it in items:
            all_item_codes.add(it["item_code"])


    # -------------------------------------------------
    # STEP 6 : ITEM SETTINGS  (1 query)
    # -------------------------------------------------

    items_meta = frappe.db.get_all(
        "Item",
        filters={"name": ["in", list(all_item_codes)]},
        fields=["name", "is_stock_item", "safety_stock"]
    )

    item_settings = {i.name: i for i in items_meta}


    # -------------------------------------------------
    # STEP 7 : STOCK MAP + ASN MAP  (2–3 queries)
    # -------------------------------------------------

    stock_map = fetch_stock_map(warehouses)
    asn_map   = fetch_asn_map(warehouses)


    # -------------------------------------------------
    # STEP 8 : PROCESS ORDERS
    # -------------------------------------------------

    results = []
    fulfillable_orders   = 0
    unfulfillable_orders = 0

    for so in orders:

        so_items = resolved_so_items[so.name]   # already resolved — no extra work

        total_items     = len(so_items)
        fulfilled_items = 0
        item_details    = []

        for it in so_items:

            item_code = it["item_code"]
            req_qty   = it["qty"] or 0

            stock_used = 0
            asn_used   = 0
            remaining  = req_qty

            setting      = item_settings.get(item_code)
            is_stock_item = 1 if setting and setting.is_stock_item else 0
            min_stock     = setting.safety_stock if setting else 0

            # ---- Non-stock item ----
            if not is_stock_item:
                stock_used = 0
                asn_used   = 0
                remaining  = 0
                fulfilled_items += 1

            else:

                # --- Stock ---
                stock_available = stock_map.get(item_code, 0)

                if stock_available > 0:
                    use        = min(stock_available, remaining)
                    stock_used = use
                    remaining -= use
                    stock_map[item_code] -= use

                # --- ASN ---
                if remaining > 0:
                    asn_available = asn_map.get(item_code, 0)

                    if asn_available > 0:
                        use       = min(asn_available, remaining)
                        asn_used  = use
                        remaining -= use
                        asn_map[item_code] -= use

                if remaining == 0:
                    fulfilled_items += 1

            stock_balance = stock_map.get(item_code, 0)
            asn_balance   = asn_map.get(item_code, 0)
            total_balance = stock_balance + asn_balance

            item_details.append({
                "item_code":      item_code,
                "requested_qty":  req_qty,
                "stock_used":     stock_used,
                "asn_used":       asn_used,
                "remaining_need": remaining,
                "stock_balance":  stock_balance,
                "asn_balance":    asn_balance,
                "total_balance":  total_balance,
                "is_stock_item":  is_stock_item,
                "min_stock":      min_stock
            })

        percent = round((fulfilled_items / total_items) * 100) if total_items else 0

        if percent == 100:
            fulfillable_orders += 1
        else:
            unfulfillable_orders += 1

        results.append({
            "sales_order":    so.name,
            "order_type":     "magic_box" if so.custom_magic_box else "regular",
            "transaction_date": so.transaction_date,
            "status":         so.status,
            "creation":       so.creation,
            "customer":       so.customer,
            "amount":         so.grand_total,
            "fulfillment":    percent,
            "items":          item_details
        })

    data["fulfillable_orders"]   = fulfillable_orders
    data["unfulfillable_orders"] = unfulfillable_orders


    # -------------------------------------------------
    # STEP 9 : PAGINATION
    # -------------------------------------------------

    start = (page - 1) * page_size
    end   = start + page_size

    data["orders"]     = results[start:end]
    data["asn_map"]    = asn_map
    data["total_rows"] = len(results)

    return data


# =====================================================
# RESOLVE SALES ORDER DEMAND  (bulk version)
# =====================================================

def get_sales_order_item_demand(so_list=None, so_items_map=None,
                                so_subitem_map=None, item_group_map=None,
                                bom_cache=None):
    """
    Accepts pre-loaded caches when called from get_warehouse_sales_projection
    to avoid duplicate DB work. Falls back to self-loading for standalone use.
    """

    demand_map = {}

    if so_list is None:

        orders = frappe.get_all(
            "Sales Order",
            filters={
                "docstatus": 1,
                "status": "To Deliver and Bill"
            },
            fields=["name", "custom_magic_box"]
        )

    else:
        orders = so_list

    if not orders:
        return demand_map

    so_names = [o.name for o in orders]

    # ---- load caches if not provided ----

    if so_items_map is None or so_subitem_map is None:
        so_items_map, so_subitem_map = load_all_so_data(so_names)

    if item_group_map is None:
        all_codes = set()
        for rows in so_items_map.values():
            for r in rows:
                all_codes.add(r["item_code"])
        item_group_rows = frappe.db.sql("""
            SELECT name, item_group
            FROM `tabItem`
            WHERE name IN %(items)s
        """, {"items": tuple(all_codes)}, as_dict=True)
        item_group_map = {i.name: i.item_group for i in item_group_rows}

    if bom_cache is None:
        bundle_items = {
            code for code in item_group_map
            if item_group_map[code] == "Books Bundle"
        }
        bom_cache = build_bom_cache(bundle_items)

    # ---- accumulate demand ----

    for so in orders:

        if so.custom_magic_box:
            for row in so_subitem_map.get(so.name, []):
                demand_map[row["item_code"]] = (
                    demand_map.get(row["item_code"], 0) + row["qty"]
                )
            continue

        for item in so_items_map.get(so.name, []):

            item_group = item_group_map.get(item["item_code"])

            if item_group == "Books Bundle":

                bom_tree  = resolve_bom_tree_from_cache(item["item_code"], bom_cache)
                flat_items = flatten_bom(bom_tree, item["qty"])

                for fi in flat_items:
                    demand_map[fi["item_code"]] = (
                        demand_map.get(fi["item_code"], 0) + fi["qty"]
                    )

            else:
                demand_map[item["item_code"]] = (
                    demand_map.get(item["item_code"], 0) + item["qty"]
                )

    return demand_map


# =====================================================
# WAREHOUSE SALES PROJECTION
# =====================================================

@frappe.whitelist()
def get_warehouse_sales_projection(warehouses=None):

    if isinstance(warehouses, str):
        warehouses = frappe.parse_json(warehouses)

    # ------------------------------------------------
    # STEP 1 : ORDERS
    # ------------------------------------------------

    orders = frappe.get_all(
        "Sales Order",
        filters={
            "docstatus": 1,
            "status": "To Deliver and Bill"
        },
        fields=["name", "custom_magic_box"]
    )

    if not orders:
        return []

    so_names = [o.name for o in orders]

    # ------------------------------------------------
    # STEP 2 : BULK LOAD ALL DATA UPFRONT
    # ------------------------------------------------

    so_items_map, so_subitem_map = load_all_so_data(so_names)

    # all raw item codes (before BOM expansion)
    all_raw_codes = set()
    for rows in so_items_map.values():
        for r in rows:
            all_raw_codes.add(r["item_code"])
    for rows in so_subitem_map.values():
        for r in rows:
            all_raw_codes.add(r["item_code"])

    item_group_rows = frappe.db.sql("""
        SELECT name, item_group
        FROM `tabItem`
        WHERE name IN %(items)s
    """, {"items": tuple(all_raw_codes)}, as_dict=True)

    item_group_map = {i.name: i.item_group for i in item_group_rows}

    bundle_items = {
        code for code in all_raw_codes
        if item_group_map.get(code) == "Books Bundle"
    }

    bom_cache = build_bom_cache(bundle_items)

    # ------------------------------------------------
    # STEP 3 : DEMAND  (reuses all caches — no extra queries)
    # ------------------------------------------------

    demand_map = get_sales_order_item_demand(
        so_list        = orders,
        so_items_map   = so_items_map,
        so_subitem_map = so_subitem_map,
        item_group_map = item_group_map,
        bom_cache      = bom_cache
    )

    item_list = list(demand_map.keys())

    if not item_list:
        return []

    # ------------------------------------------------
    # STEP 4 : ITEM SETTINGS  (1 query)
    # ------------------------------------------------

    item_rows = frappe.db.get_all(
        "Item",
        filters={"name": ["in", item_list]},
        fields=["name", "is_stock_item", "safety_stock"]
    )

    item_settings = {i.name: i for i in item_rows}

    # ------------------------------------------------
    # STEP 5 : STOCK + ASN  (2–3 queries)
    # ------------------------------------------------

    stock_map = fetch_stock_map(warehouses)
    asn_map   = fetch_asn_map(warehouses)

    # ------------------------------------------------
    # STEP 6 : BUILD RESULT
    # ------------------------------------------------

    result = []

    for item_code in item_list:

        item_setting  = item_settings.get(item_code)
        is_stock_item = item_setting.is_stock_item if item_setting else 0
        min_stock     = item_setting.safety_stock  if item_setting else 0

        stock   = stock_map.get(item_code, 0)
        asn     = asn_map.get(item_code, 0)
        demand  = demand_map.get(item_code, 0)

        total_available = stock + asn
        balance = (total_available - demand) if is_stock_item else total_available

        result.append({
            "item_code":            item_code,
            "stock":                stock,
            "asn":                  asn,
            "total_available":      total_available,
            "sales_order_demand":   demand,
            "balance_after_orders": balance,
            "is_stock_item":        is_stock_item,
            "min_stock":            min_stock
        })

    return result