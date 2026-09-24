import frappe
import re
import qrcode
import base64
import json
from io import BytesIO

def validate(self,method=None):
   last_batch = frappe.db.sql("""
      SELECT batch_id
      FROM `tabBatch`
      WHERE batch_id REGEXP '^[0-9]+$'
      ORDER BY CAST(batch_id AS UNSIGNED) DESC
      LIMIT 1
   """, as_dict=True)

   last_batch_no = int(last_batch[0].batch_id) if last_batch else 0
   new_batch_no = last_batch_no + 1

   # For each item in Purchase Receipt
   for item in self.items:
      print(f"\n{item.batch_no}\n")
      if (item.batch_no == None) and (self.docstatus != 1):
         # Create a new Batch doc
         batch = frappe.new_doc("Batch")
         batch.item = item.item_code
         batch.batch_id = str(new_batch_no)
         batch.save(ignore_permissions=True)

         # Assign batch to Purchase Receipt Item
         item.batch_no = batch.name

         frappe.msgprint(f"Batch #{new_batch_no} created and assigned to all items.")

@frappe.whitelist()
def generate_qr_code(qr_data, quantity):
   """Generate QR code for purchase receipt items"""
   try:
      # Parse qr_data if it's a string, otherwise use as is
      if isinstance(qr_data, str):
         qr_info = frappe._dict(json.loads(qr_data))
      else:
         qr_info = frappe._dict(qr_data)
      
      # Create QR code content
      qr_content = f"""
         PURCHASE RECEIPT: {qr_info.purchase_receipt}
         ITEM: {qr_info.item_code}
         NAME: {qr_info.item_name}
         QUANTITY TYPE: {qr_info.quantity_type.upper()}
         SEQUENCE NO: {qr_info.start_number}
         BATCH: {qr_info.batch_no or 'N/A'}
         SERIAL: {qr_info.serial_no or 'N/A'}
         PRINT TYPE: {qr_info.print_type.upper()}
         TIME: {qr_info.timestamp}
         """

      # Generate QR code
      qr = qrcode.QRCode(
         version=1,
         error_correction=qrcode.constants.ERROR_CORRECT_L,
         box_size=10,
         border=4,
      )
      qr.add_data(qr_content)
      qr.make(fit=True)
      img = qr.make_image(fill_color="black", back_color="white")

      # Convert to base64 for web display
      buffered = BytesIO()
      img.save(buffered, format="PNG")
      img_str = base64.b64encode(buffered.getvalue()).decode()

      return {
         'qr_image': img_str,
         'qr_content': qr_content,
         'quantity': int(quantity),
         'print_type': qr_info.print_type,
         'item_code': qr_info.item_code,
         'item_name': qr_info.item_name,
         'quantity_type': qr_info.quantity_type,
         'start_number': qr_info.start_number
      }
   except Exception as e:
      frappe.log_error(frappe.get_traceback(), 'QR Code Generation Error')
      frappe.throw(f"Error generating QR code: {str(e)}")