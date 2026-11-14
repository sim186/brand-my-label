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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "site" / "index.html"
DOCS = ROOT / "docs"
BASE = "https://labels.sim1.org"
PAGES = {"it": "/", "en": "/en/"}
GUIDE_TEMPLATE = ROOT / "site" / "guida.html"
GUIDE_PATH = "/guida/logo-etichetta-vinted/"
GUIDE = {
    "title": "Come mettere il logo sull'etichetta Vinted (gratis) | Brand My Label",
    "headline": "Come aggiungere il logo all'etichetta di spedizione Vinted (gratis)",
    "description": ("Guida passo passo per mettere il logo del tuo negozio sull'etichetta di "
                    "spedizione Vinted, Poste, BRT, InPost e DPD: in un minuto, gratis, senza "
                    "programmi di grafica. Dove va il logo per ogni corriere e che logo usare."),
    "published": "2026-11-12",
}

META = {
    "it": {
        "title": "Metti il logo sull'etichetta Vinted, BRT, Poste | Brand My Label",
        "description": ("Aggiungi gratis il logo del tuo negozio alle etichette di spedizione "
                        "di Vinted, Poste Italiane, BRT, InPost e DPD. Carichi il PDF, scarichi "
                        "l'etichetta pronta da stampare. Niente viene salvato."),
        "og_title": "Il tuo logo su ogni etichetta di spedizione",
        "og_desc": "Gratis, per venditori Vinted e piccoli negozi. Carichi il PDF, scarichi l'etichetta con il logo.",
        "locale": "it_IT",
    },
    "en": {
        "title": "Add your logo to Vinted, BRT, Poste shipping labels | Brand My Label",
        "description": ("Free tool to add your shop logo to shipping labels from Vinted, "
                        "Poste Italiane, BRT, InPost and DPD. Upload the PDF, download a "
                        "print-ready label. Nothing is stored."),
        "og_title": "Your logo on every shipping label",
        "og_desc": "Free, for Vinted sellers and small shops. Upload the PDF, download the label with your logo.",
        "locale": "en_GB",
    },
}


CARRIER_TEMPLATE = ROOT / "site" / "corriere.html"
CARRIERS = {
    "brt": {
        "name": "BRT", "layout": "strip",
        "intro": ("Le etichette BRT, anche quelle generate da Vinted, hanno una striscia da ritagliare "
                  "in fondo alla pagina. Brand My Label mette il logo dentro la striscia, ruotato come il "
                  "testo, così non finisce nella parte che butti."),
        "where": ("Il logo va <strong>dentro la striscia da ritagliare</strong>, in piccolo e ruotato nello "
                  "stesso verso del testo. Sul resto dell'etichetta non viene aggiunto nulla."),
    },
    "poste": {
        "name": "Poste Italiane", "layout": "top",
        "intro": ("L'etichetta Poste Italiane è in alto sulla pagina A4 e sotto resta spazio bianco. "
                  "Brand My Label usa quello spazio per mettere il tuo logo."),
        "where": ("Il logo va <strong>centrato sotto l'etichetta</strong>, nello spazio bianco della pagina A4."),
    },
    "dpd": {
        "name": "DPD", "layout": "top",
        "intro": ("L'etichetta DPD occupa la parte alta della pagina A4 e lascia spazio libero sotto. "
                  "Brand My Label ci mette il logo del tuo negozio."),
        "where": ("Il logo va <strong>centrato sotto l'etichetta</strong>, nello spazio libero della pagina A4."),
    },
    "inpost": {
        "name": "InPost", "layout": "a6",
        "intro": ("L'etichetta InPost è in formato A6, piccola. Brand My Label la centra su una pagina A4 e "
                  "mette il logo nello spazio che si libera, così la stampi con la stampante di casa."),
        "where": ("La pagina viene <strong>ricentrata su A4</strong> con margini adatti alla stampante e il logo "
                  "va nello spazio libero accanto all'etichetta."),
    },
}
LAYOUT_IMG = {
    "top": ("top-before.png", "top-after.png", "Etichetta con spazio bianco sotto, senza e con il logo"),
    "strip": ("strip-before.png", "strip-after.png", "Etichetta con striscia da ritagliare, senza e con il logo"),
    "a6": ("a6-before.png", "a6-after.png", "Etichetta A6, senza e con il logo"),
}
CARRIER_FAQ = [
    ("È gratis?", "Sì. Brand My Label è gratuito e senza pubblicità."),
    ("L'etichetta viene salvata?",
     "No. Viene elaborata in memoria e cancellata subito; il logo resta solo nel tuo browser."),
    ("Il logo copre il codice a barre o l'indirizzo?",
     "No. Il logo viene messo solo nello spazio vuoto. Se non c'è posto, l'etichetta torna indietro "
     "senza modifiche e ti viene segnalato."),
]


def carrier_path(key: str) -> str:
    return f"/guida/logo-etichetta-{key}/"


def carrier_page(key: str) -> str:
    c = CARRIERS[key]
    name = c["name"]
    url = BASE + carrier_path(key)
    title = f"Logo sull'etichetta {name}: come aggiungerlo (gratis) | Brand My Label"
    h1 = f"Come aggiungere il logo all'etichetta {name}"
    desc = (f"Metti gratis il logo del tuo negozio sull'etichetta di spedizione {name}: carichi il PDF, "
            f"scarichi l'etichetta pronta da stampare. Dove finisce il logo e che logo usare.")
    before, after, alt = LAYOUT_IMG[c["layout"]]
    e = lambda s: html.escape(s, quote=True)  # noqa: E731
    ld = [{
        "@context": "https://schema.org", "@type": "Article", "headline": h1, "description": desc,
        "inLanguage": "it", "datePublished": GUIDE["published"], "dateModified": GUIDE["updated"],
        "image": f"{BASE}/og-it.png", "mainEntityOfPage": url,
        "author": {"@type": "Person", "name": "Simone Celestino", "url": "https://www.sim1.org"},
        "publisher": {"@type": "Organization", "name": "Brand My Label", "url": BASE + "/"},
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Brand My Label", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Guida logo etichetta Vinted", "item": BASE + GUIDE_PATH},
            {"@type": "ListItem", "position": 3, "name": f"Etichetta {name}", "item": url},
        ],
    }, {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in CARRIER_FAQ],
    }]
    head_html = f"""<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#f5c84c">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Brand My Label">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:locale" content="it_IT">
<meta property="og:image" content="{BASE}/og-it.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{BASE}/og-it.png">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>"""
    others = " · ".join(f'<a href="{carrier_path(k)}">{v["name"]}</a>' for k, v in CARRIERS.items() if k != key)
    faq = "".join(f"\n    <h3>{html.escape(q)}</h3>\n    <p>{html.escape(a)}</p>" for q, a in CARRIER_FAQ)
    article = f"""  <article>
    <nav class="crumbs"><a href="/">Brand My Label</a> › <a href="{GUIDE_PATH}">Guide</a> › {name}</nav>
    <h1>{h1}</h1>
    <p class="lead">{c['intro']}</p>
    <p class="meta">Aggiornata il {{{{UPDATED}}}}</p>

    <figure>
      <div class="pair">
        <img src="/examples/{before}" alt="{e(alt.split(',')[0])}: prima" width="1000" height="840">
        <img src="/examples/{after}" alt="{e(alt.split(',')[0])}: dopo, con il logo" width="1000" height="840">
      </div>
      <figcaption>Prima e dopo, su un'etichetta di esempio con dati inventati.</figcaption>
    </figure>

    <h2>Come fare in 3 passaggi</h2>
    <ol>
      <li><strong>Scarica l'etichetta {name} in PDF</strong> dal servizio con cui l'hai generata (anche da Vinted, se la spedizione passa da {name}).</li>
      <li><strong>Apri <a href="/">Brand My Label</a></strong> e carica l'etichetta e il logo (meglio un PNG con sfondo trasparente).</li>
      <li><strong>Scarica il PDF</strong> con il logo già posizionato e stampalo come sempre.</li>
    </ol>

    <h2>Dove finisce il logo sulle etichette {name}</h2>
    <p>{c['where']} Non copre mai codici a barre, QR code o indirizzi. Se non c'è spazio, l'etichetta torna indietro identica.</p>

    <div class="cta">
      <p><strong>Provalo subito</strong>: è gratis e l'etichetta non viene salvata da nessuna parte.</p>
      <a class="btn" href="/" data-cta="middle">Aggiungi il logo</a>
    </div>

    <h2>Che logo usare</h2>
    <ul>
      <li><strong>PNG con sfondo trasparente</strong>, così non si vede un rettangolo bianco.</li>
      <li><strong>Scuro o in bianco e nero</strong>: molte stampanti per etichette sono monocromatiche.</li>
      <li><strong>Semplice e orizzontale</strong>: lo spazio è poco, serve un marchio leggibile anche a 3-4 cm.</li>
    </ul>

    <h2>Domande frequenti</h2>{faq}

    <p class="note">Altri corrieri: <a href="{GUIDE_PATH}">Vinted</a> · {others}</p>

    <div class="cta">
      <p><strong>Pronto?</strong> Carica l'etichetta {name} e il logo: in pochi secondi hai il PDF da stampare.</p>
      <a class="btn" href="/" data-cta="bottom">Apri Brand My Label</a>
    </div>
  </article>"""
    d, m_, y = GUIDE["updated"].split("-")[2], int(GUIDE["updated"].split("-")[1]), GUIDE["updated"].split("-")[0]
    months = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
              "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    return (CARRIER_TEMPLATE.read_text().replace("{{HEAD}}", head_html).replace("{{ARTICLE}}", article)
            .replace("{{UPDATED}}", f"{int(d)} {months[m_ - 1]} {y}"))


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
    # aria-label from data-i18n-aria (replace an existing aria-label value)
    def aria(m):
        tag = m.group(0)
        val = html.escape(strings[m.group(1)], quote=True)
        if re.search(r'\saria-label="[^"]*"', tag):
            return re.sub(r'(\saria-label=")[^"]*(")', lambda a: a.group(1) + val + a.group(2), tag, count=1)
        return tag.replace(" data-i18n-aria", f' aria-label="{val}" data-i18n-aria', 1)
    src = re.sub(r'<\w+\b[^>]*\sdata-i18n-aria="(\w+)"[^>]*>', aria, src)
    return src


def faq_ld(strings: dict) -> dict:
    """FAQPage markup built from the visible FAQ strings (q1..q6), tags stripped."""
    def plain(t: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()
    items = []
    for i in range(1, 7):
        a = strings[f"a{i}"] + (" " + strings["a6_privacy"] if i == 6 else "")
        items.append({"@type": "Question", "name": plain(strings[f"q{i}"]),
                      "acceptedAnswer": {"@type": "Answer", "text": plain(a)}})
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items}


def head(lang: str, strings: dict) -> str:
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
    site = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Brand My Label",
        "alternateName": ["BrandMyLabel", "labels.sim1.org"],
        "url": BASE + "/",
        "inLanguage": lang,
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
<script type="application/ld+json">{json.dumps([site, ld, faq_ld(strings)], ensure_ascii=False)}</script>"""


def guide_head() -> str:
    url = BASE + GUIDE_PATH
    e = lambda s: html.escape(s, quote=True)  # noqa: E731
    ld = [{
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": GUIDE["headline"],
        "description": GUIDE["description"],
        "inLanguage": "it",
        "datePublished": GUIDE["published"],
        "dateModified": GUIDE["updated"],
        "image": f"{BASE}/og-it.png",
        "mainEntityOfPage": url,
        "author": {"@type": "Person", "name": "Simone Celestino", "url": "https://www.sim1.org"},
        "publisher": {"@type": "Organization", "name": "Brand My Label", "url": BASE + "/"},
    }, {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Brand My Label", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Guida logo etichetta Vinted", "item": url},
        ],
    }]
    return f"""<title>{e(GUIDE['title'])}</title>
<meta name="description" content="{e(GUIDE['description'])}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#f5c84c">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Brand My Label">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(GUIDE['title'])}">
<meta property="og:description" content="{e(GUIDE['description'])}">
<meta property="og:locale" content="it_IT">
<meta property="og:image" content="{BASE}/og-it.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{BASE}/og-it.png">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>"""


def render(lang: str, src: str, i18n: dict) -> str:
    out = src.replace("{{LANG}}", lang).replace("{{HEAD}}", head(lang, i18n[lang]))
    return fill(out, i18n[lang])


def build() -> dict[Path, str]:
    src = TEMPLATE.read_text()
    i18n = load_i18n(src)
    files = {
        DOCS / "index.html": render("it", src, i18n),
        DOCS / "en" / "index.html": render("en", src, i18n),
        DOCS / "robots.txt": f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n",
    }
    GUIDE["updated"] = GUIDE.get("updated", GUIDE["published"])
    months = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
              "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    y, m, d = (int(x) for x in GUIDE["updated"].split("-"))
    files[DOCS / GUIDE_PATH.strip("/") / "index.html"] = (
        GUIDE_TEMPLATE.read_text().replace("{{HEAD}}", guide_head())
        .replace("{{UPDATED}}", f"{d} {months[m - 1]} {y}"))
    for key in CARRIERS:
        files[DOCS / carrier_path(key).strip("/") / "index.html"] = carrier_page(key)
    urls = "".join(
        f"""  <url>
    <loc>{BASE + path}</loc>
    <xhtml:link rel="alternate" hreflang="it" href="{BASE}/"/>
    <xhtml:link rel="alternate" hreflang="en" href="{BASE}/en/"/>
  </url>
""" for path in PAGES.values())
    urls += f"""  <url>
    <loc>{BASE + GUIDE_PATH}</loc>
    <lastmod>{GUIDE["updated"]}</lastmod>
  </url>
"""
    for key in CARRIERS:
        urls += f"""  <url>
    <loc>{BASE + carrier_path(key)}</loc>
    <lastmod>{GUIDE["updated"]}</lastmod>
  </url>
"""
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
