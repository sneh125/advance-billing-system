# Advance Billing System with QR

A Django-based billing system with QR code generation for Admin and Distributor roles.

## Features (Day 1 - Completed)
- Django project setup with SQLite3
- Admin and Distributor login UI with route separation
- Backend login/logout logic using Django Authentication

## Tech Stack
- Python 3.x
- Django 6.1
- SQLite3

## Setup Instructions

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/advance-billing-system.git
cd advance-billing-system

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run migrations
python manage.py migrate

# 5. Create superuser (Admin)
python manage.py createsuperuser

# 6. Run the server
python manage.py runserver
```

## Project Structure
```
Advance Billing System/
├── accounts/       # Authentication, Registration, OTP, Profile
├── billing/        # Customer Management, Invoices (coming next)
├── config/         # Project settings & URLs
├── templates/      # HTML templates
│   ├── accounts/   # Login, Register, Forgot Password
│   ├── admin/      # Admin dashboard
│   ├── distributor/# Distributor dashboard, Profile
│   └── billing/    # Customer List, Add/Edit Customer Forms
├── static/         # CSS stylesheets (Zero inline styles)
│   └── css/
└── manage.py
```

