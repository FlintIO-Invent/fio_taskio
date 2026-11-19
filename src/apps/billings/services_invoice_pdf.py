"""Services customer document layout. Reads authorized saved facts; never settles invoices."""

from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REGULAR = "MotionmateInvoiceManrope"
BOLD = "MotionmateInvoiceManropeBold"
FONT_LOCK = Lock()
INK = colors.HexColor("#182235")
MUTED = colors.HexColor("#526079")
DIVIDER = colors.HexColor("#D8DFEA")


def _fonts():
    with FONT_LOCK:
        base = Path(__file__).resolve().parents[2] / "static/assets/fonts/manrope"
        for name, file in [(REGULAR, "manrope-regular.ttf"), (BOLD, "manrope-bold.ttf")]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(base / file)))
        pdfmetrics.registerFontFamily(
            REGULAR, normal=REGULAR, bold=BOLD, italic=REGULAR, boldItalic=BOLD
        )


def render_services_invoice_pdf(context):
    """Compose only Services; generic entrypoint already applied tenant/access checks."""
    from .pdf import _money, _quantity

    invoice = context["invoice"]
    if invoice.business.vertical != "SERVICE":
        raise ValueError("Services document renderer requires a Services invoice.")
    _fonts()
    business = context["business"]
    financial = context["invoice_presentation"]
    buffer = BytesIO()
    width, height = letter
    body = ParagraphStyle(
        "InvoiceBody",
        fontName=REGULAR,
        fontSize=9.5,
        leading=14,
        textColor=INK,
        wordWrap="CJK",
        spaceAfter=4,
    )
    small = ParagraphStyle("InvoiceSmall", parent=body, fontSize=8.5, leading=12, textColor=MUTED)
    heading = ParagraphStyle(
        "InvoiceHeading", parent=body, fontName=BOLD, fontSize=11, leading=15, spaceAfter=8
    )
    issuer = ParagraphStyle("InvoiceIssuer", parent=heading, fontSize=18, leading=22, spaceAfter=12)
    title = ParagraphStyle("InvoiceTitle", parent=heading, fontSize=22, leading=28, alignment=2)
    right = ParagraphStyle("InvoiceRight", parent=body, alignment=2)
    total = ParagraphStyle("InvoiceTotal", parent=right, fontName=BOLD, fontSize=12, leading=17)

    def paragraph(text, style=body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            kwargs.update(invariant=True, pageCompression=0)
            super().__init__(*args, **kwargs)
            self._invoice_pages = []

        def showPage(self):
            self._invoice_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            count = len(self._invoice_pages)
            for page_state in self._invoice_pages:
                self.__dict__.update(page_state)
                self.setFillColor(MUTED)
                self.setFont(REGULAR, 7)
                self.drawString(54, 26, "Invoice " + invoice.invoice_number)
                self.drawRightString(width - 54, 26, f"Page {self._pageNumber} of {count}")
                super().showPage()
            super().save()

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=50,
        title="Invoice " + invoice.invoice_number,
        author=business.name,
    )
    story = []
    issuer_parts = []
    logo = context["invoice_logo"]
    if logo:
        scale = min(144 / logo.width, 54 / logo.height)
        issuer_parts.append(Spacer(1, logo.height * scale + 10))
    issuer_parts.append(paragraph(business.name, issuer))
    contacts = list(context["business_address_lines"])
    if business.email:
        contacts.append(business.email)
    if business.phone:
        contacts.append(business.phone)
    issuer_parts.append(paragraph("\n".join(contacts), small))
    meta = [
        paragraph("INVOICE", title),
        paragraph(invoice.invoice_number, right),
        paragraph(context["issue_date"].strftime("%b %d, %Y"), right),
    ]
    header = Table([[issuer_parts, meta]], colWidths=[300, 204], hAlign="LEFT")
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
                ("LINEBELOW", (0, -1), (-1, -1), 1.2, colors.HexColor("#3949DB")),
            ]
        )
    )
    story.extend(
        [
            header,
            Spacer(1, 18),
            paragraph("Bill to", heading),
            paragraph(context["client_name"], heading),
            paragraph("\n".join(context["client_address_lines"]), small),
            Spacer(1, 16),
        ]
    )
    if invoice.appointment_id:
        story.extend(
            [
                paragraph("Appointment", heading),
                paragraph(invoice.appointment.title),
                paragraph(invoice.appointment.location or "", small),
                Spacer(1, 12),
            ]
        )
    table_rows = [
        [
            paragraph("Description", small),
            paragraph("Qty", small),
            paragraph("Unit price", small),
            paragraph("Amount", small),
        ]
    ]
    for line in context["lines"]:
        table_rows.append(
            [
                paragraph(line.description),
                paragraph(_quantity(line.quantity), right),
                paragraph(_money(line.unit_price, financial.currency), right),
                paragraph(_money(line.line_total, financial.currency), right),
            ]
        )
    if not context["lines"]:
        table_rows.append([paragraph("No invoice lines added yet."), "", "", ""])
    items = Table(table_rows, colWidths=[250, 40, 105, 109], repeatRows=1, hAlign="LEFT")
    items.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F7FB")),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, DIVIDER),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, DIVIDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([items, Spacer(1, 18)])
    amounts = [
        [
            paragraph("Subtotal", small),
            paragraph(_money(invoice.subtotal, financial.currency), right),
        ]
    ]
    if invoice.tax:
        amounts.append(
            [
                paragraph(f"Tax ({invoice.tax_rate_percentage}%)", small),
                paragraph(_money(invoice.tax, financial.currency), right),
            ]
        )
    amounts.append(
        [paragraph("Total Amount", total), paragraph(context["invoice_total_text"], total)]
    )
    amount_table = Table(amounts, colWidths=[145, 135], hAlign="RIGHT")
    amount_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, DIVIDER),
                ("TOPPADDING", (0, -1), (-1, -1), 12),
            ]
        )
    )
    closing = [amount_table]
    for text in (financial.note, financial.refund_note, *financial.issues):
        if text:
            closing.extend([Spacer(1, 12), paragraph(text, small)])
    if context["include_notes"] and invoice.notes:
        closing.extend([Spacer(1, 20), paragraph("Notes", heading), paragraph(invoice.notes)])
    # Keep a short closing section together; long Notes remain splittable.
    if len(invoice.notes or "") < 1800:
        story.append(KeepTogether(closing))
    else:
        story.extend(closing)
    story.extend(
        [
            Spacer(1, 24),
            paragraph(
                context["powered_by"],
                ParagraphStyle("InvoiceAttribution", parent=small, fontSize=7.5, alignment=1),
            ),
        ]
    )

    def first_page(pdf, _document):
        if logo:
            pdf.drawImage(
                ImageReader(BytesIO(logo.png_data)),
                54,
                height - 54 - logo.height * scale,
                width=logo.width * scale,
                height=logo.height * scale,
                mask="auto",
            )

    document.build(story, canvasmaker=NumberedCanvas, onFirstPage=first_page)
    return buffer.getvalue()
