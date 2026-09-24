# Copyright (c) 2025, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class GateEntry(Document):
    def before_save(self):
        if not self.name.startswith("#"):
            self.name = f"#{self.name}"
        if not self.gate_entry_number:
            self.gate_entry_number = self.name
 