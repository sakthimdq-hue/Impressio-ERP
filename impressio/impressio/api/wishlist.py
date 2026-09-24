import frappe
from impressio.impressio.api.base import BaseAPI
from impressio.impressio.api.helper import sanitize_request,  success, error, validate_fields, get_customer_shipping_address,is_book_item, get_full_image_url, validate_customer_access
from frappe.utils import get_url

@frappe.whitelist(allow_guest=True)
def toggle_wishlist(**kwargs):
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required", 401)
 
    is_error, payload = sanitize_request(
        kwargs,
        required=["item_code"]
    )
    if is_error:
        return error(payload, 422)

    item_code = payload.get("item_code")

    if not frappe.db.exists("Item", item_code):
        return error("Invalid Item Code", 422)

    wishlist_name = frappe.db.get_value(
        "Website Wishlist",
        {
            "website_user": user.name,
            "item_code": item_code
        },
        "name"
    )

    # -----------------------------
    # REMOVE if exists
    # -----------------------------
    if wishlist_name:
        frappe.delete_doc(
            "Website Wishlist",
            wishlist_name,
            ignore_permissions=True
        )

        return success("Item removed from wishlist", {
            "item_code": item_code,
            "in_wishlist": 0
        })

    # -----------------------------
    # ADD if not exists
    # -----------------------------
    wishlist = frappe.new_doc("Website Wishlist")
    wishlist.website_user = user.name
    wishlist.item_code = item_code
    wishlist.added_on = frappe.utils.now()
    wishlist.insert(ignore_permissions=True)

    return success("Item added to wishlist", {
        "item_code": item_code,
        "in_wishlist": 1
    })


@frappe.whitelist(allow_guest=True)
def wishlist_items():
    api = BaseAPI()
    user = api.user

    if not user:
        return error("Login required")

    wishlist = frappe.get_all(
        "Website Wishlist",
        filters={"website_user": user.name},
        fields=["item_code", "added_on"],
        order_by="added_on desc"
    )

    items = []

    for row in wishlist:
        item = frappe.get_doc("Item", row.item_code)

        price = frappe.get_value(
            "Item Price",
            {"item_code": item.name},
            "price_list_rate"
        ) or 0

        parent_item_code = item.variant_of if item.variant_of else item.name
        has_attributes = 1 if item.variant_of else 0

        attributes = {}
        if has_attributes:
            attrs = frappe.get_all(
                "Item Variant Attribute",
                filters={"parent": item.name},
                fields=["attribute", "attribute_value"]
            )
            attributes = {
                a.attribute: a.attribute_value
                for a in attrs
            }

        item_type = "book" if is_book_item(item.name) else "product"

        items.append({
            "item_code": item.name,
            "parent_item_code": parent_item_code,
            "item_name": item.item_name,
            "rate": price,
            "uom": item.stock_uom,
            "image": get_full_image_url(item.image),
            "has_attributes": has_attributes,
            "attributes": attributes,
            "type": item_type,
            "added_on": row.added_on
        })

    return {
        "total_items": len(items),
        "items": items
    }
