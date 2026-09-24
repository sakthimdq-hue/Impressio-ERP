import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote


class CustomDeliveryNote(DeliveryNote):

    # def validate(self):
    #     from impressio.material_out.api.logistics.delivery_note import validate
    #     frappe.log_error(title='validate', message=str(validate))
    #     validate(self)

    def on_update_after_submit(self):
        frappe.log_error("ON UPDATE HIT", "DEBUG")
        if not self.custom_is_delivered or not self.custom_delivered_date:
            return

        so_ids = self._collect_sales_order_ids()
        frappe.log_error(title='so_ids', message=str(so_ids))
        if not so_ids:
            return

        for so_name in so_ids:
            if self._is_so_fully_delivered(so_name):
                self._complete_rer_for_sales_order(so_name)

    # ------------------------------------------------------------------ #
    #  Check Full Delivery                                                 #
    # ------------------------------------------------------------------ #

    def _is_so_fully_delivered(self, so_name: str) -> bool:
        linked_dn_names = frappe.get_all(
            "Delivery Note Item",
            filters={"against_sales_order": so_name, "docstatus": 1},
            pluck="parent",
        )
        custom_linked_dn_names = []
        if frappe.db.has_column("Delivery Note Item", "custom_custom_against_sales_order"):
            try:
                custom_linked_dn_names = frappe.get_all(
                    "Delivery Note Item",
                    filters={"custom_custom_against_sales_order": so_name, "docstatus": 1},
                    pluck="parent",
                )
            except Exception:
                custom_linked_dn_names = []

        all_dn_names = list(set(linked_dn_names + custom_linked_dn_names))
        if not all_dn_names:
            return False

        fields = ["name"]
        has_delivered_field = frappe.db.has_column("Delivery Note", "custom_is_delivered")
        has_delivered_date_field = frappe.db.has_column("Delivery Note", "custom_delivered_date")
        if has_delivered_field:
            fields.append("custom_is_delivered")
        if has_delivered_date_field:
            fields.append("custom_delivered_date")

        all_dns = frappe.get_all(
            "Delivery Note",
            filters={
                "name": ["in", all_dn_names],
                "docstatus": 1,
                "is_return": 0,
            },
            fields=fields,
        )

        if not all_dns:
            return False

        if not has_delivered_field or not has_delivered_date_field:
            return False

        return all(
            dn.get("custom_is_delivered") and dn.get("custom_delivered_date")
            for dn in all_dns
        )

    # ------------------------------------------------------------------ #
    #  Complete RER                                                        #
    # ------------------------------------------------------------------ #

    def _complete_rer_for_sales_order(self, so_name: str):
        if not frappe.db.table_exists("Return Exchange Request"):
            return

        try:
            rer_list = frappe.get_all(
                "Return Exchange Request",
                filters={
                    "replacement_sales_order": so_name,  # ✅ replacement SO
                    "status": "In Progress",
                },
                pluck="name",
            )

            if not rer_list:
                return

            for rer_name in rer_list:
                rer_doc = frappe.get_doc("Return Exchange Request", rer_name)
                rer_doc.status = "Completed"
                rer_doc.save(ignore_permissions=True)

            frappe.msgprint(
                f"{len(rer_list)} Return Exchange Request(s) marked as Completed for {so_name}.",
                indicator="green",
                alert=True,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Helper                                                              #
    # ------------------------------------------------------------------ #

    def _collect_sales_order_ids(self) -> list:
        so_ids = set()
        for item in self.items:
            if getattr(item, "against_sales_order", None):
                so_ids.add(item.against_sales_order)
            if getattr(item, "custom_custom_against_sales_order", None):
                so_ids.add(item.custom_custom_against_sales_order)
        return list(so_ids)