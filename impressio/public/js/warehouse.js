frappe.ui.form.on("Warehouse", {
   refresh: function (frm) {
      // Ensure button only appears when document is saved
      if (!frm.doc.__islocal) {
         frm.add_custom_button(__('Print QR Code'), function () {
            generateWarehouseQRCode(frm);
         });
      }
   }
});

function generateWarehouseQRCode(frm) {

   let qr_payload = {
      warehouse_name: frm.doc.warehouse_name,
      warehouse_id: frm.doc.name,
      parent_warehouse: frm.doc.parent_warehouse || '',
      warehouse_type: frm.doc.warehouse_type || '',
      timestamp: frappe.datetime.now_datetime()
   };

   frappe.call({
      method: "impressio.impressio_transaction.override_class.warehouse.generate_warehouse_qr",
      args: {
         qr_data: qr_payload
      },
      callback: function (r) {
         if (r.message) {
            printWarehouseQR(frm, r.message);
         }
      },
      error: function (err) {
         frappe.msgprint(__('Error generating Warehouse QR: {0}', [err.message]));
      }
   });
}

function printWarehouseQR(frm, qr_data) {

   let html = `
    <html>
    <head>
        <title>Warehouse QR</title>
        <style>
            @page {
                size: 50mm 25mm;
                margin: 0;
            }

            body {
                margin: 0;
                padding: 0;
                font-family: Arial, sans-serif;
            }

            .qr-label {
                width: 50mm;
                height: 25mm;
                box-sizing: border-box;
                padding: 2mm;
                display: flex;
                flex-direction: row;
                align-items: center;
                border: 1px solid #000;
            }

            .qr-section {
                width: 20mm;
                text-align: center;
            }

            .qr-section img {
                width: 18mm;
                height: 18mm;
            }

            .info-section {
                width: 28mm;
                font-size: 8px;
                padding-left: 2mm;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                height: 100%;
            }

            .title {
                font-size: 9px;
                font-weight: bold;
                margin-bottom: 1mm;
            }

            .row {
                line-height: 1.2;
            }

            .date {
                text-align: right;
                font-size: 7px;
                margin-top: auto;
            }
        </style>
    </head>
    <body>
        <div class="qr-label">
            
            <div class="qr-section">
                <img src="data:image/png;base64,${qr_data.qr_image}" />
            </div>

            <div class="info-section">
                <div>
                    <div class="title">${frm.doc.warehouse_name}</div>
                    <div class="row"><strong>ID:</strong> ${frm.doc.name}</div>
                    <div class="row"><strong>Type:</strong> ${frm.doc.warehouse_type || 'N/A'}</div>
                    <div class="row"><strong>Parent:</strong> ${frm.doc.parent_warehouse || 'N/A'}</div>
                </div>

                <div class="date">
                    ${frappe.datetime.nowdate()}
                </div>
            </div>

        </div>

        <script>
            window.onload = function() {
                window.print();
            };
        </script>
    </body>
    </html>`;

   let w = window.open("", "_blank");
   w.document.write(html);
   w.document.close();
}
