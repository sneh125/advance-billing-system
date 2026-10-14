# Advance-Billing-System

## Project Description
Advance-Billing-System is a professional, cloud-based multi-tenant billing, inventory, and invoice management platform built with Django. It empowers distributors and enterprise administrators to manage customer directories, maintain product inventories, perform real-time multi-item billing calculations, generate vector PDF invoices with dynamically embedded verification QR codes, filter and export date-range sales reports, and decode/verify billing QR codes using computer vision (`pyzbar`).
The platform includes a fully custom admin and distributor dashboard for managing invoices, products, customers, sales reports, financial analytics, QR code verification, and profile settings -- separate from Django's default admin panel.

## Features
- **User Registration & Login** -- Role-based authentication (Admin & Distributor) with secure session handling, multi-tenant isolation, OTP-based email password recovery, and distributor profile management.
- **Customer & Client Management** -- Complete customer CRUD lifecycle with real-time metrics, search/filter capabilities, delete confirmation modals, and REST API endpoints for distributor client onboarding.
- **Product Inventory Management** -- Rich product catalog with SKU, category, stock quantity, unit prices, real-time search, and dedicated REST API endpoints (`/api/products/`).
- **Dynamic Multi-Item Quick Billing** -- Interactive invoice creation interface with real-time JavaScript subtotal, GST tax, discount calculations, and atomic database transaction commits.
- **Vector PDF Invoices & Dynamic QR Code Generation** -- Instant downloadable vector PDF invoices using `xhtml2pdf` and `reportlab`, featuring company branding, tax breakdowns, and automated high-contrast verification QR codes.
- **Date-Range Sales Reports & PDF Export** -- Advanced reporting module to filter invoices by date range, displaying total invoice counts and total revenue collected with instant downloadable A4 landscape PDF summary reports.
- **QR Code Decoder & Verification Tool** -- Upload invoice images or scan via camera to decode QR payloads using `pyzbar`, auto-match records against live database invoices, and display formatted data cards with animated toast/alert notifications for success and error outcomes.
- **Custom Admin & Distributor Dashboards** -- Dedicated administrative command centers for business metrics, monthly billing charts, customer insights, and quick billing shortcuts.

## Windows
```powershell
# 1. Clone the repository
git clone https://github.com/sneh125/advance-billing-system.git
cd "Advance Billing System"

# 2. Create and activate virtual environment
python -m venv myenv
myenv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
# (Optional) Customize settings in config/settings.py if required

# 5. Run database migrations
python manage.py migrate

# 6. Create a superuser (admin account)
python manage.py createsuperuser

# 7. Start the development server
python manage.py runserver
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000/) in your browser.

## macOS / Linux
```bash
# 1. Clone the repository
git clone https://github.com/sneh125/advance-billing-system.git
cd "Advance Billing System"

# 2. Create and activate virtual environment
python3 -m venv myenv
source myenv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
# (Optional) Customize settings in config/settings.py if required

# 5. Run database migrations
python3 manage.py migrate

# 6. Create a superuser (admin account)
python3 manage.py createsuperuser

# 7. Start the development server
python3 manage.py runserver
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000/) in your browser.

## Credentials :-
**Admin Account:**
- Username :- `admin`
- Email :- `admin@gmail.com`
- Password :- `Admin@123`

**Distributor Account:**
- Username :- `distributor`
- Email :- `distributor@gmail.com`
- Password :- `Dist@123`

## Screenshots
- Home / Login Page
- Distributor Dashboard
- Customer & Product Management
- Quick Bill Invoice Generation
- Invoice PDF with Verification QR Code
- Date-Range Sales Reports & Export
- QR Code Decoder & Scanner Tool
