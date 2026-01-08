from flask import render_template, send_file, request
from io import BytesIO
from typing import Optional
from utils.results_manager import ResultManager
from utils.result_templates import get_template_path
from utils.pdf_generator import generate_pdf_from_html

def render_html(student_data: dict) -> str:
    """
    Render HTML string using the active result template.
    student_data: dictionary of variables passed to the template (profile, exam_results, etc.)
    """
    template_name = ResultManager.get_template_name()
    template_path = get_template_path(template_name)
    return render_template(template_path, **(student_data or {}))

def render_pdf(student_data: dict, download_name: Optional[str] = None):
    """
    Render PDF and return a Flask response (send_file).
    """
    html = render_html(student_data)
    base_url = request.host_url
    pdf_buf = generate_pdf_from_html(html, base_url=base_url)

    if not download_name:
        sid = (
            student_data.get("student_id")
            or student_data.get("profile", {}).get("user", {}).get("user_id")
            or "results"
        )
        download_name = f"results_{sid}.pdf"

    pdf_buf.seek(0)
    return send_file(
        pdf_buf,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/pdf'
    )
