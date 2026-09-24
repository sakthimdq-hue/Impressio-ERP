import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from impressio.material_out.packing_material.custom_fields import get_packing_material_custom_fields


def get_warehouse_custom_fields():
	"""Returns custom fields for Sales Order, Delivery Note, and Delivery Note Item"""
	return {
		"Sales Order": [
			{
				"fieldname": "custom_display_status",
				"label": "Display Status",
				"fieldtype": "Select",
				"options": "\nNot Yet Delivered\nShipment Created\nPartially Delivered\nCancelled",
				"insert_after": "status",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"read_only": 1,
				"description": "Auto-calculated warehouse delivery status",
			}
		],
		"Delivery Note": [
			{
				"fieldname": "custom_logistics_section",
				"label": "Logistics & Delivery Info",
				"fieldtype": "Section Break",
				"insert_after": "terms",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_is_delivered",
				"label": "Is Delivered",
				"fieldtype": "Check",
				"insert_after": "custom_logistics_section",
				"read_only": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_delivered_date",
				"label": "Delivered Date",
				"fieldtype": "Datetime",
				"insert_after": "custom_is_delivered",
				"read_only": 1,
			},
			{
				"fieldname": "tracking_status",
				"label": "Tracking Status JSON",
				"fieldtype": "Long Text",
				"insert_after": "custom_delivered_date",
				"hidden": 1,
			},
		],
		"Delivery Note Item": [
			{
				"fieldname": "custom_custom_against_sales_order",
				"label": "Against Sales Order",
				"fieldtype": "Link",
				"options": "Sales Order",
				"insert_after": "against_sales_order",
				"description": "Linked Sales Order for sub-items / bundle components",
			}
		],
	}


def get_quotation_custom_fields():
	"""Custom fields for Quotation and Quotation Item to capture external Impressio API data"""
	return {
		"Quotation": [
			{
				"fieldname": "custom_external_quotation_section",
				"label": "External Impressio Quotation Details",
				"fieldtype": "Section Break",
				"insert_after": "order_type",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_quote_number",
				"label": "External Quote Number",
				"fieldtype": "Data",
				"insert_after": "custom_external_quotation_section",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"read_only": 1,
			},
			{
				"fieldname": "custom_external_quote_id",
				"label": "External Quote ID",
				"fieldtype": "Int",
				"insert_after": "custom_quote_number",
				"read_only": 1,
			},
			{
				"fieldname": "custom_school_name",
				"label": "School Name",
				"fieldtype": "Data",
				"insert_after": "custom_external_quote_id",
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_academic_year",
				"label": "Academic Year",
				"fieldtype": "Data",
				"insert_after": "custom_school_name",
			},
			{
				"fieldname": "custom_external_status",
				"label": "External Status",
				"fieldtype": "Data",
				"insert_after": "custom_academic_year",
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_created_by_name",
				"label": "Created By (External)",
				"fieldtype": "Data",
				"insert_after": "custom_external_status",
			},
			{
				"fieldname": "custom_agent_col_break",
				"fieldtype": "Column Break",
				"insert_after": "custom_created_by_name",
			},
			{
				"fieldname": "custom_agent_name",
				"label": "Agent Name",
				"fieldtype": "Data",
				"insert_after": "custom_agent_col_break",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_agent_id",
				"label": "Agent ID",
				"fieldtype": "Data",
				"insert_after": "custom_agent_name",
			},
			{
				"fieldname": "custom_customer_phone",
				"label": "Customer Phone",
				"fieldtype": "Data",
				"insert_after": "custom_agent_id",
			},
			{
				"fieldname": "custom_customer_email",
				"label": "Customer Email",
				"fieldtype": "Data",
				"insert_after": "custom_customer_phone",
			},
			{
				"fieldname": "custom_city",
				"label": "City",
				"fieldtype": "Data",
				"insert_after": "custom_customer_email",
			},
			{
				"fieldname": "custom_state",
				"label": "State",
				"fieldtype": "Data",
				"insert_after": "custom_city",
			},
			{
				"fieldname": "custom_pincode",
				"label": "Pincode",
				"fieldtype": "Data",
				"insert_after": "custom_state",
			},
			{
				"fieldname": "custom_commission_section",
				"label": "Commission & Totals Breakdown",
				"fieldtype": "Section Break",
				"insert_after": "custom_pincode",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_agent_commission_percent",
				"label": "Agent Commission %",
				"fieldtype": "Percent",
				"insert_after": "custom_commission_section",
			},
			{
				"fieldname": "custom_agent_commission_amount",
				"label": "Agent Commission Amount",
				"fieldtype": "Currency",
				"insert_after": "custom_agent_commission_percent",
			},
			{
				"fieldname": "custom_school_commission_amount",
				"label": "School Commission Amount",
				"fieldtype": "Currency",
				"insert_after": "custom_agent_commission_amount",
			},
			{
				"fieldname": "custom_totals_col_break",
				"fieldtype": "Column Break",
				"insert_after": "custom_school_commission_amount",
			},
			{
				"fieldname": "custom_total_before_gst",
				"label": "Total Before GST (External)",
				"fieldtype": "Currency",
				"insert_after": "custom_totals_col_break",
			},
			{
				"fieldname": "custom_total_gst_amount",
				"label": "Total GST (External)",
				"fieldtype": "Currency",
				"insert_after": "custom_total_before_gst",
			},
			{
				"fieldname": "custom_api_grand_total",
				"label": "Grand Total (External)",
				"fieldtype": "Currency",
				"insert_after": "custom_total_gst_amount",
			},
		],
		"Quotation Item": [
			{
				"fieldname": "custom_product_id",
				"label": "External Product ID",
				"fieldtype": "Int",
				"insert_after": "item_name",
				"read_only": 1,
			},
			{
				"fieldname": "custom_category_name",
				"label": "Category",
				"fieldtype": "Data",
				"insert_after": "custom_product_id",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_tier_group",
				"label": "Tier / Group",
				"fieldtype": "Data",
				"insert_after": "custom_category_name",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_addon_1",
				"label": "Addon 1",
				"fieldtype": "Data",
				"insert_after": "custom_tier_group",
			},
			{
				"fieldname": "custom_addon_2",
				"label": "Addon 2",
				"fieldtype": "Data",
				"insert_after": "custom_addon_1",
			},
			{
				"fieldname": "custom_addon_3",
				"label": "Addon 3",
				"fieldtype": "Data",
				"insert_after": "custom_addon_2",
			},
			{
				"fieldname": "custom_unit_price_msp",
				"label": "MSP Rate",
				"fieldtype": "Currency",
				"insert_after": "rate",
			},
			{
				"fieldname": "custom_addon_cost",
				"label": "Addon Cost",
				"fieldtype": "Currency",
				"insert_after": "custom_unit_price_msp",
			},
			{
				"fieldname": "custom_surcharge",
				"label": "Surcharge",
				"fieldtype": "Currency",
				"insert_after": "custom_addon_cost",
			},
			{
				"fieldname": "custom_subtotal_before_gst",
				"label": "Subtotal Before GST",
				"fieldtype": "Currency",
				"insert_after": "custom_surcharge",
			},
			{
				"fieldname": "custom_gst_rate",
				"label": "GST Rate %",
				"fieldtype": "Percent",
				"insert_after": "custom_subtotal_before_gst",
			},
			{
				"fieldname": "custom_gst_amount",
				"label": "GST Amount",
				"fieldtype": "Currency",
				"insert_after": "custom_gst_rate",
			},
			{
				"fieldname": "custom_final_mrp_per_unit",
				"label": "Final MRP / Unit",
				"fieldtype": "Currency",
				"insert_after": "custom_gst_amount",
			},
			{
				"fieldname": "custom_agent_commission_amount",
				"label": "Agent Commission",
				"fieldtype": "Currency",
				"insert_after": "custom_final_mrp_per_unit",
			},
			{
				"fieldname": "custom_school_commission_amount",
				"label": "School Commission",
				"fieldtype": "Currency",
				"insert_after": "custom_agent_commission_amount",
			},
		],
	}


def get_student_custom_fields():
	"""Custom fields for Students doctype to capture external Impressio API data"""
	return {
		"Students": [
			{
				"fieldname": "custom_external_student_section",
				"label": "External Impressio Student Info",
				"fieldtype": "Section Break",
				"insert_after": "customer_group",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_external_student_id",
				"label": "External Student ID",
				"fieldtype": "Int",
				"insert_after": "custom_external_student_section",
				"in_list_view": 1,
				"read_only": 1,
			},
			{
				"fieldname": "custom_school_id",
				"label": "School ID",
				"fieldtype": "Int",
				"insert_after": "custom_external_student_id",
				"read_only": 1,
			},
			{
				"fieldname": "custom_school_name",
				"label": "School Name",
				"fieldtype": "Data",
				"insert_after": "custom_school_id",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_school_city",
				"label": "School City",
				"fieldtype": "Data",
				"insert_after": "custom_school_name",
			},
			{
				"fieldname": "custom_school_state",
				"label": "School State",
				"fieldtype": "Data",
				"insert_after": "custom_school_city",
			},
			{
				"fieldname": "custom_student_col_break",
				"fieldtype": "Column Break",
				"insert_after": "custom_school_state",
			},
			{
				"fieldname": "custom_student_code",
				"label": "Student Code",
				"fieldtype": "Data",
				"insert_after": "custom_student_col_break",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_academic_year",
				"label": "Academic Year",
				"fieldtype": "Data",
				"insert_after": "custom_student_code",
			},
			{
				"fieldname": "custom_grade_id",
				"label": "Grade ID",
				"fieldtype": "Int",
				"insert_after": "custom_academic_year",
			},
			{
				"fieldname": "custom_section_id",
				"label": "Section ID",
				"fieldtype": "Int",
				"insert_after": "custom_grade_id",
			},
			{
				"fieldname": "custom_house_id",
				"label": "House ID",
				"fieldtype": "Int",
				"insert_after": "custom_section_id",
			},
			{
				"fieldname": "custom_house_name",
				"label": "House Name",
				"fieldtype": "Data",
				"insert_after": "custom_house_id",
			},
			{
				"fieldname": "custom_customer_mapping_status",
				"label": "Customer Mapping Status",
				"fieldtype": "Data",
				"insert_after": "custom_house_name",
			},
			{
				"fieldname": "custom_customer_mapped_on",
				"label": "Customer Mapped On",
				"fieldtype": "Datetime",
				"insert_after": "custom_customer_mapping_status",
			},
			{
				"fieldname": "custom_subject_names",
				"label": "Subjects",
				"fieldtype": "Small Text",
				"insert_after": "custom_customer_mapped_on",
			},
			{
				"fieldname": "custom_full_address",
				"label": "Full Address",
				"fieldtype": "Small Text",
				"insert_after": "custom_subject_names",
			},
		]
	}


def get_sales_order_custom_fields():
	"""Custom fields for Sales Order to capture external Impressio Website Order data"""
	return {
		"Sales Order": [
			{
				"fieldname": "custom_external_order_section",
				"label": "External Website Order Info",
				"fieldtype": "Section Break",
				"insert_after": "custom_display_status",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_external_order_id",
				"label": "External Order ID",
				"fieldtype": "Int",
				"insert_after": "custom_external_order_section",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"read_only": 1,
			},
			{
				"fieldname": "custom_student_name",
				"label": "Student Name (Order)",
				"fieldtype": "Data",
				"insert_after": "custom_external_order_id",
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "custom_student_id",
				"label": "Student ID (Order)",
				"fieldtype": "Data",
				"insert_after": "custom_student_name",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_ordered_by",
				"label": "Ordered By",
				"fieldtype": "Data",
				"insert_after": "custom_student_id",
			},
			{
				"fieldname": "custom_external_order_status",
				"label": "External Order Status",
				"fieldtype": "Data",
				"insert_after": "custom_ordered_by",
				"in_list_view": 1,
			},
			{
				"fieldname": "custom_shipping_charges",
				"label": "Shipping Charges",
				"fieldtype": "Currency",
				"insert_after": "custom_external_order_status",
			},
		]
	}


@frappe.whitelist()
def setup_all_custom_fields():
	"""Setup all custom fields needed for warehouse operations, packing materials, external quotations, external orders, and students"""
	wh_fields = get_warehouse_custom_fields()
	create_custom_fields(wh_fields, update=True)

	pm_fields = get_packing_material_custom_fields()
	create_custom_fields(pm_fields, update=True)

	qtn_fields = get_quotation_custom_fields()
	create_custom_fields(qtn_fields, update=True)

	so_fields = get_sales_order_custom_fields()
	create_custom_fields(so_fields, update=True)

	student_fields = get_student_custom_fields()
	create_custom_fields(student_fields, update=True)

	frappe.db.commit()
	frappe.clear_cache()
	frappe.msgprint("All custom fields created successfully!", alert=True)
	return {"success": True, "message": "Custom fields created successfully"}


