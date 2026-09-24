# File: /home/mdq/frappe-bench-v15/apps/inventre/inventre/material_out/api/logistics/utils.py
"""
Main utility functions for multi-carrier logistics
"""

import frappe
import json
from frappe import _
from frappe.utils import now_datetime
from .carrier_factory import get_carrier_instance
from frappe.utils import now


def get_item_description(doc):
    """
    Uses SO custom_sub_items:
    - parent_item_code == item_code  → standalone item (show parent_item_code + qty)
    - parent_item_code != item_code  → sub-item (show parent_item_code, deduplicated, no qty)
    """
    try:
        parent_names = {}   # { "CAS LR CBSE Grade 1 Bookkit": True } — deduped, no qty
        main_items   = {}   # { "SAS BP Sports Track": 1.0 }           — with qty

        def _clean(name):
            """Strip $$ suffix, colons, extra spaces"""
            if not name:
                return ""
            if '$$' in name:
                name = name.split('$$')[0]
            return name.lstrip(':').strip()

        def _process_sub_items(rows):
            for row in rows:
                parent_code = (row.get("parent_item_code") or "").strip()
                item_code   = (row.get("item_code") or "").strip()
                qty         = float(row.get("qty") or 1)

                if not parent_code:
                    continue

                if parent_code == item_code:
                    # ── Standalone item: same code on both sides ──
                    label = _clean(parent_code)
                    if not label:
                        continue
                    if len(label) > 35:
                        label = label[:32] + "..."
                    main_items[label] = main_items.get(label, 0) + qty
                else:
                    # ── Sub-item: parent is the kit/bundle name ──
                    label = _clean(parent_code)
                    if not label:
                        continue
                    if len(label) > 35:
                        label = label[:32] + "..."
                    parent_names[label] = True   # dedup

        # ── Priority 1: Sales Order custom_sub_items ──
        sales_order_id = None
        if doc.get("sales_order") and frappe.db.exists("Sales Order", doc.sales_order):
            sales_order_id = doc.sales_order
        elif doc.get("order_no") and frappe.db.exists("Sales Order", doc.order_no):
            sales_order_id = doc.order_no
        elif doc.get("order_no") and frappe.db.exists("Delivery Note", doc.order_no):
            # order_no is a DN — find the linked SO via DN items
            try:
                so_from_dn = frappe.db.get_value(
                    "Delivery Note Item",
                    {"parent": doc.order_no},
                    "custom_custom_against_sales_order"
                )
                if so_from_dn and frappe.db.exists("Sales Order", so_from_dn):
                    sales_order_id = so_from_dn
            except Exception:
                pass

        if sales_order_id:
            sub_items = []
            try:
                if frappe.db.table_exists("Sale Order Sub Items"):
                    sub_items = frappe.db.sql("""
                        SELECT parent_item_code, item_code, qty
                        FROM `tabSale Order Sub Items`
                        WHERE parent = %s
                        ORDER BY idx ASC
                    """, sales_order_id, as_dict=True)
            except Exception:
                sub_items = []

            if sub_items:
                _process_sub_items(sub_items)

        # ── Priority 2: packing_materials fallback ──
        if not parent_names and not main_items and doc.get("packing_materials"):
            for row in doc.packing_materials:
                item_name = (row.get("item_name") or row.get("item_code") or "").strip()
                qty = float(row.get("qty") or 1)
                label = _clean(item_name)
                if not label:
                    continue
                if len(label) > 35:
                    label = label[:32] + "..."
                main_items[label] = main_items.get(label, 0) + qty

        # ── Priority 3: Final fallback ──
        if not parent_names and not main_items:
            return doc.description or "General Goods"

        # ── Build display list ──
        result = []
        for name in parent_names:                      # sub-item parents, no qty
            result.append(name)
        for name, qty in main_items.items():           # standalone items, with qty
            result.append(f"{name} x{int(qty)}")

        # ── Format ──
        total = len(result)
        if total == 1:
            return result[0]
        elif total <= 3:
            desc = ", ".join(result)
            return desc[:200] if len(desc) <= 200 else desc[:197] + "..."
        elif total <= 10:
            return f"{', '.join(result[:3])} + {total - 3} more items"
        else:
            return f"{', '.join(result[:2])} + {total - 2} more items"

    except Exception as e:
        frappe.log_error("get_item_description failed", str(e))
        return doc.description or "General Goods"
 
    

@frappe.whitelist()
def create_shipment(docname):
    """Create shipment with selected carrier"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)

        # ---------------------------------------------
        # BASIC REQUIRED FIELDS (ALL CARRIERS)
        # ---------------------------------------------
        required_fields = [
            "customer_name",
            "address",
            "pincode",
            "location",
            "state"
        ]

        missing_fields = []
        for field in required_fields:
            if not doc.get(field):
                missing_fields.append(frappe.unscrub(field))

        if missing_fields:
            frappe.throw(_("Please fill in: {0}").format(", ".join(missing_fields)))

        # Warn if address is too long
        if doc.address and len(doc.address.strip()) > 180:
            frappe.throw(_(
                "Address is too long ({0} chars). Maximum allowed is 180 characters. "
                "Please shorten it."
            ).format(len(doc.address.strip())))

        # Warn if declared value is 0
        if not doc.declared_value or float(doc.declared_value) <= 0:
            frappe.throw(_(
                "Declared value must be greater than 0. "
                "Please enter the shipment value."
            ))

        # ---------------------------------------------
        # Prevent duplicate shipment
        # ---------------------------------------------
        if doc.logistics_tracking_number:
            frappe.throw(_("Tracking number already exists"))

        # ---------------------------------------------
        # Get carrier
        # ---------------------------------------------
        carrier = get_carrier_instance(doc.logistics_partner)

                # ---------------------------------------------
        # Determine the label package reference (Order ID)
        # This appears as INVOICE ID on the Amazon label
        # Priority: Sales Order > Delivery Note's linked Sales Order > HLG Name
        # ---------------------------------------------
        order_id_for_label = None

        # First priority: Direct Sales Order
        if doc.sales_order:
            order_id_for_label = doc.sales_order
        elif doc.order_no:
            # Check if order_no is a Sales Order
            if frappe.db.exists("Sales Order", doc.order_no):
                order_id_for_label = doc.order_no
            else:
                # It might be a Delivery Note - try to find linked Sales Order
                try:
                    if frappe.db.exists("Delivery Note", doc.order_no):
                        dn = frappe.get_doc("Delivery Note", doc.order_no)
                        if dn.items and len(dn.items) > 0:
                            # FIRST check custom_custom_against_sales_order
                            for item in dn.items:
                                if item.get('custom_custom_against_sales_order'):
                                    order_id_for_label = item.custom_custom_against_sales_order
                                    break
                            # If not found, check against_sales_order
                            if not order_id_for_label:
                                for item in dn.items:
                                    if item.get('against_sales_order'):
                                        order_id_for_label = item.against_sales_order
                                        break
                except:
                    pass
                
                # If still no Sales Order found, use Delivery Note name
                if not order_id_for_label:
                    order_id_for_label = doc.order_no

        # Final fallback
        if not order_id_for_label:
            order_id_for_label = doc.name
        
        # ========== CLEAN ORDER ID FOR LABEL DISPLAY ==========
        # Keep full Sales Order ID, just remove special characters
        original_id = order_id_for_label
        import re
        order_id_for_label = re.sub(r'[^\w\s\-]', '', original_id)
        
        frappe.log_error(
            "Order ID for Amazon Label",
            f"Displaying: {order_id_for_label}"
        )
        # ========== END OF ORDER ID LOGIC ==========
        
        # ---------------------------------------------
        # Prepare shipment data
        # ---------------------------------------------
        shipment_data = {
            "external_id": doc.name,
            "order_id_for_label": order_id_for_label,
            "customer": {
                "name": doc.customer_name.strip(),
                "phone": (doc.customer_phone or "").strip(),
                "pincode": str(doc.pincode).strip(),
                "address": doc.address.strip(),
                "city": doc.location.strip(),
                "state": doc.state.strip()
            },
            "package": {
                "weight": float(doc.weight or 0.5),
                "dimensions": {
                    "length": float(doc.length or 10),
                    "width": float(doc.width or 10),
                    "height": float(doc.height or 10)
                },
                "value": float(doc.declared_value or 1),
                "description": get_item_description(doc),
                "cbm": float(doc.total_cbm or 0),
                "max_dimension": float(doc.max_dimension or 0)
            },
            "order": {
                "id": order_id_for_label,
                "invoice_value": float(doc.invoice_value or 0),
                "invoice_number": doc.invoice_number or "",
                "payment_type": doc.payment_type or "Prepaid",
                "cod_amount": float(doc.cod_amount or 0)
            },
            "service_type": doc.service_type or "",
            "shipment_category": doc.shipment_category or "Non-Large",
            # "is_large_shipment": doc.shipment_category == "Large"
        }

        # ---------------------------------------------
        # Create shipment
        # ---------------------------------------------
                # ✅ FIXED CODE
        result = carrier.create_shipment(shipment_data)

        # Store label_package_ref in result so download knows what ref was used
        result["label_package_ref"] = order_id_for_label

        # ✅ CHECK IF CARRIER ACTUALLY ACCEPTED THE SHIPMENT
        if not result.get("success"):
            error_msg = result.get("error_message") or result.get("error") or "Shipment was rejected by carrier"
            
            # Still save the failed response for debugging
            doc.carrier_response = json.dumps(result, indent=2)
            doc.carrier_status = "Exception"
            doc.save(ignore_permissions=True)
            frappe.db.commit()

            frappe.throw(
                _("Shipment rejected by {0}: {1}").format(
                    doc.logistics_partner,
                    error_msg
                )
            )

        # ✅ ONLY reach here if success is True
        doc.logistics_tracking_number = result.get("tracking_number")
        doc.carrier_response = json.dumps(result, indent=2)
        doc.carrier_name = doc.logistics_partner
        doc.carrier_status = "Created"

        if doc.logistics_partner == "Ekart":
            doc.ekart_tracking_number = result.get("tracking_number")
            doc.ekart_awb_number = result.get("awb_number")
            doc.ekart_shipment_status = "Created"
            doc.ekart_manifest_id = result.get("manifest_id", "")

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.msgprint(
            _("{0} shipment created! Tracking ID: {1}").format(
                doc.logistics_partner,
                result.get("tracking_number")
            ),
            indicator="green",
            alert=True
        )

        return {
            "status": "success",
            "carrier": doc.logistics_partner,
            "tracking_number": result.get("tracking_number"),
            "message": _("Shipment created successfully")
        }

    except Exception as e:
        frappe.log_error(
            title="Shipment Creation Failed",
            message=f"Doc: {docname}\nError: {str(e)}"
        )
        frappe.throw(_("Failed to create shipment: {0}").format(str(e)))


@frappe.whitelist()
def get_available_services(carrier=None, docname=None):
    """Get available service types for carrier"""
    try:
        if carrier:
            carrier_name = carrier
        elif docname:
            doc = frappe.get_doc("Handover To Logistics", docname)
            carrier_name = doc.logistics_partner
        else:
            return []

        carrier = get_carrier_instance(carrier_name)
        return carrier.get_service_types()

    except Exception as e:
        frappe.log_error(title="Get Services Failed", message=str(e))
        return []


# @frappe.whitelist()
# def track_shipment(docname=None, tracking_number=None):
#     """Track a shipment - accepts either docname or tracking_number"""

#     if docname and not tracking_number:
#         try:
#             doc = frappe.get_doc("Handover To Logistics", docname)
#             tracking_number = doc.logistics_tracking_number
#             frappe.log_error(
#                 title="Track Shipment - Got tracking from doc",
#                 message=f"Doc: {docname}, Tracking: {tracking_number}"
#             )
#         except Exception as e:
#             frappe.log_error(
#                 title="Track Shipment - Error getting doc",
#                 message=f"Doc: {docname}, Error: {str(e)}"
#             )

#     if not tracking_number:
#         tracking_number = frappe.local.form_dict.get('tracking_number')

#     if not tracking_number:
#         frappe.throw(
#             "Tracking number is required. Please provide either docname or tracking_number."
#         )

#     try:
#         settings = frappe.get_single("Logistics Settings")

#         carrier_name = None

#         if docname:
#             doc = frappe.get_doc("Handover To Logistics", docname)
#             carrier_name = doc.logistics_partner
#         else:
#             doc_name = frappe.db.get_value("Handover To Logistics",
#                 {"logistics_tracking_number": tracking_number}, "name")
#             if doc_name:
#                 doc = frappe.get_doc("Handover To Logistics", doc_name)
#                 carrier_name = doc.logistics_partner

#         if carrier_name:
#             carrier = get_carrier_instance(carrier_name)
#         else:
#             from .amazon_carrier import AmazonCarrier
#             carrier = AmazonCarrier(settings)

#         result = carrier.track_shipment(tracking_number)

#         amazon_status = result.get("current_status", "Unknown")
#         mapped_status = map_amazon_status(amazon_status)

#         result["current_status"] = mapped_status
#         result["carrier_status"] = mapped_status
#         result["original_status"] = amazon_status

#         if docname:
#             doc = frappe.get_doc("Handover To Logistics", docname)
#         elif 'doc' in locals():
#             doc = locals()['doc']
#         else:
#             doc = None

#         if doc:
#             is_submitted = doc.docstatus == 1

#             doc.db_set("carrier_status", mapped_status)

#             carrier_response = {}
#             if doc.carrier_response:
#                 try:
#                     carrier_response = json.loads(doc.carrier_response)
#                 except:
#                     carrier_response = {}

#             carrier_response["last_tracking"] = {
#                 "amazon_status": amazon_status,
#                 "mapped_status": mapped_status,
#                 "timestamp": now_datetime().isoformat(),
#                 "tracking_history": result.get("tracking_history", [])
#             }

#             if result.get("raw_response"):
#                 carrier_response["last_raw_response"] = result.get("raw_response")

#             doc.db_set("carrier_response", json.dumps(carrier_response, indent=2))

#             if not is_submitted:
#                 meta = frappe.get_meta("Handover To Logistics")
#                 tracking_field = meta.get_field("tracking_history")

#                 if tracking_field and tracking_field.fieldtype == "Table":
#                     if result.get("tracking_history"):
#                         doc.set("tracking_history", [])

#                         for history_item in result.get("tracking_history"):
#                             history_status = history_item.get("status", "")
#                             mapped_history_status = map_amazon_status(history_status)

#                             doc.append("tracking_history", {
#                                 "status": mapped_history_status,
#                                 "location": history_item.get("location", ""),
#                                 "timestamp": history_item.get("date", ""),
#                                 "description": f"Original: {history_status}"
#                             })

#                         doc.save(ignore_permissions=True)
#             else:
#                 frappe.log_error(
#                     title="Tracking - Document Submitted",
#                     message=f"Doc {doc.name} is submitted. Tracking history stored in carrier_response only."
#                 )

#             frappe.db.commit()

#             if is_submitted:
#                 frappe.msgprint(
#                     f"✅ Tracking updated: {mapped_status}<br><small>Note: Document is submitted. Full history stored in carrier_response.</small>",
#                     indicator="green",
#                     alert=True
#                 )

#         return result

#     except Exception as e:
#         frappe.log_error(
#             title="Track Shipment Error",
#             message=f"Tracking: {tracking_number}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
#         )
#         frappe.throw(f"Failed to track shipment: {str(e)}")
@frappe.whitelist()
def track_shipment(docname=None, tracking_number=None):
    """Track a shipment - accepts either docname or tracking_number"""

    if docname and not tracking_number:
        try:
            doc = frappe.get_doc("Handover To Logistics", docname)
            tracking_number = doc.logistics_tracking_number
            frappe.log_error(
                title="Track Shipment - Got tracking from doc",
                message=f"Doc: {docname}, Tracking: {tracking_number}"
            )
        except Exception as e:
            frappe.log_error(
                title="Track Shipment - Error getting doc",
                message=f"Doc: {docname}, Error: {str(e)}"
            )

    if not tracking_number:
        tracking_number = frappe.local.form_dict.get('tracking_number')

    if not tracking_number:
        frappe.throw(
            "Tracking number is required. Please provide either docname or tracking_number."
        )

    try:
        settings = frappe.get_single("Logistics Settings")
        doc = None
        carrier_name = None

        if docname:
            doc = frappe.get_doc("Handover To Logistics", docname)
            carrier_name = doc.logistics_partner
        else:
            doc_name = frappe.db.get_value("Handover To Logistics",
                {"logistics_tracking_number": tracking_number}, "name")
            if doc_name:
                doc = frappe.get_doc("Handover To Logistics", doc_name)
                carrier_name = doc.logistics_partner

        if not carrier_name:
            # Try to detect from tracking number pattern
            if tracking_number.startswith('IES') or tracking_number.startswith('IEL'):
                carrier_name = "Ekart"
            elif tracking_number.startswith('amzn1.sid'):
                carrier_name = "Amazon Shipping"
            else:
                carrier_name = "Amazon Shipping"  # Default

        if carrier_name:
            carrier = get_carrier_instance(carrier_name)
        else:
            from .amazon_carrier import AmazonCarrier
            carrier = AmazonCarrier(settings)

        # Call carrier's track_shipment method
        result = carrier.track_shipment(tracking_number)

        # ===== IMPORTANT: DON'T map status here - carriers already map their own statuses =====
        # The carrier should return already-mapped statuses
        
        if doc:
            is_submitted = doc.docstatus == 1

            # Update carrier status
            # doc.db_set("carrier_status", result.get("current_status", "Pending"))
            current_status = result.get("current_status", "Pending")
            VALID_STATUSES = [
                    "", "Pending", "Created", "Picked Up", "In Transit",
                    "Out for Delivery", "Delivered", "RTO", "Exception", "Cancelled"
            ]
            if current_status not in VALID_STATUSES:
                current_status = map_amazon_status(current_status)
            doc.db_set("carrier_status", current_status)

            # Update carrier_response with tracking data
            carrier_response = {}
            if doc.carrier_response:
                try:
                    carrier_response = json.loads(doc.carrier_response)
                except:
                    carrier_response = {}

            carrier_response["last_tracking"] = {
                "carrier": carrier_name,
                "timestamp": now_datetime().isoformat(),
                "tracking_history": result.get("tracking_history", []),
                "current_status": result.get("current_status", "Unknown")
            }

            if result.get("raw_response"):
                carrier_response["last_raw_response"] = result.get("raw_response")

            doc.db_set("carrier_response", json.dumps(carrier_response, indent=2))

            # Update tracking_history child table (only if document is NOT submitted)
            if not is_submitted:
                tracking_history = result.get("tracking_history", [])
                
                if tracking_history and len(tracking_history) > 0:
                    # Clear existing tracking history
                    doc.set("tracking_history", [])
                    
                    # Add all events to child table
                    # for event in tracking_history:
                    #     doc.append("tracking_history", {
                    #         "event_time": event.get("date"),        # Maps to event_time field
                    #         "status": event.get("status"),          # Maps to status field  
                    #         "location": event.get("location", "N/A"), # Maps to location field
                    #         "remarks": event.get("description", event.get("status", "")) # Maps to remarks field
                    #     })
                    for event in tracking_history:
                        raw_status = event.get("status", "")
                        VALID_STATUSES = [
                            "", "Pending", "Created", "Picked Up", "In Transit",
                            "Out for Delivery", "Delivered", "RTO", "Exception", "Cancelled"
                        ]
                        mapped_status = raw_status if raw_status in VALID_STATUSES else map_amazon_status(raw_status)
                        doc.append("tracking_history", {
                            "event_time": event.get("date"),
                            "status": mapped_status,
                            "location": event.get("location", "N/A"),
                            "remarks": event.get("description", event.get("status", ""))
                        })
                    
                    # Save the document
                    doc.save(ignore_permissions=True)
                    
                    frappe.log_error(
                        title="Tracking - Document Updated",
                        message=f"Document {doc.name} updated with {len(tracking_history)} tracking events"
                    )
                else:
                    frappe.log_error(
                        title="Tracking - No History",
                        message=f"Document {doc.name} - No tracking history returned by carrier"
                    )
            else:
                frappe.log_error(
                    title="Tracking - Document Submitted",
                    message=f"Doc {doc.name} is submitted. Tracking history stored in carrier_response only."
                )

            frappe.db.commit()

            # Show message to user
            if is_submitted:
                frappe.msgprint(
                    f"✅ Tracking updated: {result.get('current_status', 'Unknown')}<br><small>Note: Document is submitted. Full history stored in carrier_response.</small>",
                    indicator="green",
                    alert=True
                )
            else:
                history_count = len(result.get("tracking_history", []))
                frappe.msgprint(
                    f"✅ Tracking updated: {result.get('current_status', 'Unknown')}<br>Found {history_count} tracking event(s)",
                    indicator="green",
                    alert=True
                )

        return result

    except Exception as e:
        frappe.log_error(
            title="Track Shipment Error",
            message=f"Tracking: {tracking_number}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
        )
        frappe.throw(f"Failed to track shipment: {str(e)}")
        
        

def map_amazon_status(amazon_status):
    """Map Amazon shipping status to your predefined statuses"""

    status_mapping = {
        "ReadyForReceive": "Created",
        "PickupCancelled": "Cancelled",
        "PickupScheduled": "Created",
        "PreTransit": "Created",
        "PickedUp": "Picked Up",
        "InTransit": "In Transit",
        "OutForDelivery": "Out for Delivery",
        "Delivered": "Delivered",
        "Returned": "RTO",
        "Exception": "Exception",
        "Cancelled": "Cancelled",
        "Unknown": "Pending"
    }

    return status_mapping.get(amazon_status, "Exception")


@frappe.whitelist()
def download_label(docname):
    """Download shipping label for a shipment"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)

        if not doc.logistics_tracking_number:
            frappe.throw("No tracking number found for this shipment")

        carrier = get_carrier_instance(doc.logistics_partner)

        # ---------------------------------------------
        # Get the correct packageClientReferenceId
        # Must match exactly what was used when shipment was created
        # New shipments store label_package_ref in carrier_response
        # Old shipments used docname (HLG number)
        # ---------------------------------------------
        package_ref = docname  # default for old shipments
        if doc.carrier_response:
            try:
                cr = json.loads(doc.carrier_response)
                if cr.get("label_package_ref"):
                    package_ref = cr.get("label_package_ref")
            except:
                package_ref = docname

        frappe.publish_realtime(
            "msgprint",
            {"message": f"Downloading label for {doc.logistics_tracking_number}..."},
            user=frappe.session.user
        )

        result = carrier.download_label(
            shipment_id=doc.logistics_tracking_number,
            package_client_reference_id=package_ref
        )

        if result.get("file_url"):
            doc.db_set("label_url", result["file_url"])
            doc.db_set("carrier_status", "Label Generated")

        frappe.publish_realtime(
            "msgprint",
            {"message": f"✅ Label downloaded successfully!"},
            user=frappe.session.user
        )

        return result

    except Exception as e:
        frappe.log_error(
            title="Download Label Error",
            message=f"Document: {docname}\nError: {str(e)}"
        )
        frappe.throw(f"Failed to download label: {str(e)}")


@frappe.whitelist()
def cancel_shipment(docname):
    """Cancel shipment"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)

        if not doc.logistics_tracking_number:
            frappe.throw(_("No tracking number available"))

        carrier = get_carrier_instance(doc.logistics_partner)
        result = carrier.cancel_shipment(doc.logistics_tracking_number)

        if result.get("success"):
            doc.db_set("carrier_status", "Cancelled")

            if doc.logistics_partner == "Ekart":
                doc.db_set("ekart_shipment_status", "Cancelled")

            carrier_response = {}
            if doc.carrier_response:
                try:
                    carrier_response = json.loads(doc.carrier_response)
                except:
                    carrier_response = {}

            carrier_response["cancellation"] = {
                "timestamp": now_datetime().isoformat(),
                "result": result
            }

            doc.db_set("carrier_response", json.dumps(carrier_response, indent=2))

            frappe.db.commit()

            frappe.msgprint(_("Shipment cancelled successfully"), indicator="green")
            return {"success": True, "message": "Shipment cancelled successfully"}
        else:
            error_details = result.get("error_details", "")
            error_message = result.get("error_message", "Cancellation failed")

            if "ineligible state" in error_details.lower():
                frappe.msgprint(
                    msg=_("Cannot cancel shipment: {0}").format(error_details),
                    title=_("Cancellation Not Allowed"),
                    indicator="orange"
                )

                carrier_response = {}
                if doc.carrier_response:
                    try:
                        carrier_response = json.loads(doc.carrier_response)
                    except:
                        carrier_response = {}

                carrier_response["cancellation_attempt"] = {
                    "timestamp": now_datetime().isoformat(),
                    "success": False,
                    "reason": error_details
                }

                doc.db_set("carrier_response", json.dumps(carrier_response, indent=2))

                return {
                    "success": False,
                    "message": error_details,
                    "eligible": False
                }
            else:
                frappe.throw(_("Cancellation failed: {0}").format(error_details or error_message))

    except Exception as e:
        frappe.log_error(
            title="Cancellation Failed",
            message=f"Doc: {docname}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
        )
        frappe.throw(_("Cancellation failed: {0}").format(str(e)))


@frappe.whitelist()
def validate_address(pincode, carrier=None):
    """Validate address serviceability"""
    try:
        if not carrier:
            settings = frappe.get_single("Logistics Settings")
            results = {}

            if getattr(settings, 'enable_ekart', False):
                ekart = get_carrier_instance("Ekart")
                results["Ekart"] = ekart.validate_address(pincode)

            if getattr(settings, 'enable_amazon', False):
                amazon = get_carrier_instance("Amazon Shipping")
                results["Amazon"] = amazon.validate_address(pincode)

            if getattr(settings, 'enable_shiprocket', False):
                shiprocket = get_carrier_instance("Shiprocket")
                results["Shiprocket"] = shiprocket.validate_address(pincode)

            return results
        else:
            carrier = get_carrier_instance(carrier)
            return carrier.validate_address(pincode)

    except Exception as e:
        frappe.log_error(title="Address Validation Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def bulk_create_shipments(docnames):
    """Bulk create shipments"""
    try:
        docnames = json.loads(docnames)
        results = {
            "success": [],
            "failed": [],
            "success_count": 0,
            "failed_count": 0
        }

        for docname in docnames:
            try:
                result = create_shipment(docname)
                if result.get("status") == "success":
                    results["success"].append({
                        "docname": docname,
                        "tracking_number": result.get("tracking_number")
                    })
                    results["success_count"] += 1
                else:
                    results["failed"].append({
                        "docname": docname,
                        "error": result.get("message", "Unknown error")
                    })
                    results["failed_count"] += 1
            except Exception as e:
                results["failed"].append({
                    "docname": docname,
                    "error": str(e)
                })
                results["failed_count"] += 1

        return results

    except Exception as e:
        frappe.log_error(title="Bulk Creation Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def bulk_track_shipments(docnames):
    """Bulk track shipments"""
    try:
        docnames = json.loads(docnames)
        count = 0

        for docname in docnames:
            try:
                track_shipment(docname)
                count += 1
            except:
                pass

        return {"count": count}

    except Exception as e:
        frappe.log_error(title="Bulk Tracking Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def get_carrier_rates(docname):
    """Get shipping rates for document"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)

        shipment_data = {
            "customer": {
                "pincode": doc.pincode,
                "address": doc.address,
                "city": doc.location or ""
            },
            "package": {
                "weight": float(doc.weight or 0.5),
                "dimensions": {
                    "length": float(doc.length or 10),
                    "width": float(doc.width or 10),
                    "height": float(doc.height or 10)
                },
                "value": float(doc.declared_value or 0),
                "cbm": float(doc.total_cbm or 0),
                "max_dimension": float(doc.max_dimension or 0)
            },
            "order": {
                "payment_type": doc.payment_type or "Prepaid",
                "cod_amount": float(doc.cod_amount or 0)
            },
            "shipment_category": doc.shipment_category or "Non-Large",
            # "is_large_shipment": doc.shipment_category == "Large"
        }

        carrier = get_carrier_instance(doc.logistics_partner)
        return carrier.get_rates(shipment_data)

    except Exception as e:
        frappe.log_error(title="Get Rates Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def compare_rates(pincode, weight, length=10, width=10, height=10):
    """Compare rates from all enabled carriers"""
    try:
        settings = frappe.get_single("Logistics Settings")
        results = {}

        shipment_data = {
            "customer": {"pincode": pincode},
            "package": {
                "weight": float(weight),
                "dimensions": {
                    "length": float(length),
                    "width": float(width),
                    "height": float(height)
                }
            },
            "order": {"payment_type": "Prepaid"}
        }

        if getattr(settings, 'enable_ekart', False):
            try:
                ekart = get_carrier_instance("Ekart")
                results["Ekart"] = ekart.get_rates(shipment_data)
            except Exception as e:
                results["Ekart"] = {"error": str(e)}

        if getattr(settings, 'enable_amazon', False):
            try:
                amazon = get_carrier_instance("Amazon Shipping")
                results["Amazon"] = amazon.get_rates(shipment_data)
            except Exception as e:
                results["Amazon"] = {"error": str(e)}

        if getattr(settings, 'enable_shiprocket', False):
            try:
                shiprocket = get_carrier_instance("Shiprocket")
                results["Shiprocket"] = shiprocket.get_rates(shipment_data)
            except Exception as e:
                results["Shiprocket"] = {"error": str(e)}

        return results

    except Exception as e:
        frappe.log_error(title="Compare Rates Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def test_carrier_connection(carrier):
    """Test connection to carrier API"""
    try:
        carrier_instance = get_carrier_instance(carrier)
        result = carrier_instance.authenticate()

        if result.get("token"):
            return {
                "status": "success",
                "message": f"Successfully connected to {carrier}",
                "token_obtained": True
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to get token from {carrier}"
            }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def discover_ekart_endpoints():
    """Utility to discover correct Ekart API endpoints"""
    try:
        settings = frappe.get_single("Logistics Settings")
        from .ekart_carrier import EkartCarrier

        carrier = EkartCarrier(settings)
        result = carrier._discover_endpoints()

        if result:
            return {
                "success": True,
                "endpoints": result,
                "message": "Endpoints discovered successfully"
            }
        else:
            return {
                "success": False,
                "message": "No working endpoints found"
            }

    except Exception as e:
        frappe.log_error("Endpoint Discovery Error", str(e))
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def bulk_download_labels(docnames):
    """Bulk download shipping labels for multiple documents"""
    try:
        docnames = json.loads(docnames) if isinstance(docnames, str) else docnames
        results = {
            "success": [],
            "failed": [],
            "success_count": 0,
            "failed_count": 0
        }

        for docname in docnames:
            try:
                doc = frappe.get_doc("Handover To Logistics", docname)

                if not doc.logistics_tracking_number:
                    results["failed"].append({
                        "docname": docname,
                        "error": "No tracking number found"
                    })
                    results["failed_count"] += 1
                    continue

                from .utils import get_carrier_instance
                carrier = get_carrier_instance(doc.logistics_partner)

                if doc.logistics_partner == "Amazon Shipping":
                    # Get the correct package ref (matches what was used at creation)
                    package_ref = None
                    
                    # First try from stored response
                    if doc.carrier_response:
                        try:
                            cr = json.loads(doc.carrier_response)
                            if cr.get("label_package_ref"):
                                package_ref = cr.get("label_package_ref")
                        except:
                            pass
                    
                    # If not stored, try to determine from doc
                    if not package_ref:
                        if doc.sales_order:
                            package_ref = doc.sales_order
                        elif doc.order_no:
                            if frappe.db.exists("Sales Order", doc.order_no):
                                package_ref = doc.order_no
                            else:
                                try:
                                    if frappe.db.exists("Delivery Note", doc.order_no):
                                        dn = frappe.get_doc("Delivery Note", doc.order_no)
                                        if dn.items and dn.items[0].against_sales_order:
                                            package_ref = dn.items[0].against_sales_order
                                        else:
                                            package_ref = doc.order_no
                                except:
                                    package_ref = doc.order_no
                        else:
                            package_ref = doc.name
                    
                    result = carrier.download_label(
                        shipment_id=doc.logistics_tracking_number,
                        package_client_reference_id=package_ref
                    )
                elif doc.logistics_partner == "Ekart":
                    result = carrier.download_label(doc.logistics_tracking_number)
                else:
                    result = carrier.download_label(doc.logistics_tracking_number)

                if result.get("success") and result.get("file_url"):
                    results["success"].append({
                        "docname": docname,
                        "file_url": result.get("file_url"),
                        "tracking_number": doc.logistics_tracking_number
                    })
                    results["success_count"] += 1
                else:
                    results["failed"].append({
                        "docname": docname,
                        "error": result.get("message", "Unknown error")
                    })
                    results["failed_count"] += 1

            except Exception as e:
                results["failed"].append({
                    "docname": docname,
                    "error": str(e)
                })
                results["failed_count"] += 1

        return results

    except Exception as e:
        frappe.log_error(title="Bulk Label Download Error", message=str(e))
        return {"error": str(e)}


@frappe.whitelist()
def bulk_set_carrier_and_create(docnames, logistics_partner):
    """Bulk set carrier and create shipments"""
    try:
        docnames = json.loads(docnames) if isinstance(docnames, str) else docnames
        results = {
            "success": [],
            "failed": [],
            "success_count": 0,
            "failed_count": 0
        }

        for docname in docnames:
            try:
                doc = frappe.get_doc("Handover To Logistics", docname)
                doc.logistics_partner = logistics_partner
                doc.save(ignore_permissions=True)
                frappe.db.commit()

                result = create_shipment(docname)

                if result.get("status") == "success":
                    results["success"].append({
                        "docname": docname,
                        "tracking_number": result.get("tracking_number")
                    })
                    results["success_count"] += 1
                else:
                    results["failed"].append({
                        "docname": docname,
                        "error": result.get("message", "Unknown error")
                    })
                    results["failed_count"] += 1

            except Exception as e:
                results["failed"].append({
                    "docname": docname,
                    "error": str(e)
                })
                results["failed_count"] += 1

        return results

    except Exception as e:
        frappe.log_error(title="Bulk Set Carrier & Create Failed", message=str(e))
        return {"error": str(e)}

@frappe.whitelist()
def cancel_and_recreate_shipment(docname, new_logistics_partner=None):
    """Cancel existing shipment and clear tracking so a new one can be created"""
    try:
        doc = frappe.get_doc("Handover To Logistics", docname)

        if not doc.logistics_tracking_number:
            frappe.throw(_("No tracking number found — nothing to cancel"))

        carrier = get_carrier_instance(doc.logistics_partner)
        
        # Try to cancel with carrier
        cancel_result = None
        cancel_success = False
        cancel_error = None
        
        try:
            cancel_result = carrier.cancel_shipment(doc.logistics_tracking_number)
            if cancel_result.get("success"):
                cancel_success = True
            else:
                cancel_error = cancel_result.get("error_message", "Cancellation failed")
        except Exception as e:
            cancel_error = str(e)
            frappe.log_error(
                title="Cancel & Recreate - Carrier Cancel Failed",
                message=f"Doc: {docname}\nTracking: {doc.logistics_tracking_number}\nError: {cancel_error}"
            )
        
        # For Ekart non-large shipments, 404 is expected - we still clear tracking
        is_ekart_non_large = doc.logistics_partner == "Ekart" and not doc.logistics_tracking_number.startswith("IEL")
        
        if not cancel_success:
            # Check if it's an expected failure (Ekart IES 404)
            if is_ekart_non_large and "404" in str(cancel_error):
                frappe.log_error(
                    title="Ekart IES Cancellation - Expected Failure",
                    message=f"Tracking: {doc.logistics_tracking_number}\nError: {cancel_error}\nProceeding to clear tracking locally."
                )
                # Don't throw error - proceed with clearing tracking
            else:
                # For other failures, check if it's a real error
                error_details = cancel_result.get("error_details", "") if cancel_result else ""
                error_message = cancel_result.get("error_message", "") if cancel_result else ""
                
                if error_details and "ineligible" in error_details.lower():
                    frappe.throw(
                        _("Cannot cancel: shipment is already in transit. Details: {0}").format(error_details)
                    )
                else:
                    # For unexpected errors, still try to clear tracking but show warning
                    frappe.log_error(
                        title="Cancel & Recreate - Unexpected Error",
                        message=f"Doc: {docname}\nTracking: {doc.logistics_tracking_number}\nError: {cancel_error}\nProceeding to clear tracking."
                    )
                    # Optionally show a warning but still proceed

        old_tracking = doc.logistics_tracking_number

        carrier_response = {}
        if doc.carrier_response:
            try:
                carrier_response = json.loads(doc.carrier_response)
            except:
                carrier_response = {}

        carrier_response["cancelled"] = {
            "timestamp": now_datetime().isoformat(),
            "old_tracking_number": old_tracking,
            "cancelled_by": frappe.session.user,
            "carrier_cancel_success": cancel_success,
            "carrier_cancel_error": cancel_error if not cancel_success else None
        }

        # Clear tracking information
        doc.db_set("logistics_tracking_number", "")
        doc.db_set("carrier_status", "Cancelled")
        doc.db_set("carrier_response", json.dumps(carrier_response, indent=2))

        if doc.logistics_partner == "Ekart":
            doc.db_set("ekart_tracking_number", "")
            doc.db_set("ekart_awb_number", "")
            doc.db_set("ekart_shipment_status", "Cancelled")
            doc.db_set("ekart_manifest_id", "")

        if new_logistics_partner and new_logistics_partner != doc.logistics_partner:
            doc.db_set("logistics_partner", new_logistics_partner)

        frappe.db.commit()

        # Show appropriate message based on cancellation result
        if cancel_success:
            message = _("Shipment {0} cancelled successfully. You can now create a new shipment.").format(old_tracking)
        else:
            if is_ekart_non_large and "404" in str(cancel_error):
                message = _("Ekart non-large shipments cannot be cancelled via API. Tracking number {0} has been cleared from your system. You can now create a new shipment. The original shipment in Ekart remains active.").format(old_tracking)
            else:
                message = _("Shipment tracking cleared. Note: Carrier cancellation may have failed, but you can now create a new shipment. Original tracking: {0}").format(old_tracking)

        frappe.msgprint(message, indicator="green" if cancel_success else "orange")

        return {
            "success": True,
            "message": message,
            "old_tracking": old_tracking,
            "carrier_cancel_success": cancel_success,
            "carrier_cancel_error": cancel_error if not cancel_success else None
        }

    except Exception as e:
        frappe.log_error(
            title="Cancel & Recreate Failed",
            message=f"Doc: {docname}\nError: {str(e)}\n{frappe.get_traceback()}"
        )
        frappe.throw(_("Failed to cancel shipment: {0}").format(str(e)))

@frappe.whitelist()
def bulk_cancel_and_recreate(docnames, new_logistics_partner=None):
    """Bulk cancel shipments and optionally set a new carrier"""
    try:
        docnames = json.loads(docnames) if isinstance(docnames, str) else docnames
        results = {"success": [], "failed": [], "success_count": 0, "failed_count": 0}

        for docname in docnames:
            try:
                result = cancel_and_recreate_shipment(docname, new_logistics_partner)
                results["success"].append({
                    "docname": docname,
                    "old_tracking": result.get("old_tracking", "")
                })
                results["success_count"] += 1
            except Exception as e:
                results["failed"].append({"docname": docname, "error": str(e)})
                results["failed_count"] += 1

        return results

    except Exception as e:
        frappe.log_error(title="Bulk Cancel Failed", message=str(e))
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_tracking_by_dn(dn_name):
    try:
        hlg_name = frappe.db.get_value(
            "Handover To Logistics",
            {"order_no": dn_name},
            "name"
        )

        if not hlg_name:
            return {"message": {"success": False, "message": "No shipment found for this Delivery Note"}}

        # ✅ Hit Ekart API live every time — no manual Track button needed
        track_shipment(docname=hlg_name)

        # Now read the freshly updated carrier_response
        hlg = frappe.get_doc("Handover To Logistics", hlg_name)
        tracking_data = get_unified_tracking_data(hlg)

        return {"message": tracking_data}

    except Exception as e:
        frappe.log_error(f"get_tracking_by_dn failed for {dn_name}: {str(e)}", "Tracking API Error")
        return {"message": {"success": False, "message": str(e)}}


def get_unified_tracking_data(hlg):
    """Convert carrier-specific tracking data to unified format and store in Delivery Note"""

    tracking_history = []
    carrier_data = {}

    if hlg.carrier_response:
        try:
            carrier_data = json.loads(hlg.carrier_response)
        except:
            carrier_data = {}

    if hlg.logistics_partner == "Amazon Shipping":
        tracking_history = parse_amazon_tracking(carrier_data, hlg)
    elif hlg.logistics_partner == "Ekart":
        tracking_history = parse_ekart_tracking(carrier_data, hlg)
    else:
        tracking_history = parse_generic_tracking(carrier_data, hlg)

    unified_data = {
        "success": True,
        "dn_name": hlg.order_no,
        "hlg_name": hlg.name,
        "shipping_partner": hlg.logistics_partner,
        "tracking_number": hlg.logistics_tracking_number,
        "status": hlg.carrier_status or "Pending",
        "tracking_history": tracking_history,
        "last_updated": frappe.utils.now_datetime().strftime("%d-%b-%Y %H:%M:%S")
    }

    store_tracking_in_delivery_note(hlg.order_no, unified_data)

    return unified_data


def parse_amazon_tracking(carrier_data, hlg):
    """Convert Amazon tracking to unified format"""
    history = []

    last_tracking = carrier_data.get("last_tracking", {})
    amazon_history = last_tracking.get("tracking_history", [])

    if amazon_history:
        for event in amazon_history:
            history.append({
                "date": event.get("date", ""),
                "status": event.get("status", ""),
                "location": event.get("location", "N/A"),
                "description": event.get("description", "")
            })
    else:
        history.append({
            "date": hlg.modified.strftime("%d-%b-%Y %H:%M:%S") if hlg.modified else frappe.utils.now_datetime().strftime("%d-%b-%Y %H:%M:%S"),
            "status": hlg.carrier_status or "Created",
            "location": "N/A",
            "description": f"Shipment {hlg.carrier_status.lower() if hlg.carrier_status else 'created'}"
        })

    return history



def parse_ekart_tracking(carrier_data, hlg):
    """Convert Ekart tracking to unified format"""
    history = []

    last_tracking = carrier_data.get("last_tracking", {})
    ekart_history = last_tracking.get("tracking_history", [])

    if ekart_history:
        for event in ekart_history:
            history.append({
                "date": event.get("date", ""),
                "status": event.get("status", ""),
                "location": event.get("location", "N/A"),
                "description": event.get("description", "")
            })

    if not history and hlg.carrier_status:
        history.append({
            "date": hlg.modified.strftime("%d-%b-%Y %H:%M:%S") if hlg.modified else frappe.utils.now_datetime().strftime("%d-%b-%Y %H:%M:%S"),
            "status": hlg.carrier_status,
            "location": "N/A",
            "description": f"Shipment is {hlg.carrier_status.lower()}"
        })

    return history



def parse_generic_tracking(carrier_data, hlg):
    """Generic parser for other shipping partners"""
    history = []

    if carrier_data.get("tracking_history"):
        for event in carrier_data.get("tracking_history", []):
            history.append({
                "date": event.get("date") or event.get("timestamp") or event.get("time") or "",
                "status": event.get("status") or event.get("event") or event.get("state") or "",
                "location": event.get("location") or event.get("city") or event.get("hub") or "N/A",
                "description": event.get("description") or event.get("remarks") or event.get("note") or ""
            })
    elif carrier_data.get("history"):
        for event in carrier_data.get("history", []):
            history.append({
                "date": event.get("timestamp") or event.get("date") or "",
                "status": event.get("event") or event.get("status") or "",
                "location": event.get("location") or "N/A",
                "description": event.get("description") or ""
            })

    if not history and hlg.carrier_status:
        history.append({
            "date": hlg.modified.strftime("%d-%b-%Y %H:%M:%S") if hlg.modified else frappe.utils.now_datetime().strftime("%d-%b-%Y %H:%M:%S"),
            "status": hlg.carrier_status,
            "location": "N/A",
            "description": f"Shipment is {hlg.carrier_status.lower()}"
        })

    return history





# ══════════════════════════════════════════════════════════════════════════════
# REPLACE the existing store_tracking_in_delivery_note function in utils.py
# with this entire block (_parse_delivered_date + store_tracking_in_delivery_note)
#
# Both carriers already return mapped status "Delivered" (capital D).
# Ekart date format:  "2026-03-14 10:30:00"  (already MySQL format)
# Amazon date format: "2026-03-14 22:33:14"  (already MySQL format)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_delivered_date(date_str):
    """
    Convert carrier date string → clean YYYY-MM-DD for Frappe Date field.

    Both Ekart and Amazon already format to "YYYY-MM-DD HH:MM:SS" in their
    track_shipment() methods, so we just split on space.
    Also handles edge cases from older records.
    """
    from frappe.utils import today
    from datetime import datetime

    if not date_str:
        return today()

    date_str = str(date_str).strip()

    # Fast path: already YYYY-MM-DD or starts with it
    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        return date_str[:10]   # "2026-03-14 10:30:00" → "2026-03-14"

    # Fallback formats (for any old records stored differently)
    fallback_formats = [
        "%d-%b-%Y %H:%M:%S",   # 14-Mar-2026 04:09:00  (Amazon old format)
        "%d-%b-%Y %H:%M",
        "%d-%b-%Y",
        "%Y-%m-%dT%H:%M:%SZ",  # 2026-03-14T04:09:49Z
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y %H:%M:%S",   # 14-03-2026 10:30:00
        "%d-%m-%Y",
        "%d/%m/%Y",
    ]
    for fmt in fallback_formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    frappe.log_error(
        title="store_tracking — unparseable date",
        message=f"Could not parse: {repr(date_str)}"
    )
    return today()


def store_tracking_in_delivery_note(dn_name, tracking_data):
    """
    Store unified tracking data in Delivery Note fields.

    Auto-marks as delivered when carrier status == "Delivered":
      custom_is_delivered   = 1
      custom_delivered_date = YYYY-MM-DD (parsed from carrier event date)

    Both Ekart and Amazon return status "Delivered" (capital D, already mapped).
    """
    try:
        if not dn_name:
            return

        # ── 1. Store full tracking JSON ──────────────────────────────────────
        frappe.db.set_value(
            "Delivery Note", dn_name,
            "custom_status_tracking",
            json.dumps(tracking_data, indent=2)
        )

        history    = tracking_data.get("tracking_history", [])
        top_status = (tracking_data.get("status") or "").strip()

        # ── 2. Determine delivered status ─────────────────────────────────────
        # Check both the top-level status AND each history event.
        # Both carriers already map to "Delivered" (exact string).
        is_delivered   = 0
        delivered_date = None

        # Scan history for a Delivered event (most reliable — has the date)
        delivered_event = next(
            (e for e in reversed(history)
             if (e.get("status") or "").strip() == "Delivered"),
            None
        )

        if delivered_event:
            is_delivered   = 1
            delivered_date = _parse_delivered_date(delivered_event.get("date"))
        elif top_status == "Delivered":
            # Top-level says Delivered but no event in history yet — use today
            is_delivered   = 1
            from frappe.utils import today
            delivered_date = today()

        # ── 3. Write to DN ───────────────────────────────────────────────────
        frappe.db.set_value(
            "Delivery Note", dn_name,
            "custom_is_delivered", is_delivered
        )
        frappe.db.set_value(
            "Delivery Note", dn_name,
            "custom_delivered_date", delivered_date
        )

        frappe.db.commit()

        # ── 4. Log result (remove after confirming it works) ─────────────────
        frappe.log_error(
            title=f"Tracking stored — {dn_name}",
            message=(
                f"top_status     : {repr(top_status)}\n"
                f"is_delivered   : {is_delivered}\n"
                f"delivered_date : {delivered_date}\n"
                f"history events : {len(history)}\n"
                f"all statuses   : {[e.get('status') for e in history]}"
            )
        )

    except Exception as e:
        frappe.log_error(
            title="store_tracking_in_delivery_note Failed",
            message=f"DN: {dn_name}\nError: {str(e)}\n{frappe.get_traceback()}"
        )