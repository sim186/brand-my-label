"""docs/ is generated from site/index.html: fail if someone forgot to rebuild."""

import shutil

import pytest

from scripts.build_site import build


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_docs_up_to_date():
    stale = [str(p) for p, content in build().items() if p.read_text() != content]
    assert not stale, f"run: python scripts/build_site.py  (stale: {stale})"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_pages_have_real_text_and_seo_tags():
    files = build()
    for path, content in files.items():
        if path.name != "index.html":
            continue
        assert 'data-i18n="q1"></' not in content          # text pre-rendered
        assert '<link rel="canonical"' in content
        if "guida" not in str(path):  # the guide is Italian-only
            assert 'hreflang="x-default"' in content
        assert 'og:image" content="https://labels.sim1.org/og-' in content


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_guide_in_sitemap_and_linked():
    files = {str(p): c for p, c in build().items()}
    sitemap = next(c for p, c in files.items() if p.endswith("sitemap.xml"))
    assert "/guida/logo-etichetta-vinted/" in sitemap
    home = next(c for p, c in files.items() if p.endswith("docs/index.html"))
    assert 'href="/guida/logo-etichetta-vinted/"' in home
