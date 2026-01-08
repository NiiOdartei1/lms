# utils/pdf_generator.py
from io import BytesIO
from typing import Optional

def generate_pdf_from_html(html: str, base_url: Optional[str] = None) -> BytesIO:
    """
    Convert HTML string to PDF BytesIO.
    Tries WeasyPrint first, then pdfkit if available.
    """
    # Try WeasyPrint
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html, base_url=base_url).write_pdf()
        bio = BytesIO(pdf_bytes)
        bio.seek(0)
        return bio
    except Exception as weasy_err:
        pass

    # Try pdfkit
    try:
        import pdfkit
        options = {'enable-local-file-access': None, 'quiet': ''}
        pdf_bytes = pdfkit.from_string(html, False, options=options)
        bio = BytesIO(pdf_bytes)
        bio.seek(0)
        return bio
    except Exception as pdfkit_err:
        pass

    # If both fail
    raise RuntimeError(
        f"No HTML→PDF backend available.\nWeasyPrint error: {weasy_err!r}\n"
        f"pdfkit error: {pdfkit_err!r}"
    )
