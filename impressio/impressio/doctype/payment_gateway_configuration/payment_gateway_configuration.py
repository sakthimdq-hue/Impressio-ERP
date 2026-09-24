import frappe
from frappe.model.document import Document


class PaymentGatewayConfiguration(Document):

    # ------------------------------------------------------------
    # Build standardized name: PROVIDER-ENVIRONMENT
    # Example: CCAVENUE-LIVE, PINELABS-UAT
    # ------------------------------------------------------------
    def _build_name(self):
        provider = (self.gateway_provider or "").strip().upper()
        env = (self.environment or "").strip().upper()
        return f"{provider}-{env}"

    # ------------------------------------------------------------
    # Set name when creating new document
    # ------------------------------------------------------------
    def autoname(self):
        if self.gateway_provider and self.environment:
            self.name = self._build_name()

    # ------------------------------------------------------------
    # Rename automatically if provider or environment changes
    # ------------------------------------------------------------
    def before_save(self):

        # Skip rename for new documents
        if self.is_new():
            return

        # Get previous saved version from DB
        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_name = old_doc.name
        new_name = self._build_name()

        # If name is same → nothing to do
        if old_name == new_name:
            return

        # Prevent infinite rename recursion
        if getattr(frappe.flags, "in_gateway_rename", False):
            return

        frappe.flags.in_gateway_rename = True

        try:
            # Bypass permission checks (system rename)
            frappe.flags.ignore_permissions = True

            frappe.rename_doc(
                self.doctype,
                old_name,
                new_name,
                force=True,
                merge=False
            )

            # Update current document object
            self.name = new_name

            # Clear cache so scheduler/webhook uses new config
            frappe.clear_cache()

        finally:
            frappe.flags.in_gateway_rename = False
            frappe.flags.ignore_permissions = False

    # ------------------------------------------------------------
    # Validation:
    # Allow multiple environments
    # BUT prevent duplicate ACTIVE config for same provider+environment
    # ------------------------------------------------------------
    def validate(self):

        if not self.is_active:
            return

        duplicate = frappe.db.exists(
            self.doctype,
            {
                "gateway_provider": self.gateway_provider,
                "environment": self.environment,
                "is_active": 1,
                "name": ["!=", self.name],
            },
        )

        if duplicate:
            frappe.throw(
                f"An ACTIVE configuration already exists for "
                f"<b>{self.gateway_provider} - {self.environment}</b>: "
                f"<b>{duplicate}</b>"
            )