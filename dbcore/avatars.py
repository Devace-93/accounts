"""Avatar processing: uploads become a 256×256 WebP; users without an upload
get a generated SVG (initials on a colour derived from the user id).
"""
from __future__ import annotations

import hashlib
import io
from html import escape

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
SIZE = 256
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
# Decompression-bomb guard: anything above this many pixels is refused.
MAX_PIXELS = 40_000_000


class InvalidImage(ValueError):
    """``code``: ``invalid_image`` | ``image_too_large``."""

    def __init__(self, code: str = "invalid_image"):
        super().__init__(code)
        self.code = code


def process_upload(data: bytes) -> bytes:
    """Validate + normalise an uploaded image. Returns WebP bytes."""
    if not data:
        raise InvalidImage("invalid_image")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage("image_too_large")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise InvalidImage("invalid_image")
        img.load()  # decode now so a corrupt file fails here, not during save
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as err:
        raise InvalidImage("invalid_image") from err
    # Honour EXIF orientation, drop animation (first frame), centre-crop square.
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=80, method=4)
    return out.getvalue()


_PALETTE = ("#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626", "#7c3aed", "#db2777", "#2563eb", "#65a30d", "#ea580c")


def initials(name: str | None, handle: str) -> str:
    source = (name or "").strip() or handle
    parts = [p for p in source.replace("-", " ").replace("_", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return source[:2].upper() if source else "?"


def default_svg(user_id, name: str | None, handle: str) -> bytes:
    digest = hashlib.sha256(str(user_id).encode()).digest()
    colour = _PALETTE[digest[0] % len(_PALETTE)]
    text = escape(initials(name, handle))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">'
        f'<rect width="{SIZE}" height="{SIZE}" rx="{SIZE // 2}" fill="{colour}"/>'
        f'<text x="50%" y="50%" dy=".35em" text-anchor="middle" font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif" '
        f'font-size="{SIZE * 0.42:.0f}" font-weight="600" fill="#ffffff">{text}</text></svg>'
    )
    return svg.encode()
