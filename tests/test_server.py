from fastapi.testclient import TestClient

from server.main import app
from tests.test_stamp import logo_png, make_pdf, top_label


def test_stamp_endpoint():
    with TestClient(app) as client:
        r = client.post("/api/stamp", files={
            "label": ("my label.pdf", make_pdf(draw=top_label), "application/pdf"),
            "logo": ("logo.png", logo_png(), "image/png"),
        })
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
    assert r.headers["x-placement-mode"] == "below-content"
    assert 'filename="my_label-branded.pdf"' in r.headers["content-disposition"]


def test_rejects_non_pdf():
    with TestClient(app) as client:
        r = client.post("/api/stamp", files={
            "label": ("x.txt", b"hello", "text/plain"),
            "logo": ("logo.png", logo_png(), "image/png"),
        })
    assert r.status_code == 422 and r.json()["error"] == "not_pdf"
