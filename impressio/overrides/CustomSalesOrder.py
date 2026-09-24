# your_app/overrides/sales_order.py

import frappe
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder


class CustomSalesOrder(SalesOrder):

    def on_update(self):
        super().on_update()
        if self._is_so_fully_delivered():
            self._complete_rer_for_sales_order()

    # ------------------------------------------------------------------ #
    #  Check Full Delivery                                                 #
    # ------------------------------------------------------------------ #

    def _is_so_fully_delivered(self) -> bool:
        """
        All submitted, non-returned Delivery Notes linked to this SO
        must have custom_is_delivered = 1 and custom_delivered_date set.
        """
        linked_dn_names = frappe.get_all(
            "Delivery Note Item",
            filters={"against_sales_order": self.name},
            pluck="parent",
        )

        if not linked_dn_names:
            return False

        all_dns = frappe.get_all(
            "Delivery Note",
            filters={
                "name": ["in", linked_dn_names],
                "docstatus": 1,     # submitted only
                "is_return": 0,     # exclude return notes
            },
            fields=["name", "custom_is_delivered", "custom_delivered_date"],
        )

        if not all_dns:
            return False

        return all(
            dn.custom_is_delivered and dn.custom_delivered_date
            for dn in all_dns
        )

    # ------------------------------------------------------------------ #
    #  Complete RER                                                        #
    # ------------------------------------------------------------------ #

    def _complete_rer_for_sales_order(self):
        """
        Find In-Progress Return Exchange Requests linked to this SO
        via replacement_sales_order → mark Completed.
        """
        rer_list = frappe.get_all(
            "Return Exchange Request",
            filters={
                "replacement_sales_order": self.name,
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
            f"{len(rer_list)} Return Exchange Request(s) marked as Completed.",
            indicator="green",
            alert=True,
        )