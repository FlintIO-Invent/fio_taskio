"""One on-demand, vector 4 x 6 inch layout for PDF, preview and browser printing."""

import base64
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import reportlab
from django.core.exceptions import ValidationError
from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.shapes import Drawing, Group, Line, Rect, String
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .location_reference import country_choices, exact_country_code
from .tracking_codes import TRACKING_CODE_PREFIX

LABEL_WIDTH = 288  # 4 inches, PDF points (72 per inch).
LABEL_HEIGHT = 432  # 6 inches.
CONTENT_X = 64
CONTENT_WIDTH = 212
BAR_MODULE_WIDTH = 0.66  # 9.17 mils; retain quiet zones, never squeeze across 4 inches.
V2_BAR_MODULE_WIDTH = 0.72  # 10 mils, just over two printer dots at 203 DPI.
FONT = "MotionmateLabel"
BOLD = "MotionmateLabelBold"


@lru_cache(maxsize=1)
def label_fonts():
    root = Path(reportlab.__file__).parent / "fonts"
    paths = {FONT: root / "Vera.ttf", BOLD: root / "VeraBd.ttf"}
    for name, path in paths.items():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    return paths


def shipping_party_lines(parcel, side):
    """Use stored snapshots only, never substitute live CRM or inferred geography."""
    name = getattr(parcel, f"{side}_name")
    structured = [
        getattr(parcel, f"{side}_{suffix}") or ""
        for suffix in ("address_line_1", "address_line_2", "city", "region", "postal_code")
    ]
    legacy = (getattr(parcel, f"{side}_address") or "").splitlines()
    street = [structured[0]] if structured[0] else legacy
    address = [*street, structured[1], ", ".join(v for v in structured[2:] if v)]
    country = getattr(parcel, f"{side}_country_code") or ""
    country = dict(country_choices()).get(exact_country_code(country), country)
    contact = getattr(parcel, f"{side}_contact")
    return [value for value in (name, *address, country, contact) if value and value.strip()]


def client_shipping_prefill(client):
    """An explicit draft copy; neither the Client nor any Parcel is modified."""
    return {
        "name": str(client),
        "contact": client.phone or client.email,
        "address_line_1": client.street_address,
        "address_line_2": "",
        "city": client.get_district_display(),
        "region": "",
        "postal_code": "" if client.postal_code == "N/A" else client.postal_code,
        "country_code": exact_country_code(client.country) or "",
    }


def _wrapped(values, width, size, font=FONT):
    """Width-based wrapping also breaks long tokens; no clipping or text truncation."""
    lines = []
    face = pdfmetrics.getFont(font).face
    for value in values:
        text = " ".join(str(value).split())
        if any(ord(char) not in face.charToGlyph for char in text):
            raise ValidationError("Some shipping text cannot be printed with the label font.")
        remaining = text
        while remaining:
            end = 1
            while (
                end <= len(remaining)
                and pdfmetrics.stringWidth(remaining[:end], font, size) <= width
            ):
                end += 1
            end -= 1
            if end == 0:
                raise ValidationError("Shipping text does not fit this label.")
            if end < len(remaining) and " " in remaining[:end]:
                end = remaining.rfind(" ", 0, end) or end
            lines.append(remaining[:end])
            remaining = remaining[end:].lstrip()
    return lines


def _text(drawing, text, x, y, *, size=8, bold=False):
    drawing.add(String(x, y, text, fontName=BOLD if bold else FONT, fontSize=size))


def _block(drawing, values, x, top, width, height, *, size=9, minimum=6.5, bold=False):
    font = BOLD if bold else FONT
    while size >= minimum:
        lines = _wrapped(values, width, size, font)
        if len(lines) * size * 1.2 <= height:
            for index, line in enumerate(lines):
                _text(drawing, line, x, top - size - index * size * 1.2, size=size, bold=bold)
            return
        size -= 0.5
    raise ValidationError(
        "Shipping information is too long for a readable 4 × 6 label. "
        "Shorten the shipping address or contact text before printing."
    )


def shipping_label_drawing(parcel, *, shipment=None):
    label_fonts()
    drawing = Drawing(LABEL_WIDTH, LABEL_HEIGHT)
    drawing.add(Rect(0, 0, LABEL_WIDTH, LABEL_HEIGHT, fillColor=colors.white, strokeColor=None))
    # V2's 46 characters fit at 10 mils with explicit 10-module quiet zones.
    # Keep the existing width/default quiet zones for longer legacy codes.
    v2 = parcel.tracking_code.startswith(TRACKING_CODE_PREFIX)
    module_width = V2_BAR_MODULE_WIDTH if v2 else BAR_MODULE_WIDTH
    barcode = createBarcodeDrawing(
        "Code128",
        value=parcel.tracking_code,
        barWidth=module_width,
        barHeight=34,
        humanReadable=False,
        quiet=True,
        **({"lquiet": 10 * module_width, "rquiet": 10 * module_width} if v2 else {}),
    )
    barcode._bc.validate()
    if barcode._bc.validated != parcel.tracking_code:
        raise ValidationError("The stored tracking code cannot be encoded exactly as Code 128.")
    if barcode.width > LABEL_HEIGHT - 24:
        raise ValidationError("This tracking code is too long for the shipping label.")
    symbol = Group(barcode, transform=(0, 1, -1, 0, 46, (LABEL_HEIGHT - barcode.width) / 2))
    drawing.add(symbol)
    drawing.add(Line(54, 12, 54, 420, strokeWidth=0.5))
    _text(drawing, "MOTIONMATE LOGISTICS", CONTENT_X, 420, size=8, bold=True)
    _block(drawing, [parcel.business.name], CONTENT_X, 414, CONTENT_WIDTH, 27, size=12, bold=True)
    drawing.add(Line(CONTENT_X, 382, 276, 382, strokeWidth=0.7))

    sender = shipping_party_lines(parcel, "sender") or ["Sender information not recorded"]
    recipient = shipping_party_lines(parcel, "recipient") or ["Recipient information not recorded"]
    size = 9
    while size >= 6.5:
        from_lines = _wrapped(sender, CONTENT_WIDTH, size)
        to_lines = _wrapped(recipient, CONTENT_WIDTH, size)
        if (len(from_lines) + len(to_lines)) * size * 1.2 + 36 <= 228:
            break
        size -= 0.5
    if size < 6.5:
        raise ValidationError(
            "Shipping information is too long for a readable 4 × 6 label. "
            "Shorten the shipping address or contact text before printing."
        )
    y = 372
    for heading, lines in (("FROM / SENDER", from_lines), ("TO / RECIPIENT", to_lines)):
        _text(drawing, heading, CONTENT_X, y, size=8, bold=True)
        y -= 14
        for line in lines:
            _text(drawing, line, CONTENT_X, y, size=size)
            y -= size * 1.2
        y -= 8
    drawing.add(Line(CONTENT_X, 150, 276, 150, strokeWidth=0.5))
    route = []
    for side in ("origin", "destination"):
        values = [getattr(parcel, side) or "Not recorded"]
        country = getattr(parcel, f"{side}_country_code")
        site = getattr(parcel, f"{side}_location")
        if country:
            values.append(country)
        if site:
            values.append(site.code)
        route.append(f"{side.title()}: " + " · ".join(values))
    _block(drawing, route, CONTENT_X, 146, CONTENT_WIDTH, 49, size=8)
    qr = createBarcodeDrawing("QR", value=parcel.tracking_code, width=72, height=72, barLevel="M")
    drawing.add(Group(qr, transform=(1, 0, 0, 1, CONTENT_X, 12)))
    _text(drawing, "TRACKING CODE", 145, 87, size=6.5, bold=True)
    _block(drawing, [parcel.tracking_code], 145, 84, 131, 24, size=7, minimum=7, bold=True)
    details = []
    if parcel.weight_kg is not None:
        details.append(f"Weight: {parcel.weight_kg} kg")
    if shipment:
        details.append(f"Shipment: {shipment.reference}")
        if shipment.transport_mode:
            details.append(f"Mode: {shipment.get_transport_mode_display()}")
        elif parcel.mode_of_transport:
            details.append(f"Mode: {parcel.mode_of_transport}")
    elif parcel.mode_of_transport:
        details.append(f"Mode: {parcel.mode_of_transport}")
    _block(drawing, details, 145, 57, 131, 45, size=7)
    return drawing


def render_shipping_label_pdf(parcel, *, current_business, shipment=None):
    _validate_context(parcel, current_business, shipment)
    drawing = shipping_label_drawing(parcel, shipment=shipment)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT), invariant=True)
    pdf.setTitle(f"Shipping label {parcel.tracking_code}")
    renderPDF.draw(drawing, pdf, 0, 0)
    pdf.save()
    return buffer.getvalue()


def render_shipping_label_svg(parcel, *, current_business, shipment=None):
    _validate_context(parcel, current_business, shipment)
    svg = renderSVG.drawToString(shipping_label_drawing(parcel, shipment=shipment))
    # Only the server-generated drawing is embedded, never user-supplied markup.
    return svg[svg.index("<svg") :]


def _validate_context(parcel, business, shipment):
    if parcel.business_id != business.pk:
        raise ValueError("Parcel does not belong to the current workspace.")
    if shipment and (shipment.business_id != business.pk or shipment.pk != parcel.shipment_id):
        raise ValueError("Shipment does not belong to this Parcel and workspace.")


def shipping_label_font_css():
    return "\n".join(
        f"@font-face {{font-family: '{name}'; src: url(data:font/ttf;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}) format('truetype');}}"
        for name, path in label_fonts().items()
    )


def shipping_label_filename(parcel):
    code = re.sub(r"[^A-Za-z0-9_-]", "-", parcel.tracking_code)
    return f"parcel-{code}.pdf"
