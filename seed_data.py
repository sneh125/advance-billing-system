import os
import django
from decimal import Decimal
from datetime import datetime, timedelta
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from billing.models import Customer, Product, Invoice, InvoiceItem

def seed():
    # 1. Get or create distributor user
    distributor, _ = User.objects.get_or_create(
        username="distributor",
        defaults={
            "email": "distributor@gmail.com",
            "first_name": "Sneh",
            "last_name": "Prajapati"
        }
    )
    if not distributor.has_usable_password():
        distributor.set_password("Dist@123")
        distributor.save()

    print(f"Using distributor: {distributor.username}")

    # 2. Realistic Customers Data (10)
    customers_data = [
        {
            "name": "Shree Ganesh Electronics",
            "email": "ganesh.elec@gmail.com",
            "phone": "9825012345",
            "address": "Shop 12, Navrangpura Complex",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "pincode": "380009"
        },
        {
            "name": "Vibrant Tech Solutions",
            "email": "contact@vibranttech.in",
            "phone": "9898123456",
            "address": "402, Silicon Valley Building, Ring Road",
            "city": "Surat",
            "state": "Gujarat",
            "pincode": "395002"
        },
        {
            "name": "Apex Retail Hub",
            "email": "apex.vadodara@gmail.com",
            "phone": "9724123890",
            "address": "B-14, Alkapuri Arcade, RC Dutt Road",
            "city": "Vadodara",
            "state": "Gujarat",
            "pincode": "390007"
        },
        {
            "name": "Krishna Mobile & Gadgets",
            "email": "krishna.gadgets@yahoo.com",
            "phone": "9426789012",
            "address": "Opp. Crystal Mall, Kalawad Road",
            "city": "Rajkot",
            "state": "Gujarat",
            "pincode": "360005"
        },
        {
            "name": "Royal Enterprise Pvt Ltd",
            "email": "purchase@royalenterprise.com",
            "phone": "9909234567",
            "address": "Plot 88, Sector 25 GIDC",
            "city": "Gandhinagar",
            "state": "Gujarat",
            "pincode": "382025"
        },
        {
            "name": "Navkar Infotech",
            "email": "navkar.info@gmail.com",
            "phone": "9824345678",
            "address": "22, Waghawadi Road, Near City Center",
            "city": "Bhavnagar",
            "state": "Gujarat",
            "pincode": "364002"
        },
        {
            "name": "Maruti Trading Co.",
            "email": "maruti.trading@gmail.com",
            "phone": "9978456123",
            "address": "Grain Market Main Road",
            "city": "Jamnagar",
            "state": "Gujarat",
            "pincode": "361001"
        },
        {
            "name": "Siddhi Super Mart",
            "email": "siddhi.mart@outlook.com",
            "phone": "9408567890",
            "address": "Station Road, Anand Town",
            "city": "Anand",
            "state": "Gujarat",
            "pincode": "388001"
        },
        {
            "name": "Omkar Electricals",
            "email": "omkar.elec@gmail.com",
            "phone": "9712678901",
            "address": "Highway Commercial Hub, Radhanpur Road",
            "city": "Mehsana",
            "state": "Gujarat",
            "pincode": "384002"
        },
        {
            "name": "Mahavir Hardware Store",
            "email": "mahavir.hardware@gmail.com",
            "phone": "9879789012",
            "address": "Near Railway Station, Station Road",
            "city": "Bharuch",
            "state": "Gujarat",
            "pincode": "392001"
        }
    ]

    created_customers = []
    for cdata in customers_data:
        cust, created = Customer.objects.update_or_create(
            distributor=distributor,
            phone=cdata["phone"],
            defaults={
                "name": cdata["name"],
                "email": cdata["email"],
                "address": cdata["address"],
                "city": cdata["city"],
                "state": cdata["state"],
                "pincode": cdata["pincode"],
                "is_active": True
            }
        )
        created_customers.append(cust)
    print(f"Created/Updated {len(created_customers)} Customers.")

    # 3. Realistic Products Data (10)
    products_data = [
        {
            "name": "Logitech Wireless Optical Mouse M185",
            "category": "Computer Peripherals",
            "price": Decimal("599.00"),
            "stock": 120,
            "gst_rate": Decimal("18.00"),
            "description": "2.4GHz wireless connection, 12-month battery life, compact ergonomic design."
        },
        {
            "name": "Redragon Mechanical RGB Keyboard K552",
            "category": "Computer Peripherals",
            "price": Decimal("2450.00"),
            "stock": 45,
            "gst_rate": Decimal("18.00"),
            "description": "Tenkeyless compact mechanical keyboard with tactile red switches and RGB backlighting."
        },
        {
            "name": "Samsung 24-inch Borderless IPS Monitor",
            "category": "Displays & Monitors",
            "price": Decimal("9200.00"),
            "stock": 25,
            "gst_rate": Decimal("18.00"),
            "description": "Full HD 1080p, 75Hz refresh rate, AMD FreeSync, ultra-slim bezel."
        },
        {
            "name": "Braided USB-C Fast Charging Cable 65W (2m)",
            "category": "Cables & Adapters",
            "price": Decimal("349.00"),
            "stock": 250,
            "gst_rate": Decimal("18.00"),
            "description": "Heavy-duty nylon braided cable supporting PD 65W fast charge and high-speed data transfer."
        },
        {
            "name": "Ergonomic Mesh High-Back Office Chair",
            "category": "Office Furniture",
            "price": Decimal("7500.00"),
            "stock": 15,
            "gst_rate": Decimal("18.00"),
            "description": "Adjustable lumbar support, 3D armrests, heavy metal base, breathable mesh back."
        },
        {
            "name": "Mi 20000mAh Power Bank 3i (18W Fast Charge)",
            "category": "Mobile Accessories",
            "price": Decimal("1899.00"),
            "stock": 80,
            "gst_rate": Decimal("18.00"),
            "description": "Triple port output, dual input micro-USB and Type-C, high density lithium polymer battery."
        },
        {
            "name": "Epson Thermal Receipt POS Printer 80mm",
            "category": "Point of Sale",
            "price": Decimal("4800.00"),
            "stock": 35,
            "gst_rate": Decimal("18.00"),
            "description": "High-speed 250mm/s printing, USB + Ethernet interface, auto-cutter."
        },
        {
            "name": "Honeywell High-Speed 1D/2D Barcode Scanner",
            "category": "Point of Sale",
            "price": Decimal("2150.00"),
            "stock": 60,
            "gst_rate": Decimal("18.00"),
            "description": "Omnidirectional handheld laser scanner for fast retail checkout and inventory checking."
        },
        {
            "name": "SanDisk Extreme Portable SSD 1TB (USB 3.2)",
            "category": "Storage Devices",
            "price": Decimal("7999.00"),
            "stock": 30,
            "gst_rate": Decimal("18.00"),
            "description": "Up to 1050MB/s read speed, IP55 water and dust resistance, shock resistant."
        },
        {
            "name": "D-Link Cat6 UTP Ethernet Cable (305m Roll)",
            "category": "Networking",
            "price": Decimal("4200.00"),
            "stock": 20,
            "gst_rate": Decimal("18.00"),
            "description": "High performance 4-pair unshielded twisted pair cable for gigabit LAN setups."
        }
    ]

    created_products = []
    for pdata in products_data:
        prod, created = Product.objects.update_or_create(
            distributor=distributor,
            name=pdata["name"],
            defaults={
                "category": pdata["category"],
                "price": pdata["price"],
                "stock": pdata["stock"],
                "gst_rate": pdata["gst_rate"],
                "description": pdata["description"]
            }
        )
        created_products.append(prod)
    print(f"Created/Updated {len(created_products)} Products.")

    # 4. Realistic Invoices (10) spanning different dates & customers
    invoices_meta = [
        {
            "inv_no": "INV-2026-001",
            "cust_idx": 0,
            "status": "Paid",
            "days_ago": 18,
            "items": [(0, 5), (1, 2)]  # (prod_idx, qty)
        },
        {
            "inv_no": "INV-2026-002",
            "cust_idx": 1,
            "status": "Paid",
            "days_ago": 15,
            "items": [(2, 2), (3, 10)]
        },
        {
            "inv_no": "INV-2026-003",
            "cust_idx": 2,
            "status": "Pending",
            "days_ago": 12,
            "items": [(4, 1), (0, 2)]
        },
        {
            "inv_no": "INV-2026-004",
            "cust_idx": 3,
            "status": "Paid",
            "days_ago": 10,
            "items": [(5, 4), (3, 6)]
        },
        {
            "inv_no": "INV-2026-005",
            "cust_idx": 4,
            "status": "Paid",
            "days_ago": 8,
            "items": [(6, 2), (7, 2)]
        },
        {
            "inv_no": "INV-2026-006",
            "cust_idx": 5,
            "status": "Pending",
            "days_ago": 6,
            "items": [(8, 1), (1, 1)]
        },
        {
            "inv_no": "INV-2026-007",
            "cust_idx": 6,
            "status": "Paid",
            "days_ago": 4,
            "items": [(9, 1), (3, 5)]
        },
        {
            "inv_no": "INV-2026-008",
            "cust_idx": 7,
            "status": "Paid",
            "days_ago": 3,
            "items": [(2, 1), (0, 3)]
        },
        {
            "inv_no": "INV-2026-009",
            "cust_idx": 8,
            "status": "Pending",
            "days_ago": 2,
            "items": [(7, 3), (6, 1)]
        },
        {
            "inv_no": "INV-2026-010",
            "cust_idx": 9,
            "status": "Paid",
            "days_ago": 1,
            "items": [(5, 2), (8, 1), (1, 1)]
        }
    ]

    base_date = timezone.now()

    for im in invoices_meta:
        inv_date = base_date - timedelta(days=im["days_ago"])
        customer = created_customers[im["cust_idx"]]

        # Calculate items subtotal and total
        subtotal = Decimal("0.00")
        gst_total = Decimal("0.00")

        invoice, _ = Invoice.objects.update_or_create(
            invoice_number=im["inv_no"],
            defaults={
                "distributor": distributor,
                "customer": customer,
                "status": im["status"],
                "subtotal": Decimal("0.00"),
                "gst_amount": Decimal("0.00"),
                "total_amount": Decimal("0.00")
            }
        )

        # Clear existing items for clean re-seed
        invoice.items.all().delete()

        for prod_idx, qty in im["items"]:
            prod = created_products[prod_idx]
            item_subtotal = (prod.price * qty).quantize(Decimal("0.01"))
            item_gst = ((item_subtotal * prod.gst_rate) / Decimal("100")).quantize(Decimal("0.01"))
            item_total = item_subtotal + item_gst

            subtotal += item_subtotal
            gst_total += item_gst

            InvoiceItem.objects.create(
                invoice=invoice,
                product=prod,
                quantity=qty,
                unit_price=prod.price,
                gst_rate=prod.gst_rate,
                subtotal=item_subtotal,
                total=item_total
            )

        invoice.subtotal = subtotal
        invoice.gst_amount = gst_total
        invoice.total_amount = subtotal + gst_total
        invoice.save()

        # Update creation timestamp so date-range filtering works realistically
        Invoice.objects.filter(pk=invoice.pk).update(created_at=inv_date, invoice_date=inv_date)

    print(f"Created/Updated {len(invoices_meta)} realistic Invoices with Items.")

if __name__ == "__main__":
    seed()
