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
        "rect": rect_dict,
        "total_detected": len(decoded_objects)
    }


def decode_qr_image(image_file):
    """
    Wrapper for read_qr_code_data to maintain backwards compatibility.
    """
    return read_qr_code_data(image_file)


