#!/usr/bin/env python3
"""
The Economist Weekly Edition Downloader
========================================
Télécharge l'édition hebdomadaire de The Economist et génère des PDFs
formatés pour différents appareils de lecture.

Basé sur la recipe Calibre de Kovid Goyal & unkn0wn, adapté en script standalone.

Formats disponibles :
    phone      : 📱 Téléphone (62×110mm)
    ereader    : 📖 Liseuse 6 pouces (76×114mm)
    tablet7    : 📱 Tablette 7 pouces (100×160mm)
    tablet10   : 📱 Tablette 10 pouces (135×200mm)
    a4premium  : 🖨️  A4 Premium deux colonnes (210×297mm)
    all        : ✨ Tous les formats (5 PDFs)

Usage:
    python3 economist_downloader.py                       # Menu interactif
    python3 economist_downloader.py --format all          # Tous les formats
    python3 economist_downloader.py --format tablet7      # Tablette 7 pouces
    python3 economist_downloader.py --format a4premium    # A4 deux colonnes
    python3 economist_downloader.py --sections asia       # D'Asia à Obituary
    python3 economist_downloader.py --date 2025-02-07     # Édition spécifique
    python3 economist_downloader.py --list-only           # Afficher le sommaire
    python3 economist_downloader.py --no-images           # Sans images

Nécessite: pip install requests beautifulsoup4 weasyprint
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlencode
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

from epub_generator import generate_epub

# ─── Utilitaires de parsing JSON (portés depuis la recipe Calibre) ──────────

def safe_dict(data, *names):
    """Navigue en sécurité dans un dict imbriqué."""
    ans = data
    for x in names:
        ans = ans.get(x) or {}
    return ans


def parse_txt(ty):
    """Parse récursivement les nœuds textJson de l'API Economist."""
    typ = ty.get('type', '')
    children = ty.get('children', [])
    href = '#'
    attributes = ty.get('attributes') or ()
    for a in attributes:
        if a.get('name') == 'href':
            href = a.get('value', href)
            break

    tag_map = {
        'text': lambda: [ty.get('value', '')],
        'scaps': lambda: [
            f'<span style="text-transform:uppercase;font-size:0.85em;letter-spacing:0.05em;">'
            f'{"".join(parse_txt(c))}</span>'
            for c in children
        ],
        'bold': lambda: [f'<b>{"".join(parse_txt(c))}</b>' for c in children],
        'drop_caps': lambda: [f'<b>{"".join(parse_txt(c))}</b>' for c in children],
        'italic': lambda: [f'<i>{"".join(parse_txt(c))}</i>' for c in children],
        'linebreak': lambda: ['<br>'],
        'external_link': lambda: [
            f'<a href="{href}">{"".join(parse_txt(c))}</a>' for c in children
        ],
        'internal_link': lambda: [
            f'<a href="{href}">{"".join(parse_txt(c))}</a>' for c in children
        ],
        'ufinish': lambda: [text for c in children for text in parse_txt(c)],
        'subscript': lambda: [f'<sub>{"".join(parse_txt(c))}</sub>' for c in children],
        'superscript': lambda: [f'<sup>{"".join(parse_txt(c))}</sup>' for c in children],
    }

    if typ in tag_map:
        yield from tag_map[typ]()


def parse_textjson(nt):
    """Convertit un tableau textJson en HTML."""
    return ''.join(''.join(parse_txt(n)) for n in nt)


def process_web_list(li_node):
    """Convertit une liste non-ordonnée."""
    li_html = ''
    for li in li_node.get('items', []):
        if li.get('textHtml'):
            li_html += f'<li>{li["textHtml"]}</li>'
        elif li.get('textJson'):
            li_html += f'<li>{parse_textjson(li["textJson"])}</li>'
        else:
            li_html += f'<li>{li.get("text", "")}</li>'
    return '<ul>' + li_html + '</ul>'


def process_info_box(bx):
    """Convertit un infobox."""
    info = ''
    for x in safe_dict(bx, 'components') or []:
        info += f'<blockquote>{process_web_node(x)}</blockquote>'
    return info


def process_web_node(node):
    """Convertit un nœud de contenu en HTML."""
    ntype = node.get('type', '')

    if ntype == 'CROSSHEAD':
        text = node.get('textHtml') or node.get('text', '')
        return f'<h4>{text}</h4>'

    elif ntype in ('PARAGRAPH', 'BOOK_INFO'):
        if node.get('textHtml'):
            return f'\n<p>{node["textHtml"]}</p>'
        elif node.get('textJson'):
            return f'\n<p>{parse_textjson(node["textJson"])}</p>'
        return f'\n<p>{node.get("text", "")}</p>'

    elif ntype == 'IMAGE' or node.get('__typename', '') == 'ImageComponent':
        alt = node.get('altText') or ''
        cap = ''
        if node.get('caption'):
            if node['caption'].get('textHtml') is not None:
                cap = node['caption']['textHtml']
            elif node['caption'].get('textJson') is not None:
                cap = parse_textjson(node['caption']['textJson'])
            elif node['caption'].get('text') is not None:
                cap = node['caption']['text']
        url = node.get('url', '')
        return (f'<div class="img-container"><img src="{url}" alt="{alt}"></div>'
                f'<div class="caption">{cap}</div>')

    elif ntype == 'PULL_QUOTE':
        if node.get('textHtml'):
            return f'<blockquote class="pullquote">{node["textHtml"]}</blockquote>'
        elif node.get('textJson'):
            return f'<blockquote class="pullquote">{parse_textjson(node["textJson"])}</blockquote>'
        return f'<blockquote class="pullquote">{node.get("text", "")}</blockquote>'

    elif ntype == 'BLOCK_QUOTE':
        if node.get('textHtml'):
            return f'<blockquote><i>{node["textHtml"]}</i></blockquote>'
        elif node.get('textJson'):
            return f'<blockquote><i>{parse_textjson(node["textJson"])}</i></blockquote>'
        return f'<blockquote><i>{node.get("text", "")}</i></blockquote>'

    elif ntype == 'DIVIDER':
        return '<hr>'

    elif ntype == 'INFOGRAPHIC':
        if node.get('fallback'):
            return process_web_node(node['fallback'])

    elif ntype == 'INFOBOX':
        return process_info_box(node)

    elif ntype == 'UNORDERED_LIST':
        if node.get('items'):
            return process_web_list(node)

    return ''


def article_json_to_html(data, img_width='600'):
    """Convertit les données JSON d'un article en HTML propre."""
    body = ''

    fly_title = data.get('flyTitle', '')
    if fly_title:
        body += f'<div class="fly-title">{fly_title}</div>'

    body += f'<h1>{data.get("headline", "")}</h1>'

    rubric = data.get('rubric')
    if rubric:
        body += f'<div class="rubric">{rubric}</div>'

    # Date
    date_str = data.get('dateModified') or data.get('datePublished', '')
    if date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            formatted_date = dt.strftime('%b %d, %Y %I:%M %p')
        except Exception:
            formatted_date = date_str
        dateline = data.get('dateline') or ''
        if dateline:
            body += f'<p class="meta">{formatted_date} | {dateline}</p>'
        else:
            body += f'<p class="meta">{formatted_date}</p>'

    # Image principale
    lead = safe_dict(data, 'leadComponent')
    if lead and lead.get('url'):
        body += process_web_node(lead)

    # Auteur
    byline = data.get('byline')
    if byline:
        body += f'<p class="byline">By {byline}</p>'

    # Corps de l'article
    for node in data.get('body', []):
        body += process_web_node(node)

    # Appliquer le redimensionnement des images
    qua = f'economist.com/cdn-cgi/image/width={img_width},quality=80,format=auto/'
    body = body.replace('economist.com/', qua)

    return body


# ─── Requête GraphQL (API Android, pas d'auth requise) ─────────────────────

GRAPHQL_QUERY = (
    'query ArticleDeeplinkQuery($ref: String!, $includeRelatedArticles: Boolean = true ) '
    '{ findArticleByUrl(url: $ref) { __typename ...ArticleDataFragment } }  '
    'fragment ContentIdentityFragment on ContentIdentity { articleType forceAppWebView leadMediaType }  '
    'fragment NarrationFragment on Narration { album bitrate duration filename id provider url isAiGenerated fileHash }  '
    'fragment ImageTeaserFragment on ImageComponent { altText height imageType source url width }  '
    'fragment PodcastAudioFragment on PodcastEpisode { id audio { url durationInSeconds } }  '
    'fragment ArticleTeaserFragment on Article { id tegId url rubric headline flyTitle brand byline '
    'dateFirstPublished dateline dateModified datePublished dateRevised estimatedReadTime wordCount '
    'printHeadline contentIdentity { __typename ...ContentIdentityFragment } section { tegId name } '
    'teaserImage { __typename type ...ImageTeaserFragment } leadComponent { __typename type ...ImageTeaserFragment } '
    'narration(selectionMethod: PREFER_ACTOR_NARRATION) { __typename ...NarrationFragment } '
    'podcast { __typename ...PodcastAudioFragment } }  '
    'fragment AnnotatedTextFragment on AnnotatedText { text textJson annotations { type length index '
    'attributes { name value } } }  '
    'fragment ImageComponentFragment on ImageComponent { altText caption { __typename ...AnnotatedTextFragment } '
    'credit height imageType mode source url width }  '
    'fragment BlockQuoteComponentFragment on BlockQuoteComponent { text textJson annotations { type length index '
    'attributes { name value } } }  '
    'fragment BookInfoComponentFragment on BookInfoComponent { text textJson annotations { type length index '
    'attributes { name value } } }  '
    'fragment ParagraphComponentFragment on ParagraphComponent { text textJson annotations { type length index '
    'attributes { name value } } }  '
    'fragment PullQuoteComponentFragment on PullQuoteComponent { text textJson annotations { type length index '
    'attributes { name value } } }  '
    'fragment CrossheadComponentFragment on CrossheadComponent { text }  '
    'fragment OrderedListComponentFragment on OrderedListComponent { items { __typename ...AnnotatedTextFragment } }  '
    'fragment UnorderedListComponentFragment on UnorderedListComponent { items { __typename ...AnnotatedTextFragment } }  '
    'fragment VideoComponentFragment on VideoComponent { url title thumbnailImage }  '
    'fragment InfoboxComponentFragment on InfoboxComponent { components { __typename type '
    '...BlockQuoteComponentFragment ...BookInfoComponentFragment ...ParagraphComponentFragment '
    '...PullQuoteComponentFragment ...CrossheadComponentFragment ...OrderedListComponentFragment '
    '...UnorderedListComponentFragment ...VideoComponentFragment } }  '
    'fragment InfographicComponentFragment on InfographicComponent { url title width fallback '
    '{ __typename ...ImageComponentFragment } altText height width }  '
    'fragment ArticleDataFragment on Article { id url brand byline rubric headline layout { headerStyle } '
    'contentIdentity { __typename ...ContentIdentityFragment } dateline dateFirstPublished dateModified '
    'datePublished dateRevised estimatedReadTime narration(selectionMethod: PREFER_ACTOR_NARRATION) '
    '{ __typename ...NarrationFragment } printFlyTitle printHeadline printRubric flyTitle wordCount '
    'section { tegId name articles(pagingInfo: { pagingType: OFFSET pageSize: 6 pageNumber: 1 } ) '
    '@include(if: $includeRelatedArticles) { edges { node { __typename ...ArticleTeaserFragment } } } } '
    'teaserImage { __typename type ...ImageComponentFragment } tegId leadComponent { __typename type '
    '...ImageComponentFragment } body { __typename type ...BlockQuoteComponentFragment '
    '...BookInfoComponentFragment ...ParagraphComponentFragment ...PullQuoteComponentFragment '
    '...CrossheadComponentFragment ...OrderedListComponentFragment ...UnorderedListComponentFragment '
    '...InfoboxComponentFragment ...ImageComponentFragment ...VideoComponentFragment '
    '...InfographicComponentFragment } footer { __typename type ...ParagraphComponentFragment } '
    'tags { name } ads { adData } podcast { __typename ...PodcastAudioFragment } }'
)

ANDROID_HEADERS = {
    'User-Agent': 'TheEconomist-Liskov-android',
    'accept': 'multipart/mixed; deferSpec=20220824, application/json',
    'accept-encoding': 'gzip',
    'content-type': 'application/json',
    'x-economist-consumer': 'TheEconomist-Liskov-android',
    'x-teg-client-name': 'Economist-Android',
    'x-teg-client-os': 'Android',
    'x-teg-client-version': '4.40.0',
}

# ─── Profils écran ────────────────────────────────────────────────────────────

FORMATS = {
    "phone": {
        "label": "📱 Téléphone",
        "suffix": "telephone",
        "w_mm": 62, "h_mm": 110,
        "body_pt": 7, "title_pt": 12,
        "margin_mm": "4mm 5mm 6mm 5mm",
    },
    "ereader": {
        "label": "📖 Liseuse 6 pouces",
        "suffix": "liseuse",
        "w_mm": 76, "h_mm": 114,
        "body_pt": 8.5, "title_pt": 13,
        "margin_mm": "5mm 7mm 8mm 7mm",
    },
    "tablet7": {
        "label": "📱 Tablette 7 pouces",
        "suffix": "tablette7",
        "w_mm": 100, "h_mm": 160,
        "body_pt": 9, "title_pt": 14,
        "margin_mm": "8mm 10mm 12mm 10mm",
    },
    "tablet10": {
        "label": "📱 Tablette 10 pouces",
        "suffix": "tablette10",
        "w_mm": 135, "h_mm": 200,
        "body_pt": 9, "title_pt": 15,
        "margin_mm": "10mm 12mm 14mm 12mm",
    },
    "a4premium": {
        "label": "🖨️  A4 Premium (magazine)",
        "suffix": "A4_premium",
        "w_mm": 210, "h_mm": 297,
        "body_pt": 10, "title_pt": 22,
        "margin_mm": "18mm 20mm 22mm 20mm",
        "two_column": True,
    },
    "a4landscape": {
        "label": "🖨️  A4 Premium Paysage",
        "suffix": "A4_premium_landscape",
        "w_mm": 297, "h_mm": 210,
        "body_pt": 10.5, "title_pt": 22,
        "margin_mm": "18mm 22mm 20mm 22mm",
        "two_column": True,
        "three_column": True,
    },
}
DEFAULT_FORMAT = "tablet7"


def select_format_profile() -> tuple[str, dict]:
    """Menu interactif pour choisir le format d'écran."""
    profiles = list(FORMATS.items())
    print("\n┌─────────────────────────────────────┐")
    print("│   Format de sortie PDF              │")
    print("├─────────────────────────────────────┤")
    for i, (key, p) in enumerate(profiles, 1):
        print(f"│  {i}. {p['label']:<32s}│")
    print(f"│  {len(profiles)+1}. {'✨ Tous les formats':<32s}│")
    print("└─────────────────────────────────────┘")
    while True:
        choice = input(f"Choix [1-{len(profiles)+1}, défaut=3]: ").strip()
        if not choice:
            key, prof = profiles[2]  # tablet7
            print(f"  → {prof['label']}")
            return (key, prof)
        try:
            idx = int(choice)
            if idx == len(profiles) + 1:
                print("  → Tous les formats")
                return ("all", None)
            if 1 <= idx <= len(profiles):
                key, prof = profiles[idx - 1]
                print(f"  → {prof['label']}")
                return (key, prof)
        except ValueError:
            pass
        print("  ⚠ Choix invalide, réessayez.")


def select_sections() -> str:
    """Menu interactif pour choisir les sections à inclure."""
    print("\n┌─────────────────────────────────────┐")
    print("│   Sections à inclure                │")
    print("├─────────────────────────────────────┤")
    print("│  1. 📰 Toute l'édition              │")
    print("│  2. 🌏 D'Asia à Obituary            │")
    print("│     (sans Leaders/US/Americas)       │")
    print("└─────────────────────────────────────┘")
    while True:
        choice = input("Choix [1-2, défaut=1]: ").strip()
        if not choice or choice == '1':
            print("  → Toute l'édition")
            return 'all'
        if choice == '2':
            print("  → D'Asia à Obituary")
            return 'asia'
        print("  ⚠ Choix invalide, réessayez.")


def build_css(fmt: dict = None) -> str:
    """Génère le CSS adapté au profil écran."""
    if fmt is None:
        fmt = FORMATS[DEFAULT_FORMAT]
    w = fmt["w_mm"]
    h = fmt["h_mm"]
    body_pt = fmt["body_pt"]
    margin = fmt["margin_mm"]
    title_pt = fmt["title_pt"]
    scale = body_pt / 9.0
    two_col = fmt.get("two_column", False)
    three_col = fmt.get("three_column", False)

    # A4 premium: two-column article body
    column_css = ""
    if two_col:
        col_count = 3 if three_col else 2
        column_css = f"""
article .article-body {{
    column-count: {col_count};
    column-gap: 6mm;
    column-rule: 0.3pt solid #ddd;
}}
article .article-body h1,
article .article-body .fly-title,
article .article-body .rubric,
article .article-body .meta,
article .article-body .byline {{
    column-span: all;
}}
article .article-body p:first-of-type {{
    text-indent: 0;
}}
article .article-body .img-container,
article .article-body .caption,
article .article-body blockquote.pullquote {{
    column-span: all;
}}
article .article-body h4 {{
    column-span: all;
}}
.cover-page {{
    padding-top: 40mm;
}}
.cover-page img {{
    max-width: 120mm;
}}
.toc-page {{
    column-count: 2;
    column-gap: 8mm;
}}
.toc-page h2 {{
    column-span: all;
}}
"""

    return f"""
@page {{
    size: {w}mm {h}mm;
    margin: {margin};
    @bottom-center {{
        content: counter(page);
        font-size: {max(5, 7*scale):.1f}pt;
        color: #999;
    }}
}}

body {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: {body_pt}pt;
    line-height: 1.45;
    color: #1a1a1a;
}}

.cover-page {{
    page-break-after: always;
    text-align: center;
    padding-top: {max(5, 15*scale):.0f}mm;
}}
.cover-page h1 {{
    font-size: {18*scale:.1f}pt;
    color: #e3120b;
    margin-bottom: 3mm;
    font-family: 'Helvetica', 'Arial', sans-serif;
}}
.cover-page .edition-date {{
    font-size: {11*scale:.1f}pt;
    color: #555;
    margin-bottom: {max(3, 8*scale):.0f}mm;
}}
.cover-page .description {{
    font-size: {body_pt}pt;
    color: #333;
    font-style: italic;
    margin-bottom: {max(3, 8*scale):.0f}mm;
}}
.cover-page img {{
    max-width: {max(35, 65*scale):.0f}mm;
    margin: 0 auto;
}}

.toc-page {{
    page-break-after: always;
}}
.toc-page h2 {{
    font-size: {13*scale:.1f}pt;
    color: #e3120b;
    border-bottom: 1.5pt solid #e3120b;
    padding-bottom: 2mm;
    margin-bottom: 4mm;
    font-family: 'Helvetica', 'Arial', sans-serif;
}}
.toc-section {{
    margin-bottom: 3mm;
}}
.toc-section h3 {{
    font-size: {9*scale:.1f}pt;
    color: #e3120b;
    margin: 2mm 0 1mm 0;
    font-family: 'Helvetica', 'Arial', sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
}}
.toc-item {{
    font-size: {8*scale:.1f}pt;
    line-height: 1.35;
    margin-left: 3mm;
    margin-bottom: 0.8mm;
}}
.toc-item .toc-title {{
    font-weight: bold;
    color: #1a1a1a;
}}
.toc-item .toc-desc {{
    color: #666;
    font-style: italic;
}}

article {{
    page-break-before: always;
}}
article:first-of-type {{
    page-break-before: avoid;
}}

.section-header {{
    font-size: {8*scale:.1f}pt;
    color: #e3120b;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    font-family: 'Helvetica', 'Arial', sans-serif;
    margin-bottom: 2mm;
    border-bottom: 0.5pt solid #e3120b;
    padding-bottom: 1mm;
}}

.fly-title {{
    color: #e3120b;
    font-size: {8*scale:.1f}pt;
    font-weight: bold;
    margin-bottom: 1mm;
}}

h1 {{
    font-size: {title_pt}pt;
    line-height: 1.2;
    margin: 1mm 0 2mm 0;
    color: #1a1a1a;
}}

.rubric {{
    font-style: italic;
    color: #333;
    font-size: {body_pt}pt;
    margin-bottom: 2mm;
    line-height: 1.3;
}}

.meta {{
    color: #999;
    font-size: {7*scale:.1f}pt;
    margin: 1mm 0;
}}

.byline {{
    color: #666;
    font-size: {7.5*scale:.1f}pt;
    font-style: italic;
    margin: 1mm 0 3mm 0;
}}

p {{
    text-align: justify;
    margin: 0 0 2mm 0;
    text-indent: 3mm;
}}

article p:first-of-type {{
    text-indent: 0;
}}

h4 {{
    font-size: {10*scale:.1f}pt;
    color: #333;
    margin: 4mm 0 2mm 0;
}}

blockquote {{
    margin: 3mm 4mm;
    padding-left: 3mm;
    border-left: 1.5pt solid #e3120b;
    color: #444;
    font-style: italic;
}}

blockquote.pullquote {{
    font-size: {10*scale:.1f}pt;
    text-align: center;
    border-left: none;
    border-top: 0.5pt solid #ccc;
    border-bottom: 0.5pt solid #ccc;
    padding: 2mm 3mm;
    margin: 3mm 5mm;
    color: #333;
}}

.img-container {{
    text-align: center;
    margin: 3mm 0 1mm 0;
}}

img {{
    max-width: 100%;
    height: auto;
}}

.caption {{
    text-align: center;
    font-size: {7*scale:.1f}pt;
    color: #888;
    margin: 1mm 0 3mm 0;
    font-style: italic;
}}

hr {{
    border: none;
    border-top: 0.5pt solid #ddd;
    margin: 4mm 15mm;
}}

a {{
    color: #e3120b;
    text-decoration: none;
}}

ul, ol {{
    margin: 2mm 0 2mm 5mm;
    padding-left: 3mm;
}}

li {{
    margin-bottom: 1mm;
    font-size: {body_pt}pt;
}}

sub, sup {{
    font-size: 0.7em;
}}

{column_css}
"""


# ─── Classe principale ─────────────────────────────────────────────────────

class EconomistDownloader:
    def __init__(self, output_dir=None, img_width='600', include_images=True,
                 delay=1.0, edition_date=None, fmt=None, sections_filter='all'):
        self.output_dir = Path(output_dir or (
            Path.home() / 'kDrive' / 'newspapers' / 'journaux_du_jour'
        ))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.img_width = img_width
        self.include_images = include_images
        self.delay = delay
        self.edition_date = edition_date
        self.fmt = fmt or FORMATS[DEFAULT_FORMAT]
        self.sections_filter = sections_filter or 'all'

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        })

        self.sections = []      # [(section_name, [articles])]
        self.cover_url = None
        self.edition_title = ''
        self.edition_formatted_date = ''

        self.stats = {
            'articles': 0,
            'errors': 0,
            'skipped_interactive': 0,
        }
        self._article_cache = []  # [(section_name, json_data)] for EPUB

    # ─── Index de l'édition ─────────────────────────────────────────────

    def _fetch_index_requests(self, url):
        """Tentative 1 : requests simple."""
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text, resp.url

    def _fetch_index_cloudscraper(self, url):
        """Tentative 2 : cloudscraper (contourne Cloudflare JS challenge)."""
        try:
            import cloudscraper
        except ImportError:
            print('    💡 pip install cloudscraper  (recommandé)')
            raise
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'linux', 'desktop': True}
        )
        resp = scraper.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text, resp.url

    def _fetch_index_playwright(self, url):
        """Tentative 3 : Playwright (navigateur headless complet)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print('    💡 pip install playwright && playwright install chromium')
            raise
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='networkidle', timeout=45000)
            final_url = page.url
            html = page.content()
            browser.close()
        return html, final_url

    def fetch_edition_index(self):
        """Récupère le sommaire de l'édition depuis le site web.
        Essaie 3 méthodes : requests → cloudscraper → playwright."""
        if self.edition_date:
            url = f'https://www.economist.com/weeklyedition/{self.edition_date}'
        else:
            url = 'https://www.economist.com/weeklyedition'

        print(f'📰 Récupération du sommaire : {url}')

        methods = [
            ('requests',      self._fetch_index_requests),
            ('cloudscraper',  self._fetch_index_cloudscraper),
            ('playwright',    self._fetch_index_playwright),
        ]

        html_text = None
        final_url = url

        for name, method in methods:
            try:
                print(f'  → Tentative {name}...', end=' ', flush=True)
                html_text, final_url = method(url)
                # Vérifier que c'est bien du HTML avec __NEXT_DATA__
                if '__NEXT_DATA__' in html_text:
                    print('✅')
                    break
                else:
                    print('⚠ (HTML reçu mais sans __NEXT_DATA__, Cloudflare ?)')
                    html_text = None
            except Exception as e:
                print(f'❌ ({e})')
                html_text = None

        if html_text is None:
            print('\n❌ Impossible de récupérer le sommaire.')
            print('   Installe un des packages suivants :')
            print('     pip install cloudscraper')
            print('     pip install playwright && playwright install chromium')
            sys.exit(1)

        # Extraire la date depuis l'URL finale
        date_match = re.search(r'/(\d{4}-\d{2}-\d{2})', final_url)
        if date_match:
            self.edition_date = date_match.group(1)

        soup = BeautifulSoup(html_text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')

        if script_tag is None:
            print('❌ __NEXT_DATA__ introuvable dans le HTML.')
            sys.exit(1)

        data = json.loads(script_tag.string)
        content = safe_dict(data, 'props', 'pageProps', 'content')

        self.edition_title = content.get('headline', 'The Economist')
        self.edition_formatted_date = content.get('formattedIssueDate', self.edition_date or '')

        # Couverture
        cover_url = safe_dict(content, 'cover', 'url')
        if cover_url:
            self.cover_url = (
                cover_url
                .replace('economist.com/',
                         'economist.com/cdn-cgi/image/width=960,quality=80,format=auto/')
                .replace('SQ_', '').replace('_AS', '_AP')
            )

        # Sections et articles
        all_sections = (
            (content.get('headerSections') or []) +
            (content.get('sections') or [])
        )

        for part in all_sections:
            section_name = safe_dict(part, 'name') or ''
            if not section_name:
                continue

            articles = []
            for ar in part.get('articles', []):
                title = safe_dict(ar, 'headline') or ''
                art_url = safe_dict(ar, 'url') or ''
                if not title or not art_url:
                    continue
                if art_url.startswith('/'):
                    art_url = 'https://www.economist.com' + art_url

                desc = safe_dict(ar, 'rubric') or ''
                fly = safe_dict(ar, 'flyTitle') or ''
                if fly and section_name != fly:
                    desc = f'{fly} :: {desc}' if desc else fly

                articles.append({
                    'title': title,
                    'url': art_url,
                    'description': desc,
                    'fly_title': fly,
                })

            if articles:
                self.sections.append((section_name, articles))

        total = sum(len(arts) for _, arts in self.sections)
        print(f'✅ {len(self.sections)} sections, {total} articles')

        # ── Filtrage par région ────────────────────────────────────────
        if self.sections_filter == 'asia':
            # Garder tout à partir de la section "Asia" jusqu'à la fin
            # (Asia, China, Middle East, Europe, Britain, ... Obituary)
            start_lower = 'asia'
            start_idx = None
            for i, (name, _arts) in enumerate(self.sections):
                if start_lower in name.lower():
                    start_idx = i
                    break

            if start_idx is not None:
                dropped = self.sections[:start_idx]
                self.sections = self.sections[start_idx:]
                total = sum(len(a) for _, a in self.sections)
                if dropped:
                    dropped_names = ", ".join(n for n, _ in dropped)
                    print(f'✂️  Sections éliminées ({len(dropped)}) : {dropped_names}')
                kept_names = ", ".join(n for n, _ in self.sections)
                print(f'📖 Sections conservées ({len(self.sections)}) : {kept_names}')
                print(f'📊 Total après filtrage : {len(self.sections)} sections, {total} articles')
            else:
                print('⚠  Section « Asia » non trouvée, toutes les sections conservées')

        print(f'📅 Édition : {self.edition_formatted_date}')
        if self.cover_url:
            print(f'🖼  Couverture : trouvée')

        return self.sections

    # ─── Téléchargement d'un article via l'API GraphQL ──────────────────

    def fetch_article_api(self, url):
        """Télécharge un article via l'API GraphQL Android (pas d'auth)."""
        query_params = {
            'operationName': 'ArticleDeeplinkQuery',
            'variables': json.dumps({'ref': url}),
            'query': GRAPHQL_QUERY,
        }
        api_url = (
            'https://cp2-graphql-gateway.p.aws.economist.com/graphql?'
            + urlencode(query_params, safe='()!', quote_via=quote)
        )

        headers = dict(ANDROID_HEADERS)
        headers['x-app-trace-id'] = str(uuid4())

        resp = requests.get(api_url, headers=headers, timeout=30)
        resp.raise_for_status()

        raw = resp.json()
        data = raw.get('data', {}).get('findArticleByUrl')
        if not data:
            return None
        return data

    def fetch_article_web(self, url):
        """Fallback : récupère l'article via le parsing web."""
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        if script_tag is None:
            return None

        raw = json.loads(script_tag.string)
        try:
            data = raw['props']['pageProps']['cp2Content']
        except (KeyError, TypeError):
            try:
                data = raw['props']['pageProps']['content']
            except (KeyError, TypeError):
                return None
        return data

    def fetch_article(self, url):
        """Récupère un article (API d'abord, web en fallback)."""
        # Skip les articles interactifs
        if '/interactive/' in url:
            self.stats['skipped_interactive'] += 1
            return None

        try:
            data = self.fetch_article_api(url)
            if data:
                return data
        except Exception as e:
            print(f'    ⚠  API échouée ({e}), fallback web...')

        try:
            return self.fetch_article_web(url)
        except Exception as e:
            print(f'    ❌ Web aussi échoué : {e}')
            return None

    # ─── Génération du HTML complet ─────────────────────────────────────

    def build_full_html(self):
        """Construit le HTML complet de l'édition."""
        html_parts = []

        # Page de couverture
        cover_img = ''
        if self.cover_url and self.include_images:
            cover_img = f'<img src="{self.cover_url}" alt="Cover">'

        html_parts.append(f'''
        <div class="cover-page">
            <h1>The Economist</h1>
            <div class="edition-date">{self.edition_formatted_date}</div>
            <div class="description">{self.edition_title}</div>
            {cover_img}
        </div>
        ''')

        # Table des matières
        toc_html = '<div class="toc-page"><h2>Contents</h2>'
        for section_name, articles in self.sections:
            toc_html += f'<div class="toc-section"><h3>{section_name}</h3>'
            for art in articles:
                desc = f' — <span class="toc-desc">{art["description"]}</span>' if art['description'] else ''
                toc_html += f'<div class="toc-item"><span class="toc-title">{art["title"]}</span>{desc}</div>'
            toc_html += '</div>'
        toc_html += '</div>'
        html_parts.append(toc_html)

        # Articles
        total = sum(len(arts) for _, arts in self.sections)
        current = 0

        for section_name, articles in self.sections:
            for art in articles:
                current += 1
                print(f'  [{current}/{total}] {art["title"][:60]}...', end=' ', flush=True)

                data = self.fetch_article(art['url'])

                if data is None:
                    print('⏭ ')
                    self.stats['errors'] += 1
                    continue

                self._article_cache.append((section_name, data))
                article_html = article_json_to_html(data, self.img_width)
                html_parts.append(
                    f'<article>'
                    f'<div class="section-header">{section_name}</div>'
                    f'<div class="article-body">{article_html}</div>'
                    f'</article>'
                )
                self.stats['articles'] += 1
                print('✅')

                if self.delay > 0:
                    time.sleep(self.delay)

        # Suppression des images si demandé
        full_html = '\n'.join(html_parts)
        if not self.include_images:
            full_html = re.sub(r'<div class="img-container">.*?</div>\s*<div class="caption">.*?</div>',
                               '', full_html, flags=re.DOTALL)
            full_html = re.sub(r'<img[^>]*>', '', full_html)

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <style>{build_css(self.fmt)}</style>
</head>
<body>
{full_html}
</body>
</html>'''

    # ─── Génération du PDF ──────────────────────────────────────────────

    def generate_pdf(self, fmt=None):
        """Génère le PDF final pour un format donné."""
        try:
            from weasyprint import HTML
        except ImportError:
            print('❌ weasyprint non installé. pip install weasyprint')
            sys.exit(1)

        if fmt:
            self.fmt = fmt

        suffix = self.fmt.get('suffix', 'tablette7')
        date_str = self.edition_date or datetime.now().strftime('%Y-%m-%d')
        filename = f'{date_str}-economist_{suffix}.pdf'
        pdf_path = self.output_dir / filename

        print(f'\n📄 Génération du PDF ({self.fmt["label"]})...')

        full_html = self.build_full_html()

        # Sauvegarder le HTML intermédiaire (utile pour debug)
        html_debug = self.output_dir / f'{date_str}-economist_{suffix}.html'
        html_debug.write_text(full_html, encoding='utf-8')

        HTML(string=full_html).write_pdf(str(pdf_path))

        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        print(f'✅ PDF créé : {pdf_path} ({size_mb:.1f} Mo)')

        return pdf_path

    def generate_all_pdfs(self):
        """Génère les PDFs pour tous les formats (un seul fetch)."""
        paths = []
        for key, fmt in FORMATS.items():
            try:
                path = self.generate_pdf(fmt=fmt)
                paths.append(path)
            except Exception as e:
                print(f'  ⚠ Erreur format {key}: {e}')
        return paths

    def generate_epub_book(self):
        """Generate an EPUB from cached article data."""
        if not self._article_cache:
            print('  ⚠ No articles cached for EPUB generation')
            return None

        date_str = self.edition_date or datetime.now().strftime('%Y-%m-%d')
        epub_path = self.output_dir / f'{date_str}-economist.epub'

        epub_articles = []
        for section_name, data in self._article_cache:
            # Extract image URL from lead component or teaser image
            image_url = ""
            lead = safe_dict(data, 'leadComponent')
            if lead and lead.get('url'):
                image_url = lead['url']
            elif safe_dict(data, 'teaserImage') and safe_dict(data, 'teaserImage').get('url'):
                image_url = safe_dict(data, 'teaserImage')['url']

            # Build per-article body HTML (without the title/rubric/byline —
            # the EPUB generator adds those itself)
            body_parts = []
            for node in data.get('body', []):
                body_parts.append(process_web_node(node))
            body_html = '\n'.join(body_parts)

            epub_articles.append({
                'title': data.get('headline', data.get('printHeadline', 'Untitled')),
                'author': data.get('byline', ''),
                'category': section_name,
                'lead': data.get('rubric', ''),
                'content_html': body_html,
                'image_url': image_url,
                'image_caption': '',
            })

        def _fetch_image(url):
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                ctype = resp.headers.get('Content-Type', 'image/jpeg')
                return resp.content, ctype
            except Exception:
                return None

        generate_epub(
            epub_articles,
            publication_title='The Economist',
            edition_title=self.edition_formatted_date or f'Edition of {date_str}',
            date_str=date_str,
            output_path=epub_path,
            language='en',
            publisher='The Economist',
            image_fetcher=_fetch_image if self.include_images else None,
        )
        return epub_path

    # ─── Affichage du sommaire ──────────────────────────────────────────

    def print_toc(self):
        """Affiche le sommaire en mode texte."""
        print(f'\n{"="*60}')
        print(f'  The Economist — {self.edition_formatted_date}')
        print(f'  {self.edition_title}')
        print(f'{"="*60}')

        for section_name, articles in self.sections:
            print(f'\n  ■ {section_name}')
            for art in articles:
                fly = f'[{art["fly_title"]}] ' if art.get('fly_title') else ''
                print(f'    • {fly}{art["title"]}')
                if art.get('description'):
                    # Nettoyer la description (supprimer le fly_title dupliqué)
                    desc = art['description']
                    if ' :: ' in desc:
                        desc = desc.split(' :: ', 1)[1]
                    if desc:
                        print(f'      {desc[:80]}')

    # ─── Résumé ─────────────────────────────────────────────────────────

    def print_summary(self):
        """Affiche les statistiques."""
        print(f'\n{"="*60}')
        print(f'✅ Téléchargement terminé !')
        print(f'   📄 Articles récupérés   : {self.stats["articles"]}')
        print(f'   ⏭  Interactifs ignorés  : {self.stats["skipped_interactive"]}')
        print(f'   ⚠  Erreurs              : {self.stats["errors"]}')
        print(f'   📁 Dossier              : {self.output_dir.resolve()}')
        print(f'{"="*60}')

    # ─── Point d'entrée principal ───────────────────────────────────────

    def run(self, list_only=False, generate_all=False, epub_only=False, formats_list=None):
        """Exécute le workflow complet."""
        self.fetch_edition_index()

        if list_only:
            self.print_toc()
            return None

        if epub_only:
            # Build HTML to populate article cache, then generate EPUB
            self.build_full_html()
            epub_path = self.generate_epub_book()
            self.print_summary()
            return epub_path

        if generate_all:
            paths = self.generate_all_pdfs()
            epub_path = self.generate_epub_book()
            if epub_path:
                paths.append(epub_path)
            self.print_summary()
            return paths

        if formats_list:
            # Generate a specific subset of formats
            paths = []
            pdf_keys = [f for f in formats_list if f != 'epub']
            want_epub = 'epub' in formats_list
            for key in pdf_keys:
                try:
                    path = self.generate_pdf(fmt=FORMATS[key])
                    paths.append(path)
                except Exception as e:
                    print(f'  ⚠ Erreur format {key}: {e}')
            if want_epub:
                epub_path = self.generate_epub_book()
                if epub_path:
                    paths.append(epub_path)
            self.print_summary()
            return paths

        pdf_path = self.generate_pdf()
        self.print_summary()
        return pdf_path


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='📰 The Economist Weekly Edition Downloader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Exemples:
  %(prog)s                          # Dernière édition, tablette 7"
  %(prog)s --format all             # Tous les formats (5 PDFs)
  %(prog)s --format a4premium       # A4 premium deux colonnes
  %(prog)s --sections asia          # D'Asia à Obituary (sans Leaders/US/Americas)
  %(prog)s --date 2025-02-07        # Édition du 7 février 2025
  %(prog)s --list-only              # Afficher le sommaire uniquement
  %(prog)s --no-images              # PDF sans images (plus léger)
  %(prog)s --width 960 --delay 0.5  # Images HD, téléchargement rapide
        '''
    )
    parser.add_argument('--date', '-d',
                        help='Date de l\'édition (YYYY-MM-DD)')
    parser.add_argument('--output', '-o',
                        default=None,
                        help='Dossier de sortie (défaut: ~/kDrive/newspapers/journaux_du_jour)')
    parser.add_argument('--list-only', '-l', action='store_true',
                        help='Afficher le sommaire sans télécharger')
    parser.add_argument('--no-images', action='store_true',
                        help='Exclure les images du PDF')
    parser.add_argument('--width', '-w', default='600',
                        help='Largeur des images en px (défaut: 600)')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Délai entre requêtes en secondes (défaut: 1.0)')
    parser.add_argument('--format', '-f',
                        default=None,
                        help='Format(s) : phone,ereader,tablet7,tablet10,a4premium,a4landscape,epub,all (comma-separated)')
    parser.add_argument('--sections', '-s',
                        choices=['all', 'asia'],
                        default=None,
                        help='Sections à inclure : all (défaut) ou asia (d\'Asia à Obituary, sans Leaders/US/Americas)')

    args = parser.parse_args()

    # Format selection
    generate_all = False
    epub_only = False
    formats_list = None  # None = single format; list = specific subset
    if args.format == 'all':
        generate_all = True
        fmt = FORMATS[DEFAULT_FORMAT]  # used for initial setup
    elif args.format and ',' in args.format:
        # Multiple comma-separated formats
        valid = set(FORMATS.keys()) | {'epub'}
        formats_list = [f.strip() for f in args.format.split(',')]
        for f in formats_list:
            if f not in valid:
                print(f'  ❌ Format inconnu : {f!r} (valides : {", ".join(sorted(valid))})')
                sys.exit(1)
        fmt = FORMATS[DEFAULT_FORMAT]
    elif args.format == 'epub':
        epub_only = True
        fmt = FORMATS[DEFAULT_FORMAT]
    elif args.format:
        if args.format not in FORMATS:
            print(f'  ❌ Format inconnu : {args.format!r}')
            sys.exit(1)
        fmt = FORMATS[args.format]
    elif not args.list_only:
        key, fmt = select_format_profile()
        if key == 'all':
            generate_all = True
            fmt = FORMATS[DEFAULT_FORMAT]
    else:
        fmt = FORMATS[DEFAULT_FORMAT]

    # Sections selection
    if args.sections:
        sections_filter = args.sections
    elif not args.list_only:
        sections_filter = select_sections()
    else:
        sections_filter = 'all'

    output_dir = args.output or str(Path.home() / 'kDrive' / 'newspapers' / 'journaux_du_jour')

    downloader = EconomistDownloader(
        output_dir=output_dir,
        img_width=args.width,
        include_images=not args.no_images,
        delay=args.delay,
        edition_date=args.date,
        fmt=fmt,
        sections_filter=sections_filter,
    )

    downloader.run(list_only=args.list_only, generate_all=generate_all,
                   epub_only=epub_only, formats_list=formats_list)


if __name__ == '__main__':
    main()
