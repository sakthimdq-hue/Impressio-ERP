import frappe
from frappe.model.document import Document

class OrderProcessingAgainstWebsiteOrders(Document):
    def on_update(self):
        # Called automatically when OP document is saved
        update_op_orders(self.asn_no)

# ---------------- INBOUND TRANSIT -----------------

def update_op_orders(asn_name):
    """
    Update all OP Against Website Orders linked to an ASN
    with ASN status and Transit status
    """
    if not asn_name:
        return

    # Get all OP orders linked to this ASN
    orders = frappe.get_all(
        "Order Processing Against Website Orders",
        filters={"asn_no": asn_name},
        fields=["name"]
    )

    if not orders:
        return

    # Get ASN document
    asn = frappe.get_doc("ASN Creation", asn_name)

    # Map ASN status → Transit Status
    status_map = {
        "In Progress": "In Transit",
        "In Transit": "In Transit",
        "Arrived": "Arrived",
        "Completed": "Completed"
    }
    transit_status = status_map.get(asn.asn_status, "In Transit")

    # Update each OP order
    for op in orders:
        doc = frappe.get_doc("Order Processing Against Website Orders", op.name)
        doc.asn_status = asn.asn_status
        doc.transit_status = transit_status
        doc.save(ignore_permissions=True)

# ---------------- FETCH SALES ORDER DETAILS -----------------

@frappe.whitelist()
def fetch_order_details_and_items(order_no):
    """
    Fetch Sales Order details + items for OP document
    """
    so = frappe.get_doc("Sales Order", order_no)
    items = []

    for item in so.items:
        items.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "delivered_qty": item.delivered_qty,
            "warehouse": item.warehouse or so.get("set_warehouse") or "",
            "batch_no": item.get("batch_no", ""),
            "category": item.item_group,
            "date": so.transaction_date
        })

    return {
        "customer_name": so.customer,
        "date": so.transaction_date,
        "items": items
    }

# ---------------- FILTER FUNCTIONS -----------------

@frappe.whitelist()
def get_0_to_50_completed_orders():
    return get_orders_in_range(0, 50)

@frappe.whitelist()
def get_50_to_100_completed_orders():
    return get_orders_in_range(50, 100)

@frappe.whitelist()
def get_fully_completed_orders():
    return get_orders_in_range(100, 100)

def get_orders_in_range(min_p, max_p):
    """
    Helper: Get OP orders filtered by completion_percentage
    """
    orders = frappe.get_all(
        "Order Processing Against Website Orders",
        fields=["name", "order_no", "customer_name", "date", "completion_percentage"]
    )

    results = []
    for order in orders:
        percentage = order.completion_percentage or 0
        if min_p <= percentage <= max_p:
            status = get_status_label(percentage)
            results.append({
                "name": order.name,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "date": order.date,
                "completion_percentage": percentage,
                "completion_status": status
            })
    return results

def get_status_label(p):
    """
    Convert completion percentage → status label
    """
    if p == 100:
        return "Fully Completed"
    if 50 <= p < 100:
        return "50-100% Completed"
    if 0 <= p < 50:
        return "0-50% Completed"
    return "Not Started"

# ---------------- ASN AVAILABILITY FILTER -----------------

@frappe.whitelist()
def filter_by_asn_availability():
    """
    Filter orders based on ASN availability
    Returns ALL orders with their ASN fulfillment status and warehouse stock
    """
    try:
        # Get all Order Processing documents
        orders = frappe.get_all(
            "Order Processing Against Website Orders",
            fields=["name", "order_no", "customer_name", "completion_percentage", 
                    "transit_status", "asn_no", "asn_status"]
        )
        
        filtered_orders = []
        order_names = []
        total_items_with_stock = 0
        total_items_missing_stock = 0
        
        # Get ALL active ASNs first for better performance
        all_asn_products = frappe.db.sql("""
            SELECT 
                pc.product_code,
                pc.pending_qty,
                ac.name as asn_name,
                ac.asn_status,
                ac.vendor_name
            FROM `tabASN Creation` ac
            INNER JOIN `tabASN Child Table` pc ON ac.name = pc.parent
            WHERE ac.asn_status IN ('In Progress', 'Arrived', 'In Transit')
            AND ac.docstatus = 1
            ORDER BY ac.creation DESC
        """, as_dict=True)
        
        # Create a dictionary of ASN products by product_code
        asn_product_map = {}
        for product in all_asn_products:
            product_code = product.product_code
            if product_code not in asn_product_map:
                asn_product_map[product_code] = []
            asn_product_map[product_code].append(product)
        
        # Track processed order numbers to avoid duplicates
        processed_order_nos = set()
        
        for order in orders:
            # Skip if we already processed this order number (avoid duplicates)
            if order.order_no in processed_order_nos:
                continue
                
            processed_order_nos.add(order.order_no)
            
            # Get order items
            order_doc = frappe.get_doc("Order Processing Against Website Orders", order.name)
            order_items = order_doc.get("table", [])
            
            if not order_items:
                continue
                
            order_data = {
                "name": order.name,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "completion_percentage": order.completion_percentage or 0,
                "transit_status": order.transit_status or "",
                "asn_no": order.asn_no or "",
                "asn_status": order.asn_status or "",
                "items": [],
                "can_fulfill_all": False,
                "can_fulfill_some": False,
                "total_items": len(order_items),
                "fulfillable_items": 0,
                "missing_items": 0,
                "total_shortage": 0,
                "show_in_filter": True
            }
            
            items_with_stock = 0
            items_missing_stock = 0
            total_shortage = 0
            
            # Check each item against ASN and Warehouse
            for item in order_items:
                item_code = item.item_code
                order_qty = item.qty or 0
                warehouse = item.warehouse or ""
                
                # Get warehouse stock quantity
                warehouse_qty = 0
                if warehouse:
                    warehouse_qty = get_warehouse_stock(item_code, warehouse)
                
                # Find ASN with this product
                can_fulfill_asn = False
                asn_pending_qty = 0
                best_asn = None
                asn_name = ""
                asn_status = ""
                
                if item_code in asn_product_map:
                    # Get all ASNs that have this product
                    asn_products = asn_product_map[item_code]
                    
                    # Find the best ASN (highest pending quantity)
                    for asn_product in asn_products:
                        available_qty = asn_product.pending_qty or 0
                        if available_qty >= order_qty:
                            can_fulfill_asn = True
                            asn_pending_qty = available_qty
                            best_asn = asn_product
                            break
                        elif available_qty > asn_pending_qty:
                            # Track the ASN with highest quantity even if not enough
                            asn_pending_qty = available_qty
                            best_asn = asn_product
                
                if best_asn:
                    asn_name = best_asn.asn_name
                    asn_status = best_asn.asn_status
                
                # Check if item can be fulfilled from either source
                can_fulfill_warehouse = warehouse_qty >= order_qty
                can_fulfill = can_fulfill_asn or can_fulfill_warehouse
                
                # Calculate shortage
                total_available = max(asn_pending_qty, warehouse_qty)
                shortage = max(0, order_qty - total_available)
                
                if can_fulfill:
                    items_with_stock += 1
                    total_items_with_stock += 1
                else:
                    items_missing_stock += 1
                    total_items_missing_stock += 1
                    total_shortage += shortage
                
                # Determine fulfillment source
                fulfillment_source = ""
                if can_fulfill_asn and can_fulfill_warehouse:
                    fulfillment_source = "both"
                elif can_fulfill_asn:
                    fulfillment_source = "asn"
                elif can_fulfill_warehouse:
                    fulfillment_source = "warehouse"
                else:
                    fulfillment_source = "none"
                
                order_data["items"].append({
                    "item_code": item_code,
                    "item_name": item.item_name or item_code,
                    "order_qty": order_qty,
                    "warehouse_qty": warehouse_qty,
                    "warehouse": warehouse,
                    "asn_pending_qty": asn_pending_qty,
                    "asn_name": asn_name,
                    "asn_status": asn_status,
                    "can_fulfill": can_fulfill,
                    "can_fulfill_asn": can_fulfill_asn,
                    "can_fulfill_warehouse": can_fulfill_warehouse,
                    "fulfillment_source": fulfillment_source,
                    "shortage": shortage,
                    "total_available": total_available
                })
            
            # Store counts for this order
            order_data["fulfillable_items"] = items_with_stock
            order_data["missing_items"] = items_missing_stock
            order_data["total_shortage"] = total_shortage
            
            # Determine if order can be fulfilled (from either ASN or warehouse)
            if items_with_stock > 0:
                order_data["can_fulfill_some"] = True
                if items_missing_stock == 0:
                    order_data["can_fulfill_all"] = True
            
            filtered_orders.append(order_data)
            order_names.append(order.name)
        
        # Sort orders by fulfillment status
        filtered_orders.sort(key=lambda x: (
            not x["can_fulfill_all"],  # Fully fulfillable first
            not x["can_fulfill_some"],  # Partially fulfillable next
            x["total_shortage"],  # Then by total shortage (lowest first)
            x["order_no"]  # Finally by order number
        ))
        
        return {
            "orders": filtered_orders,
            "order_names": order_names,
            "total_orders": len(filtered_orders),
            "total_items": sum(len(order["items"]) for order in filtered_orders),
            "total_items_with_stock": total_items_with_stock,
            "total_items_missing_stock": total_items_missing_stock,
            "total_shortage_all_orders": sum(order["total_shortage"] for order in filtered_orders),
            "summary": {
                "orders_can_fulfill_all": sum(1 for order in filtered_orders if order["can_fulfill_all"]),
                "orders_partial_only": sum(1 for order in filtered_orders if order["can_fulfill_some"] and not order["can_fulfill_all"]),
                "orders_cannot_fulfill": sum(1 for order in filtered_orders if not order["can_fulfill_some"]),
                "total_order_items": sum(len(order["items"]) for order in filtered_orders)
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error in filter_by_asn_availability: {str(e)}", "ASN Filter Error")
        frappe.log_error(frappe.get_traceback(), "ASN Filter Error")
        return {
            "orders": [],
            "order_names": [],
            "total_orders": 0,
            "total_items": 0,
            "total_items_with_stock": 0,
            "total_items_missing_stock": 0,
            "total_shortage_all_orders": 0,
            "summary": {
                "orders_can_fulfill_all": 0,
                "orders_partial_only": 0,
                "orders_cannot_fulfill": 0,
                "total_order_items": 0
            },
            "error": str(e),
            "traceback": frappe.get_traceback()
        }

def get_warehouse_stock(item_code, warehouse):
    """
    Get available stock quantity for an item in a specific warehouse
    """
    try:
        # Check if Bin exists for this item in the warehouse
        bin_data = frappe.db.get_value("Bin", {
            "item_code": item_code,
            "warehouse": warehouse
        }, ["actual_qty", "reserved_qty"], as_dict=True)
        
        if bin_data:
            # Calculate available quantity (actual_qty - reserved_qty)
            actual_qty = bin_data.actual_qty or 0
            reserved_qty = bin_data.reserved_qty or 0
            available_qty = actual_qty - reserved_qty
            return max(available_qty, 0)  # Return 0 if negative
        else:
            # Check if item exists in Stock Ledger Entry
            sle_data = frappe.db.sql("""
                SELECT SUM(actual_qty) as total_qty
                FROM `tabStock Ledger Entry`
                WHERE item_code = %s AND warehouse = %s
                GROUP BY item_code, warehouse
            """, (item_code, warehouse), as_dict=True)
            
            if sle_data and sle_data[0].total_qty:
                return max(sle_data[0].total_qty, 0)
            else:
                return 0
    except Exception as e:
        frappe.log_error(f"Error getting warehouse stock for {item_code} in {warehouse}: {str(e)}")
        return 0