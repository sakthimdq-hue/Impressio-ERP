import frappe
from erpnext.stock.doctype.batch.batch import get_batch_qty

def validate(self, method=None):
    for row in self.items:
        if not row.item_code:
            continue

        # Determine warehouse
        warehouse = row.s_warehouse or row.t_warehouse
        if not warehouse:
            continue

        # 🔥 GET ITEM
        item = frappe.get_doc("Item", row.item_code)

        # ✅ SKIP NON-BATCH ITEMS COMPLETELY
        if not item.has_batch_no:
            continue

        # 🔁 ONLY BATCH ITEMS BELOW THIS LINE
        batches = get_batch_qty(
            item_code=row.item_code,
            warehouse=warehouse
        )

        selected_batch = None
        for b in batches:
            if (b.get("qty") or 0) >= row.qty:
                selected_batch = b.get("batch_no")
                break

        if selected_batch:
            row.batch_no = selected_batch
            continue

        # 🏭 MANUFACTURE → AUTO CREATE BATCH
        if self.stock_entry_type == "Manufacture":
            if not row.batch_no:
                last_batch = frappe.db.sql("""
                    SELECT batch_id
                    FROM `tabBatch`
                    WHERE batch_id REGEXP '^[0-9]+$'
                    ORDER BY CAST(batch_id AS UNSIGNED) DESC
                    LIMIT 1
                """, as_dict=True)

                last_no = int(last_batch[0].batch_id) if last_batch else 0
                new_batch_no = str(last_no + 1)

                batch = frappe.new_doc("Batch")
                batch.item = row.item_code
                batch.batch_id = new_batch_no
                batch.insert(ignore_permissions=True)

                row.batch_no = new_batch_no
                frappe.msgprint(
                    f"Batch #{new_batch_no} created and assigned to {row.item_code}"
                )
        else:
            frappe.throw(
                f"No available batch with stock for item {row.item_code} in {warehouse}"
            )
