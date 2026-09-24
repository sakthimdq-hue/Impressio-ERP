# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import frappe.utils


class GatePass(Document):                
    def on_submit(self):
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.stock_entry_type = "Material Transfer"
        stock_entry.company = self.company

        for row in self.gate_pass_table:
            if row.qty <= 0:
                continue

            stock_entry.append("items", {
                "item_code": row.item_code,
                "qty": row.qty,
                "uom": row.uom,
                "s_warehouse": row.from_warehouse,
                "t_warehouse": row.warehouse,
                "conversion_factor": 1
            })

        stock_entry.insert(ignore_permissions=True)
        stock_entry.submit()

        frappe.msgprint(f"✔ Stock Transfer Created: <b>{stock_entry.name}</b>")
        