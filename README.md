# Advance Billing System with QR

A Django-based SaaS billing application with role-based dashboards (Admin & Distributor), customer management, OTP-based password recovery, and secure authentication.

---

## 🚀 Features Completed

### 🔐 1. Authentication & Security
- Admin and Distributor login with role-based dashboard redirection
- Distributor registration with comprehensive frontend & backend validations
- Forgot password with temporary OTP generation, validation, and expiry mechanism
- Resend OTP functionality with previous OTP invalidation
- Session management, login required decorators, and CSRF protection on all forms

### 👤 2. Distributor Profile Management
- Distributor profile view displaying user details, contact info, and registration date
- Live profile edit functionality (Name, Email, Phone) with database persistence and duplicate check

### 👥 3. Customer Management Module (SaaS UI)
- **Customer List & Dashboard**: Real-time database metrics (Total Customers, Active Customers, Recently Added, This Month)
- **Search & Filter**: Search customers by Name, Email, Phone, or City with dynamic "Clear Search"
- **Add Customer**: Two-column responsive card form with field icons, visible labels, and strict validation
- **Edit Customer**: Pre-filled update form with real-time feedback
- **Delete Confirmation Modal**: Interactive popup modal with CSRF-protected POST deletion
- **Multi-Tenant Data Isolation**: Logged-in distributors can only access, edit, or delete their own customers

---

## 🛠️ Tech Stack

- **Backend:** Python 3.12+ / Django 6.1
- **Database:** SQLite3 (Django ORM)
- **Frontend:** HTML5, Vanilla CSS3 (Zero inline styles, separate stylesheets)
- **Design System:** SaaS modern light theme (Navy `#0f172a`, Teal `#14b8a6`, Inter typography)

---

## ⚙️ Setup & Installation

```bash
# 1. Clone the repository
git clone https://github.com/sneh125/advance-billing-system.git
cd advance-billing-system

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate   # On Windows
# source venv/bin/activate  # On Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run database migrations
python manage.py migrate

# 5. Run the development server
python manage.py runserver
```

Open `http://127.0.0.1:8000/login/` in your browser.

---

## 🔑 Default Credentials

| Role | Username | Password |
|------|----------|----------|
| **Admin** | `admin` | `Admin@123` |
| **Distributor** | `distributor` | `Dist@123` |

---

## 📁 Project Structure

```
Advance Billing System/
├── accounts/               # Authentication, Registration, OTP, Profile views & models
│   ├── models.py           # PasswordResetOTP, DistributorProfile
│   ├── urls.py             # Auth & profile routes
│   └── views.py            # Login, Register, OTP, Profile controllers
├── billing/                # Customer, Product & Invoice Management
│   ├── models.py           # Customer, Product, Invoice, InvoiceItem models
│   ├── urls.py             # Customer & Product CRUD routes
│   ├── views.py            # Customer & Product CRUD + search & pagination logic
│   └── tests.py            # 11 Automated unit tests
├── config/                 # Root project settings & URL configuration
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── templates/              # Clean HTML templates (No inline CSS)
│   ├── accounts/           # login.html, register.html, forgot_password.html
│   ├── admin/              # dashboard.html
│   ├── distributor/        # dashboard.html, profile.html, update_profile.html
│   └── billing/            # customer_list, customer_form, product_list, product_add, product_edit
├── static/
│   └── css/                # Separate CSS stylesheets
│       ├── login.css
│       ├── register.css
│       ├── forgot_password.css
│       ├── dashboard.css
│       ├── customers.css
│       ├── customer_form.css
│       ├── product_list.css
│       ├── product_add.css
│       └── product_edit.css
├── manage.py
└── requirements.txt
```
