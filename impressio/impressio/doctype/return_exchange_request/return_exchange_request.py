# Copyright (c) 2026, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from impressio.impressio.api.helper import get_product_prices
from impressio.impressio.api.sms_service import SMSService


class ReturnExchangeRequest(Document):

    def before_save(self):
        if self.status != "Approved":
            return

        prev = self.get_doc_before_save()
        already_approved = prev and prev.status == "Approved"

        if not self.return_delivery_note:
            if not already_approved:
                self._create_return_delivery_note()

        if not self.replacement_sales_order:
            self._create_replacement_sales_order()

    # ------------------------------------------------------------------ #
    #  Return Delivery Note                                                #
    # ------------------------------------------------------------------ #

    def _create_return_delivery_note(self):
        original_dn = frappe.get_doc("Delivery Note", self.delivery_note)

        dn_item_row_map = {}
        for row in original_dn.items:
            if row.item_code not in dn_item_row_map:
                dn_item_row_map[row.item_code] = row

        missing = [
            reri.old_item_code
            for reri in self.return_exchange_request_item
            if reri.old_item_code not in dn_item_row_map
        ]
        if missing:
            frappe.throw(
                f"The following items were not found in Delivery Note "
                f"{self.delivery_note}: {', '.join(missing)}",
                title="Return DN Creation Failed"
            )

        return_dn = frappe.new_doc("Delivery Note")
        return_dn.is_return = 1
        return_dn.return_against = self.delivery_note
        return_dn.customer = original_dn.customer
        return_dn.company = original_dn.company
        return_dn.posting_date = frappe.utils.today()
        return_dn.set_warehouse = original_dn.set_warehouse or "Stores - IESPL"
        return_dn.currency = original_dn.currency

        for reri in self.return_exchange_request_item:
            src = dn_item_row_map[reri.old_item_code]
            return_dn.append("items", {
                "item_code": reri.old_item_code,
                "qty": -abs(int(reri.qty)),
                "warehouse": src.warehouse or return_dn.set_warehouse,
                "uom": src.uom,
                "stock_uom": src.stock_uom,
                "conversion_factor": src.conversion_factor or 1,
                "dn_detail": src.name,
                "rate": src.rate,
                "price_list_rate": src.price_list_rate or src.rate,
                "against_sales_order": src.against_sales_order or "",
                "custom_custom_against_sales_order": src.get("custom_custom_against_sales_order") or "",
                "so_detail": src.so_detail or "",
            })

        try:
            return_dn.flags.ignore_permissions = True
            return_dn.flags.ignore_mandatory = True
            return_dn.insert(ignore_permissions=True)
            return_dn.submit()
            frappe.db.commit()

        except Exception:
            self._cleanup_stuck_draft(return_dn)
            frappe.log_error(
                frappe.get_traceback(),
                f"_create_return_delivery_note failed for RER {self.name}"
            )
            frappe.throw(
                "Failed to create Return Delivery Note automatically. "
                "Please check the error log and create it manually.",
                title="Return DN Creation Failed"
            )

        self.return_delivery_note = return_dn.name
        frappe.msgprint(
            f"Return Delivery Note <b>{return_dn.name}</b> created and submitted.",
            indicator="green",
            alert=True
        )

    # ------------------------------------------------------------------ #
    #  Replacement Sales Order                                             #
    # ------------------------------------------------------------------ #

    def _create_replacement_sales_order(self):
        """
        Decision table:
          Missing           -> Submit immediately
          Exchange net == 0 -> Submit immediately
          Exchange net <  0 -> Draft (refund details collected at checkout)
          Exchange net >  0 -> Draft (payment collected at checkout)

        no_charge items carry real new_rate in SO,
        and receive a full discount so net contribution = 0.
        SMS + Mail sent for all 4 paths.
        """
        original_so = frappe.get_doc("Sales Order", self.sales_order)
        is_missing = (self.action_type == "Missing")

        # ── Price calculation ─────────────────────────────────────────────
        so_item_rate_map = {
            item.item_code: float(item.rate or 0)
            for item in original_so.items
        }
        sub_item_parent_map = {
            sub.item_code: sub.parent_item_code
            for sub in (original_so.custom_sub_items or [])
        }

        line_items = []
        total_discount = 0
        total_new_amount = 0

        for reri in self.return_exchange_request_item:
            qty = int(reri.qty or 1)
            old_item_code = reri.old_item_code
            new_item_code = reri.new_item_code

            is_same_item = (old_item_code == new_item_code)
            parent_of_old = sub_item_parent_map.get(old_item_code)
            is_sub_item = parent_of_old is not None and parent_of_old != old_item_code
            no_charge = is_missing or is_same_item or is_sub_item

            old_rate = so_item_rate_map.get(old_item_code, 0)

            # Always fetch real new price
            new_prices = get_product_prices(new_item_code)
            new_rate = float(new_prices.get("Standard Selling") or 0)

            line_new_amount = new_rate * qty

            if no_charge:
                # Customer pays nothing -> discount covers full new price
                line_discount = new_rate * qty
            else:
                # Customer gets credit for old item value
                line_discount = old_rate * qty

            total_new_amount += line_new_amount
            total_discount += line_discount

            line_items.append({
                "new_item_code": new_item_code,
                "old_item_code": old_item_code,
                "qty": qty,
                "new_rate": new_rate,
                "old_item_price": old_rate,
                "new_item_price": new_rate,
                "no_charge": no_charge,
            })

        net_payable = round(total_new_amount - total_discount, 2)

        # ── Build SO ──────────────────────────────────────────────────────
        company = frappe.defaults.get_user_default("Company")
        selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
        currency = frappe.get_cached_value("Company", company, "default_currency")

        new_so = frappe.new_doc("Sales Order")
        new_so.customer = original_so.customer
        new_so.company = company
        new_so.order_type = "Shopping Cart"
        new_so.currency = currency
        new_so.set_warehouse = "Stores - IESPL"
        new_so.selling_price_list = selling_price_list
        new_so.contact_person = original_so.contact_person
        new_so.contact_mobile = original_so.contact_mobile
        new_so.contact_email = original_so.contact_email
        new_so.custom_is_replacement_so = 1
        new_so.custom_parent_sales_order = original_so.name
        new_so.custom_student_school = original_so.custom_student_school
        new_so.custom_student_grade = original_so.custom_student_grade
        new_so.custom_payment_status = "PENDING"

        # Addresses from original SO
        new_so.shipping_address_name = original_so.shipping_address_name
        new_so.shipping_address = original_so.shipping_address
        new_so.customer_address = original_so.customer_address
        new_so.address_display = original_so.address_display

        # ── Items — always use real new_rate ──────────────────────────────
        for li in line_items:
            new_so.append("items", {
                "item_code": li["new_item_code"],
                "qty": li["qty"],
                "rate": li["new_rate"],
            })

        for idx, li in enumerate(line_items, start=1):
            new_so.append("custom_sub_items", {
                "parent_item_code": li["new_item_code"],
                "item_code": li["new_item_code"],
                "qty": li["qty"],
                "idx": idx,
            })

        # ── Discount ──────────────────────────────────────────────────────
        if total_discount > 0:
            capped_discount = min(total_discount, total_new_amount)
            if capped_discount > 0:
                new_so.discount_amount = capped_discount
                new_so.apply_discount_on = "Grand Total"

        # ── Insert ────────────────────────────────────────────────────────
        try:
            new_so.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"_create_replacement_sales_order insert failed for RER {self.name}"
            )
            frappe.throw(
                "Failed to create Replacement Sales Order. "
                "Please check the error log.",
                title="Replacement SO Creation Failed"
            )

        # ── Submit decision ───────────────────────────────────────────────
        # Missing   -> always submit
        # net == 0  -> submit (straight swap)
        # net <  0  -> Draft (checkout collects refund details)
        # net >  0  -> Draft (checkout collects payment)
        should_submit = is_missing or net_payable == 0

        if should_submit:
            try:
                new_so.custom_payment_status = "SUCCESS"
                new_so.flags.ignore_permissions = True
                new_so.submit()
                self.status = "In Progress"
                frappe.db.commit()
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"_create_replacement_sales_order submit failed for RER {self.name}"
                )
                frappe.throw(
                    "Replacement Sales Order was created but could not be submitted. "
                    "Please check the error log.",
                    title="Replacement SO Submit Failed"
                )

        # ── Update RERI price fields ──────────────────────────────────────
        price_map = {
            li["old_item_code"]: {
                "old_item_price": li["old_item_price"],
                "new_item_price": li["new_item_price"],
            }
            for li in line_items
        }
        for reri in self.return_exchange_request_item:
            prices = price_map.get(reri.old_item_code)
            if prices:
                reri.old_item_price = prices["old_item_price"]
                reri.new_item_price = prices["new_item_price"]

        self.replacement_sales_order = new_so.name
        self.old_sales_order_grant_total = total_discount
        self.new_sales_order_grant_total = total_new_amount
        self.grand_total = net_payable

        frappe.msgprint(
            f"Replacement Sales Order <b>{new_so.name}</b> "
            f"{'submitted' if should_submit else 'created as Draft'}.",
            indicator="green",
            alert=True
        )

        # ── SMS + Mail ────────────────────────────────────────────────────
        self._notify_replacement_so(
            original_so=original_so,
            new_so_name=new_so.name,
            is_missing=is_missing,
            net_payable=net_payable,
        )

    # ------------------------------------------------------------------ #
    #  Notifications                                                       #
    # ------------------------------------------------------------------ #

    def _notify_replacement_so(self, original_so, new_so_name, is_missing, net_payable):

        mobile = original_so.contact_mobile or ""
        user = frappe.get_value(
            "User",
            {"mobile_no": mobile},
            ["name", "full_name","email"],
            as_dict=True
        ) if mobile else None

        email = user.email if user else None
         # Resolve name
        customer_name = user.full_name if user and user.full_name else "Customer"
        order_no = original_so.name
        abs_amount = str(abs(round(net_payable, 2)))

        if is_missing:
            scenario = "missing"
        elif net_payable == 0:
            scenario = "zero"
        elif net_payable < 0:
            scenario = "refund"
        else:
            scenario = "payment"

        # ── SMS ───────────────────────────────────────────────────────────
        try:
            if mobile:
                if scenario == "missing":
                    SMSService.send_rer_missing_confirmed(
                        mobile=mobile,
                        customer_name=customer_name,
                        order_no=order_no
                    )
                elif scenario == "zero":
                    SMSService.send_rer_exchange_confirmed(
                        mobile=mobile,
                        customer_name=customer_name,
                        order_no=order_no
                    )
                elif scenario == "refund":
                    SMSService.send_rer_refund_processing(
                        mobile=mobile,
                        customer_name=customer_name,
                        order_no=order_no,
                        refund_amount=abs_amount
                    )
                else:
                    SMSService.send_rer_payment_required(
                        mobile=mobile,
                        customer_name=customer_name,
                        order_no=order_no,
                        amount=abs_amount
                    )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"RER SMS failed for {self.name}"
            )

        # ── Mail ──────────────────────────────────────────────────────────
        try:
            if email:
                subject, body = self._build_mail_content(
                    scenario=scenario,
                    customer_name=customer_name,
                    order_no=order_no,
                    new_so_name=new_so_name,
                    abs_amount=abs_amount,
                )
                frappe.sendmail(
                    recipients=[email],
                    subject=subject,
                    message=body,
                    now=True
                )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"RER Mail failed for {self.name}"
            )

    def _build_mail_content(self, scenario, customer_name, order_no, new_so_name, abs_amount):
        footer = """
            <br><br>
            <p style="font-size:12px; color:#888;">
                This is an automated message from Inventre Eduservices Pvt. Ltd.
                Please do not reply to this email.
            </p>
        """

        style = "font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.6;"

        if scenario == "missing":
            subject = f"Missing Item Replacement Confirmed - {order_no}"
            body = f"""
                <div style="{style}">
                    <p>Dear {customer_name},</p>
                    <p>Your missing item request for order <strong>{order_no}</strong>
                    has been approved and your replacement order
                    <strong>{new_so_name}</strong> is confirmed.</p>
                    <p>We will process your replacement shortly.</p>
                    {footer}
                </div>
            """

        elif scenario == "zero":
            subject = f"Exchange Confirmed - No Payment Needed - {order_no}"
            body = f"""
                <div style="{style}">
                    <p>Dear {customer_name},</p>
                    <p>Your exchange request for order <strong>{order_no}</strong>
                    has been approved. No additional payment is required.</p>
                    <p>Your replacement order <strong>{new_so_name}</strong>
                    is confirmed and will be processed shortly.</p>
                    {footer}
                </div>
            """

        elif scenario == "refund":
            subject = f"Exchange Approved - Refund of Rs.{abs_amount} Pending - {order_no}"
            body = f"""
                <div style="{style}">
                    <p>Dear {customer_name},</p>
                    <p>Your exchange request for order <strong>{order_no}</strong>
                    has been approved.</p>
                    <p>A refund of <strong>Rs.{abs_amount}</strong> is owed to you.
                    Please complete the checkout to provide your refund details
                    (UPI / Bank Account) so we can process it.</p>
                    <p>Replacement order reference: <strong>{new_so_name}</strong></p>
                    {footer}
                </div>
            """

        else:
            subject = f"Exchange Approved - Payment of Rs.{abs_amount} Required - {order_no}"
            body = f"""
                <div style="{style}">
                    <p>Dear {customer_name},</p>
                    <p>Your exchange request for order <strong>{order_no}</strong>
                    has been approved.</p>
                    <p>To confirm your replacement order <strong>{new_so_name}</strong>,
                    please complete the payment of <strong>Rs.{abs_amount}</strong>
                    via the app.</p>
                    {footer}
                </div>
            """

        return subject, body

    # ------------------------------------------------------------------ #
    #  Helper                                                              #
    # ------------------------------------------------------------------ #

    def _cleanup_stuck_draft(self, return_dn):
        try:
            if return_dn.name and frappe.db.exists("Delivery Note", return_dn.name):
                stuck = frappe.get_doc("Delivery Note", return_dn.name)
                if stuck.docstatus == 0:
                    frappe.delete_doc(
                        "Delivery Note",
                        return_dn.name,
                        force=True,
                        ignore_permissions=True
                    )
                    frappe.db.commit()
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Cleanup of stuck draft DN failed for RER {self.name}"
            )