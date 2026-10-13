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


def decode_qr_image(image_file):
    """
    Task 47 & 48: Use pyzbar and Pillow to decode QR code data from an uploaded image.
    Supports file-like objects, BytesIO, or file paths.
    """
    from PIL import Image, UnidentifiedImageError
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except ImportError:
        return {
            "success": False,
            "error": "pyzbar library is not installed or available on this system."
        }

    try:
        # Open image with PIL
        if hasattr(image_file, "read"):
            image_file.seek(0)
            img = Image.open(image_file)
        elif isinstance(image_file, Image.Image):
            img = image_file
        else:
            img = Image.open(image_file)
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

    # Decode QR code using pyzbar
    try:
        decoded_objects = pyzbar_decode(img)
    except Exception as e:
        return {
            "success": False,
            "error": f"Error during QR code decoding: {str(e)}"
        }

    if not decoded_objects:
        return {
            "success": False,
            "error": "No QR code detected in the uploaded image. Please ensure the QR code is clearly visible and in focus."
        }

    # Extract first decoded object (or multiple if present)
    primary = decoded_objects[0]
    raw_data = primary.data.decode("utf-8", errors="replace")
    qr_type = primary.type

    # Parse payload structure
    parsed_info = {
        "raw_text": raw_data,
        "code_type": qr_type,
        "is_invoice": False,
        "is_upi": False,
        "invoice_data": {},
        "upi_data": {},
    }

    # 1. Check if it is an Invoice QR (format: "Invoice: INV-...\nCustomer: ...")
    if "Invoice:" in raw_data and "Customer:" in raw_data:
        parsed_info["is_invoice"] = True
        inv_details = {}
        for line in raw_data.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                inv_details[k.strip().lower()] = v.strip()
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
        "total_detected": len(decoded_objects)
    }

