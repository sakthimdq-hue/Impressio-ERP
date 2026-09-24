import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import now_datetime, get_datetime


class WebsiteCartCoupon(Document):

    # =========================================================
    # VALIDATION
    # =========================================================
    def validate(self):

        # 1. Coupon Code Safety
        if not self.coupon_code:
            frappe.throw(_("Coupon Code is required"))

        self.coupon_code = self.coupon_code.strip().upper()

        # 2. Mutual Exclusion Rule
        if self.one_time_use and self.can_use_multiple_times:
            frappe.throw(_("Coupon cannot be both One Time Use and Multiple Use"))

        if self.one_time_use:
            self.can_use_multiple_times = 0

        if self.can_use_multiple_times:
            self.one_time_use = 0

        # 3. Discount Validation
        if self.discount_type not in ("Fixed", "Percentage"):
            frappe.throw(_("Discount Type must be either Fixed or Percentage"))

        if self.discount is None:
            frappe.throw(_("Discount value is required"))

        if self.discount <= 0:
            frappe.throw(_("Discount must be greater than 0"))

        if self.discount_type == "Percentage" and self.discount > 100:
            frappe.throw(_("Percentage discount cannot exceed 100%"))

        # 4. Maximum Discount Amount
        if self.maximum_discount_amount:
            if self.maximum_discount_amount <= 0:
                frappe.throw(_("Maximum Discount Amount must be greater than 0"))

            if self.discount_type == "Fixed":
                self.maximum_discount_amount = None

        # 5. Date Validation
        start_dt = None
        end_dt = None

        try:
            if self.start_datetime:
                start_dt = get_datetime(self.start_datetime)
                self.start_datetime = start_dt

            if self.end_datetime:
                end_dt = get_datetime(self.end_datetime)
                self.end_datetime = end_dt

            if start_dt and end_dt and end_dt < start_dt:
                frappe.throw(_("End Datetime must be after Start Datetime"))

            if end_dt and end_dt < now_datetime():
                frappe.throw(_("End Datetime cannot be in the past"))

        except Exception:
            frappe.throw(_("Invalid datetime format. Use YYYY-MM-DD HH:MM:SS"))

        # 6. School / Student Logic
        if self.student and not self.school:
            frappe.throw(_("School is required when Student is selected"))

        if self.is_active is None:
            self.is_active = 1



@frappe.whitelist()
def get_coupon_usage_data(coupon_name, page=1, page_length=10):

    page = int(page)
    page_length = int(page_length)
    start = (page - 1) * page_length

    # TOTAL RECORD COUNT
    total_records = frappe.db.count(
        "Sales Order",
        {
            "custom_cart_coupon_code": coupon_name,
            "docstatus": 1
        }
    )

    # SUMMARY
    totals = frappe.db.sql("""
        SELECT COUNT(name) as total_orders,
               IFNULL(SUM(discount_amount),0) as total_discount
        FROM `tabSales Order`
        WHERE custom_cart_coupon_code=%s AND docstatus=1
    """, coupon_name, as_dict=True)[0]

    # PAGINATED RECORDS
    sales_orders = frappe.get_all(
        "Sales Order",
        filters={
            "custom_cart_coupon_code": coupon_name,
            "docstatus": 1
        },
        fields=[
            "name",
            "customer",
            "transaction_date",
            "grand_total",
            "discount_amount"
        ],
        order_by="creation desc",
        start=start,
        page_length=page_length
    )

    return {
        "summary": totals,
        "records": sales_orders,
        "total_records": total_records
    }
