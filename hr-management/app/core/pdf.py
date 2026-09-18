"""Mechanical HTML -> PDF conversion (WeasyPrint). No business logic here —
which template and what data go into the HTML is a services/ concern
(app.services.certificates_service), same layering as app.core.crypto.
"""

from __future__ import annotations

from weasyprint import HTML


def render_html_to_pdf(html: str) -> bytes:
    return HTML(string=html).write_pdf()
