"""Generate the demo assets used by the website (docs/examples/).

Everything here is synthetic: invented names and addresses, generic
"courier" layouts that mimic the *shape* of real labels (A4 with label on
top, A4 with a cut-out strip, A6) without any carrier branding.

    uv pip install pypdfium2
    python examples/make_examples.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, A6
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brand_my_label import stamp_pdf  # noqa: E402

OUT = ROOT / "docs" / "examples"

SENDER = ["MITTENTE / SENDER", "Giulia Bianchi", "Via dei Fiori 12", "20121 Milano MI", "Italia"]
RECIPIENT = ["DESTINATARIO / RECIPIENT", "Marco Verdi", "Corso Esempio 45", "00184 Roma RM", "Italia"]


# ------------------------------------------------------------------ logo
def make_logo() -> bytes:
    """Fictional wordmark: a tag icon + YOUR SHOP, transparent background."""
    w, h = 900, 300
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # tag icon
    d.rounded_rectangle((20, 50, 220, 250), radius=40, fill=(22, 21, 15, 255))
    d.ellipse((70, 100, 110, 140), fill=(0, 0, 0, 0))
    d.polygon([(95, 175), (195, 175), (145, 225)], fill=(245, 200, 76, 255))
    big = ImageFont.load_default(size=118)
    small = ImageFont.load_default(size=44)
    d.text((255, 40), "YOUR", font=big, fill=(22, 21, 15, 255), stroke_width=4, stroke_fill=(22, 21, 15, 255))
    d.text((255, 150), "SHOP", font=big, fill=(22, 21, 15, 255), stroke_width=4, stroke_fill=(22, 21, 15, 255))
    d.text((612, 196), "est. 2026", font=small, fill=(22, 21, 15, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ----------------------------------------------------------- label parts
def barcode(c, x, y, value, width, height):
    bc = code128.Code128(value, barHeight=height, barWidth=1.1, humanReadable=True)
    s = width / bc.width
    c.saveState()
    c.translate(x, y)
    c.scale(s, 1)
    bc.drawOn(c, 0, 0)
    c.restoreState()


def qrcode(c, x, y, value, size):
    w = qr.QrCodeWidget(value)
    b = w.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0,
                                       size / (b[3] - b[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def address(c, x, y, lines, big=False):
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x, y, lines[0])
    size = 13 if big else 9
    for i, line in enumerate(lines[1:]):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", size)
        c.drawString(x, y - 6 - (i + 1) * (size + 3), line)


def label_block(c, x, y, w, h, tracking="IT 0042 7781 0093"):
    """Generic shipping label box with origin (x, y) bottom-left."""
    c.setLineWidth(1.5)
    c.rect(x, y, w, h)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x + 14, y + h - 26, "SPEDIZIONE / SHIPMENT")
    c.setFont("Helvetica", 8)
    c.drawRightString(x + w - 14, y + h - 22, "Peso 0,8 kg  ·  Colli 1/1")
    c.line(x, y + h - 36, x + w, y + h - 36)
    address(c, x + 14, y + h - 52, SENDER)
    address(c, x + w / 2 + 6, y + h - 52, RECIPIENT, big=True)
    c.line(x, y + h * 0.42, x + w, y + h * 0.42)
    q = min(h * 0.34, w * 0.26)  # QR side, fits both wide and narrow boxes
    barcode(c, x + 14, y + 18, tracking.replace(" ", ""),
            w - q - 48, min(h * 0.24, q * 0.7))
    qrcode(c, x + w - 14 - q, y + 14, tracking, q)


def pdf_top_label() -> bytes:
    """A4, label in the top half, white below (Poste / DPD shape)."""
    buf = io.BytesIO()
    W, H = A4
    c = canvas.Canvas(buf, pagesize=A4)
    label_block(c, 40, H - 420, W - 80, 380)
    c.save()
    return buf.getvalue()


def pdf_cut_strip() -> bytes:
    """A4: instructions on top, cut line, rotated label strip at the bottom
    (Vinted + BRT shape)."""
    buf = io.BytesIO()
    W, H = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, H - 60, "Come spedire il tuo pacco / How to ship")
    c.setFont("Helvetica", 10)
    steps = ["1. Stampa questa pagina / Print this page",
             "2. Ritaglia l'etichetta lungo la linea / Cut along the line",
             "3. Incollala sul pacco / Stick it on the parcel",
             "4. Porta il pacco al punto di ritiro / Drop it off"]
    for i, s in enumerate(steps):
        c.drawString(40, H - 92 - i * 18, s)
    c.setFillGray(0.93)
    c.rect(40, H - 380, W - 80, 180, stroke=0, fill=1)
    c.setFillGray(0)
    c.setFont("Helvetica", 9)
    c.drawString(56, H - 222, "Note: invented example, not a real shipment.")
    c.setDash(4, 3)
    c.line(20, 380, W - 20, 380)
    c.setDash()
    c.setFont("Helvetica", 8)
    c.drawString(24, 384, "✂ - - - - - -")
    # strip: content rotated 90 degrees, like the real ones
    sx, sy, sw, sh = 20, 3, W - 40, 340
    c.rect(sx, sy, sw, sh)
    # rotate(-90) maps local (x, y) to page (X0 + y, Y0 - x): the label's
    # width runs down the strip, its height runs right. Leave the left
    # margin free (that's where the logo lands on real strips).
    c.saveState()
    c.translate(sx + 80, sy + sh - 10)
    c.rotate(-90)
    label_block(c, 0, 0, sh - 20, sw - 100)
    c.restoreState()
    c.save()
    return buf.getvalue()


def pdf_a6() -> bytes:
    """Compact A6 label (InPost shape)."""
    buf = io.BytesIO()
    W, H = A6
    c = canvas.Canvas(buf, pagesize=A6)
    c.setLineWidth(1.2)
    c.rect(8, H - 250, W - 16, 242)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(16, H - 26, "LOCKER  ·  PARCEL")
    address(c, 16, H - 46, RECIPIENT, big=True)
    barcode(c, 16, H - 236, "LCK00427781", W - 120, 60)
    qrcode(c, W - 92, H - 240, "LCK00427781", 74)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- render
def render(pdf: bytes, width: int) -> Image.Image:
    doc = pdfium.PdfDocument(pdf)
    page = doc[0]
    scale = width / page.get_width()
    img = page.render(scale=scale).to_pil().convert("RGB")
    doc.close()
    return img


def save_png(img: Image.Image, name: str):
    img.save(OUT / name, "PNG", optimize=True)
    print("wrote", name, img.size)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logo = make_logo()
    (OUT / "sample-logo.png").write_bytes(logo)
    cases = {"top": pdf_top_label(), "strip": pdf_cut_strip(), "a6": pdf_a6()}
    for name, pdf in cases.items():
        (OUT / f"sample-{name}.pdf").write_bytes(pdf)
        res = stamp_pdf(pdf, logo)
        print(name, res.mode)
        save_png(render(pdf, 600), f"{name}-before.png")
        save_png(render(res.pdf, 600), f"{name}-after.png")
        if name == "top":  # hero crops: label + logo, 2x for sharpness
            for tag, src in (("before", pdf), ("after", res.pdf)):
                big = render(src, 1000)
                save_png(big.crop((0, 0, 1000, 840)), f"hero-{tag}.png")
        if name == "strip":  # close-up of the logo inside the cut-out strip
            big = render(res.pdf, 1600)
            w, h = big.size
            save_png(big.crop((0, int(h * 0.74), int(w * 0.3), h)), "strip-zoom.png")


if __name__ == "__main__":
    main()
