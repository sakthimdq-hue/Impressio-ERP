import frappe
import hashlib
from impressio.impressio.api.helper import (sanitize_request, success, error)

RECIPIENTS = ["it@impressio.in"]  # List of email addresses to receive partnership requests

@frappe.whitelist(allow_guest=True)
def send_school_partnership(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=[
            "school_name",
            "contact_person",
            "official_email",
            "phone_number",
        ],
        optional=[
            "partnership_interest",
            "school_board",
            "school_address",
            "additional_information"
        ]
    )

    if is_error:
        return error(payload, 422)

    try:

        school_name = payload.get("school_name")
        contact_person = payload.get("contact_person")
        official_email = payload.get("official_email")
        phone_number = payload.get("phone_number")
        partnership_interest = payload.get("partnership_interest")
        school_board = payload.get("school_board")
        school_address = payload.get("school_address")
        additional_information = payload.get("additional_information")

        message = f"""
        <h3>New School Partnership Request</h3>

        <b>School Name:</b> {school_name} <br>
        <b>Contact Person:</b> {contact_person} <br>
        <b>Official Email:</b> {official_email} <br>
        <b>Phone Number:</b> {phone_number} <br>
        <b>Partnership Interest:</b> {partnership_interest or "-"} <br>
        <b>School Board:</b> {school_board or "-"} <br>
        <b>School Address:</b> {school_address or "-"} <br>
        <b>Additional Information:</b> {additional_information or "-"} <br>
        """

        frappe.sendmail(
            recipients=RECIPIENTS,
            subject="New School Partnership Request",
            message=message,
            now=True   # immediate send
        )

        return success("Request sent successfully")

    except Exception as e:

        frappe.log_error(
            title="School Partnership Email Failed",
            message=frappe.get_traceback()
        )

        return error({
            "message": "Email sending failed",
            "details": str(e)
        }, 500)



@frappe.whitelist(allow_guest=True)
def send_business_partnership(**kwargs):

    is_error, payload = sanitize_request(
        kwargs,
        required=[
            "business_name",
            "contact_person",
            "email_address",
            "phone_number",
        ],
        optional=[
            "business_type",
            "gst_number",
            "business_address",
            "additional_information"
        ]
    )

    if is_error:
        return error(payload, 422)

    try:

        business_name = payload.get("business_name")
        contact_person = payload.get("contact_person")
        email_address = payload.get("email_address")
        phone_number = payload.get("phone_number")
        business_type = payload.get("business_type")
        gst_number = payload.get("gst_number")
        business_address = payload.get("business_address")
        additional_information = payload.get("additional_information")

        message = f"""
        <h3>New Business Partnership Request</h3>

        <b>Business Name:</b> {business_name} <br>
        <b>Contact Person:</b> {contact_person} <br>
        <b>Email Address:</b> {email_address} <br>
        <b>Phone Number:</b> {phone_number} <br>
        <b>Business Type:</b> {business_type or "-"} <br>
        <b>GST Number:</b> {gst_number or "-"} <br>
        <b>Business Address:</b> {business_address or "-"} <br>
        <b>Additional Information:</b> {additional_information or "-"} <br>
        """

        frappe.sendmail(
            recipients=RECIPIENTS,
            subject="New Business Partnership Request",
            message=message,
            now=True
        )

        return success("Request sent successfully")

    except Exception as e:

        frappe.log_error(
            title="Business Partnership Email Failed",
            message=frappe.get_traceback()
        )

        return error({
            "message": "Email sending failed",
            "details": str(e)
        }, 500)