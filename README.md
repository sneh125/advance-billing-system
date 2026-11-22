<p align="center">
  <img src="static/images/brand_logo_full.png" alt="Advance Billing System" width="380">
</p>

# Advance Billing System

A multi-tenant Indian GST Billing, Inventory, Customer Khata (Ledger), Quotation, QR Verification, and Business Analytics web application built with **Django**.

---

## Key Features

### 1. Authentication, Email OTP & Role-Based Access
- **Separate Admin & Distributor Portals**: Unified login (`/login/`) plus dedicated `/admin-login/` and `/distributor-login/` routes with strict multi-tenant data isolation.
- **Email OTP Distributor Registration**: 2-step distributor signup with cryptographically secure 6-digit Email OTP verification, expiry, attempt limits, and resend rate-limiting.
- **OTP Password Recovery**: 3-step forgot-password flow (`Email -> OTP -> Reset`) with HTML/Text SMTP delivery, 5-minute expiry, attempt lockout, and resend throttling.
- **Security Hardening**: Django password hashing, CSRF protection, `HttpOnly`/`SameSite` sessions, open-redirect protection, CSV formula sanitization, and auto-enabled HTTPS/HSTS headers when `DJANGO_DEBUG=False`.

### 2. Customer Management & Khata Ledger
- Customer CRUD with search, pagination, GSTIN validation, and Customer Details (`/customers/<pk>/`).
- **Customer Khata Ledger** (`/customers/<pk>/ledger/`): Running Debit/Credit balance, Total Billed vs Paid vs Pending Dues, overdue alerts, quick payment entry, WhatsApp reminder link, and CSV export.

### 3. Product Inventory & Stock Audit Ledger
- Product CRUD with SKU, HSN/SAC Code, Category, Price, Stock Quantity, GST Rate, search, pagination, and Low-Stock (`<= 10`) / Out-of-Stock badges.
- **Stock-In & Movement Ledger** (`/products/stock-ledger/`): Full audit trail of Opening Stock, Purchase Restocks, Invoice Sales, Invoice Edits, Cancellation Restores, and CSV export.

### 4. GST Tax Invoicing, Partial Payments & Quotations
- **POS Invoice Creator** (`/invoices/create/`): Searchable customer selector, SKU/HSN quick-add (`Alt+A`, `Ctrl+Enter`), dynamic multi-row items, live CGST+SGST (Intra-State) vs IGST (Inter-State) calculation, credit due dates, initial partial payment, and optional round-off.
- **Transaction-Safe Editing & Cancellation**: Server-side total/GST validation, atomic `select_for_update()` stock locking, and automatic stock reconciliation on edit or cancellation.
- **Partial Payments**: Track Cash, UPI, Bank Transfer, Card, and Cheque installments (`Pending -> Partial -> Paid`) with reference/UTR numbers.
- **GST PDF & Dual QR Codes**: Branded A4 PDF (`xhtml2pdf`), HSN-wise tax summary, Indian Amount in Words, pre-filled **UPI Scan & Pay QR**, **Invoice Verification QR**, Email PDF, and WhatsApp share.
- **Quotations / Estimates** (`/quotations/`): Non-stock GST estimates with PDF export and 1-click conversion into a Tax Invoice.

### 5. QR Code Decoder
- Upload invoice/QR images (`/qr/decode/` or `/api/qr/decode/`) with file-size (`<= 10MB`), extension, and image validation.
- Decodes via `pyzbar` + Pillow contrast fallback and displays verified invoice details scoped to the logged-in tenant.

### 6. Dashboards, Reports & GSTR-1 Exports
- **Admin Dashboard** (`/admin-dashboard/`): Platform KPIs, Revenue & GST Bar/Line charts, Distributor rankings, Settlement & Stock Health charts, System-Wide Low-Stock Watchlist, Distributor active/inactive controls, CSV export, and One-Click DB Backup.
- **Distributor Dashboard** (`/distributor/dashboard/`): Tenant-isolated KPIs, interactive 6-Month Sales & GST Bar/Area chart, cash-flow settlement ratio, low-stock alerts, and recent invoices.
- **Reports & GSTR-1** (`/invoices/report/`): Date-range, status, and customer filters, Billed vs Collected metrics, PDF report export, and CA-ready **GSTR-1 B2B / B2C / HSN CSV** exports.

---

## Tech Stack

- **Backend**: Python, Django 5.x, SQLite (local) / PostgreSQL (production via `DATABASE_URL`)
- **Frontend**: Django Template Inheritance (`templates/base.html` + modular `includes/`), Custom SaaS Design Tokens CSS, Responsive SVG Charts
- **PDF & QR**: `xhtml2pdf`, `reportlab`, `qrcode`, `pyzbar`, `Pillow`
- **Email**: Django SMTP (`smtp.gmail.com` TLS via `.env`) with automatic console fallback when SMTP credentials are empty

---

## Project Structure

```text
advance-billing-system/
├── config/                 # Django settings, root URLs, WSGI/ASGI
├── accounts/               # Auth, Email OTP, RBAC, Admin & Distributor Dashboards
├── billing/                # Customers, Products, Stock Ledger, Invoices, Quotes, Reports, QR
├── templates/
│   ├── base.html           # Shared authenticated shell (header, toasts, footer)
│   ├── includes/           # Reusable header, footer, and brand logo SVG
│   ├── admin/              # Admin dashboard
│   ├── distributor/        # Distributor dashboard and profile pages
│   ├── billing/            # Billing UI pages + printable PDF templates
│   ├── accounts/           # Standalone login, OTP registration, and password recovery
│   └── emails/             # HTML & plain-text OTP email templates
├── static/css/             # Design tokens and modular page stylesheets
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
└── DEPLOYMENT.md           # Production deployment guide
```

---

## Local Setup

### 1. Clone & Create Virtual Environment

**Windows (PowerShell):**
```powershell
git clone https://github.com/sneh125/advance-billing-system.git
cd advance-billing-system
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
git clone https://github.com/sneh125/advance-billing-system.git
cd advance-billing-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

*(Note: On Ubuntu/Debian install `sudo apt-get install libzbar0` and on macOS run `brew install zbar` for `pyzbar` QR decoding. Windows bundles `libzbar` automatically.)*

### 2. Configure Email OTP (Optional for Local)
Edit `.env` and add your Gmail address and 16-character Google App Password to send real OTP emails:
```env
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your16charapppassword
DEFAULT_FROM_EMAIL=Advance Billing System <your-email@gmail.com>
```
Verify SMTP delivery anytime:
```bash
python manage.py test_smtp your-email@gmail.com
```
*(If `EMAIL_HOST_USER` is left empty, Django automatically falls back to `console.EmailBackend`.)*

### 3. Migrate Database & Run Server
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Optional — seed sample demo data:
```bash
python seed_data.py
```

### Portal URLs
- Unified Login: `http://127.0.0.1:8000/login/`
- Admin Login: `http://127.0.0.1:8000/admin-login/`
- Distributor Login: `http://127.0.0.1:8000/distributor-login/`

---

## Testing & Maintenance

```bash
python manage.py check
python manage.py test --verbosity=1
python manage.py backup_db --format json
```

For PostgreSQL, Gunicorn, HTTPS, and production hosting setup, see [DEPLOYMENT.md](DEPLOYMENT.md).
