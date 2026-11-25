"""Shared template context processors for Advance Billing System."""

_ACTIVE_PAGE_BY_URL_NAME = {
    "admin_dashboard": "dashboard",
    "admin_distributor_detail": "distributors",
    "distributor_dashboard": "dashboard",
    "customer_list": "customers",
    "customer_add": "customers",
    "customer_register": "customers",
    "customer_register_alias": "customers",
    "customer_register_page": "customers",
    "customer_detail": "customers",
    "customer_edit": "customers",
    "customer_ledger": "customers",
    "product_list": "products",
    "product_add": "products",
    "product_edit": "products",
    "product_detail": "products",
    "stock_ledger": "products",
    "invoice_list": "invoices",
    "invoice_create": "invoices",
    "invoice_detail": "invoices",
    "invoice_edit": "invoices",
    "invoice_preview": "invoices",
    "quotation_list": "quotations",
    "quotation_create": "quotations",
    "quotation_detail": "quotations",
    "invoice_report": "reports",
    "reports_invoices": "reports",
    "qr_decoder": "qr",
    "tools_qr_decoder": "qr",
    "distributor_profile": "profile",
    "update_profile": "profile",
}


def active_nav_context(request):
    """Automatically provide `active_page` for the shared header navigation."""
    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    return {"active_page": _ACTIVE_PAGE_BY_URL_NAME.get(url_name, "")}

