<p align="center">
  <img src="static/images/brand_logo_full.png" alt="Advance Billing System" width="360">
</p>

# 🧾 Advance Billing System

## Project Description

**Advance Billing System** is a modern, multi-tenant Indian GST billing, inventory, and distribution ERP web application built with **Python and Django**. It provides an end-to-end digital billing platform that enables businesses and distributors to manage customers, track product stock with audit logs, create multi-item GST tax invoices (CGST/SGST & IGST), record partial payments in a Customer Khata ledger, convert quotations to tax invoices in one click, generate branded A4 PDF invoices with UPI & verification QR codes, and export CA-ready GSTR-1 reports.

The platform implements **Role-Based Access Control (RBAC)** with strict multi-tenant data isolation across two dedicated portals:

- **Distributor Portal**: Manage own customers & Khata (Udhar) ledger, product inventory & stock-in audit trail, fast POS tax invoicing, quotations/estimates, partial payments, QR code invoice verification, date-range & GSTR-1 CSV/PDF reports, profile management, and interactive 6-month Sales & GST analytics.
- **Admin Portal**: Centralized control center providing platform-wide KPIs, revenue & GST trend charts, distributor rankings, settlement & stock health analytics, system-wide low-stock watchlist, distributor activate/deactivate controls, CSV exports, and one-click database backups.

---

## Features

- **User Registration, Roles & Email OTP**: Separate Admin and Distributor login portals, 2-step distributor registration with Gmail SMTP OTP verification, session-based authentication, and 3-step OTP password recovery with rate limiting.
- **Customer Management & Khata Ledger**: Full customer CRUD with search, pagination, GSTIN validation, running Debit/Credit balance, overdue alerts, quick payment recording, WhatsApp due reminders, and CSV statement export.
- **Product Inventory & Stock-In Audit Ledger**: Product catalog with SKU, HSN/SAC codes, GST slabs, low-stock alerts, and full movement tracking (opening stock, purchase restocks, sales deductions, edit/cancellation restores).
- **Advanced GST Tax Invoicing**: Dynamic multi-row invoice creator with SKU quick-add, live intra-state (CGST+SGST) vs inter-state (IGST) calculation, server-side total validation, atomic stock locking, partial payments, and safe invoice editing/cancellation.
- **Quotations & 1-Click Conversion**: Create non-stock GST estimates/quotations, download PDFs, share via WhatsApp, and convert approved quotes into final Tax Invoices in one click.
- **Branded PDF Invoices & Dual QR Codes**: Instant A4 PDF generation (`xhtml2pdf`) with HSN-wise tax breakup, Indian Amount in Words, pre-filled UPI Scan & Pay QR code, Invoice Verification QR code, and direct email/WhatsApp sharing.
- **QR Code Scanner & Decoder**: Upload invoice/QR images to decode and verify authentic invoices directly against the database (`pyzbar` + Pillow).
- **Analytics Dashboards & GSTR-1 Reports**: Interactive Bar/Area monthly sales charts, date-range revenue & collection reports, PDF report export, and CA-ready GSTR-1 B2B / B2C / HSN CSV exports.

---

## Installation & Setup

### Windows (PowerShell / Command Prompt)

```powershell
# 1. Clone the repository
git clone https://github.com/sneh125/advance-billing-system.git
cd advance-billing-system

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1
# For standard Command Prompt: venv\Scripts\activate.bat

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Set up environment variables (add Gmail SMTP credentials in .env for real email OTP)
copy .env.example .env

# 5. Apply database migrations
python manage.py makemigrations
python manage.py migrate

# 6. (Optional) Seed sample distributor, customers, products, and invoices
python seed_data.py

# 7. Create a superuser (admin account)
python manage.py createsuperuser

# 8. Start the development server
python manage.py runserver
```

### macOS / Linux (Terminal)

```bash
# 1. Clone the repository
git clone https://github.com/sneh125/advance-billing-system.git
cd advance-billing-system

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Set up environment variables (add Gmail SMTP credentials in .env for real email OTP)
cp .env.example .env

# 5. Apply database migrations
python3 manage.py makemigrations
python3 manage.py migrate

# 6. (Optional) Seed sample distributor, customers, products, and invoices
python3 seed_data.py

# 7. Create a superuser (admin account)
python3 manage.py createsuperuser

# 8. Start the development server
python3 manage.py runserver
```

*(Note: For `pyzbar` QR decoding on Ubuntu/Debian run `sudo apt-get install libzbar0`; on macOS run `brew install zbar`. Windows includes it automatically.)*

---

## Demo & Admin Credentials

### Distributor Demo Account *(created by `seed_data.py`)*
- **Username**: `distributor`
- **Email**: `distributor@gmail.com`
- **Password**: `Dist@123`

### Admin / Superuser Account
- Create your own admin account using `python manage.py createsuperuser` or register via `/admin-register/`.

---

## Local Server Links

Once the development server is running, access the local application:

- 🔗 **Unified Login**: http://127.0.0.1:8000/login/
- 🔗 **Admin Login**: http://127.0.0.1:8000/admin-login/
- 🔗 **Distributor Login**: http://127.0.0.1:8000/distributor-login/

---

## Live Demo

*(See [DEPLOYMENT.md](DEPLOYMENT.md) for PythonAnywhere / Render / PostgreSQL deployment steps — add your live URL here once deployed.)*

---

## Screenshots

1. **Login Page**
2. **Distributor Registration (with Email OTP)**
3. **Distributor Dashboard & Monthly Sales Chart**
4. **GST Invoice Creator & Preview**
5. **Reports & GSTR-1 Export**
6. **Admin Dashboard**

*(Tip: Save screenshots into `docs/screenshots/` and add `![Login Page](docs/screenshots/login.png)` under each item above to display them directly on GitHub.)*
