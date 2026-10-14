import io
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa


def render_to_pdf(template_src, context_dict=None):
    """
    Utility function to render an HTML template into a PDF file stream
    using xhtml2pdf / pisa engine.
    """
    if context_dict is None:
        context_dict = {}

    template = get_template(template_src)
    html = template.render(context_dict)
    result = io.BytesIO()

    # Generate PDF document
    pdf = pisa.pisaDocument(
        io.BytesIO(html.encode("utf-8")),
        result,
        encoding="utf-8"
    )

    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type="application/pdf")
    
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
            "error": "The uploaded file is not a valid image format."
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


