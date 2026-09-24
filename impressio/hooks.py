app_name = "impressio"
app_title = "Impressio"
app_publisher = "Sakthi"
app_description = "Impressio App"
app_email = "sakthimurugan@mdqualityapps.com"
app_license = "mit"

# Export Role fixtures (Category Team, Logistics Team, Sales Team, Business Head)
fixtures = [
	{
		"doctype": "Role",
		"filters": [
			["name", "in", ["Category Team", "Logistics Team", "Sales Team", "Business Head"]]
		],
	},
	{
		"doctype": "Custom DocPerm",
		"filters": [
			["role", "in", ["Category Team", "Logistics Team", "Sales Team"]]
		],
	},
	{
		"doctype": "Custom Field",
		"filters": [
			["dt", "in", ["Sales Invoice", "Sales Order", "Delivery Note", "Stock Entry", "Purchase Receipt", "Item", "Customer", "BOM", "Mode of Payment", "Quotation", "Quotation Item", "Students"]]
		]
	}
]

# Apps
# ------------------

# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_js = [
	"assets/impressio/js/override_js/table_multiselected_patch2.js",
	"/assets/impressio/js/sales_invoice_force.js",
	"assets/impressio/js/list_pagination.js",
]

# include js in doctype views
doctype_js = {
	"Delivery Note": "public/js/delivery_note.js",
	"Warehouse": "public/js/warehouse.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Item": "material_out/packing_material/item_packing_material.js",
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
	"Quality Inspection": "public/js/quality_inspection.js",
}

doctype_list_js = {
	"Item": "public/js/item_list.js",
	"Sales Order": "public/js/sales_order_list.js",
	"Delivery Note": "public/js/delivery_note_list.js",
	"Pick List": "public/js/pick_list_list.js",
	"Stock Entry": "public/js/stock_entry_list.js",
	"Quotation": "public/js/quotation_list.js",
	"BOM": "public/js/bom_list.js",
	"Website Cart Coupon": "public/js/cart_coupon_list.js",
	"Students": "public/js/students_list.js",
}

# Installation
# ------------

after_install = "impressio.setup_custom_fields.setup_all_custom_fields"
after_migrate = "impressio.setup_custom_fields.setup_all_custom_fields"

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
	"Sales Invoice": "impressio.overrides.sales_invoice.sales_invoice.CustomSalesInvoice",
	"Delivery Note": "impressio.overrides.CustomDeliveryNote.CustomDeliveryNote",
	"Sales Order": "impressio.overrides.CustomSalesOrder.CustomSalesOrder",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Purchase Receipt": {
		"validate": "impressio.impressio_transaction.override_class.purchase_receipt.validate"
	},
	"Stock Entry": {
		"validate": "impressio.impressio_transaction.override_class.stock_entry.validate"
	},
	"Item": {
		"validate": [
			"impressio.material_out.packing_material.utils.validate_packing_material",
		],
		"before_save": "impressio.material_out.packing_material.utils.calculate_packing_material_cbm",
		"after_insert": "impressio.material_out.packing_material.qr_code.generate_packing_material_qr",
		"on_update": "impressio.material_out.packing_material.qr_code.generate_packing_material_qr",
	},
	"Delivery Note": {
		"on_submit": "impressio.impressio.bulk_delivery_note.on_delivery_note_submit",
		"on_cancel": "impressio.impressio.bulk_delivery_note.on_delivery_note_submit",
	},
	"Sales Order": {
		"on_submit": "impressio.impressio.bulk_delivery_note.on_sales_order_submit",
		"on_cancel": "impressio.impressio.bulk_delivery_note.on_sales_order_cancel",
		"before_save": "impressio.impressio.bulk_delivery_note.on_sales_order_save",
	},
}
