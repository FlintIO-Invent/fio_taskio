"""Operational-only PDF exports; no manifest, dispatch or parcel writes."""

from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django.utils.text import slugify
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .monitoring import observe_document
from .parcel_services import parcels_for_business
from .shipment_services import require_shipment_access
from .shipping_labels import BOLD, FONT, label_fonts


def manifest_filename(business, period):
    name = slugify(business.name)[:60] or f"business-{business.pk}"
    return f"{name}-manifest-{period['start_date']:%Y-%m-%d}-to-{period['end_date']:%Y-%m-%d}.pdf"


@observe_document("parcel_manifest_pdf")
def render_parcel_manifest_pdf(*, business, actor, period, generated_at):
    # Retain the existing manifest entitlement and independently recheck Parcel access.
    current = require_shipment_access(business=business, actor=actor, manifest=True)
    parcels = (
        parcels_for_business(business=current, actor=actor)
        .filter(created_at__gte=period["start_at"], created_at__lt=period["end_at"])
        .order_by("created_at", "pk")
        .values_list(
            "tracking_code",
            "sender_name",
            "client__first_name",
            "client__last_name",
            "client__company_name",
            "recipient_name",
            "destination",
            "package_description",
            "weight_kg",
            "current_status",
        )
    )
    # The allowlist never loads declared values, charges, payments or private notes.
    label_fonts()
    body = ParagraphStyle("ManifestBody", fontName=FONT, fontSize=8, leading=11)
    heading = ParagraphStyle("ManifestHeading", fontName=BOLD, fontSize=17, leading=22)
    header = ParagraphStyle(
        "ManifestHeader", fontName=BOLD, fontSize=8, leading=11, textColor=colors.white
    )

    def paragraph(value, style=body):
        return Paragraph(escape(str(value if value not in (None, "") else "—")), style)

    rows = [
        [
            paragraph(label, header)
            for label in (
                "Tracking number",
                "Sender / customer",
                "Recipient",
                "Destination",
                "Parcel description",
                "Weight (kg)",
                "Current status",
            )
        ]
    ]
    statuses = dict(parcels.model.Status.choices)
    for (
        tracking,
        sender,
        first,
        last,
        company,
        recipient,
        destination,
        description,
        weight,
        status,
    ) in parcels.iterator(chunk_size=1000):
        customer = " ".join(part for part in (first, last) if part) or company
        rows.append(
            [
                paragraph(value)
                for value in (
                    tracking,
                    sender or customer,
                    recipient,
                    destination,
                    description,
                    weight,
                    statuses.get(status, status),
                )
            ]
        )
    count = len(rows) - 1
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=16 * mm,
        title=f"Parcel manifest - {current.name}",
        author=current.name,
    )
    local_generated = generated_at.astimezone(ZoneInfo(current.timezone))
    story = [
        paragraph(current.name, heading),
        paragraph("Parcel manifest", heading),
        Spacer(1, 4 * mm),
        paragraph(
            f"Registration period: {period['start_date']:%d %b %Y} to {period['end_date']:%d %b %Y} (inclusive)"
        ),
        paragraph(f"Inclusion: parcel registration date · Business timezone: {current.timezone}"),
        paragraph(f"Generated: {local_generated:%d %b %Y, %H:%M:%S %Z} · Total parcels: {count}"),
        paragraph(
            "Current operational details for parcels within your location access. Parcel type is shown as the recorded package description."
        ),
        Spacer(1, 5 * mm),
    ]
    if count:
        table = LongTable(
            rows,
            colWidths=[
                doc.width * fraction for fraction in (0.18, 0.16, 0.14, 0.14, 0.18, 0.07, 0.13)
            ],
            repeatRows=1,
            splitInRow=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#283c55")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f2f5f8")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d7dee7")),
                ]
            )
        )
        story.append(table)
    else:
        story.append(
            paragraph("No parcels were registered in this period within your location access.")
        )

    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor("#526174"))
        canvas.drawString(doc.leftMargin, 8 * mm, "Motionmate Logistics · Registration manifest")
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()
