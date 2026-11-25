# Advance Billing System — Production Deployment Guide

This guide covers switching Advance Billing System from local SQLite/Console development mode to live business production with **PostgreSQL**, **Real SMTP Email**, **HTTPS Hardening**, and **Automated Daily Backups**.

## 1. Environment Configuration (`.env`)
Copy `.env.example` to `.env` in the project root and set production values:

```env
DJANGO_SECRET_KEY=<generate-a-64-char-random-secret>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=billing.yourdomain.com,www.yourdomain.com
DJANGO_TIME_ZONE=Asia/Kolkata

# PostgreSQL Connection URL
DATABASE_URL=postgresql://billing_user:StrongPassword@127.0.0.1:5432/advance_billing?sslmode=prefer

# Real SMTP Email (Gmail App Password example)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=yourbusiness@gmail.com
EMAIL_HOST_PASSWORD=xxxx-xxxx-xxxx-xxxx
DEFAULT_FROM_EMAIL=Your Business Name <yourbusiness@gmail.com>
```

> When `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` are set, `config/settings.py` automatically enables `django.core.mail.backends.smtp.EmailBackend`.

## 2. Install Production Drivers & Migrate PostgreSQL
```bash
pip install -r requirements.txt
pip install "psycopg[binary]>=3.1" gunicorn whitenoise
python manage.py migrate
python manage.py collectstatic --noinput
```

Verify email delivery before going live:
```bash
python manage.py test_smtp yourname@example.com
```

## 3. Automated Database Backups
Run manually or schedule daily backups (keeps last 14 backups automatically):
```bash
python manage.py backup_db --keep 14
```
- On SQLite: performs a hot online `sqlite3.backup()` copy into `backups/`.
- On PostgreSQL: executes `pg_dump` into `backups/`.
- Universal snapshot: `python manage.py backup_db --format json`.
- Administrators can also download an instant backup from **Admin Dashboard -> Backup DB**.

### Windows Task Scheduler (Daily 11:30 PM)
- Action: `powershell.exe`
- Arguments: `-NoProfile -Command "cd 'D:\Task\Advance Billing System'; .\venv\Scripts\python.exe manage.py backup_db --keep 30"`

### Linux Cron (Daily 2:00 AM)
```cron
0 2 * * * cd /srv/advance-billing && /srv/advance-billing/venv/bin/python manage.py backup_db --keep 30 >> /var/log/billing_backup.log 2>&1
```

## 4. Run Production WSGI Server
```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
```
Place Nginx or Caddy in front with Let's Encrypt SSL certificates. When `DJANGO_DEBUG=False`, Django automatically enforces `SECURE_SSL_REDIRECT`, HSTS, `SESSION_COOKIE_SECURE`, and `CSRF_COOKIE_SECURE`.

