"""Stamp a logo onto a shipping label PDF, wherever it fits.

Placement is decided from the page layout, not from a per-carrier config:

1. white space below the label content  -> logo centred under the label
2. cut-out label strip at the page bottom (BRT/Vinted style) -> small logo
   inside the strip, rotated 90 degrees like the strip text, so it survives
   the cut
3. neither -> the PDF is returned unchanged (``placed=False``)

Everything works on bytes in memory: no files, no network, no globals.
"""

from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass

import pdfplumber
from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

log = logging.getLogger(__name__)

PRODUCER_TAG = "BrandMyLabel"
A4W, A4H = 595.276, 841.89

# Decompression-bomb guard: refuse absurdly large logos instead of warning.
Image.MAX_IMAGE_PIXELS = 25_000_000
LOGO_MAX_PX = 1200  # logos are downscaled to this width before embedding


class StampError(ValueError):
    """Input is not usable (bad PDF, bad logo, too many pages...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class StampResult:
    pdf: bytes
    placed: bool           # logo was added
    mode: str              # below-content | inside-strip-rot90 | none | already-stamped
    carrier: str           # best-effort guess, for stats only
    normalized_a4: bool    # small page (e.g. A6) re-centred on A4
    page_count: int


# ------------------------------------------------------------------- logo
def load_logo(data: bytes) -> Image.Image:
    """Decode and sanitise a logo image (PNG/JPEG/WebP)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            img.load()
    except Exception as e:  # noqa: BLE001 - any decode failure is a bad input
        raise StampError("bad_logo", f"logo is not a readable image: {e}") from e
    if img.format not in ("PNG", "JPEG", "WEBP"):
        raise StampError("bad_logo", "logo must be PNG, JPEG or WebP")
    img = img.convert("RGBA")
    if img.width > LOGO_MAX_PX:
        h = round(img.height * LOGO_MAX_PX / img.width)
        img = img.resize((LOGO_MAX_PX, max(h, 1)), Image.LANCZOS)
    bbox = img.getchannel("A").getbbox()  # trim transparent margins
    if bbox:
        img = img.crop(bbox)
    return img


# ------------------------------------------------------------- placement
def place_below(page_w, page_h, content_bottom, content_center_x, ratio):
    """(x, y, w, h) in reportlab coords (origin bottom-left), or None."""
    small = page_w < 340  # thermal/receipt formats
    base_w = min(130.0, page_w * 0.24) if not small else min(60.0, page_w * 0.35)
    w, h = base_w, base_w * ratio
    top = content_bottom + 8.0
    free = page_h - top - 6.0
    if free < 24:  # no usable white space left
        return None
    if h > free:  # shrink to fit
        h = free
        w = h / ratio
    x = min(max(content_center_x - w / 2, 6), page_w - w - 6)
    y = page_h - top - h
    return x, y, w, h


def measure_content(pdf_bytes: bytes):
    """Bottom edge (from page top) and x-centre of page-1 content."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        pw, ph = page.width, page.height
        objects = page.chars + page.rects + page.lines + page.images + page.curves
        # drop clip-path/alpha artifacts covering (almost) the whole page
        objects = [o for o in objects
                   if not (o["width"] > 0.8 * pw and o["height"] > 0.8 * ph)]
        strip = strip_box(page)
        if not objects:
            return ph * 0.45, pw / 2, page.width, page.height, strip
        bottom = max(o["bottom"] for o in objects)
        xs = [o["x0"] for o in objects] + [o["x1"] for o in objects]
        return bottom, (min(xs) + max(xs)) / 2, page.width, page.height, strip


def strip_box(page):
    """Cut-out layout: big bordered strip in the lower half of the page."""
    ph = page.height
    cands = [r for r in page.rects
             if r["width"] > 0.6 * page.width
             and r["height"] > 0.2 * ph
             and r["top"] > 0.45 * ph]
    if not cands:
        return None
    r = max(cands, key=lambda r: r["bottom"])
    return {k: float(r[k]) for k in ("x0", "x1", "top", "bottom")}


def choose_placement(pw, ph, content_bottom, content_center_x, strip, ratio):
    pos = place_below(pw, ph, content_bottom, content_center_x, ratio)
    if pos:
        return pos, "below-content"
    if strip:
        w = 50.0
        h = w * ratio
        x = strip["x0"] + 8
        y = (ph - strip["bottom"]) + 8  # inside, above the bottom border
        # strip text runs rotated 90 deg CW: footprint is h wide x w tall
        if y + w < (ph - strip["top"]) - 8 and x + h < strip["x1"] - 8:
            return (x, y, w, h), "inside-strip-rot90"
    return None, "none"


# --------------------------------------------------------------- carrier
CARRIER_KEYWORDS = {
    "poste": ("lettera di vettura", "poste.it", "punto poste"),
    "inpost": ("inpost",),
    "dpd": ("www.dpd.com",),
    "brt": ("bartolini", "brt-"),
    "gls": ("gls-",),
    "ups": ("ups.com",),
    "dhl": ("dhl",),
    "mondial_relay": ("mondial relay",),
}


def detect_carrier(text: str) -> str:
    t = text.lower()
    for carrier, kws in CARRIER_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return carrier
    return "generic"


# ------------------------------------------------------------------ main
def _page_dims(page):
    pw, ph = float(page.mediabox.width), float(page.mediabox.height)
    if (page.get("/Rotate") or 0) in (90, 270):
        pw, ph = ph, pw
    return pw, ph


def _open_pdf(pdf: bytes) -> PdfReader:
    if pdf[:5] != b"%PDF-":
        raise StampError("not_pdf", "file is not a PDF")
    try:
        reader = PdfReader(io.BytesIO(pdf))
        if reader.is_encrypted:
            raise StampError("encrypted_pdf", "encrypted PDFs are not supported")
        _ = len(reader.pages)
        return reader
    except StampError:
        raise
    except Exception as e:  # noqa: BLE001
        raise StampError("bad_pdf", f"PDF could not be read: {e}") from e


def already_stamped(reader: PdfReader) -> bool:
    meta = reader.metadata or {}
    return PRODUCER_TAG in str(meta.get("/Producer", ""))


def _normalize(reader: PdfReader, to_a4: bool) -> tuple[bytes, bool]:
    """Re-centre pages smaller than A4 (e.g. A6) on A4 with margins, so the
    label border does not fall in a laser printer's unprintable zone."""
    writer = PdfWriter()
    dims = [_page_dims(p) for p in reader.pages]
    needs = to_a4 and any(abs(pw - A4W) > 2 or abs(ph - A4H) > 2 for pw, ph in dims)
    for page, (pw, ph) in zip(reader.pages, dims):
        if not needs:
            writer.add_page(page)
            continue
        try:
            s = min((A4W - 40) / pw, (A4H - 40) / ph, 1.0)
            tx, ty = (A4W - pw * s) / 2, (A4H - ph * s) / 2
            newp = writer.add_blank_page(width=A4W, height=A4H)
            newp.merge_transformed_page(page, Transformation().scale(s).translate(tx, ty))
        except Exception as e:  # noqa: BLE001
            log.warning("A4 normalisation failed (%s), keeping page as is", e)
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), needs


def stamp_pdf(pdf: bytes, logo: bytes, *, to_a4: bool = True,
              max_pages: int = 10) -> StampResult:
    """Return the label with the logo stamped on page 1."""
    reader = _open_pdf(pdf)
    n = len(reader.pages)
    if n == 0:
        raise StampError("bad_pdf", "PDF has no pages")
    if n > max_pages:
        raise StampError("too_many_pages", f"PDF has {n} pages (max {max_pages})")
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:2])
    carrier = detect_carrier(text)
    if already_stamped(reader):
        return StampResult(pdf, False, "already-stamped", carrier, False, n)

    img = load_logo(logo)
    ratio = img.height / img.width

    raw, normalized = _normalize(reader, to_a4)
    reader = PdfReader(io.BytesIO(raw))
    page = reader.pages[0]
    pw, ph = _page_dims(page)
    rot = page.get("/Rotate") or 0

    c_bottom, c_center, _, _, strip = measure_content(raw)
    if rot in (90, 270):  # best effort for rotated pages
        c_center = pw - c_center
    pos, mode = choose_placement(pw, ph, c_bottom, c_center, strip, ratio)

    writer = PdfWriter(clone_from=io.BytesIO(raw))
    if pos:
        x, y, w, h = pos
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        ir = ImageReader(img)
        if mode == "inside-strip-rot90":
            c.saveState()
            c.translate(x, y + w)
            c.rotate(-90)
            c.drawImage(ir, 0, 0, width=w, height=h, mask="auto")
            c.restoreState()
        else:
            c.drawImage(ir, x, y, width=w, height=h, mask="auto")
        c.save()
        buf.seek(0)
        writer.pages[0].merge_page(PdfReader(buf).pages[0])
    writer.add_metadata({"/Producer": PRODUCER_TAG})
    out = io.BytesIO()
    writer.write(out)
    return StampResult(out.getvalue(), pos is not None, mode, carrier, normalized, n)
