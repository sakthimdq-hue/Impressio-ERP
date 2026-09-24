# Copyright (c) 2026, MDQ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebsiteNotificationSchool(Document):
	pass



@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def school_query(doctype, txt, searchfield, start, page_len, filters):

    return frappe.db.sql("""
        SELECT
            name,
            school_name
        FROM `tabSchool`
        WHERE
            name LIKE %(txt)s
            OR school_name LIKE %(txt)s
        ORDER BY school_name
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })