"""Bounded, database-backed invoice branding; no public files or external requests."""

import base64
import logging
import warnings
from dataclasses import dataclass
from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import BusinessInvoiceLogo

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_LOGO_BYTES = 512 * 1024
MAX_INPUT_SIDE = 4096
MAX_INPUT_PIXELS = 16_000_000
LOGO_SIZE = (1000, 500)
IMAGE_ERRORS = (
    UnidentifiedImageError,
    OSError,
    ValueError,
    SyntaxError,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
)


@dataclass(frozen=True)
class InvoiceLogo:
    png_data: bytes
    width: int
    height: int

    @property
    def data_uri(self):
        return "data:image/png;base64," + base64.b64encode(self.png_data).decode("ascii")


def normalize_invoice_logo(upload) -> bytes:
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("Choose a PNG or JPG image no larger than 2 MB.")
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("Choose a PNG or JPG image no larger than 2 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=("PNG", "JPEG")) as source:
                if getattr(source, "n_frames", 1) != 1:
                    raise ValidationError("Choose a still image; animated logos are not supported.")
                width, height = source.size
                if max(width, height) > MAX_INPUT_SIDE or width * height > MAX_INPUT_PIXELS:
                    raise ValidationError(
                        "Choose an image up to 4096 pixels per side and 16 megapixels."
                    )
                source.verify()
            with Image.open(BytesIO(data), formats=("PNG", "JPEG")) as source:
                image = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                image = image.convert(mode)
                image.thumbnail(LOGO_SIZE, Image.Resampling.LANCZOS)
                # A new pixel-only image strips EXIF, comments and other uploaded metadata.
                normalized = Image.new(mode, image.size)
                normalized.paste(image)
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
    except IMAGE_ERRORS as exc:
        raise ValidationError("Upload a valid PNG or JPG image.") from exc
    if output.tell() > MAX_LOGO_BYTES:
        raise ValidationError("This logo is too detailed. Choose a simpler or smaller image.")
    return output.getvalue()


def load_invoice_logo(business_id) -> InvoiceLogo | None:
    stored = (
        BusinessInvoiceLogo.objects.filter(business_id=business_id)
        .values_list("png_data", flat=True)
        .first()
    )
    if stored is None:
        return None
    try:
        data = bytes(stored)
        if not data or len(data) > MAX_LOGO_BYTES:
            raise ValueError("Invalid stored logo size")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=("PNG",)) as image:
                width, height = image.size
                if width > LOGO_SIZE[0] or height > LOGO_SIZE[1] or image.n_frames != 1:
                    raise ValueError("Invalid stored logo dimensions")
                image.load()
        return InvoiceLogo(data, width, height)
    except IMAGE_ERRORS:
        logger.warning("Invoice logo could not be decoded for business_id=%s", business_id)
        return None
