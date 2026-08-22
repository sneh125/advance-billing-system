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
├── accounts/       # Login, Logout, Dashboard views
├── billing/        # Billing app (coming soon)
├── config/         # Project settings & URLs
├── templates/      # HTML templates
│   ├── accounts/   # Login page
│   ├── admin/      # Admin dashboard
│   └── distributor/ # Distributor dashboard
├── static/         # CSS, JS, Images
└── manage.py
```
