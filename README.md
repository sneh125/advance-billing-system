# Advance Billing System

A production-ready, multi-tenant Indian GST Billing, Inventory, Customer Khata (Ledger), Quotation, QR Verification, and Business Analytics ERP built with **Django**.

---

## Core Modules & Features (85 Requirements Complete)

### 1. Authentication, Roles & Security
- **Role-Based Portals**: Dual login portal (`/login/`) plus dedicated `/admin-login/` and `/distributor-login/` routes with strict role enforcement and multi-tenant data isolation.
- **Custom Admin & Distributor Profiles**: `Admin` (`accounts.Admin`) and `DistributorProfile` (`accounts.DistributorProfile` with Business Name, GSTIN, Address, State, UPI ID).
- **Secure 3-Step OTP Password Recovery**: Cryptographically secure 6-digit OTPs, 5-minute expiry, attempt lockout (`MAX_ATTEMPTS = 5`), resend rate-limiting (max 3 resends per 15 minutes), and formatted HTML/Text email delivery.
- **Hardened Session & Web Security**: PBKDF2 password hashing, CSRF protection on browser forms, `HttpOnly`/`SameSite` sessions, open-redirect protection, CSV formula injection protection, and auto-enabled HTTPS/HSTS headers when `DJANGO_DEBUG=False`.

### 2. Customer Management & Khata (Udhar Ledger)
- Full Customer CRUD, search, pagination, GSTIN validation, and dedicated **Customer Details** (`/customers/<pk>/`).
- **Customer Khata Ledger** (`/customers/<pk>/ledger/`): Chronological Debit/Credit running balance, Total Billed vs Paid vs Udhar Due, Overdue alerts, Quick Payment entry, 1-click **WhatsApp Udhar Reminder**, and CSV Statement export.

### 3. Product Inventory & Stock-In Audit Ledger
- Product CRUD with SKU, HSN/SAC Code, Category, Price, Stock, GST Rate, search, pagination, and Low-Stock (`<= 10`) / Out-of-Stock indicators.
- **Stock-In / Restock & Audit Ledger** (`/products/stock-ledger/`): Tracks Opening Stock, Purchase Restocks, Invoice Sales, Invoice Edits, Cancellation Restores, and Manual Adjustments with before/after stock snapshots and CSV export.

### 4. GST Tax Invoicing, Partial Payments & Quotations
- **Fast POS Bill Creator** (`/invoices/create/`): Searchable customer filter, SKU/HSN/Barcode quick-add bar (`Alt+A`, `Ctrl+Enter`), dynamic multi-row items, live CGST+SGST (Intra-State) vs IGST (Inter-State) preview, Credit Due Dates, Initial Partial Payment, and Optional Auto Round-Off.
- **Transaction-Safe Invoice Editing & Cancellation** (`/invoices/<pk>/edit/`, `/invoices/<pk>/cancel/`): Atomic `select_for_update()` stock locking, full stock reconciliation, and payment-floor protection.
- **Partial Payment Ledger**: Record Cash, UPI, Bank Transfer, Card, or Cheque payments with UTR/Reference numbers (`Pending → Partial → Paid`).
- **GST-Compliant PDF & Dual QR Codes**: Branded A4 PDF (`xhtml2pdf`), Seller Business Name/GSTIN, Place of Supply, HSN/SAC & Discount columns, HSN-wise Tax Summary, **Indian Amount in Words**, **UPI Scan & Pay QR** (pre-filled with payable balance), **Invoice Verification QR**, Email PDF, and WhatsApp Share.
- **Quotations / Estimates** (`/quotations/`): Create GST estimates without deducting stock, download PDF, share on WhatsApp, and **Convert to Tax Invoice in 1 click**.

### 5. QR Code Decoder & Verification
- Upload bill/QR images (`/qr/decode/` or `/api/qr/decode/`) with strict file size (`<= 10MB`), empty-file, extension, and image MIME validation.
- Decodes via `pyzbar` + Pillow contrast fallback and matches authentic invoices in the database (strictly gated by authentication and tenant ownership).

### 6. Reports, GSTR-1 CA Exports & Dashboards
- **Admin Control Center** (`/admin-dashboard/`): Platform KPIs, Revenue & GST Bar/Line trend chart, Distributor rankings, Settlement & Stock Health donut charts, System-Wide Low-Stock Watchlist, Distributor Activate/Deactivate controls, CSV export, and **One-Click DB Backup**.
- **Distributor Dashboard** (`/distributor/dashboard/`): Isolated KPIs, 6-Month Monthly Sales & GST chart, Cash-Flow Settlement ratio, Overdue count, Low-Stock alerts, and Recent Transactions.
- **Reports & CA-Ready GSTR-1** (`/invoices/report/`): Date-range/status/customer filtering, separate Billed vs Actual Collected metrics, Cancelled count, 6-Month Revenue vs Collected chart, Customer-Wise Sales table, A4 PDF export, and **GSTR-1 B2B / B2C / HSN CSV** exports.

---

## Installation & Setup

### Windows (PowerShell)
```powershell
git clone https://github.com/sneh125/advance-billing-system.git
cd "Advance Billing System"

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS / Linux
```bash
git clone https://github.com/sneh125/advance-billing-system.git
cd "Advance Billing System"

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

---

## Database Migrations & Superuser Creation

```bash
python manage.py migrate
python manage.py createsuperuser
```

(Optional) Seed demo data for local evaluation:
```bash
python seed_data.py
```

### Start Development Server
```bash
python manage.py runserver
```
Open:
- Unified Login: `http://127.0.0.1:8000/login/`
- Admin Login: `http://127.0.0.1:8000/admin-login/`
- Distributor Login: `http://127.0.0.1:8000/distributor-login/`

---

## Testing & Verification Commands

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --verbosity=2
```

---

## External Dependencies & Safe Local Testing

| Dependency | Production Usage | Safe Local Testing Method |
|---|---|---|
| **SMTP Email** (Gmail / AWS SES) | Set `EMAIL_HOST_USER` & `EMAIL_HOST_PASSWORD` in `.env` (auto-enables `smtp.EmailBackend`). Verify via `python manage.py test_smtp you@example.com`. | Leave `EMAIL_HOST_USER` empty in `.env` — defaults automatically to Django `console.EmailBackend` so OTPs and invoice emails print safely in your terminal. |
| **ZBar (`pyzbar`)** | Decodes uploaded invoice QR images. On Windows, `pyzbar` bundles `libzbar-64.dll`; on Ubuntu/Debian install `sudo apt-get install libzbar0`; on macOS run `brew install zbar`. | Verified locally via `billing.tests` using `qrcode` + Pillow in-memory PNG fixtures. |
| **PostgreSQL** | Set `DATABASE_URL=postgresql://user:pass@host:5432/db` in `.env` and install `psycopg[binary]`. See `DEPLOYMENT.md`. | Leave `DATABASE_URL` empty to run locally on `db.sqlite3`. |
| **Database Backups** | Schedule daily `python manage.py backup_db --keep 14` or download via Admin Dashboard -> **Backup DB**. | Run `python manage.py backup_db --format json` anytime to verify backups into `backups/`. |

See [DEPLOYMENT.md](DEPLOYMENT.md) for full PostgreSQL, Gunicorn, HTTPS, and automated backup instructions.
