import frappe
import requests

@frappe.whitelist(allow_guest=True)
def get_auth_token():
    url = "https://api.ekartlogistics.com/login/v1/oauth/token"

    payload = {
        "username": frappe.conf.ekart_username,
        "password": frappe.conf.ekart_password,
        "grant_type": "password"
    }

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        frappe.log_error(response.text, "Ekart Auth Error")
        return None

    return response.json().get("access_token")
