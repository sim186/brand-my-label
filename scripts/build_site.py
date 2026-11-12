"""Build the static site from site/index.html.

Writes docs/index.html (Italian, canonical /) and docs/en/index.html
(English, /en/) with the text pre-rendered into the HTML, so search engines
and link previews (WhatsApp, Facebook, Telegram) see real content, plus
robots.txt, sitemap.xml and 1200x630 Open Graph images.

    python scripts/build_site.py          # needs node (to read the I18N table)

Run it after editing site/index.html; tests/test_site.py fails if docs/ is stale.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "site" / "index.html"
DOCS = ROOT / "docs"
BASE = "https://labels.sim1.org"
PAGES = {"it": "/", "en": "/en/"}

META = {
    "it": {
        "title": "Brand My Label: il logo del tuo negozio sulle etichette di spedizione Vinted",
        "description": ("Aggiungi gratis il logo del tuo negozio alle etichette di spedizione "
                        "di Vinted, Poste Italiane, BRT, InPost e DPD. Carichi il PDF, scarichi "
                        "l'etichetta pronta da stampare. Niente viene salvato."),
        "og_title": "Il tuo logo su ogni etichetta di spedizione",
        "og_desc": "Gratis, per venditori Vinted e piccoli negozi. Carichi il PDF, scarichi l'etichetta con il logo.",
        "locale": "it_IT",
    },
    "en": {
        "title": "Brand My Label: add your shop logo to Vinted shipping labels",
        "description": ("Free tool to add your shop logo to shipping labels from Vinted, "
                        "Poste Italiane, BRT, InPost and DPD. Upload the PDF, download a "
                        "print-ready label. Nothing is stored."),
        "og_title": "Your logo on every shipping label",
        "og_desc": "Free, for Vinted sellers and small shops. Upload the PDF, download the label with your logo.",
        "locale": "en_GB",
    },
}


def load_i18n(src: str) -> dict:
    m = re.search(r"const I18N = (\{.*?\n\});\n", src, re.S)
    if not m:
        raise SystemExit("I18N table not found in template")
    out = subprocess.run(["node", "-e", f"process.stdout.write(JSON.stringify({m.group(1)}))"],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def fill(src: str, strings: dict) -> str:
    def text(m):
        return f"{m.group(1)}{html.escape(strings[m.group(3)], quote=False)}{m.group(4)}"

    def raw(m):
        return f"{m.group(1)}{strings[m.group(3)]}{m.group(4)}"

    # <tag ... data-i18n="key" ...>CONTENT</tag>  (content has no same-name tags)
    src = re.sub(r'(<(\w+)\b[^>]*\sdata-i18n="(\w+)"[^>]*>).*?(</\2>)', text, src, flags=re.S)
    src = re.sub(r'(<(\w+)\b[^>]*\sdata-i18n-html="(\w+)"[^>]*>).*?(</\2>)', raw, src, flags=re.S)
    src = re.sub(r'(<img\b[^>]*\sdata-i18n-alt="(\w+)")',
                 lambda m: m.group(1).replace(" data-i18n-alt", f' alt="{html.escape(strings[m.group(2)])}" data-i18n-alt', 1)
                 if " alt=" not in m.group(1) else m.group(1), src)
    return src


def head(lang: str) -> str:
    m = META[lang]
    url = BASE + PAGES[lang]
    other = "en" if lang == "it" else "it"
    ld = {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": "Brand My Label",
        "url": url,
        "inLanguage": lang,
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Any (web browser)",
        "description": m["description"],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
        "image": f"{BASE}/og-{lang}.png",
        "isAccessibleForFree": True,
        "sameAs": ["https://github.com/sim186/brand-my-label"],
    }
    e = lambda s: html.escape(s, quote=True)  # noqa: E731
    return f"""<title>{e(m['title'])}</title>
<meta name="description" content="{e(m['description'])}">
<link rel="canonical" href="{url}">
<link rel="alternate" hreflang="{lang}" href="{url}">
<link rel="alternate" hreflang="{other}" href="{BASE + PAGES[other]}">
<link rel="alternate" hreflang="x-default" href="{BASE}/">
<meta name="theme-color" content="#f5c84c">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Brand My Label">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(m['og_title'])}">
<meta property="og:description" content="{e(m['og_desc'])}">
<meta property="og:locale" content="{m['locale']}">
<meta property="og:image" content="{BASE}/og-{lang}.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{e(m['og_title'])}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(m['og_title'])}">
<meta name="twitter:description" content="{e(m['og_desc'])}">
<meta name="twitter:image" content="{BASE}/og-{lang}.png">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>"""


def render(lang: str, src: str, i18n: dict) -> str:
    out = src.replace("{{LANG}}", lang).replace("{{HEAD}}", head(lang))
    return fill(out, i18n[lang])


def build() -> dict[Path, str]:
    src = TEMPLATE.read_text()
    i18n = load_i18n(src)
    files = {
        DOCS / "index.html": render("it", src, i18n),
        DOCS / "en" / "index.html": render("en", src, i18n),
        DOCS / "robots.txt": f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n",
    }
    urls = "".join(
        f"""  <url>
    <loc>{BASE + path}</loc>
    <xhtml:link rel="alternate" hreflang="it" href="{BASE}/"/>
    <xhtml:link rel="alternate" hreflang="en" href="{BASE}/en/"/>
  </url>
""" for path in PAGES.values())
    files[DOCS / "sitemap.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + urls + "</urlset>\n")
    return files


def main():
    for path, content in build().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print("wrote", path.relative_to(ROOT))
    print("og images: python examples/make_examples.py")


if __name__ == "__main__":
    main()
