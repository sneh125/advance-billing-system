import io
from decimal import Decimal, ROUND_HALF_UP
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import reportlab


_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digit_words(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _indian_integer_words(n):
    if n == 0:
        return "Zero"
    parts = []
    crore, rem = divmod(n, 10000000)
    if crore:
        parts.append(f"{_indian_integer_words(crore)} Crore")
    lakh, rem = divmod(rem, 100000)
    if lakh:
        parts.append(f"{_two_digit_words(lakh)} Lakh")
    thousand, rem = divmod(rem, 1000)
    if thousand:
        parts.append(f"{_two_digit_words(thousand)} Thousand")
    hundred, rem = divmod(rem, 100)
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if rem:
        parts.append(_two_digit_words(rem))
    return " ".join(parts).strip()


def amount_to_indian_words(amount):
    """
    Convert a Decimal/numeric INR amount into Indian legal invoice wording
    (e.g., 12450.50 -> 'Rupees Twelve Thousand Four Hundred Fifty and Fifty Paise Only').
    """
    try:
        dec = Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        dec = Decimal("0.00")
    is_neg = dec < 0
    dec = abs(dec)
    rupees = int(dec)
    paise = int(((dec - Decimal(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    rupee_words = _indian_integer_words(rupees)
    prefix = "Minus " if is_neg else ""
    if paise > 0:
        return f"{prefix}Rupees {rupee_words} and {_two_digit_words(paise)} Paise Only"
    return f"{prefix}Rupees {rupee_words} Only"


def build_hsn_tax_summary(items, is_interstate=False):
    """
    Group invoice or quotation line items by (HSN/SAC code, GST rate) for
    Indian GST-compliant tax breakdown tables and GSTR-1 HSN summaries.
    """
    grouped = {}
    for item in items:
        hsn = ((getattr(item.product, "hsn_code", "") or "").strip()) or "N/A"
        gst_rate = Decimal(str(item.gst_rate or 0)).quantize(Decimal("0.01"))
        key = (hsn, gst_rate)
        taxable = Decimal(str(item.subtotal or 0)).quantize(Decimal("0.01"))
        total_val = Decimal(str(item.total or 0)).quantize(Decimal("0.01"))
        tax_amt = (total_val - taxable).quantize(Decimal("0.01"))
        if tax_amt < Decimal("0.00"):
            tax_amt = (taxable * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"))

        if is_interstate:
            cgst = Decimal("0.00")
            sgst = Decimal("0.00")
            igst = tax_amt
        else:
            cgst = (tax_amt / Decimal("2")).quantize(Decimal("0.01"))
            sgst = (tax_amt - cgst).quantize(Decimal("0.01"))
            igst = Decimal("0.00")

        if key not in grouped:
            grouped[key] = {
                "hsn_code": hsn,
                "description": item.product.name,
                "gst_rate": gst_rate,
                "quantity": 0,
                "taxable_value": Decimal("0.00"),
                "cgst": Decimal("0.00"),
                "sgst": Decimal("0.00"),
                "igst": Decimal("0.00"),
                "total_tax": Decimal("0.00"),
                "total_value": Decimal("0.00"),
            }
        row = grouped[key]
        row["quantity"] += int(item.quantity or 0)
        row["taxable_value"] += taxable
        row["cgst"] += cgst
        row["sgst"] += sgst
        row["igst"] += igst
        row["total_tax"] += tax_amt
        row["total_value"] += total_val

    return sorted(grouped.values(), key=lambda r: (r["hsn_code"], r["gst_rate"]))


def generate_invoice_pdf_bytes(template_src, context_dict=None):
    """
    Task 65: Integrate xhtml2pdf / ReportLab engine to compile an invoice HTML template
    and context dictionary into raw PDF binary bytes.
    """
    if context_dict is None:
        context_dict = {}

    template = get_template(template_src)
    html = template.render(context_dict)
    result = io.BytesIO()

    pdf = pisa.pisaDocument(
        io.BytesIO(html.encode("utf-8")),
        result,
        encoding="utf-8"
    )

    if not pdf.err:
        return result.getvalue()
    return None


def render_to_pdf(template_src, context_dict=None):
    """
    Utility function to render an HTML template into a PDF HttpResponse stream
    using xhtml2pdf / ReportLab engine.
    """
    pdf_bytes = generate_invoice_pdf_bytes(template_src, context_dict)
    if pdf_bytes is not None:
        return HttpResponse(pdf_bytes, content_type="application/pdf")
    return None


def read_qr_code_data(image_input):
    """
    Task 48: Use Python library pyzbar (and Pillow / OpenCV image preprocessing)
    to read and extract QR code data from an uploaded image.
    Supports file paths, file-like objects (BytesIO, InMemoryUploadedFile), and PIL Images.
    Includes multi-stage contrast and grayscale fallback for difficult scans.
    """
    from PIL import Image, ImageEnhance, UnidentifiedImageError
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except ImportError:
        return {
            "success": False,
            "error": "pyzbar library is not installed or available on this system."
        }

    try:
        # Check for empty file-like object (0 bytes)
        if hasattr(image_input, "seek") and hasattr(image_input, "read"):
            image_input.seek(0, 2)  # seek to end
            file_size = image_input.tell()
            image_input.seek(0)     # reset to beginning
            if file_size == 0:
                return {
                    "success": False,
                    "error": "The uploaded file is empty (0 bytes). Please select a valid QR code image."
                }

        if hasattr(image_input, "read"):
            image_input.seek(0)
            img = Image.open(image_input)
        elif isinstance(image_input, Image.Image):
            img = image_input
        else:
            img = Image.open(image_input)
    except UnidentifiedImageError:
        return {
            "success": False,
            "error": "The uploaded file is not a valid image format or is corrupted."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read image: {str(e)}"
        }

    # Attempt 1: Direct decoding with pyzbar
    decoded_objects = []
    try:
        decoded_objects = pyzbar_decode(img)
    except Exception:
        pass

    # Attempt 2: Grayscale conversion fallback
    if not decoded_objects:
        try:
            gray_img = img.convert("L")
            decoded_objects = pyzbar_decode(gray_img)
        except Exception:
            pass

    # Attempt 3: Contrast enhancement fallback
    if not decoded_objects:
        try:
            enhancer = ImageEnhance.Contrast(img.convert("L"))
            enhanced_img = enhancer.enhance(2.0)
            decoded_objects = pyzbar_decode(enhanced_img)
        except Exception:
            pass

    if not decoded_objects:
        return {
            "success": False,
            "error": "No QR code detected in the uploaded image. Please ensure the QR code is clearly visible and in focus."
        }

    # Extract primary decoded object
    primary = decoded_objects[0]
    raw_data = primary.data.decode("utf-8", errors="replace")
    qr_type = primary.type

    # Extract geometry if available
    rect_dict = {}
    if hasattr(primary, "rect") and primary.rect:
        rect_dict = {
            "left": primary.rect.left,
            "top": primary.rect.top,
            "width": primary.rect.width,
            "height": primary.rect.height
        }

    # Check for empty payload inside the detected QR code
    if not raw_data or not raw_data.strip():
        return {
            "success": False,
            "error": "The detected QR code contains empty or blank data payload.",
            "code_type": qr_type,
            "rect": rect_dict
        }

    # Parse payload structure
    parsed_info = {
        "raw_text": raw_data,
        "code_type": qr_type,
        "is_invoice": False,
        "is_upi": False,
        "invoice_data": {},
        "upi_data": {},
        "rect": rect_dict,
    }

    # 1. Check if it is an Invoice QR (format: key:value pairs, JSON, or contains invoice identifiers)
    import json
    parsed_as_json = False
    try:
        data_json = json.loads(raw_data)
        if isinstance(data_json, dict) and any(k.lower() in ["invoice", "invoice_number", "customer", "bill", "total"] for k in data_json.keys()):
            parsed_info["is_invoice"] = True
            inv_dict = {k.strip().lower(): str(v).strip() for k, v in data_json.items()}
            inv_dict["invoice_number"] = inv_dict.get("invoice") or inv_dict.get("invoice_number") or inv_dict.get("inv") or ""
            inv_dict["customer_name"] = inv_dict.get("customer") or inv_dict.get("customer_name") or ""
            inv_dict["total_amount"] = inv_dict.get("total") or inv_dict.get("total_amount") or inv_dict.get("amount") or ""
            inv_dict["date"] = inv_dict.get("date") or inv_dict.get("invoice_date") or ""
            inv_dict["products"] = inv_dict.get("products") or inv_dict.get("product_count") or inv_dict.get("items") or ""
            inv_dict["status"] = inv_dict.get("status") or ""
            parsed_info["invoice_data"] = inv_dict
            parsed_as_json = True
    except Exception:
        pass

    if not parsed_as_json and ("invoice:" in raw_data.lower() or "customer:" in raw_data.lower() or "inv-" in raw_data.upper()):
        parsed_info["is_invoice"] = True
        inv_details = {}
        for line in raw_data.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                inv_details[k.strip().lower()] = v.strip()
            elif "=" in line:
                k, v = line.split("=", 1)
                inv_details[k.strip().lower()] = v.strip()

        # Normalize common invoice field names
        inv_details["invoice_number"] = inv_details.get("invoice") or inv_details.get("invoice_number") or inv_details.get("inv") or ""
        inv_details["customer_name"] = inv_details.get("customer") or inv_details.get("customer_name") or ""
        inv_details["total_amount"] = inv_details.get("total") or inv_details.get("total_amount") or inv_details.get("amount") or ""
        inv_details["date"] = inv_details.get("date") or inv_details.get("invoice_date") or ""
        inv_details["products"] = inv_details.get("products") or inv_details.get("product_count") or inv_details.get("items") or ""
        inv_details["status"] = inv_details.get("status") or ""

        parsed_info["invoice_data"] = inv_details

    # 2. Check if it is a UPI URI
    elif raw_data.startswith("upi://pay"):
        from urllib.parse import urlparse, parse_qs
        parsed_info["is_upi"] = True
        try:
            parsed_url = urlparse(raw_data)
            params = parse_qs(parsed_url.query)
            parsed_info["upi_data"] = {
                "payee_address": params.get("pa", [""])[0],
                "payee_name": params.get("pn", [""])[0],
                "amount": params.get("am", [""])[0],
                "currency": params.get("cu", ["INR"])[0],
                "note": params.get("tn", [""])[0],
            }
        except Exception:
            pass

    return {
        "success": True,
        "raw_data": raw_data,
        "code_type": qr_type,
        "parsed": parsed_info,
        "rect": rect_dict,
        "total_detected": len(decoded_objects)
    }


def decode_qr_image(image_file):
    """
    Wrapper for read_qr_code_data to maintain backwards compatibility.
    """
    return read_qr_code_data(image_file)


