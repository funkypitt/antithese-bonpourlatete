#!/usr/bin/env python3
"""
Antithèse / Bon pour la tête — Weekly Edition Scraper & PDF Generator
======================================================================
Downloads the current edition's articles from antithese.info and generates
formatted PDF digests for phone, e-reader (6"), tablet (7"), tablet (10")
and two premium A4 "magazine" editions:
  - A4 Premium: two-column layout inspired by The New Yorker
  - A4 Éditorial: single-column layout inspired by Kinfolk / Cereal

Usage:
    python3 antithese_scraper.py                      # All formats
    python3 antithese_scraper.py --format tablet7     # Single format
    python3 antithese_scraper.py --format a4premium   # New Yorker 2-col
    python3 antithese_scraper.py --format a4editorial # Kinfolk 1-col
    python3 antithese_scraper.py --user X --password Y --format all

Dependencies:
    pip install requests beautifulsoup4 weasyprint
"""

import os
import sys

# ── PyInstaller macOS dylib fix ───────────────────────────────────────────
# On macOS, PyInstaller --onefile extracts bundled dylibs to a temp dir
# (sys._MEIPASS) but does NOT set DYLD_FALLBACK_LIBRARY_PATH.  Linux is fine
# because PyInstaller injects LD_LIBRARY_PATH automatically.  We must tell
# dlopen() where to find the Homebrew dylibs (pango, harfbuzz, etc.) BEFORE
# WeasyPrint is imported.
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        _existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if _meipass not in _existing:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{_meipass}:{_existing}" if _existing else _meipass
            )

import argparse
import base64
import getpass
import re
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from epub_generator import generate_epub

# ── Identifiants (à renseigner ici pour éviter la saisie interactive) ──────
ANTITHESE_USER = "pierre.crot@protonmail.com"
ANTITHESE_PASS = "Moroder1976!"

# ── Format profiles ────────────────────────────────────────────────────────
FORMATS = {
    "phone": {
        "label": "📱 Téléphone",
        "suffix": "telephone",
        "width_mm": 65,
        "height_mm": 115,
        "font_size": "8pt",
        "h1_size": "13pt",
        "h2_size": "11pt",
        "h3_size": "10pt",
        "margin": "6mm",
        "line_height": "1.35",
        # Enhanced layout params
        "logo_width": "25mm",
        "banner_padding": "3mm 5mm",
        "banner_width": "38mm",
        "img_max_height": "35mm",
        "drop_cap_size": "22pt",
        "drop_cap_padding": "1mm",
        "toc_num_size": "11pt",
        "toc_num_width": "7mm",
        "toc_title_size": "8pt",
        "toc_cat_size": "6pt",
        "toc_author_size": "7pt",
        "cover_subtitle_size": "8pt",
        "cover_edition_size": "8pt",
        "cover_hl_title_size": "8pt",
        "cover_hl_cat_size": "6pt",
        "cover_hl_author_size": "6.5pt",
        "cover_padding": "8mm 6mm",
        "colophon_logo_width": "18mm",
        "colophon_font_size": "6.5pt",
        "caption_size": "6pt",
    },
    "ereader": {
        "label": "📖 Liseuse 6 pouces",
        "suffix": "liseuse",
        "width_mm": 90,
        "height_mm": 122,
        "font_size": "9pt",
        "h1_size": "15pt",
        "h2_size": "12pt",
        "h3_size": "11pt",
        "margin": "8mm",
        "line_height": "1.4",
        # Enhanced layout params
        "logo_width": "30mm",
        "banner_padding": "3.5mm 6mm",
        "banner_width": "45mm",
        "img_max_height": "42mm",
        "drop_cap_size": "26pt",
        "drop_cap_padding": "1.2mm",
        "toc_num_size": "13pt",
        "toc_num_width": "8mm",
        "toc_title_size": "9pt",
        "toc_cat_size": "6.5pt",
        "toc_author_size": "7.5pt",
        "cover_subtitle_size": "9pt",
        "cover_edition_size": "8.5pt",
        "cover_hl_title_size": "9pt",
        "cover_hl_cat_size": "6.5pt",
        "cover_hl_author_size": "7pt",
        "cover_padding": "10mm 8mm",
        "colophon_logo_width": "22mm",
        "colophon_font_size": "7pt",
        "caption_size": "6.5pt",
    },
    "tablet7": {
        "label": "📱 Tablette 7 pouces",
        "suffix": "tablette7",
        "width_mm": 100,
        "height_mm": 160,
        "font_size": "9.5pt",
        "h1_size": "16pt",
        "h2_size": "13pt",
        "h3_size": "11.5pt",
        "margin": "10mm",
        "line_height": "1.45",
        # Enhanced layout params
        "logo_width": "35mm",
        "banner_padding": "4mm 7mm",
        "banner_width": "52mm",
        "img_max_height": "55mm",
        "drop_cap_size": "30pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "14pt",
        "toc_num_width": "9mm",
        "toc_title_size": "9.5pt",
        "toc_cat_size": "6.5pt",
        "toc_author_size": "8pt",
        "cover_subtitle_size": "10pt",
        "cover_edition_size": "9pt",
        "cover_hl_title_size": "9.5pt",
        "cover_hl_cat_size": "6.5pt",
        "cover_hl_author_size": "7.5pt",
        "cover_padding": "15mm 10mm",
        "colophon_logo_width": "25mm",
        "colophon_font_size": "7pt",
        "caption_size": "6.5pt",
    },
    "tablet10": {
        "label": "📱 Tablette 10 pouces",
        "suffix": "tablette10",
        "width_mm": 135,
        "height_mm": 200,
        "font_size": "9pt",
        "h1_size": "15pt",
        "h2_size": "12.5pt",
        "h3_size": "11pt",
        "margin": "12mm",
        "line_height": "1.4",
        # Enhanced layout params
        "logo_width": "42mm",
        "banner_padding": "5mm 8mm",
        "banner_width": "62mm",
        "img_max_height": "70mm",
        "drop_cap_size": "34pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "16pt",
        "toc_num_width": "10mm",
        "toc_title_size": "10pt",
        "toc_cat_size": "7pt",
        "toc_author_size": "8pt",
        "cover_subtitle_size": "10.5pt",
        "cover_edition_size": "9.5pt",
        "cover_hl_title_size": "10pt",
        "cover_hl_cat_size": "7pt",
        "cover_hl_author_size": "7.5pt",
        "cover_padding": "18mm 12mm",
        "colophon_logo_width": "30mm",
        "colophon_font_size": "7.5pt",
        "caption_size": "7pt",
    },
    "a4premium": {
        "label": "🖨️  A4 Premium — New Yorker (2 colonnes)",
        "suffix": "A4_premium",
        "width_mm": 210,
        "height_mm": 297,
        "font_size": "10pt",
        "h1_size": "28pt",
        "h2_size": "22pt",
        "h3_size": "13pt",
        "margin": "20mm",
        "line_height": "1.5",
    },
    "a4editorial": {
        "label": "🖨️  A4 Éditorial — Kinfolk (1 colonne)",
        "suffix": "A4_editorial",
        "width_mm": 210,
        "height_mm": 297,
        "font_size": "11pt",
        "h1_size": "32pt",
        "h2_size": "26pt",
        "h3_size": "13pt",
        "margin": "28mm",
        "line_height": "1.7",
    },
    "a4landscape": {
        "label": "🖨️  A4 Premium Paysage (3 colonnes)",
        "suffix": "A4_premium_landscape",
        "width_mm": 297,
        "height_mm": 210,
        "font_size": "11pt",
        "h1_size": "26pt",
        "h2_size": "20pt",
        "h3_size": "13pt",
        "margin": "18mm",
        "line_height": "1.6",
    },
}

EDITION_URL = "https://www.antithese.info/bon-pour-la-tete/"
LOGIN_URL = "https://www.antithese.info/login/"
WP_LOGIN_URL = "https://www.antithese.info/wp-login.php"
BASE_URL = "https://www.antithese.info"
OUTPUT_DIR = Path.home() / "kDrive" / "newspapers" / "journaux_du_jour"

LOGO_URL = "https://www.antithese.info/wp-content/uploads/Logo-Antihese-et-Bon-pour-la-tete.svg"
BPLT_LOGO_URL = "https://www.antithese.info/wp-content/uploads/BPLT2.svg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Authentication ─────────────────────────────────────────────────────────
def login(session: requests.Session, username: str, password: str) -> bool:
    """Log in to antithese.info via WordPress wp-login.php."""
    print(f"  🔐 Connexion en tant que {username}…")

    login_data = {
        "log": username,
        "pwd": password,
        "wp-submit": "Se connecter",
        "redirect_to": EDITION_URL,
        "testcookie": "1",
    }

    session.cookies.set("wordpress_test_cookie", "WP+Cookie+check", domain="www.antithese.info")
    resp = session.post(WP_LOGIN_URL, data=login_data, headers=HEADERS, allow_redirects=True)

    if resp.status_code == 200:
        cookies_names = [c.name for c in session.cookies]
        has_wp_cookies = any("wordpress_logged_in" in n for n in cookies_names)

        if has_wp_cookies:
            print("  ✅ Connecté avec succès.")
            return True

        if any("wordpress" in n.lower() for n in cookies_names) and "login" not in resp.url:
            print("  ✅ Connecté avec succès.")
            return True

    if "login" in resp.url.lower() and ("incorrect" in resp.text.lower() or "error" in resp.text.lower()):
        print("  ❌ Identifiants incorrects.")
        return False

    test = session.get(EDITION_URL, headers=HEADERS)
    if "Se Connecter" not in test.text or "Déconnexion" in test.text:
        print("  ✅ Connecté avec succès (vérifié).")
        return True

    print("  ❌ Échec de connexion. Vérifiez vos identifiants.")
    return False


# ── Image helpers ──────────────────────────────────────────────────────────
def download_image_as_data_uri(session: requests.Session, url: str) -> str | None:
    """Download an image and return it as a base64 data URI.
    Returns None if download fails."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "svg" in content_type or url.endswith(".svg"):
            content_type = "image/svg+xml"
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception as e:
        return None


def download_image_bytes(session: requests.Session, url: str) -> tuple[bytes, str] | None:
    """Download an image and return (bytes, content_type)."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return resp.content, content_type
    except Exception:
        return None


def download_logo(session: requests.Session) -> tuple[str | None, str | None]:
    """Download the Antithèse logo as data URIs.

    Returns (logo_dark_bg, logo_light_bg):
      - logo_dark_bg:  original SVG (white + red text, for dark backgrounds)
      - logo_light_bg: modified SVG (white replaced by near-black, for light backgrounds)

    The original logo has 'ANTI' in white and 'THÈSE' in red/magenta,
    plus 'BON POUR LA TÊTE' in white — invisible on light backgrounds.
    """
    print("  🎨 Téléchargement du logo…")
    try:
        resp = session.get(LOGO_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        svg_text = resp.content.decode("utf-8", errors="replace")

        # Original version (for dark backgrounds)
        b64_orig = base64.b64encode(resp.content).decode("ascii")
        logo_dark = f"data:image/svg+xml;base64,{b64_orig}"

        # Light-background version: replace white fills with near-black
        svg_light = svg_text
        # Replace common white color values with dark charcoal
        svg_light = re.sub(r'fill\s*:\s*#(?:fff(?:fff)?)\b', 'fill:#1a1a1a', svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*=\s*"#(?:fff(?:fff)?)"', 'fill="#1a1a1a"', svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*:\s*white\b', 'fill:#1a1a1a', svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*=\s*"white"', 'fill="#1a1a1a"', svg_light, flags=re.IGNORECASE)
        # Also handle rgb(255,255,255)
        svg_light = re.sub(
            r'fill\s*:\s*rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)',
            'fill:#1a1a1a', svg_light, flags=re.IGNORECASE
        )
        svg_light = re.sub(
            r'fill\s*=\s*"rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)"',
            'fill="#1a1a1a"', svg_light, flags=re.IGNORECASE
        )

        b64_light = base64.b64encode(svg_light.encode("utf-8")).decode("ascii")
        logo_light = f"data:image/svg+xml;base64,{b64_light}"

        print("  ✅ Logo récupéré (versions fond clair + fond sombre).")
        return logo_dark, logo_light

    except Exception as e:
        print(f"  ⚠  Logo non disponible ({e}), utilisation du texte.")
        return None, None


# ── Text cleaning helper ───────────────────────────────────────────────
def clean_text(element) -> str:
    """Extract text from a BeautifulSoup element, preserving spaces between
    inline elements (links, bold, italic, etc.).

    get_text(strip=True) strips whitespace from each text node independently,
    which causes 'sur <a>Infosperber</a>' to become 'surInfosperber'.
    Using separator=" " inserts a space at each tag boundary, then we
    normalize multiple spaces.
    """
    text = element.get_text(separator=" ")
    # Collapse multiple whitespace (incl. newlines) into single spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Scraping ───────────────────────────────────────────────────────────────
def get_edition_info(session: requests.Session) -> tuple[str, list[dict], dict | None]:
    """Fetch the edition page and extract article links + metadata.

    Returns (date_str, articles, dessin_info).
      - articles:    list of dicts with keys url, title, category, thumb_url, is_pilet
      - dessin_info: dict with keys image_url, title, artist (or None)
    """
    print("  📰 Récupération de l'édition en cours…")
    resp = session.get(EDITION_URL, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract edition date from the H1
    edition_title = ""
    h1 = soup.find("h1")
    if h1:
        edition_title = clean_text(h1)
        edition_title = re.sub(r"(du)(\d)", r"\1 \2", edition_title)
    print(f"     {edition_title}")

    # Extract date for filename
    date_match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", edition_title)
    if date_match:
        months_fr = {
            "janvier": "01", "février": "02", "mars": "03", "avril": "04",
            "mai": "05", "juin": "06", "juillet": "07", "août": "08",
            "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
        }
        day = date_match.group(1).zfill(2)
        month = months_fr.get(date_match.group(2).lower(), "00")
        year = date_match.group(3)
        date_str = f"{year}-{month}-{day}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # ── Locate content sections ────────────────────────────────────────
    brx = soup.find(id="brx-content")
    if not brx:
        return date_str, [], None

    top_sections = brx.find_all("section", class_="brxe-section", recursive=False)

    # ── Collect URLs from "Précédente édition" (section 3+) to exclude ─
    previous_urls = set()
    for sec in top_sections[2:]:  # sections after the main content
        for heading in sec.find_all(class_="brxe-heading"):
            txt = heading.get_text(strip=True).lower()
            if "dition" in txt and ("préc" in txt or "prec" in txt):
                for a in sec.find_all("a", href=True):
                    if "/articles/" in a["href"]:
                        previous_urls.add(urljoin(BASE_URL, a["href"]))
                break
    if previous_urls:
        print(f"     ↳ {len(previous_urls)} articles de l'édition précédente exclus")

    # ── Work within section 1 (main edition content) ───────────────────
    sec1 = top_sections[1] if len(top_sections) > 1 else brx

    # ── Identify Pilet article URLs ────────────────────────────────────
    pilet_urls = set()
    for heading in sec1.find_all(class_="brxe-heading"):
        if "pilet" in heading.get_text(strip=True).lower():
            container = heading.parent
            for _ in range(5):
                links = container.find_all("a", href=lambda h: h and "/articles/" in h)
                if len(set(a["href"] for a in links)) > 1:
                    break
                container = container.parent
            for a in container.find_all("a", href=lambda h: h and "/articles/" in h):
                pilet_urls.add(urljoin(BASE_URL, a["href"]))
            break
    if pilet_urls:
        print(f"     ↳ {len(pilet_urls)} articles de l'espace Jacques Pilet (filtrage par date)")

    # ── Extract "Dessin de la semaine" ─────────────────────────────────
    dessin_info = None
    for heading in sec1.find_all(class_="brxe-heading"):
        txt = heading.get_text(strip=True).lower()
        if "dessin" in txt and "semaine" in txt:
            container = heading.parent
            for _ in range(4):
                imgs = container.find_all("img")
                headings_in = container.find_all(class_="brxe-heading")
                if imgs and len(headings_in) >= 2:
                    break
                container = container.parent
            if imgs:
                img_src = imgs[0].get("src") or imgs[0].get("data-src", "")
                # Get the title: second heading (first is "Le dessin de la semaine")
                dessin_title = ""
                dessin_artist = ""
                for h in headings_in:
                    h_text = clean_text(h)
                    if "dessin" in h_text.lower():
                        continue
                    if h_text.startswith("{"):
                        # Template tag not rendered — try to extract clean part
                        if "/" in h_text:
                            h_text = h_text.split("/", 1)[1].strip()
                        elif "}" in h_text:
                            continue
                    if not dessin_title and len(h_text) > 5:
                        dessin_title = h_text
                    elif not dessin_artist and h_text and not h_text.startswith("{"):
                        dessin_artist = h_text
                if img_src:
                    # Get hi-res version
                    hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_src)
                    dessin_info = {
                        "image_url": urljoin(BASE_URL, hires),
                        "image_url_fallback": urljoin(BASE_URL, img_src),
                        "title": dessin_title,
                        "artist": dessin_artist,
                    }
                    print(f"     ↳ Dessin de la semaine: {dessin_title[:50]}")
            break

    # ── Collect article links (from section 1 only) ────────────────────
    articles = []
    seen_urls = set()

    for a_tag in sec1.find_all("a", href=True):
        href = a_tag["href"]
        if "/articles/" not in href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue

        # Skip articles from previous edition
        if full_url in previous_urls:
            seen_urls.add(full_url)
            continue

        title = ""
        category = ""

        # Look for headings inside the link — skip known category headings
        KNOWN_CATEGORIES = {
            "Economie", "Économie", "Politique", "Histoire",
            "Sciences & Technologies", "Santé", "Philosophie",
            "Culture", "Accès libre",
        }
        for heading in a_tag.find_all(["h2", "h3"]):
            h_text = clean_text(heading)
            if h_text in KNOWN_CATEGORIES:
                if not category:
                    category = h_text
                continue
            if h_text and len(h_text) >= 15:
                title = h_text
                break

        if not title:
            text = clean_text(a_tag)
            if text and text not in ("Lire la suite…", "Lire la suite", "…") and len(text) > 10:
                title = text

        if not title:
            continue  # Don't mark URL as seen — a later link may have the title

        if title in KNOWN_CATEGORIES:
            continue
        if len(title) < 15:
            continue

        # Mark URL as seen only once we have a valid article
        seen_urls.add(full_url)

        # Extract categories from link text spans
        for span in a_tag.find_all(string=True):
            txt = span.strip()
            if txt in KNOWN_CATEGORIES and txt != title:
                if category and txt not in category:
                    category += ", "
                    category += txt
                elif not category:
                    category = txt

        # Try to extract thumbnail image from the link block
        img_url = None
        img_tag = a_tag.find("img")
        if img_tag:
            src = img_tag.get("src") or img_tag.get("data-src", "")
            if src:
                img_url = urljoin(BASE_URL, src)

        articles.append({
            "url": full_url,
            "title": title,
            "category": category,
            "thumb_url": img_url,
            "is_pilet": full_url in pilet_urls,
        })

    print(f"     {len(articles)} articles trouvés.")
    return date_str, articles, dessin_info


def fetch_article(session: requests.Session, url: str,
                  fetch_images: bool = False) -> dict:
    """Fetch a single article's full content.

    The site uses Bricks Builder with this structure inside #brx-content:
      Section 0: Header (tags, title, author, date, image caption)
      Section 1: Article body (lead in brxe-text-basic, paragraphs in brxe-text)
      Section 2: Comments / subscription
      Section 3: "À lire aussi" (related articles)
    We only need sections 0 (metadata) and 1 (content).
    """
    resp = session.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    brx = soup.find(id="brx-content")
    if not brx:
        return {"url": url, "title": "", "author": "", "category": "",
                "lead": "", "content_html": "", "content_text": "",
                "image_url": None, "image_caption": None}

    sections = brx.find_all("section", class_="brxe-section", recursive=False)

    # ── Section 0: Header metadata ─────────────────────────────────────
    title = ""
    author = ""
    category = ""
    image_url = None
    image_caption = None

    if sections:
        sec0 = sections[0]

        # Title
        h1 = sec0.find(class_="brxe-heading")
        if h1:
            title = clean_text(h1)
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = clean_text(h1)

        # Author
        author_link = sec0.find("a", href=re.compile(r"/journaliste/"))
        if author_link:
            author = clean_text(author_link)

        # Category / tags
        tags_el = sec0.find(class_="brxe-post-taxonomy")
        if tags_el:
            tag_texts = [a.get_text(strip=True).lstrip("#")
                         for a in tags_el.find_all("a")]
            category = ", ".join(tag_texts[:3])

        # Hero image extraction
        # Strategy: og:image always points to the article hero (never
        # the author photo), so use it as primary source. HTML images
        # in sec0 serve as fallback, but we must skip author thumbnails
        # (class size-thumbnail, small NxN dimensions in filename).
        if fetch_images:
            # 1) Primary: og:image meta tag (most reliable)
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                image_url = og["content"]

            # 2) Fallback: find hero <img> in section 0, skip thumbnails
            if not image_url:
                for img_tag in sec0.find_all("img"):
                    src = img_tag.get("src") or img_tag.get("data-src", "")
                    if not src:
                        continue
                    cls = img_tag.get("class", [])
                    # Skip author thumbnails (class size-thumbnail)
                    if "size-thumbnail" in cls:
                        continue
                    # Skip small NxN images (e.g. 150x150 author avatars)
                    if re.search(r"-\d{2,3}x\d{2,3}\.", src):
                        continue
                    # Skip logos
                    if "logo" in src.lower():
                        continue
                    image_url = urljoin(BASE_URL, src)
                    break

            # 3) Try to find image caption
            if image_url:
                cap_el = sec0.find(class_=re.compile(
                    r"caption|credit|legend", re.IGNORECASE))
                if cap_el:
                    image_caption = clean_text(cap_el)

    # ── Publication date (for Pilet filtering) ───────────────────────
    pub_date = None
    date_meta = soup.find("meta", property="article:modified_time")
    if not date_meta:
        date_meta = soup.find("meta", property="article:published_time")
    if date_meta and date_meta.get("content"):
        try:
            pub_date = datetime.fromisoformat(
                date_meta["content"].replace("Z", "+00:00")
            ).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # ── Section 1: Article content ─────────────────────────────────────
    lead = ""
    paragraphs = []
    content_text = ""

    if len(sections) > 1:
        sec1 = sections[1]

        # Lead / chapô
        lead_el = sec1.find(class_="brxe-text-basic")
        if lead_el:
            lead = clean_text(lead_el)

        # Body paragraphs
        for text_div in sec1.find_all(class_="brxe-text"):
            for p in text_div.find_all(["p", "blockquote", "h2", "h3", "h4"]):
                text = clean_text(p)

                if not text or len(text) < 8:
                    continue
                if "©" in text:
                    continue

                # Skip "Lire l'article original" and source attribution boilerplate
                text_lower = text.lower()
                if any(pattern in text_lower for pattern in (
                    "lire l\u2019article original",
                    "lire l'article original",
                    "article publié sur",
                    "article paru sur",
                    "article paru initialement",
                    "publié initialement sur",
                    "publié originellement",
                )):
                    continue
                # Also skip paragraphs that are just an external link
                if p.name == "p":
                    link = p.find("a", href=True)
                    if link and "antithese" not in link.get("href", ""):
                        link_text = clean_text(link)
                        # If the whole paragraph is basically just the link
                        if link_text and len(link_text) >= len(text) * 0.85:
                            if any(k in text_lower for k in (
                                "lire l", "article original",
                                "source", "version originale",
                            )):
                                continue

                tag_name = p.name
                if tag_name == "blockquote":
                    paragraphs.append(
                        f'<blockquote><p class="quote">{text}</p></blockquote>')
                elif tag_name in ("h2", "h3", "h4"):
                    paragraphs.append(f"<{tag_name}>{text}</{tag_name}>")
                else:
                    # Detect bold sub-headings: <p> whose content is mostly <strong>/<b>
                    strongs = p.find_all(["strong", "b"])
                    if strongs:
                        strong_text = " ".join(clean_text(s) for s in strongs)
                        if (strong_text and len(strong_text) > 8
                                and len(strong_text) >= len(text) * 0.7):
                            paragraphs.append(f"<h3>{text}</h3>")
                            content_text += text + "\n\n"
                            continue
                    paragraphs.append(f"<p>{text}</p>")
                content_text += text + "\n\n"

    content_html = "\n".join(paragraphs)

    return {
        "url": url,
        "title": title,
        "author": author,
        "category": category,
        "lead": lead,
        "content_html": content_html,
        "content_text": content_text,
        "image_url": image_url,
        "image_caption": image_caption,
        "pub_date": pub_date,
    }


# ── PDF Generation (standard formats — enhanced with images) ──────────────
def generate_pdf(
    articles: list[dict],
    edition_title: str,
    date_str: str,
    fmt: str,
    output_path: Path,
    session: requests.Session | None = None,
    logo_light_uri: str | None = None,
    logo_dark_uri: str | None = None,
):
    """Generate an enhanced digest PDF using WeasyPrint.

    Includes: logo cover, hero images, numbered TOC, drop caps,
    decorative rules, colophon — all scaled to device dimensions.
    Single-column layout for readability on small screens.
    """
    from weasyprint import HTML

    profile = FORMATS[fmt]

    # ── Download article images ────────────────────────────────────────
    image_cache = {}
    if session:
        print(f"  🖼️  Téléchargement des images ({profile['label']})…")
        for i, art in enumerate(articles):
            img_url = art.get("image_url") or art.get("thumb_url")
            if img_url and img_url not in image_cache:
                hires_url = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
                data_uri = download_image_as_data_uri(session, hires_url)
                if not data_uri and hires_url != img_url:
                    data_uri = download_image_as_data_uri(session, img_url)
                if data_uri:
                    image_cache[img_url] = data_uri
                    image_cache[hires_url] = data_uri

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="art-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="art-author">Par {art["author"]}</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="art-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = image_cache.get(hires) or image_cache.get(img_url)
            if data_uri:
                cap = art.get("image_caption", "")
                cap_html = f'<div class="art-img-caption">{cap}</div>' if cap else ""
                image_html = f'''
                <div class="art-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        # Process body to add drop cap to first paragraph
        body_html = art.get("content_html", "")
        drop_cap_done = False
        if body_html:
            def add_drop_cap(match):
                nonlocal drop_cap_done
                if drop_cap_done:
                    return match.group(0)
                drop_cap_done = True
                inner = match.group(1)
                if inner:
                    first_char = inner[0]
                    rest = inner[1:]
                    return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
                return match.group(0)
            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap, body_html,
                               count=1, flags=re.DOTALL)

        articles_html += f"""
        <article class="art-article">
            {category_html}
            <h2 class="art-title">{art.get("title", "Sans titre")}</h2>
            {author_html}
            <div class="art-rule"></div>
            {image_html}
            {lead_html}
            <div class="article-body">
                {body_html}
            </div>
        </article>
        """

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_dark_uri:
        logo_html = f'''
        <div class="cover-banner">
            <img class="cover-logo" src="{logo_dark_uri}" alt="Antithèse" />
        </div>'''
    elif logo_light_uri:
        logo_html = f'<img class="cover-logo-light" src="{logo_light_uri}" alt="Antithèse" />'
    else:
        logo_html = '<div class="cover-title-fallback">ANTITHÈSE</div>'

    # ── Colophon logo ──────────────────────────────────────────────────
    if logo_light_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_light_uri}" alt="" />'
    elif logo_dark_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_dark_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles, 1):
        cat = (f'<span class="toc-cat">{art.get("category", "")}</span>'
               if art.get("category") else "")
        auth = (f'<span class="toc-author">{art.get("author", "")}</span>'
                if art.get("author") else "")
        toc_items += f"""
        <div class="toc-entry">
            <div class="toc-num">{idx:02d}</div>
            <div class="toc-details">
                {cat}
                <div class="toc-title">{art.get("title", "")}</div>
                {auth}
            </div>
        </div>"""

    # ── Cover highlights (first 3 articles) ────────────────────────────
    cover_highlights = ""
    for art in articles[:3]:
        cat_hl = (f'<div class="cover-hl-cat">{art.get("category", "")}</div>'
                  if art.get("category") else "")
        cover_highlights += f"""
        <div class="cover-hl">
            {cat_hl}
            <div class="cover-hl-title">{art.get("title", "")}</div>
        </div>"""

    # Shorthand
    p = profile

    # ── Full HTML document ─────────────────────────────────────────────
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       ANTITHÈSE — ÉDITION {p['label'].upper()}
       Mise en page enrichie (images, logo, sommaire, colophon)
       ================================================================ */

    @page {{
        size: {p["width_mm"]}mm {p["height_mm"]}mm;
        margin: {p["margin"]};
        @bottom-center {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 6.5pt;
            color: #aaa;
        }}
    }}

    @page :first {{
        margin: 0;
        @bottom-center {{ content: none; }}
    }}

    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: {p["font_size"]};
        line-height: {p["line_height"]};
        color: #1a1a1a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
        orphans: 2;
        widows: 2;
    }}

    /* ════════════════════════════════════════════════════════════════
       COVER PAGE
       ════════════════════════════════════════════════════════════════ */
    .cover {{
        page-break-after: always;
        width: {p["width_mm"]}mm;
        height: {p["height_mm"]}mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        background: #faf9f7;
        padding: {p["cover_padding"]};
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: {p["margin"]};
        left: {p["margin"]};
        right: {p["margin"]};
        height: 0.6pt;
        background: #1a1a1a;
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: {p["margin"]};
        left: {p["margin"]};
        right: {p["margin"]};
        height: 0.6pt;
        background: #1a1a1a;
    }}

    .cover-banner {{
        background: #1a1a1a;
        padding: {p["banner_padding"]};
        margin-bottom: 4mm;
        width: {p["banner_width"]};
        text-align: center;
    }}

    .cover-banner .cover-logo {{
        width: {p["logo_width"]};
        height: auto;
    }}

    .cover-logo-light {{
        width: {p["logo_width"]};
        height: auto;
        margin-bottom: 3mm;
    }}

    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["h1_size"]};
        font-weight: 700;
        letter-spacing: 0.1em;
        color: #1a1a1a;
        margin-bottom: 2mm;
        text-transform: uppercase;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["cover_subtitle_size"]};
        font-style: italic;
        color: #666;
        letter-spacing: 0.04em;
        margin-bottom: 5mm;
    }}

    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["cover_edition_size"]};
        font-weight: 600;
        color: #333;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 1.5mm 5mm;
        border-top: 0.4pt solid #1a1a1a;
        border-bottom: 0.4pt solid #1a1a1a;
        margin-bottom: 6mm;
    }}

    .cover-tagline {{
        font-size: {p["cover_hl_author_size"]};
        color: #888;
        font-style: italic;
        margin-bottom: 5mm;
    }}

    .cover-highlights {{
        margin-top: 3mm;
        text-align: left;
        width: 100%;
    }}

    .cover-hl {{
        margin-bottom: 2.5mm;
        padding-bottom: 2.5mm;
        border-bottom: 0.3pt solid #ccc;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["cover_hl_cat_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #999;
        margin-bottom: 0.5mm;
    }}
    .cover-hl-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["cover_hl_title_size"]};
        font-weight: 700;
        line-height: 1.25;
        color: #1a1a1a;
    }}

    /* ════════════════════════════════════════════════════════════════
       TABLE OF CONTENTS
       ════════════════════════════════════════════════════════════════ */
    .toc-page {{
        page-break-after: always;
        padding-top: 2mm;
    }}

    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_cat_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: #999;
        margin-bottom: 4mm;
        padding-bottom: 1.5mm;
        border-bottom: 0.6pt solid #1a1a1a;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 2.5mm;
        padding-bottom: 2.5mm;
        border-bottom: 0.25pt solid #e0e0e0;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_num_size"]};
        font-weight: 300;
        color: #ccc;
        min-width: {p["toc_num_width"]};
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
    }}

    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_cat_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #999;
        display: block;
        margin-bottom: 0.3mm;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["toc_title_size"]};
        font-weight: 700;
        line-height: 1.3;
        color: #1a1a1a;
    }}

    .toc-author {{
        font-size: {p["toc_author_size"]};
        font-style: italic;
        color: #777;
        display: block;
        margin-top: 0.3mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .art-article {{
        page-break-before: always;
    }}

    .art-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_cat_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #888;
        margin-bottom: 2mm;
    }}

    .art-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["h2_size"]};
        font-weight: 700;
        line-height: 1.2;
        color: #1a1a1a;
        margin-bottom: 2mm;
        letter-spacing: -0.01em;
    }}

    .art-author {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["toc_author_size"]};
        font-style: italic;
        color: #666;
        margin-bottom: 2.5mm;
    }}

    .art-rule {{
        height: 0.4pt;
        background: #ccc;
        margin-bottom: 3mm;
    }}

    .art-hero-img {{
        margin-bottom: 3mm;
        text-align: center;
    }}
    .art-hero-img img {{
        width: 100%;
        height: auto;
        max-height: {p["img_max_height"]};
        object-fit: cover;
        display: block;
    }}
    .art-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["caption_size"]};
        color: #999;
        font-style: italic;
        margin-top: 1mm;
        text-align: right;
    }}

    .art-lead {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["font_size"]};
        font-weight: 600;
        line-height: 1.35;
        color: #333;
        margin-bottom: 3mm;
        padding-bottom: 2.5mm;
        border-bottom: 0.25pt solid #ddd;
    }}

    /* Single-column body (readability first) */
    .article-body {{
        font-size: {p["font_size"]};
        line-height: {p["line_height"]};
    }}

    .article-body p {{
        margin-bottom: 0.5em;
        text-indent: 1em;
    }}
    .article-body p:first-child {{
        text-indent: 0;
    }}

    /* Drop cap */
    .drop-cap {{
        float: left;
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {p["drop_cap_size"]};
        line-height: 0.78;
        padding-right: {p["drop_cap_padding"]};
        padding-top: 1mm;
        color: #1a1a1a;
        font-weight: 700;
    }}

    .article-body h2, .article-body h3, .article-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["h3_size"]};
        font-weight: 700;
        margin-top: 1em;
        margin-bottom: 0.4em;
        text-indent: 0;
        color: #333;
    }}

    blockquote {{
        margin: 0.7em 0;
        padding: 0.4em 0.7em;
        border-left: 2pt solid #d0d0d0;
        color: #444;
        font-style: italic;
        font-size: {p["font_size"]};
        background: #faf9f7;
    }}
    blockquote p {{
        text-indent: 0 !important;
        margin-bottom: 0.3em;
    }}

    /* ════════════════════════════════════════════════════════════════
       COLOPHON
       ════════════════════════════════════════════════════════════════ */
    .colophon {{
        page-break-before: always;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        height: 100%;
    }}

    .colophon-logo {{
        width: {p["colophon_logo_width"]};
        height: auto;
        margin-bottom: 4mm;
        opacity: 0.4;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["colophon_font_size"]};
        color: #aaa;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 20mm;
        height: 0.4pt;
        background: #ccc;
        margin: 4mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>

    <div class="cover-highlights">
        {cover_highlights}
    </div>
</div>

<!-- ═══════════ TABLE OF CONTENTS ═══════════ -->
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    {toc_items}
</div>

<!-- ═══════════ ARTICLES ═══════════ -->
{articles_html}

<!-- ═══════════ COLOPHON ═══════════ -->
<div class="colophon">
    {colophon_logo}
    <div class="colophon-text">
        Antithèse — Bon pour la tête<br/>
        <em>Un média indépendant et a-partisan</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        antithese.info<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    print(f"  📄 Génération PDF ({profile['label']})…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ── PDF Generation (A4 Premium — New Yorker style) ────────────────────────
def generate_premium_pdf(
    articles: list[dict],
    edition_title: str,
    date_str: str,
    output_path: Path,
    session: requests.Session,
    logo_light_uri: str | None = None,
    logo_dark_uri: str | None = None,
    dessin_info: dict | None = None,
):
    """Generate a premium A4 magazine-style PDF with images and rich layout.

    Design philosophy inspired by The New Yorker:
    - Elegant serif typography with generous leading
    - Drop caps on article openings
    - Two-column body text
    - Full-width hero images with subtle captions
    - Thin decorative rules as separators
    - Small-caps categories, italic bylines
    - Restrained color palette (near-black + warm gray)

    logo_light_uri: SVG with whites → dark (for light backgrounds)
    logo_dark_uri:  original SVG with white text (for dark banner on cover)
    """
    from weasyprint import HTML

    print("  🎨 Préparation de l'édition premium A4…")

    # ── Download images for articles ───────────────────────────────────
    print("  🖼️  Téléchargement des images…")
    image_cache = {}
    for i, art in enumerate(articles):
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url and img_url not in image_cache:
            # Try to get the highest-resolution version
            # WP thumbnails often have -NNNxNNN before extension; strip it
            hires_url = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = download_image_as_data_uri(session, hires_url)
            if not data_uri and hires_url != img_url:
                data_uri = download_image_as_data_uri(session, img_url)
            if data_uri:
                image_cache[img_url] = data_uri
                image_cache[hires_url] = data_uri
        img_status = "✓" if (img_url and (img_url in image_cache or
                              re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url) in image_cache)) else "—"
        print(f"     [{i+1}/{len(articles)}] {img_status} {art.get('title', '')[:55]}…")

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="pm-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="pm-author">Par {art["author"]}</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="pm-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = image_cache.get(hires) or image_cache.get(img_url)
            if data_uri:
                cap = art.get("image_caption", "")
                cap_html = f'<div class="pm-img-caption">{cap}</div>' if cap else ""
                image_html = f'''
                <div class="pm-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        # Process body to add drop cap to first paragraph
        body_html = art.get("content_html", "")
        drop_cap_done = False
        if body_html:
            def add_drop_cap(match):
                nonlocal drop_cap_done
                if drop_cap_done:
                    return match.group(0)
                drop_cap_done = True
                inner = match.group(1)
                if inner:
                    first_char = inner[0]
                    rest = inner[1:]
                    return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
                return match.group(0)

            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap, body_html, count=1, flags=re.DOTALL)

        articles_html += f"""
        <article class="pm-article" id="art-{i}">
            {category_html}
            <h2 class="pm-title">{art.get("title", "Sans titre")}</h2>
            {author_html}
            <div class="pm-rule-thin"></div>
            {image_html}
            {lead_html}
            <div class="pm-body">
                {body_html}
            </div>
        </article>
        """

    # ── Cover logo: dark banner with original (white+red) logo ──────────
    if logo_dark_uri:
        logo_html = f'''
        <div class="cover-banner">
            <img class="cover-logo" src="{logo_dark_uri}" alt="Antithèse" />
        </div>'''
    elif logo_light_uri:
        # Fallback: light-bg version without banner
        logo_html = f'<img class="cover-logo-light" src="{logo_light_uri}" alt="Antithèse" />'
    else:
        logo_html = '<h1 class="cover-title-fallback">ANTITHÈSE</h1>'

    # Colophon uses the light-background version (dark text on light bg)
    if logo_light_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_light_uri}" alt="" />'
    elif logo_dark_uri:
        # Fallback: original on light bg (partially invisible but better than nothing)
        colophon_logo = f'<img class="colophon-logo" src="{logo_dark_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles):
        cat = f'<span class="toc-cat">{art.get("category", "")}</span>' if art.get("category") else ""
        auth = f'<span class="toc-author">{art.get("author", "")}</span>' if art.get("author") else ""
        toc_items += f"""
        <a class="toc-entry" href="#art-{idx}">
            <span class="toc-details">
                {cat}
                <span class="toc-title">{art.get("title", "")}</span>
                {auth}
            </span>
        </a>"""

    # ── Cover content: dessin de la semaine OR article highlights ────
    cover_content = ""
    if dessin_info:
        # Download the dessin image
        dessin_uri = download_image_as_data_uri(session, dessin_info["image_url"])
        if not dessin_uri and dessin_info.get("image_url_fallback"):
            dessin_uri = download_image_as_data_uri(session, dessin_info["image_url_fallback"])
        if dessin_uri:
            dessin_title_html = ""
            if dessin_info.get("title"):
                dessin_title_html = f'<div class="cover-dessin-title">{dessin_info["title"]}</div>'
            dessin_artist_html = ""
            if dessin_info.get("artist"):
                dessin_artist_html = f'<div class="cover-dessin-artist">{dessin_info["artist"]}</div>'
            cover_content = f"""
    <div class="cover-dessin">
        <div class="cover-dessin-label">Le dessin de la semaine</div>
        <img class="cover-dessin-img" src="{dessin_uri}" alt="" />
        {dessin_title_html}
        {dessin_artist_html}
    </div>"""
            print(f"     ↳ Dessin de la semaine en couverture")

    if not cover_content:
        # Fallback: first 4 articles with thumbnails
        cover_content = '<div class="cover-highlights">'
        for art in articles[:4]:
            cat_hl = f'<div class="cover-hl-cat">{art.get("category", "")}</div>' if art.get("category") else ""
            auth_hl = f'<div class="cover-hl-author">{art.get("author", "")}</div>' if art.get("author") else ""

            thumb_html = ""
            img_url = art.get("image_url") or art.get("thumb_url")
            if img_url:
                hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
                data_uri = image_cache.get(hires) or image_cache.get(img_url)
                if data_uri:
                    thumb_html = f'<img class="cover-hl-thumb" src="{data_uri}" alt="" />'

            cover_content += f"""
        <div class="cover-hl">
            {thumb_html}
            <div class="cover-hl-text">
                {cat_hl}
                <div class="cover-hl-title">{art.get("title", "")}</div>
                {auth_hl}
            </div>
        </div>"""
        cover_content += "\n    </div>"

    # ── Full HTML document ─────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       ANTITHÈSE — ÉDITION PREMIUM A4
       Mise en page inspirée du New Yorker
       ================================================================ */

    @page {{
        size: 210mm 297mm;
        margin: 22mm 25mm 25mm 25mm;

        @bottom-right {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 8pt;
            color: #999;
        }}
    }}

    @page :first {{
        margin: 0;
        @bottom-right {{ content: none; }}
    }}

    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, "Times New Roman", serif;
        font-size: 10pt;
        line-height: 1.55;
        color: #1a1a1a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
        orphans: 3;
        widows: 3;
    }}

    /* ════════════════════════════════════════════════════════════════
       COVER PAGE
       ════════════════════════════════════════════════════════════════ */
    .cover {{
        page-break-after: always;
        width: 210mm;
        height: 297mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        background: #faf9f7;
        padding: 30mm 25mm;
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: 20mm;
        left: 25mm;
        right: 25mm;
        height: 0.8pt;
        background: #1a1a1a;
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: 20mm;
        left: 25mm;
        right: 25mm;
        height: 0.8pt;
        background: #1a1a1a;
    }}

    /* Dark banner behind logo (original white+red SVG) */
    .cover-banner {{
        background: #1a1a1a;
        padding: 6mm 10mm;
        margin-bottom: 8mm;
        width: 80mm;
        text-align: center;
    }}

    .cover-banner .cover-logo {{
        width: 55mm;
        height: auto;
    }}

    /* Light-bg version (fallback: no banner, dark text on light bg) */
    .cover-logo-light {{
        width: 55mm;
        height: auto;
        margin-bottom: 6mm;
    }}

    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 36pt;
        font-weight: 700;
        letter-spacing: 0.12em;
        color: #1a1a1a;
        margin-bottom: 2mm;
        text-transform: uppercase;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 12pt;
        font-style: italic;
        color: #666;
        letter-spacing: 0.06em;
        margin-bottom: 10mm;
    }}

    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt;
        font-weight: 600;
        color: #333;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        padding: 2.5mm 8mm;
        border-top: 0.5pt solid #1a1a1a;
        border-bottom: 0.5pt solid #1a1a1a;
        margin-bottom: 14mm;
    }}

    .cover-tagline {{
        font-size: 9pt;
        color: #888;
        font-style: italic;
        margin-bottom: 10mm;
    }}

    .cover-highlights {{
        margin-top: 8mm;
        text-align: left;
        max-width: 140mm;
    }}

    .cover-hl {{
        display: flex;
        align-items: center;
        gap: 4mm;
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #ccc;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-thumb {{
        width: 22mm;
        height: 16mm;
        object-fit: cover;
        flex-shrink: 0;
    }}

    .cover-hl-text {{
        flex: 1;
        min-width: 0;
    }}

    .cover-hl-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #999;
        margin-bottom: 1mm;
    }}
    .cover-hl-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.25;
        color: #1a1a1a;
    }}
    .cover-hl-author {{
        font-size: 8pt;
        font-style: italic;
        color: #777;
        margin-top: 1mm;
    }}

    /* ── Cover: Dessin de la semaine ── */
    .cover-dessin {{
        margin-top: 6mm;
        text-align: center;
    }}
    .cover-dessin-label {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #999;
        margin-bottom: 4mm;
    }}
    .cover-dessin-img {{
        max-width: 120mm;
        max-height: 120mm;
        width: auto;
        height: auto;
        object-fit: contain;
    }}
    .cover-dessin-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 10pt;
        font-weight: 700;
        color: #1a1a1a;
        margin-top: 3mm;
        line-height: 1.3;
    }}
    .cover-dessin-artist {{
        font-size: 8pt;
        font-style: italic;
        color: #777;
        margin-top: 1mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       TABLE OF CONTENTS
       ════════════════════════════════════════════════════════════════ */
    .toc-page {{
        page-break-after: always;
        padding-top: 5mm;
    }}

    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: #999;
        margin-bottom: 6mm;
        padding-bottom: 2mm;
        border-bottom: 0.8pt solid #1a1a1a;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
        text-decoration: none;
        color: inherit;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-entry::before {{
        content: target-counter(attr(href), page);
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt;
        font-weight: 300;
        color: #555;
        min-width: 12mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
        display: block;
    }}

    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #999;
        display: block;
        margin-bottom: 0.5mm;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.3;
        color: #1a1a1a;
        display: block;
    }}

    .toc-author {{
        font-size: 8.5pt;
        font-style: italic;
        color: #777;
        display: block;
        margin-top: 0.5mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .pm-article {{
        page-break-before: always;
    }}

    .pm-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #888;
        margin-bottom: 3mm;
    }}

    .pm-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 22pt;
        font-weight: 700;
        line-height: 1.15;
        color: #1a1a1a;
        margin-bottom: 3mm;
        letter-spacing: -0.01em;
    }}

    .pm-author {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 9pt;
        font-style: italic;
        color: #666;
        margin-bottom: 4mm;
    }}

    .pm-rule-thin {{
        height: 0.5pt;
        background: #ccc;
        margin-bottom: 5mm;
    }}

    .pm-hero-img {{
        margin-bottom: 5mm;
        text-align: center;
    }}
    .pm-hero-img img {{
        width: 100%;
        height: auto;
        max-height: 85mm;
        object-fit: cover;
        display: block;
    }}
    .pm-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        color: #999;
        font-style: italic;
        margin-top: 1.5mm;
        text-align: right;
    }}

    .pm-lead {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 600;
        line-height: 1.4;
        color: #333;
        margin-bottom: 5mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #ddd;
    }}

    /* Two-column body */
    .pm-body {{
        column-count: 2;
        column-gap: 7mm;
        column-rule: 0.3pt solid #e5e5e5;
        font-size: 9.5pt;
        line-height: 1.55;
    }}

    .pm-body p {{
        margin-bottom: 0.5em;
        text-indent: 1.2em;
    }}
    .pm-body p:first-child {{
        text-indent: 0;
    }}

    /* Drop cap */
    .drop-cap {{
        float: left;
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 42pt;
        line-height: 0.75;
        padding-right: 2mm;
        padding-top: 2mm;
        color: #1a1a1a;
        font-weight: 700;
    }}

    .pm-body h2, .pm-body h3, .pm-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 10pt;
        font-weight: 700;
        margin-top: 1em;
        margin-bottom: 0.4em;
        text-indent: 0;
        column-span: none;
        color: #333;
    }}

    .pm-body blockquote {{
        margin: 0.8em 0;
        padding: 0.5em 0.8em;
        border-left: 2.5pt solid #d0d0d0;
        color: #444;
        font-style: italic;
        font-size: 9.5pt;
        background: #faf9f7;
    }}
    .pm-body blockquote p {{
        text-indent: 0 !important;
        margin-bottom: 0.3em;
    }}

    /* ════════════════════════════════════════════════════════════════
       COLOPHON
       ════════════════════════════════════════════════════════════════ */
    .colophon {{
        page-break-before: always;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        height: 100%;
    }}

    .colophon-logo {{
        width: 35mm;
        height: auto;
        margin-bottom: 8mm;
        opacity: 0.4;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #aaa;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 30mm;
        height: 0.5pt;
        background: #ccc;
        margin: 6mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>

    {cover_content}
</div>

<!-- ═══════════ TABLE OF CONTENTS ═══════════ -->
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    {toc_items}
</div>

<!-- ═══════════ ARTICLES ═══════════ -->
{articles_html}

<!-- ═══════════ COLOPHON ═══════════ -->
<div class="colophon">
    {colophon_logo}
    <div class="colophon-text">
        Antithèse — Bon pour la tête<br/>
        <em>Un média indépendant et a-partisan</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        antithese.info<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    print(f"  📄 Génération PDF (🖨️  A4 Premium)…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ── PDF Generation (A4 Éditorial — single-column contemporary style) ───────
def generate_editorial_pdf(
    articles: list[dict],
    edition_title: str,
    date_str: str,
    output_path: Path,
    session: requests.Session,
    logo_light_uri: str | None = None,
    logo_dark_uri: str | None = None,
    dessin_info: dict | None = None,
):
    """Generate a single-column A4 editorial PDF with generous white space.

    Design philosophy inspired by Kinfolk / Cereal / Apartamento:
    - Single-column body text with wide margins for a luxurious feel
    - Large serif typography with generous leading (1.7)
    - Ample breathing room between elements
    - Full-width hero images with subtle captions
    - Refined pull quotes (centered, thin rules above/below)
    - Drop caps with modern proportions
    - Minimal, elegant cover with strong typographic hierarchy
    - Warm, restrained palette (charcoal + warm grays)
    """
    from weasyprint import HTML

    print("  🎨 Préparation de l'édition éditoriale A4…")

    # ── Download images for articles ───────────────────────────────────
    print("  🖼️  Téléchargement des images…")
    image_cache = {}
    for i, art in enumerate(articles):
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url and img_url not in image_cache:
            hires_url = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = download_image_as_data_uri(session, hires_url)
            if not data_uri and hires_url != img_url:
                data_uri = download_image_as_data_uri(session, img_url)
            if data_uri:
                image_cache[img_url] = data_uri
                image_cache[hires_url] = data_uri
        img_status = "✓" if (img_url and (img_url in image_cache or
                              re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url) in image_cache)) else "—"
        print(f"     [{i+1}/{len(articles)}] {img_status} {art.get('title', '')[:55]}…")

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="ed-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="ed-author">{art["author"]}</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="ed-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = image_cache.get(hires) or image_cache.get(img_url)
            if data_uri:
                cap = art.get("image_caption", "")
                cap_html = f'<div class="ed-img-caption">{cap}</div>' if cap else ""
                image_html = f'''
                <div class="ed-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        # Process body to add drop cap to first paragraph
        body_html = art.get("content_html", "")
        drop_cap_done = False
        if body_html:
            def add_drop_cap(match):
                nonlocal drop_cap_done
                if drop_cap_done:
                    return match.group(0)
                drop_cap_done = True
                inner = match.group(1)
                if inner:
                    first_char = inner[0]
                    rest = inner[1:]
                    return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
                return match.group(0)

            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap, body_html, count=1, flags=re.DOTALL)

        articles_html += f"""
        <article class="ed-article" id="art-{i}">
            <div class="ed-article-header">
                {category_html}
                <h2 class="ed-title">{art.get("title", "Sans titre")}</h2>
                {author_html}
            </div>
            <div class="ed-rule"></div>
            {image_html}
            {lead_html}
            <div class="ed-body">
                {body_html}
            </div>
            <div class="ed-article-end">&#9830;</div>
        </article>
        """

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_dark_uri:
        logo_html = f'''
        <div class="cover-banner">
            <img class="cover-logo" src="{logo_dark_uri}" alt="Antithèse" />
        </div>'''
    elif logo_light_uri:
        logo_html = f'<img class="cover-logo-light" src="{logo_light_uri}" alt="Antithèse" />'
    else:
        logo_html = '<h1 class="cover-title-fallback">ANTITHÈSE</h1>'

    # Colophon logo
    if logo_light_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_light_uri}" alt="" />'
    elif logo_dark_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_dark_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles):
        cat = f'<span class="toc-cat">{art.get("category", "")}</span>' if art.get("category") else ""
        auth = f'<span class="toc-author">{art.get("author", "")}</span>' if art.get("author") else ""
        toc_items += f"""
        <a class="toc-entry" href="#art-{idx}">
            <span class="toc-details">
                {cat}
                <span class="toc-title">{art.get("title", "")}</span>
                {auth}
            </span>
        </a>"""

    # ── Cover content: dessin or featured article ─────────────────────
    cover_content = ""
    if dessin_info:
        dessin_uri = download_image_as_data_uri(session, dessin_info["image_url"])
        if not dessin_uri and dessin_info.get("image_url_fallback"):
            dessin_uri = download_image_as_data_uri(session, dessin_info["image_url_fallback"])
        if dessin_uri:
            dessin_title_html = ""
            if dessin_info.get("title"):
                dessin_title_html = f'<div class="cover-dessin-title">{dessin_info["title"]}</div>'
            dessin_artist_html = ""
            if dessin_info.get("artist"):
                dessin_artist_html = f'<div class="cover-dessin-artist">{dessin_info["artist"]}</div>'
            cover_content = f"""
    <div class="cover-dessin">
        <div class="cover-dessin-label">Le dessin de la semaine</div>
        <img class="cover-dessin-img" src="{dessin_uri}" alt="" />
        {dessin_title_html}
        {dessin_artist_html}
    </div>"""
            print(f"     ↳ Dessin de la semaine en couverture")

    if not cover_content:
        # Minimal cover: just the first article title as featured
        if articles:
            feat = articles[0]
            feat_cat = f'<div class="cover-feat-cat">{feat.get("category", "")}</div>' if feat.get("category") else ""
            feat_auth = f'<div class="cover-feat-author">{feat.get("author", "")}</div>' if feat.get("author") else ""
            # Try to get the featured image
            feat_img_html = ""
            feat_img_url = feat.get("image_url") or feat.get("thumb_url")
            if feat_img_url:
                hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", feat_img_url)
                data_uri = image_cache.get(hires) or image_cache.get(feat_img_url)
                if data_uri:
                    feat_img_html = f'<img class="cover-feat-img" src="{data_uri}" alt="" />'
            cover_content = f"""
    <div class="cover-featured">
        {feat_img_html}
        {feat_cat}
        <div class="cover-feat-title">{feat.get("title", "")}</div>
        {feat_auth}
    </div>"""

    # ── Full HTML document ─────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       ANTITHÈSE — ÉDITION ÉDITORIALE A4
       Mise en page une colonne, inspiration Kinfolk / Cereal
       ================================================================ */

    @page {{
        size: 210mm 297mm;
        margin: 28mm 30mm 30mm 30mm;

        @bottom-center {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 7pt;
            color: #b0b0b0;
            letter-spacing: 0.1em;
        }}
    }}

    @page :first {{
        margin: 0;
        @bottom-center {{ content: none; }}
    }}

    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, "Times New Roman", serif;
        font-size: 11pt;
        line-height: 1.7;
        color: #2a2a2a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
        orphans: 3;
        widows: 3;
    }}

    /* ════════════════════════════════════════════════════════════════
       COVER PAGE — Minimal, airy, typographic
       ════════════════════════════════════════════════════════════════ */
    .cover {{
        page-break-after: always;
        width: 210mm;
        height: 297mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        background: #ffffff;
        padding: 35mm 30mm;
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: 22mm;
        left: 30mm;
        right: 30mm;
        height: 0.5pt;
        background: #2a2a2a;
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: 22mm;
        left: 30mm;
        right: 30mm;
        height: 0.5pt;
        background: #2a2a2a;
    }}

    .cover-banner {{
        background: #2a2a2a;
        padding: 6mm 10mm;
        margin-bottom: 12mm;
        width: 80mm;
        text-align: center;
    }}

    .cover-banner .cover-logo {{
        width: 55mm;
        height: auto;
    }}

    .cover-logo-light {{
        width: 55mm;
        height: auto;
        margin-bottom: 10mm;
    }}

    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 36pt;
        font-weight: 700;
        letter-spacing: 0.15em;
        color: #2a2a2a;
        margin-bottom: 3mm;
        text-transform: uppercase;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-style: italic;
        color: #888;
        letter-spacing: 0.08em;
        margin-bottom: 14mm;
    }}

    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        font-weight: 400;
        color: #555;
        text-transform: uppercase;
        letter-spacing: 0.25em;
        padding: 3mm 10mm;
        border-top: 0.4pt solid #2a2a2a;
        border-bottom: 0.4pt solid #2a2a2a;
        margin-bottom: 18mm;
    }}

    .cover-tagline {{
        font-size: 8.5pt;
        color: #aaa;
        font-style: italic;
        letter-spacing: 0.05em;
        margin-bottom: 14mm;
    }}

    /* ── Cover: Featured article (minimal) ── */
    .cover-featured {{
        margin-top: 6mm;
        text-align: center;
        max-width: 130mm;
    }}

    .cover-feat-img {{
        max-width: 110mm;
        max-height: 80mm;
        width: auto;
        height: auto;
        object-fit: contain;
        margin-bottom: 6mm;
    }}

    .cover-feat-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: #aaa;
        margin-bottom: 3mm;
    }}

    .cover-feat-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 16pt;
        font-weight: 700;
        line-height: 1.25;
        color: #2a2a2a;
        margin-bottom: 3mm;
    }}

    .cover-feat-author {{
        font-size: 9pt;
        font-style: italic;
        color: #999;
    }}

    /* ── Cover: Dessin de la semaine ── */
    .cover-dessin {{
        margin-top: 6mm;
        text-align: center;
    }}
    .cover-dessin-label {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: #aaa;
        margin-bottom: 5mm;
    }}
    .cover-dessin-img {{
        max-width: 115mm;
        max-height: 115mm;
        width: auto;
        height: auto;
        object-fit: contain;
    }}
    .cover-dessin-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 10pt;
        font-weight: 700;
        color: #2a2a2a;
        margin-top: 4mm;
        line-height: 1.3;
    }}
    .cover-dessin-artist {{
        font-size: 8pt;
        font-style: italic;
        color: #999;
        margin-top: 1mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       TABLE OF CONTENTS — Clean, spacious
       ════════════════════════════════════════════════════════════════ */
    .toc-page {{
        page-break-after: always;
        padding-top: 8mm;
    }}

    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 400;
        text-transform: uppercase;
        letter-spacing: 0.3em;
        color: #aaa;
        margin-bottom: 10mm;
        padding-bottom: 3mm;
        border-bottom: 0.5pt solid #2a2a2a;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 5mm;
        padding-bottom: 5mm;
        border-bottom: 0.25pt solid #e8e8e8;
        text-decoration: none;
        color: inherit;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-entry::before {{
        content: target-counter(attr(href), page);
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 16pt;
        font-weight: 300;
        color: #ccc;
        min-width: 14mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
        display: block;
    }}

    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 6.5pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #b0b0b0;
        display: block;
        margin-bottom: 1mm;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.3;
        color: #2a2a2a;
        display: block;
    }}

    .toc-author {{
        font-size: 8.5pt;
        font-style: italic;
        color: #999;
        display: block;
        margin-top: 1mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES — Single column, generous spacing
       ════════════════════════════════════════════════════════════════ */
    .ed-article {{
        page-break-before: always;
    }}

    .ed-article-header {{
        text-align: center;
        margin-bottom: 6mm;
    }}

    .ed-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.25em;
        color: #b0b0b0;
        margin-bottom: 5mm;
    }}

    .ed-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 26pt;
        font-weight: 700;
        line-height: 1.15;
        color: #2a2a2a;
        margin-bottom: 5mm;
        letter-spacing: -0.02em;
    }}

    .ed-author {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8.5pt;
        font-weight: 400;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #999;
    }}

    .ed-rule {{
        width: 30mm;
        height: 0.5pt;
        background: #2a2a2a;
        margin: 0 auto 7mm auto;
    }}

    .ed-hero-img {{
        margin-bottom: 7mm;
        text-align: center;
    }}
    .ed-hero-img img {{
        width: 100%;
        height: auto;
        max-height: 100mm;
        object-fit: cover;
        display: block;
    }}
    .ed-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        color: #b0b0b0;
        font-style: italic;
        margin-top: 2mm;
        text-align: right;
    }}

    .ed-lead {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 12pt;
        font-weight: 400;
        font-style: italic;
        line-height: 1.5;
        color: #555;
        margin-bottom: 7mm;
        padding-bottom: 5mm;
        border-bottom: 0.25pt solid #ddd;
        text-align: center;
    }}

    /* Single-column body — generous line-height for readability */
    .ed-body {{
        font-size: 11pt;
        line-height: 1.7;
    }}

    .ed-body p {{
        margin-bottom: 0.6em;
        text-indent: 1.5em;
    }}
    .ed-body p:first-child {{
        text-indent: 0;
    }}

    /* Drop cap — refined, modern proportions */
    .drop-cap {{
        float: left;
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 48pt;
        line-height: 0.72;
        padding-right: 2.5mm;
        padding-top: 2.5mm;
        color: #2a2a2a;
        font-weight: 700;
    }}

    .ed-body h2, .ed-body h3, .ed-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt;
        font-weight: 700;
        margin-top: 1.5em;
        margin-bottom: 0.5em;
        text-indent: 0;
        color: #2a2a2a;
        letter-spacing: 0.02em;
    }}

    /* Pull quote style — centered, elegant */
    .ed-body blockquote {{
        margin: 1.5em 10mm;
        padding: 1em 0;
        border-left: none;
        border-top: 0.5pt solid #ccc;
        border-bottom: 0.5pt solid #ccc;
        color: #555;
        font-style: italic;
        font-size: 12pt;
        line-height: 1.5;
        text-align: center;
    }}
    .ed-body blockquote p {{
        text-indent: 0 !important;
        margin-bottom: 0.3em;
    }}

    /* Article end mark */
    .ed-article-end {{
        text-align: center;
        margin-top: 8mm;
        font-size: 8pt;
        color: #ccc;
        letter-spacing: 0.3em;
    }}

    /* ════════════════════════════════════════════════════════════════
       COLOPHON — Minimal
       ════════════════════════════════════════════════════════════════ */
    .colophon {{
        page-break-before: always;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        height: 100%;
    }}

    .colophon-logo {{
        width: 30mm;
        height: auto;
        margin-bottom: 10mm;
        opacity: 0.3;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #b0b0b0;
        line-height: 2;
        letter-spacing: 0.05em;
    }}

    .colophon-rule {{
        width: 25mm;
        height: 0.4pt;
        background: #ddd;
        margin: 8mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>

    {cover_content}
</div>

<!-- ═══════════ TABLE OF CONTENTS ═══════════ -->
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    {toc_items}
</div>

<!-- ═══════════ ARTICLES ═══════════ -->
{articles_html}

<!-- ═══════════ COLOPHON ═══════════ -->
<div class="colophon">
    {colophon_logo}
    <div class="colophon-text">
        Antithèse — Bon pour la tête<br/>
        <em>Un média indépendant et a-partisan</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        antithese.info<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    print(f"  📄 Génération PDF (🖨️  A4 Éditorial)…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ── PDF Generation (A4 Premium Paysage — 3-column landscape) ──────────────
def generate_premium_landscape_pdf(
    articles: list[dict],
    edition_title: str,
    date_str: str,
    output_path: Path,
    session: requests.Session,
    logo_light_uri: str | None = None,
    logo_dark_uri: str | None = None,
    dessin_info: dict | None = None,
):
    """Generate a premium A4 landscape magazine-style PDF with 3-column layout.

    Same content as generate_premium_pdf but adapted for landscape A4:
    - 297×210mm landscape page
    - Three-column body text
    - Wider cover with two-column highlights
    - Three-column table of contents
    """
    from weasyprint import HTML

    print("  🎨 Préparation de l'édition A4 Premium Paysage…")

    # ── Download images for articles ───────────────────────────────────
    print("  🖼️  Téléchargement des images…")
    image_cache = {}
    for i, art in enumerate(articles):
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url and img_url not in image_cache:
            # Try to get the highest-resolution version
            # WP thumbnails often have -NNNxNNN before extension; strip it
            hires_url = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = download_image_as_data_uri(session, hires_url)
            if not data_uri and hires_url != img_url:
                data_uri = download_image_as_data_uri(session, img_url)
            if data_uri:
                image_cache[img_url] = data_uri
                image_cache[hires_url] = data_uri
        img_status = "✓" if (img_url and (img_url in image_cache or
                              re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url) in image_cache)) else "—"
        print(f"     [{i+1}/{len(articles)}] {img_status} {art.get('title', '')[:55]}…")

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="pm-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="pm-author">Par {art["author"]}</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="pm-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = image_cache.get(hires) or image_cache.get(img_url)
            if data_uri:
                cap = art.get("image_caption", "")
                cap_html = f'<div class="pm-img-caption">{cap}</div>' if cap else ""
                image_html = f'''
                <div class="pm-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        # Process body to add drop cap to first paragraph
        body_html = art.get("content_html", "")
        drop_cap_done = False
        if body_html:
            def add_drop_cap(match):
                nonlocal drop_cap_done
                if drop_cap_done:
                    return match.group(0)
                drop_cap_done = True
                inner = match.group(1)
                if inner:
                    first_char = inner[0]
                    rest = inner[1:]
                    return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
                return match.group(0)

            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap, body_html, count=1, flags=re.DOTALL)

        articles_html += f"""
        <article class="pm-article" id="art-{i}">
            {category_html}
            <h2 class="pm-title">{art.get("title", "Sans titre")}</h2>
            {author_html}
            <div class="pm-rule-thin"></div>
            {image_html}
            {lead_html}
            <div class="pm-body">
                {body_html}
            </div>
        </article>
        """

    # ── Cover logo: dark banner with original (white+red) logo ──────────
    if logo_dark_uri:
        logo_html = f'''
        <div class="cover-banner">
            <img class="cover-logo" src="{logo_dark_uri}" alt="Antithèse" />
        </div>'''
    elif logo_light_uri:
        # Fallback: light-bg version without banner
        logo_html = f'<img class="cover-logo-light" src="{logo_light_uri}" alt="Antithèse" />'
    else:
        logo_html = '<h1 class="cover-title-fallback">ANTITHÈSE</h1>'

    # Colophon uses the light-background version (dark text on light bg)
    if logo_light_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_light_uri}" alt="" />'
    elif logo_dark_uri:
        # Fallback: original on light bg (partially invisible but better than nothing)
        colophon_logo = f'<img class="colophon-logo" src="{logo_dark_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles):
        cat = f'<span class="toc-cat">{art.get("category", "")}</span>' if art.get("category") else ""
        auth = f'<span class="toc-author">{art.get("author", "")}</span>' if art.get("author") else ""
        toc_items += f"""
        <a class="toc-entry" href="#art-{idx}">
            <span class="toc-details">
                {cat}
                <span class="toc-title">{art.get("title", "")}</span>
                {auth}
            </span>
        </a>"""

    # ── Cover content: dessin de la semaine OR article highlights ────
    cover_content = ""
    if dessin_info:
        # Download the dessin image
        dessin_uri = download_image_as_data_uri(session, dessin_info["image_url"])
        if not dessin_uri and dessin_info.get("image_url_fallback"):
            dessin_uri = download_image_as_data_uri(session, dessin_info["image_url_fallback"])
        if dessin_uri:
            dessin_title_html = ""
            if dessin_info.get("title"):
                dessin_title_html = f'<div class="cover-dessin-title">{dessin_info["title"]}</div>'
            dessin_artist_html = ""
            if dessin_info.get("artist"):
                dessin_artist_html = f'<div class="cover-dessin-artist">{dessin_info["artist"]}</div>'
            cover_content = f"""
    <div class="cover-dessin">
        <div class="cover-dessin-label">Le dessin de la semaine</div>
        <img class="cover-dessin-img" src="{dessin_uri}" alt="" />
        {dessin_title_html}
        {dessin_artist_html}
    </div>"""
            print(f"     ↳ Dessin de la semaine en couverture")

    if not cover_content:
        # Fallback: first 4 articles with thumbnails
        cover_content = '<div class="cover-highlights">'
        for art in articles[:4]:
            cat_hl = f'<div class="cover-hl-cat">{art.get("category", "")}</div>' if art.get("category") else ""
            auth_hl = f'<div class="cover-hl-author">{art.get("author", "")}</div>' if art.get("author") else ""

            thumb_html = ""
            img_url = art.get("image_url") or art.get("thumb_url")
            if img_url:
                hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
                data_uri = image_cache.get(hires) or image_cache.get(img_url)
                if data_uri:
                    thumb_html = f'<img class="cover-hl-thumb" src="{data_uri}" alt="" />'

            cover_content += f"""
        <div class="cover-hl">
            {thumb_html}
            <div class="cover-hl-text">
                {cat_hl}
                <div class="cover-hl-title">{art.get("title", "")}</div>
                {auth_hl}
            </div>
        </div>"""
        cover_content += "\n    </div>"

    # ── Full HTML document ─────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       ANTITHÈSE — ÉDITION PREMIUM A4 PAYSAGE
       Mise en page 3 colonnes sur format paysage
       ================================================================ */

    @page {{
        size: 297mm 210mm;
        margin: 18mm 22mm 20mm 22mm;

        @bottom-right {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 8pt;
            color: #999;
        }}
    }}

    @page :first {{
        margin: 0;
        @bottom-right {{ content: none; }}
    }}

    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, "Times New Roman", serif;
        font-size: 11pt;
        line-height: 1.6;
        color: #1a1a1a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
        orphans: 3;
        widows: 3;
    }}

    /* ════════════════════════════════════════════════════════════════
       COVER PAGE
       ════════════════════════════════════════════════════════════════ */
    .cover {{
        page-break-after: always;
        width: 297mm;
        height: 210mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        background: #faf9f7;
        padding: 22mm 40mm;
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: 20mm;
        left: 25mm;
        right: 25mm;
        height: 0.8pt;
        background: #1a1a1a;
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: 20mm;
        left: 25mm;
        right: 25mm;
        height: 0.8pt;
        background: #1a1a1a;
    }}

    /* Dark banner behind logo (original white+red SVG) */
    .cover-banner {{
        background: #1a1a1a;
        padding: 6mm 10mm;
        margin-bottom: 8mm;
        width: 80mm;
        text-align: center;
    }}

    .cover-banner .cover-logo {{
        width: 55mm;
        height: auto;
    }}

    /* Light-bg version (fallback: no banner, dark text on light bg) */
    .cover-logo-light {{
        width: 55mm;
        height: auto;
        margin-bottom: 6mm;
    }}

    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 36pt;
        font-weight: 700;
        letter-spacing: 0.12em;
        color: #1a1a1a;
        margin-bottom: 2mm;
        text-transform: uppercase;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 12pt;
        font-style: italic;
        color: #666;
        letter-spacing: 0.06em;
        margin-bottom: 10mm;
    }}

    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt;
        font-weight: 600;
        color: #333;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        padding: 2.5mm 8mm;
        border-top: 0.5pt solid #1a1a1a;
        border-bottom: 0.5pt solid #1a1a1a;
        margin-bottom: 14mm;
    }}

    .cover-tagline {{
        font-size: 9pt;
        color: #888;
        font-style: italic;
        margin-bottom: 10mm;
    }}

    .cover-highlights {{
        margin-top: 8mm;
        text-align: left;
        max-width: 200mm;
        column-count: 2;
        column-gap: 10mm;
    }}

    .cover-hl {{
        display: flex;
        align-items: center;
        gap: 4mm;
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #ccc;
        break-inside: avoid;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-thumb {{
        width: 22mm;
        height: 16mm;
        object-fit: cover;
        flex-shrink: 0;
    }}

    .cover-hl-text {{
        flex: 1;
        min-width: 0;
    }}

    .cover-hl-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #999;
        margin-bottom: 1mm;
    }}
    .cover-hl-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.25;
        color: #1a1a1a;
    }}
    .cover-hl-author {{
        font-size: 8pt;
        font-style: italic;
        color: #777;
        margin-top: 1mm;
    }}

    /* ── Cover: Dessin de la semaine ── */
    .cover-dessin {{
        margin-top: 6mm;
        text-align: center;
    }}
    .cover-dessin-label {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #999;
        margin-bottom: 4mm;
    }}
    .cover-dessin-img {{
        max-width: 140mm;
        max-height: 90mm;
        width: auto;
        height: auto;
        object-fit: contain;
    }}
    .cover-dessin-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 10pt;
        font-weight: 700;
        color: #1a1a1a;
        margin-top: 3mm;
        line-height: 1.3;
    }}
    .cover-dessin-artist {{
        font-size: 8pt;
        font-style: italic;
        color: #777;
        margin-top: 1mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       TABLE OF CONTENTS
       ════════════════════════════════════════════════════════════════ */
    .toc-page {{
        page-break-after: always;
        padding-top: 5mm;
    }}

    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: #999;
        margin-bottom: 6mm;
        padding-bottom: 2mm;
        border-bottom: 0.8pt solid #1a1a1a;
    }}

    .toc-content {{
        column-count: 3;
        column-gap: 8mm;
        column-rule: 0.3pt solid #e5e5e5;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
        text-decoration: none;
        color: inherit;
        break-inside: avoid;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-entry::before {{
        content: target-counter(attr(href), page);
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt;
        font-weight: 300;
        color: #555;
        min-width: 12mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
        display: block;
    }}

    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #999;
        display: block;
        margin-bottom: 0.5mm;
        break-after: avoid;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.3;
        color: #1a1a1a;
        display: block;
    }}

    .toc-author {{
        font-size: 8.5pt;
        font-style: italic;
        color: #777;
        display: block;
        margin-top: 0.5mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .pm-article {{
        page-break-before: always;
    }}

    .pm-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #888;
        margin-bottom: 3mm;
    }}

    .pm-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 24pt;
        font-weight: 700;
        line-height: 1.15;
        color: #1a1a1a;
        margin-bottom: 3mm;
        letter-spacing: -0.01em;
    }}

    .pm-author {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 9pt;
        font-style: italic;
        color: #666;
        margin-bottom: 4mm;
    }}

    .pm-rule-thin {{
        height: 0.5pt;
        background: #ccc;
        margin-bottom: 5mm;
    }}

    .pm-hero-img {{
        margin-bottom: 5mm;
        text-align: center;
    }}
    .pm-hero-img img {{
        width: 100%;
        height: auto;
        max-height: 70mm;
        object-fit: cover;
        display: block;
    }}
    .pm-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        color: #999;
        font-style: italic;
        margin-top: 1.5mm;
        text-align: right;
    }}

    .pm-lead {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11.5pt;
        font-weight: 600;
        line-height: 1.45;
        color: #333;
        margin-bottom: 5mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #ddd;
    }}

    /* Three-column body */
    .pm-body {{
        column-count: 3;
        column-gap: 7mm;
        column-rule: 0.3pt solid #e5e5e5;
        font-size: 10pt;
        line-height: 1.6;
    }}

    .pm-body p {{
        margin-bottom: 0.5em;
        text-indent: 1.2em;
    }}
    .pm-body p:first-child {{
        text-indent: 0;
    }}

    /* Drop cap */
    .drop-cap {{
        float: left;
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 42pt;
        line-height: 0.75;
        padding-right: 2mm;
        padding-top: 2mm;
        color: #1a1a1a;
        font-weight: 700;
    }}

    .pm-body h2, .pm-body h3, .pm-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 10pt;
        font-weight: 700;
        margin-top: 1em;
        margin-bottom: 0.4em;
        text-indent: 0;
        column-span: none;
        color: #333;
    }}

    .pm-body blockquote {{
        margin: 0.8em 0;
        padding: 0.5em 0.8em;
        border-left: 2.5pt solid #d0d0d0;
        color: #444;
        font-style: italic;
        font-size: 9.5pt;
        background: #faf9f7;
    }}
    .pm-body blockquote p {{
        text-indent: 0 !important;
        margin-bottom: 0.3em;
    }}

    /* ════════════════════════════════════════════════════════════════
       COLOPHON
       ════════════════════════════════════════════════════════════════ */
    .colophon {{
        page-break-before: always;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        height: 100%;
    }}

    .colophon-logo {{
        width: 35mm;
        height: auto;
        margin-bottom: 8mm;
        opacity: 0.4;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #aaa;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 30mm;
        height: 0.5pt;
        background: #ccc;
        margin: 6mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>

    {cover_content}
</div>

<!-- ═══════════ TABLE OF CONTENTS ═══════════ -->
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    <div class="toc-content">
        {toc_items}
    </div>
</div>

<!-- ═══════════ ARTICLES ═══════════ -->
{articles_html}

<!-- ═══════════ COLOPHON ═══════════ -->
<div class="colophon">
    {colophon_logo}
    <div class="colophon-text">
        Antithèse — Bon pour la tête<br/>
        <em>Un média indépendant et a-partisan</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        antithese.info<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    print(f"  📄 Génération PDF (🖨️  A4 Premium Paysage)…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ── Interactive mode helpers ───────────────────────────────────────────────

def _is_interactive(args):
    """Return True if stdin is a TTY and --batch was not passed."""
    return sys.stdin.isatty() and not args.batch


def interactive_setup(args):
    """Prompt user for format, output dir, and verbose when no CLI args given."""
    print("  ⚙  Mode interactif — configuration\n")

    # ── Format selection ──────────────────────────────────────────────
    fmt_keys = list(FORMATS.keys())
    print("  Formats disponibles :")
    for i, key in enumerate(fmt_keys, 1):
        print(f"    {i}. {FORMATS[key]['label']}  ({key})")
    print(f"    {len(fmt_keys) + 1}. Tous les formats  (all)")
    print()

    while True:
        choice = input(f"  Choix [1-{len(fmt_keys) + 1}] (défaut: tous) : ").strip()
        if not choice:
            args.format = "all"
            break
        try:
            idx = int(choice)
            if 1 <= idx <= len(fmt_keys):
                args.format = fmt_keys[idx - 1]
                break
            elif idx == len(fmt_keys) + 1:
                args.format = "all"
                break
        except ValueError:
            pass
        print("    ⚠  Choix invalide, réessayez.")

    print(f"    → Format : {args.format}\n")

    # ── Output directory ──────────────────────────────────────────────
    default_dir = str(args.output_dir)
    custom = input(f"  Dossier de sortie [{default_dir}] : ").strip()
    if custom:
        args.output_dir = Path(custom)
    print(f"    → Dossier : {args.output_dir}\n")

    # ── Verbose ───────────────────────────────────────────────────────
    v = input("  Mode verbose ? [o/N] : ").strip().lower()
    if v in ("o", "oui", "y", "yes"):
        args.verbose = True
    print(f"    → Verbose : {'oui' if args.verbose else 'non'}\n")


def _display_articles(articles, selected):
    """Print the numbered article list with selection checkboxes."""
    print()
    print("  ┌─────────────────────────────────────────────────────────────┐")
    print("  │  Sélection des articles                                     │")
    print("  └─────────────────────────────────────────────────────────────┘")
    for i, art in enumerate(articles):
        check = "v" if selected[i] else " "
        title = art.get("title", "Sans titre")
        if len(title) > 48:
            title = title[:45] + "…"
        cat = art.get("category", "")
        author = art.get("author", "")
        cat_str = f"  [{cat}]" if cat else ""
        author_str = f"  — {author}" if author else ""
        print(f"    {i + 1:>2}. [{check}] {title}{cat_str}{author_str}")
    print()
    print("  Commandes : N = toggle article, N,N,N = toggle plusieurs")
    print("              m N P = déplacer article N en position P")
    print("              a = tout sélectionner, n = tout désélectionner")
    print("              Entrée = confirmer, q = quitter")
    print()


def interactive_article_selector(articles):
    """Let the user toggle/reorder articles. Returns the filtered list."""
    selected = [True] * len(articles)

    while True:
        _display_articles(articles, selected)
        cmd = input("  > ").strip()

        if not cmd:
            # Confirm — return only selected articles in current order
            result = [a for a, s in zip(articles, selected) if s]
            if not result:
                print("    ⚠  Aucun article sélectionné, sélectionnez-en au moins un.")
                continue
            count = sum(selected)
            print(f"\n    ✅ {count} article(s) sélectionné(s).\n")
            return result

        if cmd.lower() == "q":
            print("    ❌ Abandon.")
            sys.exit(0)

        if cmd.lower() == "a":
            selected = [True] * len(articles)
            continue

        if cmd.lower() == "n":
            selected = [False] * len(articles)
            continue

        # Move command: m N P
        if cmd.lower().startswith("m "):
            parts = cmd.split()
            if len(parts) == 3:
                try:
                    src = int(parts[1]) - 1
                    dst = int(parts[2]) - 1
                    if 0 <= src < len(articles) and 0 <= dst < len(articles):
                        art = articles.pop(src)
                        sel = selected.pop(src)
                        articles.insert(dst, art)
                        selected.insert(dst, sel)
                        continue
                except ValueError:
                    pass
            print("    ⚠  Usage : m <source> <destination>  (ex: m 3 1)")
            continue

        # Toggle: single number or comma-separated
        try:
            indices = [int(x.strip()) - 1 for x in cmd.split(",")]
            valid = True
            for idx in indices:
                if 0 <= idx < len(articles):
                    selected[idx] = not selected[idx]
                else:
                    valid = False
            if not valid:
                print(f"    ⚠  Numéro(s) hors limites (1-{len(articles)}).")
            continue
        except ValueError:
            pass

        print("    ⚠  Commande non reconnue.")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Antithèse / Bon pour la tête — Digest PDF"
    )
    parser.add_argument("--user", "-u", help="Nom d'utilisateur / email")
    parser.add_argument("--password", "-p", help="Mot de passe")
    parser.add_argument(
        "--format", "-f",
        default="all",
        help="Format(s) : phone,ereader,tablet7,tablet10,a4premium,a4editorial,epub,all (comma-separated)",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=OUTPUT_DIR,
        help=f"Dossier de sortie (défaut: {OUTPUT_DIR})",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--batch", "--non-interactive",
        action="store_true",
        help="Mode non-interactif (pas de sélection d'articles ni de setup interactif)",
    )
    args = parser.parse_args()

    # ── Interactive setup when invoked with no arguments ────────────
    if len(sys.argv) == 1 and _is_interactive(args):
        interactive_setup(args)

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  📰  Antithèse — Bon pour la tête                           ║")
    print("║  📱 phone · 📖 liseuse · 📱 tablette 7 & 10                 ║")
    print("║  🖨️  A4 Premium (New Yorker, 2 col.)                         ║")
    print("║  🖨️  A4 Éditorial (Kinfolk, 1 col.)                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ── Credentials ────────────────────────────────────────────────────
    username = ANTITHESE_USER or args.user or os.environ.get("ANTITHESE_USER", "")
    password = ANTITHESE_PASS or args.password or os.environ.get("ANTITHESE_PASS", "")

    if not username:
        username = input("  Email / identifiant : ").strip()
    if not password:
        password = getpass.getpass("  Mot de passe : ")

    if not username or not password:
        print("  ❌ Identifiants requis.")
        sys.exit(1)

    # ── Formats to generate ────────────────────────────────────────────
    if args.format == "all":
        formats_to_gen = list(FORMATS.keys()) + ["epub"]
    else:
        valid = set(FORMATS.keys()) | {"epub"}
        formats_to_gen = [f.strip() for f in args.format.split(",")]
        for f in formats_to_gen:
            if f not in valid:
                print(f"  ❌ Format inconnu : '{f}' (valides : {', '.join(sorted(valid))})")
                sys.exit(1)

    # ── Session & login ────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update(HEADERS)

    if not login(session, username, password):
        sys.exit(1)

    # ── Download logo (all formats use it now) ─────────────────────────
    logo_dark_uri, logo_light_uri = download_logo(session)

    # ── Scrape edition ─────────────────────────────────────────────────
    date_str, article_list, dessin_info = get_edition_info(session)

    if not article_list:
        print("  ⚠  Aucun article trouvé dans l'édition.")
        sys.exit(1)

    # ── Parse edition date for Pilet filtering ─────────────────────────
    try:
        edition_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        edition_date = datetime.now()

    # ── Fetch each article ─────────────────────────────────────────────
    print(f"\n  📥 Téléchargement de {len(article_list)} articles…")
    full_articles = []
    pilet_filtered = 0
    for i, art_meta in enumerate(article_list, 1):
        print(f"     [{i}/{len(article_list)}] {art_meta['title'][:60]}…")
        try:
            article = fetch_article(session, art_meta["url"],
                                     fetch_images=True)
            if not article.get("category") and art_meta.get("category"):
                article["category"] = art_meta["category"]
            if not article.get("image_url") and art_meta.get("thumb_url"):
                article["thumb_url"] = art_meta["thumb_url"]
            elif art_meta.get("thumb_url"):
                article.setdefault("thumb_url", art_meta["thumb_url"])

            if not article.get("content_html"):
                print(f"           ⚠  Contenu vide, ignoré.")
                continue

            # Filter Pilet articles: only keep if published within 7 days
            # before the edition date
            if art_meta.get("is_pilet") and article.get("pub_date"):
                try:
                    pub = datetime.strptime(article["pub_date"], "%Y-%m-%d")
                    days_before = (edition_date - pub).days
                    if days_before > 7:
                        pilet_filtered += 1
                        print(f"           ↳ Pilet ancien ({article['pub_date']}), ignoré.")
                        continue
                except ValueError:
                    pass

            full_articles.append(article)
        except Exception as e:
            print(f"           ❌ Erreur: {e}")

    if pilet_filtered:
        print(f"     ↳ {pilet_filtered} article(s) Pilet antérieur(s) à 7 jours filtré(s)")

    if not full_articles:
        print("  ❌ Aucun article récupéré avec succès.")
        sys.exit(1)

    print(f"\n  ✅ {len(full_articles)} articles récupérés.\n")

    # ── Interactive article selection ──────────────────────────────────
    if _is_interactive(args):
        full_articles = interactive_article_selector(full_articles)

    # ── Edition title for cover ────────────────────────────────────────
    edition_title = f"Édition du {date_str}"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        months_fr = [
            "", "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        ]
        edition_title = f"Édition du {dt.day} {months_fr[dt.month]} {dt.year}"
    except ValueError:
        pass

    # ── Generate PDFs ──────────────────────────────────────────────────
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for fmt_key in formats_to_gen:
        if fmt_key == "epub":
            output_path = out_dir / f"{date_str}-antithese.epub"
            generate_epub(
                full_articles,
                publication_title="Antithèse",
                edition_title=edition_title,
                date_str=date_str,
                output_path=output_path,
                subtitle="Bon pour la tête",
                tagline="Un média indépendant et a-partisan",
                publisher="Antithèse / Bon pour la tête",
                image_fetcher=lambda url: download_image_bytes(session, url),
            )
            generated.append(("EPUB", output_path))
            continue

        suffix = FORMATS[fmt_key]["suffix"]
        output_path = out_dir / f"{date_str}-antithese_{suffix}.pdf"

        if fmt_key == "a4premium":
            generate_premium_pdf(
                full_articles, edition_title, date_str,
                output_path, session, logo_light_uri, logo_dark_uri,
                dessin_info=dessin_info,
            )
        elif fmt_key == "a4editorial":
            generate_editorial_pdf(
                full_articles, edition_title, date_str,
                output_path, session, logo_light_uri, logo_dark_uri,
                dessin_info=dessin_info,
            )
        elif fmt_key == "a4landscape":
            generate_premium_landscape_pdf(
                full_articles, edition_title, date_str,
                output_path, session, logo_light_uri, logo_dark_uri,
                dessin_info=dessin_info,
            )
        else:
            generate_pdf(full_articles, edition_title, date_str, fmt_key,
                         output_path, session, logo_light_uri, logo_dark_uri)

        generated.append((FORMATS[fmt_key]['label'], output_path))

    print()
    print(f"  🎉 Terminé — {len(generated)} fichier(s) généré(s) !")
    for label, path in generated:
        print(f"     {label}: {path.name}")
    print()


if __name__ == "__main__":
    main()
