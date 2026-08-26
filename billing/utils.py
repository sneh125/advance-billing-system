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
