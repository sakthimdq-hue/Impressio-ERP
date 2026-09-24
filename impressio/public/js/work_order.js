frappe.ui.form.on("Work Order", {
   refresh: function (frm) {
      if (frm.doc.status === 'Completed') {
         frm.add_custom_button(__('Print QR'), function () {
            generate_qrcode(frm);
         });
      }
   }
});

function generate_qrcode(frm) {
   // Prepare simple QR data → only production_item
   let qr_data = {
      'production_item': frm.doc.production_item,
   };

   frappe.call({
      method: 'impressio.impressio_transaction.override_class.work_order.generate_work_order_qr',
      args: {
         'qr_data': qr_data
      },
      callback: function (r) {
         if (r.message) {
            print_qr_document(r.message, frm);
         }
      }
   });
}

function print_qr_document(qr_data, frm) {
   let print_html = `
    <html>
    <head>
        <title>Work Order QR</title>
        <style>
            body { font-family: Arial; padding: 20px; }
            .qr-box { width: 220px; border: 1px solid #ccc; padding: 10px; text-align:center; }
            .qr-img { margin: 10px 0; }
            .details { font-size: 12px; text-align:left; }
        </style>
    </head>
    <body>
        <div class="qr-box">
            <div><strong>${frm.doc.production_item}</strong></div>
            <div class="qr-img">
                <img src="data:image/png;base64,${qr_data.qr_image}" width="150" height="150">
            </div>
            <div class="details">
                <strong>FG Item:</strong> ${frm.doc.production_item}<br>
            </div>
        </div>
        <script>
            window.onload = function() { window.print(); }
        </script>
    </body>
    </html>
    `;

   let w = window.open('', '_blank');
   w.document.write(print_html);
   w.document.close();
}
