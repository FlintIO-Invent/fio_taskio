from __future__ import annotations

import logging
import re
from decimal import Decimal
from io import BytesIO
from textwrap import wrap

from django.template.loader import render_to_string
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import Invoice

logger = logging.getLogger(__name__)


PAGE_WIDTH, PAGE_HEIGHT = letter
LEFT_MARGIN = 54
RIGHT_MARGIN = 54
TOP_MARGIN = 54
BOTTOM_MARGIN = 54
LINE_HEIGHT = 14


def _money(invoice: Invoice, value: Decimal) -> str:
    return f"{invoice.currency_code} {value:.2f}"


def _quantity(value: Decimal) -> str:
    normalized = value.normalize()
    return f"{normalized:f}"


def _client_name(invoice: Invoice) -> str:
    client = invoice.client
    full_name = " ".join(part for part in [client.first_name, client.last_name] if part).strip()
    return full_name or client.company_name or client.email


def _client_address_lines(invoice: Invoice) -> list[str]:
    client = invoice.client
    lines = []
    if client.company_name:
        lines.append(client.company_name)
    lines.extend(client.formatted_address_lines)
    if client.email:
        lines.append(client.email)
    if client.phone:
        lines.append(client.phone)
    return lines


def _invoice_context(invoice: Invoice) -> dict:
    business = invoice.business
    return {
        "invoice": invoice,
        "business": business,
        "business_address_lines": business.formatted_address_lines,
        "client_name": _client_name(invoice),
        "client_address_lines": _client_address_lines(invoice),
        "lines": list(invoice.lines.all()),
        "issue_date": timezone.localtime(invoice.created_at),
        "powered_by": "Powered by Motionmate",
    }


def _ensure_invoice_business(invoice: Invoice, current_business=None) -> None:
    if current_business is not None and invoice.business_id != current_business.id:
        raise ValueError("Invoice does not belong to the current workspace.")


def render_invoice_pdf_html(invoice: Invoice, *, current_business=None) -> str:
    _ensure_invoice_business(invoice, current_business)
    return render_to_string("billings/invoice_pdf.html", _invoice_context(invoice))


def invoice_pdf_filename(invoice: Invoice) -> str:
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice.invoice_number).strip("-")
    return f"invoice-{safe_number or invoice.pk}.pdf"


def render_invoice_pdf(invoice: Invoice, *, current_business=None) -> bytes:
    _ensure_invoice_business(invoice, current_business)
    buffer = BytesIO()
    pdf = canvas.Canvas(
        buffer,
        pagesize=letter,
        pageCompression=0,
        invariant=True,
    )
    pdf.setTitle(f"Invoice {invoice.invoice_number}")

    context = _invoice_context(invoice)
    _draw_invoice(pdf, context)

    pdf.save()
    return buffer.getvalue()


def _draw_wrapped_text(
    pdf: canvas.Canvas,
    text: str,
    *,
    x: int,
    y: int,
    max_chars: int = 80,
    leading: int = LINE_HEIGHT,
) -> int:
    clean_text = (text or "").strip()
    if not clean_text:
        return y

    for line in wrap(clean_text, max_chars) or [clean_text]:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _ensure_space(pdf: canvas.Canvas, y: int, needed: int) -> int:
    if y - needed >= BOTTOM_MARGIN:
        return y

    pdf.showPage()
    pdf.setFont("Helvetica", 9)
    return PAGE_HEIGHT - TOP_MARGIN


def _draw_invoice(pdf: canvas.Canvas, context: dict) -> None:
    invoice: Invoice = context["invoice"]
    business = context["business"]
    lines = context["lines"]

    y = PAGE_HEIGHT - TOP_MARGIN
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(LEFT_MARGIN, y, business.name)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, y, "INVOICE")
    y -= 22

    pdf.setFont("Helvetica", 9)
    for line in context["business_address_lines"]:
        pdf.drawString(LEFT_MARGIN, y, line)
        y -= 12
    if business.email:
        pdf.drawString(LEFT_MARGIN, y, f"Email: {business.email}")
        y -= 12
    if business.phone:
        pdf.drawString(LEFT_MARGIN, y, f"Phone: {business.phone}")
        y -= 12

    meta_y = PAGE_HEIGHT - TOP_MARGIN - 30
    pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, meta_y, f"Invoice #: {invoice.invoice_number}")
    meta_y -= 12
    pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, meta_y, f"Date: {context['issue_date']:%b %d, %Y}")
    meta_y -= 12
    pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, meta_y, f"Status: {invoice.get_status_display()}")

    y = min(y, meta_y) - 24
    pdf.setStrokeColor(colors.HexColor("#D8DEE9"))
    pdf.line(LEFT_MARGIN, y, PAGE_WIDTH - RIGHT_MARGIN, y)
    y -= 24

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(LEFT_MARGIN, y, "Bill To")
    y -= 15
    pdf.setFont("Helvetica", 9)
    y = _draw_wrapped_text(pdf, context["client_name"], x=LEFT_MARGIN, y=y, max_chars=60)
    for line in context["client_address_lines"]:
        y = _draw_wrapped_text(pdf, line, x=LEFT_MARGIN, y=y, max_chars=60)

    if invoice.appointment_id:
        y -= 10
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(LEFT_MARGIN, y, "Appointment")
        y -= 15
        pdf.setFont("Helvetica", 9)
        y = _draw_wrapped_text(pdf, invoice.appointment.title, x=LEFT_MARGIN, y=y, max_chars=80)
        if invoice.appointment.location:
            y = _draw_wrapped_text(
                pdf,
                f"Location: {invoice.appointment.location}",
                x=LEFT_MARGIN,
                y=y,
                max_chars=80,
            )

    y -= 20
    y = _draw_line_items(pdf, invoice, lines, y)
    y -= 18
    y = _draw_totals(pdf, invoice, y)

    if invoice.notes:
        y = _ensure_space(pdf, y, 80)
        y -= 20
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(LEFT_MARGIN, y, "Notes")
        y -= 15
        pdf.setFont("Helvetica", 9)
        for paragraph in invoice.notes.splitlines():
            y = _draw_wrapped_text(pdf, paragraph, x=LEFT_MARGIN, y=y, max_chars=90)

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(PAGE_WIDTH / 2, BOTTOM_MARGIN / 2, context["powered_by"])


def _draw_line_items(pdf: canvas.Canvas, invoice: Invoice, lines: list, y: int) -> int:
    y = _ensure_space(pdf, y, 64)
    pdf.setFillColor(colors.HexColor("#F4F6F8"))
    pdf.rect(LEFT_MARGIN, y - 18, PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN, 22, fill=1, stroke=0)
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(LEFT_MARGIN + 8, y - 11, "Description")
    pdf.drawRightString(PAGE_WIDTH - 215, y - 11, "Qty")
    pdf.drawRightString(PAGE_WIDTH - 125, y - 11, "Unit Price")
    pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN - 8, y - 11, "Line Total")
    y -= 30

    pdf.setFont("Helvetica", 9)
    if not lines:
        pdf.drawString(LEFT_MARGIN + 8, y, "No invoice lines added yet.")
        return y - 18

    for line in lines:
        y = _ensure_space(pdf, y, 42)
        description_lines = wrap(line.description, 58) or [line.description]
        row_height = max(18, len(description_lines) * 12)
        top_y = y
        for description_line in description_lines:
            pdf.drawString(LEFT_MARGIN + 8, y, description_line)
            y -= 12
        pdf.drawRightString(PAGE_WIDTH - 215, top_y, _quantity(line.quantity))
        pdf.drawRightString(PAGE_WIDTH - 125, top_y, _money(invoice, line.unit_price))
        pdf.drawRightString(PAGE_WIDTH - RIGHT_MARGIN - 8, top_y, _money(invoice, line.line_total))
        y = top_y - row_height
        pdf.setStrokeColor(colors.HexColor("#E5E7EB"))
        pdf.line(LEFT_MARGIN, y + 6, PAGE_WIDTH - RIGHT_MARGIN, y + 6)
        y -= 8
    return y


def _draw_totals(pdf: canvas.Canvas, invoice: Invoice, y: int) -> int:
    y = _ensure_space(pdf, y, 72)
    label_x = PAGE_WIDTH - 190
    value_x = PAGE_WIDTH - RIGHT_MARGIN - 8
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(label_x, y, "Subtotal:")
    pdf.drawRightString(value_x, y, _money(invoice, invoice.subtotal))
    y -= 16
    if invoice.tax:
        pdf.drawRightString(label_x, y, f"Tax ({invoice.tax_rate_percentage}%):")
        pdf.drawRightString(value_x, y, _money(invoice, invoice.tax))
        y -= 16
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(label_x, y, "Total:")
    pdf.drawRightString(value_x, y, _money(invoice, invoice.total))
    return y
