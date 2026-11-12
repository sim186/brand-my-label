"""Synthetic labels only: never commit real labels (they contain addresses)."""

import io

import httpx
import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, A6
from reportlab.pdfgen import canvas

from brand_my_label import StampError, stamp_pdf
from brand_my_label.vinted import VintedError, check_url, fetch_pdf_from_html


def logo_png(w=480, h=313) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (0, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


def make_pdf(size=A4, draw=None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    draw(c, *size)
    c.save()
    return buf.getvalue()


def top_label(c, w, h):  # Poste/DPD style: label block in the top half
    c.rect(30, h - 380, w - 60, 350)
    c.drawString(50, h - 60, "lettera di vettura  TEST RECIPIENT")


def full_page(c, w, h):
    c.rect(5, 5, w - 10, h - 10)
    c.drawString(20, 10, "bottom text")
    c.drawString(20, h - 20, "top text")


def cut_strip(c, w, h):  # BRT/Vinted style: content to the bottom, strip below cut
    c.drawString(40, h - 40, "instructions bartolini")
    for i in range(30):
        c.drawString(40, h - 60 - i * 10, "lorem ipsum " * 6)
    c.line(20, 380, w - 20, 380)  # cut line
    c.rect(20, 3, w - 40, 340)    # label strip, reaches bottom margin


def logo_present(pdf: bytes) -> bool:
    return bool(PdfReader(io.BytesIO(pdf)).pages[0].images)


def test_below_content():
    r = stamp_pdf(make_pdf(draw=top_label), logo_png())
    assert r.placed and r.mode == "below-content" and r.carrier == "poste"
    assert logo_present(r.pdf)


def test_full_page_skips_logo():
    r = stamp_pdf(make_pdf(draw=full_page), logo_png())
    assert not r.placed and r.mode == "none"
    assert not logo_present(r.pdf)


def test_cut_strip_rotated():
    r = stamp_pdf(make_pdf(draw=cut_strip), logo_png())
    assert r.mode == "inside-strip-rot90" and r.carrier == "brt"


def test_a6_normalized_to_a4():
    r = stamp_pdf(make_pdf(size=A6, draw=top_label), logo_png())
    box = PdfReader(io.BytesIO(r.pdf)).pages[0].mediabox
    assert r.normalized_a4 and round(float(box.width)) == 595
    r2 = stamp_pdf(make_pdf(size=A6, draw=top_label), logo_png(), to_a4=False)
    assert not r2.normalized_a4


def test_idempotent():
    once = stamp_pdf(make_pdf(draw=top_label), logo_png()).pdf
    twice = stamp_pdf(once, logo_png())
    assert twice.mode == "already-stamped" and twice.pdf == once


@pytest.mark.parametrize("pdf,logo,code", [
    (b"hello", None, "not_pdf"),
    (None, b"not an image", "bad_logo"),
])
def test_bad_inputs(pdf, logo, code):
    with pytest.raises(StampError) as e:
        stamp_pdf(pdf or make_pdf(draw=top_label), logo or logo_png())
    assert e.value.code == code


# ------------------------------------------------------------------ vinted
OK = lambda host: True  # noqa: E731  - skip DNS in tests


@pytest.mark.parametrize("url,ok", [
    ("https://bucket.s3.eu-west-1.amazonaws.com/l.pdf?X-Amz-Signature=1", True),
    ("http://bucket.s3.amazonaws.com/l.pdf", False),        # not https
    ("https://169.254.169.254/latest/meta-data/x.pdf", False),
    ("https://evil.com/amazonaws.com/x.pdf", False),
    ("https://amazonaws.com.evil.com/x.pdf", False),
    ("https://bucket.s3.amazonaws.com:8443/x.pdf", False),  # odd port
    ("https://user:pw@bucket.s3.amazonaws.com/x.pdf", False),
])
def test_url_allowlist(url, ok):
    assert check_url(url, resolve=OK) is ok


def test_private_dns_rejected():
    assert not check_url("https://bucket.s3.amazonaws.com/x.pdf",
                         resolve=lambda h: False)


def viewer(url: str) -> bytes:
    return f'<!DOCTYPE html><html><embed src="{url}"></html>'.encode()


def test_fetch_pdf_from_viewer():
    pdf = make_pdf(draw=top_label)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=pdf)))
    got = fetch_pdf_from_html(viewer("https://b.s3.amazonaws.com/l.pdf?a=1&amp;b=2"),
                              client=client, resolve=OK)
    assert got == pdf


def test_fetch_rejects_redirect_and_size():
    redirect = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"location": "http://10.0.0.1/"})))
    with pytest.raises(VintedError):
        fetch_pdf_from_html(viewer("https://b.s3.amazonaws.com/l.pdf"),
                            client=redirect, resolve=OK)
    big = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"%PDF-" + b"0" * 2000)))
    with pytest.raises(VintedError) as e:
        fetch_pdf_from_html(viewer("https://b.s3.amazonaws.com/l.pdf"),
                            client=big, resolve=OK, max_bytes=1000)
    assert e.value.code == "too_large"
