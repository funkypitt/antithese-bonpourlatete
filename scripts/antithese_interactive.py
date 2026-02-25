#!/usr/bin/env python3
"""
Antithèse / Bon pour la tête — Interactive Edition Builder
===========================================================
Fully interactive fork of antithese_scraper.py.
Produces three output formats:
  - A4 Premium PDF (two-column, New Yorker style)
  - A4 Éditorial PDF (single-column, Kinfolk style)
  - EPUB (clean, well-formatted ebook)

No command-line arguments — everything is prompted interactively.

Dependencies:
    pip install requests beautifulsoup4 weasyprint lxml cffi
"""

import base64
import getpass
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

import requests
from bs4 import BeautifulSoup

# ── Constants ──────────────────────────────────────────────────────────────

EDITION_URL = "https://www.antithese.info/bon-pour-la-tete/"
LOGIN_URL = "https://www.antithese.info/login/"
WP_LOGIN_URL = "https://www.antithese.info/wp-login.php"
BASE_URL = "https://www.antithese.info"
DEFAULT_OUTPUT_DIR = Path.home() / "kDrive" / "newspapers" / "antithese"

LOGO_URL = "https://www.antithese.info/wp-content/uploads/Logo-Antihese-et-Bon-pour-la-tete.svg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

OUTPUT_FORMATS = {
    "a4premium": "A4 Premium — New Yorker (2 colonnes)",
    "a4editorial": "A4 Éditorial — Kinfolk (1 colonne)",
    "epub": "EPUB (ebook)",
}


# ══════════════════════════════════════════════════════════════════════════
#  INTERACTIVE PROMPTS
# ══════════════════════════════════════════════════════════════════════════

def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    """Print welcome banner."""
    print()
    print("  ╔══════════════════════════════════════════════════════════════╗")
    print("  ║                                                              ║")
    print("  ║   ANTITHÈSE — Bon pour la tête                              ║")
    print("  ║   Édition interactive                                        ║")
    print("  ║                                                              ║")
    print("  ║   Formats: A4 Premium · A4 Éditorial · EPUB                 ║")
    print("  ║                                                              ║")
    print("  ╚══════════════════════════════════════════════════════════════╝")
    print()


def prompt_credentials() -> tuple[str, str]:
    """Ask for login credentials."""
    print("  ── Connexion ─────────────────────────────────────────────────")
    print()

    # Check environment variables first
    env_user = os.environ.get("ANTITHESE_USER", "")
    env_pass = os.environ.get("ANTITHESE_PASS", "")

    if env_user and env_pass:
        print(f"  Identifiants trouvés dans l'environnement ({env_user}).")
        use = input("  Utiliser ces identifiants ? [O/n] : ").strip().lower()
        if use not in ("n", "non", "no"):
            print()
            return env_user, env_pass
        print()

    username = input("  Email / identifiant : ").strip()
    if not username:
        print("  Identifiant requis. Abandon.")
        sys.exit(1)

    password = getpass.getpass("  Mot de passe : ")
    if not password:
        print("  Mot de passe requis. Abandon.")
        sys.exit(1)

    print()
    return username, password


def prompt_output_dir() -> Path:
    """Ask for output directory."""
    print("  ── Dossier de sortie ─────────────────────────────────────────")
    print()

    default = str(DEFAULT_OUTPUT_DIR)
    custom = input(f"  Dossier [{default}] : ").strip()
    out_dir = Path(custom) if custom else DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  -> {out_dir}")
    print()
    return out_dir


def prompt_format_selection() -> list[str]:
    """Ask which output formats to generate."""
    print("  ── Formats de sortie ─────────────────────────────────────────")
    print()

    keys = list(OUTPUT_FORMATS.keys())
    for i, key in enumerate(keys, 1):
        print(f"    {i}. {OUTPUT_FORMATS[key]}")
    print(f"    {len(keys) + 1}. Tous les formats")
    print()

    while True:
        raw = input(f"  Choix (1-{len(keys)+1}, ou plusieurs séparés par des virgules) [tous] : ").strip()
        if not raw:
            print(f"  -> Tous les formats")
            print()
            return keys

        try:
            indices = [int(x.strip()) for x in raw.split(",")]
        except ValueError:
            print("  Choix invalide, réessayez.")
            continue

        if len(indices) == 1 and indices[0] == len(keys) + 1:
            print(f"  -> Tous les formats")
            print()
            return keys

        selected = []
        valid = True
        for idx in indices:
            if 1 <= idx <= len(keys):
                selected.append(keys[idx - 1])
            else:
                valid = False
        if valid and selected:
            for k in selected:
                print(f"  -> {OUTPUT_FORMATS[k]}")
            print()
            return selected
        print("  Choix invalide, réessayez.")


def display_articles(articles, selected):
    """Print the numbered article list with selection checkboxes."""
    print()
    print("  ┌─────────────────────────────────────────────────────────────┐")
    print("  │  Sélection des articles                                     │")
    print("  └─────────────────────────────────────────────────────────────┘")
    for i, art in enumerate(articles):
        check = "v" if selected[i] else " "
        title = art.get("title", "Sans titre")
        if len(title) > 48:
            title = title[:45] + "..."
        cat = art.get("category", "")
        author = art.get("author", "")
        cat_str = f"  [{cat}]" if cat else ""
        author_str = f"  -- {author}" if author else ""
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
        display_articles(articles, selected)
        cmd = input("  > ").strip()

        if not cmd:
            result = [a for a, s in zip(articles, selected) if s]
            if not result:
                print("    Aucun article sélectionné, sélectionnez-en au moins un.")
                continue
            count = sum(selected)
            print(f"\n    {count} article(s) sélectionné(s).\n")
            return result

        if cmd.lower() == "q":
            print("    Abandon.")
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
            print("    Usage : m <source> <destination>  (ex: m 3 1)")
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
                print(f"    Numéro(s) hors limites (1-{len(articles)}).")
            continue
        except ValueError:
            pass

        print("    Commande non reconnue.")


# ══════════════════════════════════════════════════════════════════════════
#  AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════

def login(session: requests.Session, username: str, password: str) -> bool:
    """Log in to antithese.info via WordPress wp-login.php."""
    print(f"  Connexion en tant que {username}...")

    login_data = {
        "log": username,
        "pwd": password,
        "wp-submit": "Se connecter",
        "redirect_to": EDITION_URL,
        "testcookie": "1",
    }

    session.cookies.set("wordpress_test_cookie", "WP+Cookie+check",
                        domain="www.antithese.info")
    resp = session.post(WP_LOGIN_URL, data=login_data, headers=HEADERS,
                        allow_redirects=True)

    if resp.status_code == 200:
        cookies_names = [c.name for c in session.cookies]
        has_wp_cookies = any("wordpress_logged_in" in n for n in cookies_names)

        if has_wp_cookies:
            print("  Connecté avec succès.")
            return True

        if (any("wordpress" in n.lower() for n in cookies_names)
                and "login" not in resp.url):
            print("  Connecté avec succès.")
            return True

    if ("login" in resp.url.lower()
            and ("incorrect" in resp.text.lower() or "error" in resp.text.lower())):
        print("  Identifiants incorrects.")
        return False

    test = session.get(EDITION_URL, headers=HEADERS)
    if "Se Connecter" not in test.text or "Déconnexion" in test.text:
        print("  Connecté avec succès (vérifié).")
        return True

    print("  Échec de connexion. Vérifiez vos identifiants.")
    return False


# ══════════════════════════════════════════════════════════════════════════
#  IMAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════

def download_image_as_data_uri(session: requests.Session, url: str) -> str | None:
    """Download an image and return it as a base64 data URI."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "svg" in content_type or url.endswith(".svg"):
            content_type = "image/svg+xml"
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
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

    Returns (logo_dark_bg, logo_light_bg).
    """
    print("  Téléchargement du logo...")
    try:
        resp = session.get(LOGO_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        svg_text = resp.content.decode("utf-8", errors="replace")

        b64_orig = base64.b64encode(resp.content).decode("ascii")
        logo_dark = f"data:image/svg+xml;base64,{b64_orig}"

        svg_light = svg_text
        svg_light = re.sub(r'fill\s*:\s*#(?:fff(?:fff)?)\b', 'fill:#1a1a1a',
                           svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*=\s*"#(?:fff(?:fff)?)"', 'fill="#1a1a1a"',
                           svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*:\s*white\b', 'fill:#1a1a1a',
                           svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(r'fill\s*=\s*"white"', 'fill="#1a1a1a"',
                           svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(
            r'fill\s*:\s*rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)',
            'fill:#1a1a1a', svg_light, flags=re.IGNORECASE)
        svg_light = re.sub(
            r'fill\s*=\s*"rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)"',
            'fill="#1a1a1a"', svg_light, flags=re.IGNORECASE)

        b64_light = base64.b64encode(svg_light.encode("utf-8")).decode("ascii")
        logo_light = f"data:image/svg+xml;base64,{b64_light}"

        print("  Logo récupéré.")
        return logo_dark, logo_light

    except Exception as e:
        print(f"  Logo non disponible ({e}), utilisation du texte.")
        return None, None


# ══════════════════════════════════════════════════════════════════════════
#  TEXT CLEANING
# ══════════════════════════════════════════════════════════════════════════

def clean_text(element) -> str:
    """Extract text from a BeautifulSoup element, preserving spaces."""
    text = element.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ══════════════════════════════════════════════════════════════════════════
#  SCRAPING
# ══════════════════════════════════════════════════════════════════════════

def get_edition_info(session: requests.Session) -> tuple[str, list[dict], dict | None]:
    """Fetch the edition page and extract article links + metadata.

    Returns (date_str, articles, dessin_info).
    """
    print("  Récupération de l'édition en cours...")
    resp = session.get(EDITION_URL, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract edition date from the H1
    edition_title = ""
    h1 = soup.find("h1")
    if h1:
        edition_title = clean_text(h1)
        edition_title = re.sub(r"(du)(\d)", r"\1 \2", edition_title)
    print(f"  {edition_title}")

    # Extract date for filename
    date_match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", edition_title)
    if date_match:
        months_fr = {
            "janvier": "01", "février": "02", "mars": "03", "avril": "04",
            "mai": "05", "juin": "06", "juillet": "07", "août": "08",
            "septembre": "09", "octobre": "10", "novembre": "11",
            "décembre": "12",
        }
        day = date_match.group(1).zfill(2)
        month = months_fr.get(date_match.group(2).lower(), "00")
        year = date_match.group(3)
        date_str = f"{year}-{month}-{day}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Locate content sections
    brx = soup.find(id="brx-content")
    if not brx:
        return date_str, [], None

    top_sections = brx.find_all("section", class_="brxe-section",
                                recursive=False)

    # Collect URLs from "Précédente édition" to exclude
    previous_urls = set()
    for sec in top_sections[2:]:
        for heading in sec.find_all(class_="brxe-heading"):
            txt = heading.get_text(strip=True).lower()
            if "dition" in txt and ("préc" in txt or "prec" in txt):
                for a in sec.find_all("a", href=True):
                    if "/articles/" in a["href"]:
                        previous_urls.add(urljoin(BASE_URL, a["href"]))
                break
    if previous_urls:
        print(f"  {len(previous_urls)} articles de l'édition précédente exclus")

    # Work within section 1 (main edition content)
    sec1 = top_sections[1] if len(top_sections) > 1 else brx

    # Identify Pilet article URLs
    pilet_urls = set()
    for heading in sec1.find_all(class_="brxe-heading"):
        if "pilet" in heading.get_text(strip=True).lower():
            container = heading.parent
            for _ in range(5):
                links = container.find_all(
                    "a", href=lambda h: h and "/articles/" in h)
                if len(set(a["href"] for a in links)) > 1:
                    break
                container = container.parent
            for a in container.find_all(
                    "a", href=lambda h: h and "/articles/" in h):
                pilet_urls.add(urljoin(BASE_URL, a["href"]))
            break
    if pilet_urls:
        print(f"  {len(pilet_urls)} articles de l'espace Jacques Pilet")

    # Extract "Dessin de la semaine"
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
                dessin_title = ""
                dessin_artist = ""
                for h in headings_in:
                    h_text = clean_text(h)
                    if "dessin" in h_text.lower():
                        continue
                    if h_text.startswith("{"):
                        if "/" in h_text:
                            h_text = h_text.split("/", 1)[1].strip()
                        elif "}" in h_text:
                            continue
                    if not dessin_title and len(h_text) > 5:
                        dessin_title = h_text
                    elif not dessin_artist and h_text and not h_text.startswith("{"):
                        dessin_artist = h_text
                if img_src:
                    hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_src)
                    dessin_info = {
                        "image_url": urljoin(BASE_URL, hires),
                        "image_url_fallback": urljoin(BASE_URL, img_src),
                        "title": dessin_title,
                        "artist": dessin_artist,
                    }
                    print(f"  Dessin de la semaine: {dessin_title[:50]}")
            break

    # Collect article links (from section 1 only)
    articles = []
    seen_urls = set()

    KNOWN_CATEGORIES = {
        "Economie", "Économie", "Politique", "Histoire",
        "Sciences & Technologies", "Santé", "Philosophie",
        "Culture", "Accès libre",
    }

    for a_tag in sec1.find_all("a", href=True):
        href = a_tag["href"]
        if "/articles/" not in href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        if full_url in previous_urls:
            seen_urls.add(full_url)
            continue

        title = ""
        category = ""

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
            if (text and text not in ("Lire la suite...", "Lire la suite", "...")
                    and len(text) > 10):
                title = text

        if not title:
            continue
        if title in KNOWN_CATEGORIES:
            continue
        if len(title) < 15:
            continue

        seen_urls.add(full_url)

        for span in a_tag.find_all(string=True):
            txt = span.strip()
            if txt in KNOWN_CATEGORIES and txt != title:
                if category and txt not in category:
                    category += ", " + txt
                elif not category:
                    category = txt

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

    print(f"  {len(articles)} articles trouvés.")
    return date_str, articles, dessin_info


def fetch_article(session: requests.Session, url: str,
                  fetch_images: bool = False) -> dict:
    """Fetch a single article's full content."""
    resp = session.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    brx = soup.find(id="brx-content")
    if not brx:
        return {"url": url, "title": "", "author": "", "category": "",
                "lead": "", "content_html": "", "content_text": "",
                "image_url": None, "image_caption": None}

    sections = brx.find_all("section", class_="brxe-section", recursive=False)

    # Section 0: Header metadata
    title = ""
    author = ""
    category = ""
    image_url = None
    image_caption = None

    if sections:
        sec0 = sections[0]

        h1 = sec0.find(class_="brxe-heading")
        if h1:
            title = clean_text(h1)
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = clean_text(h1)

        author_link = sec0.find("a", href=re.compile(r"/journaliste/"))
        if author_link:
            author = clean_text(author_link)

        tags_el = sec0.find(class_="brxe-post-taxonomy")
        if tags_el:
            tag_texts = [a.get_text(strip=True).lstrip("#")
                         for a in tags_el.find_all("a")]
            category = ", ".join(tag_texts[:3])

        if fetch_images:
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                image_url = og["content"]

            if not image_url:
                for img_tag in sec0.find_all("img"):
                    src = img_tag.get("src") or img_tag.get("data-src", "")
                    if not src:
                        continue
                    cls = img_tag.get("class", [])
                    if "size-thumbnail" in cls:
                        continue
                    if re.search(r"-\d{2,3}x\d{2,3}\.", src):
                        continue
                    if "logo" in src.lower():
                        continue
                    image_url = urljoin(BASE_URL, src)
                    break

            if image_url:
                cap_el = sec0.find(class_=re.compile(
                    r"caption|credit|legend", re.IGNORECASE))
                if cap_el:
                    image_caption = clean_text(cap_el)

    # Publication date
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

    # Section 1: Article content
    lead = ""
    paragraphs = []
    content_text = ""

    if len(sections) > 1:
        sec1 = sections[1]

        lead_el = sec1.find(class_="brxe-text-basic")
        if lead_el:
            lead = clean_text(lead_el)

        for text_div in sec1.find_all(class_="brxe-text"):
            for p in text_div.find_all(["p", "blockquote", "h2", "h3", "h4"]):
                text = clean_text(p)

                if not text or len(text) < 8:
                    continue
                if "\u00a9" in text:  # ©
                    continue

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

                if p.name == "p":
                    link = p.find("a", href=True)
                    if link and "antithese" not in link.get("href", ""):
                        link_text = clean_text(link)
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


# ══════════════════════════════════════════════════════════════════════════
#  IMAGE CACHE BUILDER
# ══════════════════════════════════════════════════════════════════════════

def build_image_cache(session, articles):
    """Download images for all articles. Returns {url: data_uri} cache."""
    print("  Téléchargement des images...")
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
        status = "ok" if (img_url and (
            img_url in image_cache
            or re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url) in image_cache
        )) else "--"
        print(f"    [{i+1}/{len(articles)}] {status} {art.get('title', '')[:55]}...")
    return image_cache


# ══════════════════════════════════════════════════════════════════════════
#  PDF GENERATION — A4 Premium (New Yorker, 2 columns)
# ══════════════════════════════════════════════════════════════════════════

def _add_drop_cap_html(body_html: str) -> str:
    """Add drop cap to the first paragraph in body_html."""
    done = False

    def replacer(match):
        nonlocal done
        if done:
            return match.group(0)
        done = True
        inner = match.group(1)
        if inner:
            first_char = inner[0]
            rest = inner[1:]
            return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
        return match.group(0)

    return re.sub(r"<p>(.+?)</p>", replacer, body_html, count=1,
                  flags=re.DOTALL)


def generate_premium_pdf(articles, edition_title, date_str, output_path,
                         session, logo_light_uri, logo_dark_uri,
                         dessin_info, image_cache):
    """Generate a premium A4 magazine-style PDF (New Yorker 2-col)."""
    from weasyprint import HTML

    print("  Préparation de l'édition A4 Premium...")

    # Build articles HTML
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
                cap_html = (f'<div class="pm-img-caption">{cap}</div>'
                            if cap else "")
                image_html = f'''
                <div class="pm-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        body_html = _add_drop_cap_html(art.get("content_html", ""))

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

    # Cover logo
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

    # TOC
    toc_items = ""
    for idx, art in enumerate(articles):
        cat = (f'<span class="toc-cat">{art.get("category", "")}</span>'
               if art.get("category") else "")
        auth = (f'<span class="toc-author">{art.get("author", "")}</span>'
                if art.get("author") else "")
        toc_items += f"""
        <a class="toc-entry" href="#art-{idx}">
            <span class="toc-details">
                {cat}
                <span class="toc-title">{art.get("title", "")}</span>
                {auth}
            </span>
        </a>"""

    # Cover content
    cover_content = ""
    if dessin_info:
        dessin_uri = download_image_as_data_uri(session,
                                                 dessin_info["image_url"])
        if not dessin_uri and dessin_info.get("image_url_fallback"):
            dessin_uri = download_image_as_data_uri(
                session, dessin_info["image_url_fallback"])
        if dessin_uri:
            dt_html = ""
            if dessin_info.get("title"):
                dt_html = f'<div class="cover-dessin-title">{dessin_info["title"]}</div>'
            da_html = ""
            if dessin_info.get("artist"):
                da_html = f'<div class="cover-dessin-artist">{dessin_info["artist"]}</div>'
            cover_content = f"""
    <div class="cover-dessin">
        <div class="cover-dessin-label">Le dessin de la semaine</div>
        <img class="cover-dessin-img" src="{dessin_uri}" alt="" />
        {dt_html}
        {da_html}
    </div>"""

    if not cover_content:
        cover_content = '<div class="cover-highlights">'
        for art in articles[:4]:
            cat_hl = (f'<div class="cover-hl-cat">{art.get("category", "")}</div>'
                      if art.get("category") else "")
            auth_hl = (f'<div class="cover-hl-author">{art.get("author", "")}</div>'
                       if art.get("author") else "")
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

    # Full HTML — reusing the exact A4 Premium CSS from the original
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
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
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, "Times New Roman", serif;
        font-size: 10pt; line-height: 1.55; color: #1a1a1a;
        text-align: justify; hyphens: auto; -webkit-hyphens: auto;
        orphans: 3; widows: 3;
    }}
    .cover {{
        page-break-after: always; width: 210mm; height: 297mm;
        display: flex; flex-direction: column; justify-content: center;
        align-items: center; text-align: center; background: #faf9f7;
        padding: 30mm 25mm; position: relative;
    }}
    .cover::before {{
        content: ""; position: absolute; top: 20mm; left: 25mm; right: 25mm;
        height: 0.8pt; background: #1a1a1a;
    }}
    .cover::after {{
        content: ""; position: absolute; bottom: 20mm; left: 25mm; right: 25mm;
        height: 0.8pt; background: #1a1a1a;
    }}
    .cover-banner {{
        background: #1a1a1a; padding: 6mm 10mm; margin-bottom: 8mm;
        width: 80mm; text-align: center;
    }}
    .cover-banner .cover-logo {{ width: 55mm; height: auto; }}
    .cover-logo-light {{ width: 55mm; height: auto; margin-bottom: 6mm; }}
    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 36pt;
        font-weight: 700; letter-spacing: 0.12em; color: #1a1a1a;
        margin-bottom: 2mm; text-transform: uppercase;
    }}
    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 12pt;
        font-style: italic; color: #666; letter-spacing: 0.06em;
        margin-bottom: 10mm;
    }}
    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt; font-weight: 600; color: #333;
        text-transform: uppercase; letter-spacing: 0.15em;
        padding: 2.5mm 8mm; border-top: 0.5pt solid #1a1a1a;
        border-bottom: 0.5pt solid #1a1a1a; margin-bottom: 14mm;
    }}
    .cover-tagline {{
        font-size: 9pt; color: #888; font-style: italic; margin-bottom: 10mm;
    }}
    .cover-highlights {{
        margin-top: 8mm; text-align: left; max-width: 140mm;
    }}
    .cover-hl {{
        display: flex; align-items: center; gap: 4mm;
        margin-bottom: 4mm; padding-bottom: 4mm;
        border-bottom: 0.3pt solid #ccc;
    }}
    .cover-hl:last-child {{ border-bottom: none; }}
    .cover-hl-thumb {{ width: 22mm; height: 16mm; object-fit: cover; flex-shrink: 0; }}
    .cover-hl-text {{ flex: 1; min-width: 0; }}
    .cover-hl-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.12em; color: #999; margin-bottom: 1mm;
    }}
    .cover-hl-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 11pt;
        font-weight: 700; line-height: 1.25; color: #1a1a1a;
    }}
    .cover-hl-author {{ font-size: 8pt; font-style: italic; color: #777; margin-top: 1mm; }}
    .cover-dessin {{ margin-top: 6mm; text-align: center; }}
    .cover-dessin-label {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.15em; color: #999; margin-bottom: 4mm;
    }}
    .cover-dessin-img {{ max-width: 120mm; max-height: 120mm; width: auto; height: auto; object-fit: contain; }}
    .cover-dessin-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 10pt;
        font-weight: 700; color: #1a1a1a; margin-top: 3mm; line-height: 1.3;
    }}
    .cover-dessin-artist {{ font-size: 8pt; font-style: italic; color: #777; margin-top: 1mm; }}
    .toc-page {{ page-break-after: always; padding-top: 5mm; }}
    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.2em; color: #999; margin-bottom: 6mm;
        padding-bottom: 2mm; border-bottom: 0.8pt solid #1a1a1a;
    }}
    .toc-entry {{
        display: flex; align-items: baseline; margin-bottom: 4mm;
        padding-bottom: 4mm; border-bottom: 0.3pt solid #e0e0e0;
        text-decoration: none; color: inherit;
    }}
    .toc-entry:last-child {{ border-bottom: none; }}
    .toc-entry::before {{
        content: target-counter(attr(href), page);
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt; font-weight: 300; color: #555; min-width: 12mm;
        line-height: 1;
    }}
    .toc-details {{ flex: 1; display: block; }}
    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.1em; color: #999; display: block; margin-bottom: 0.5mm;
    }}
    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 11pt;
        font-weight: 700; line-height: 1.3; color: #1a1a1a; display: block;
    }}
    .toc-author {{ font-size: 8.5pt; font-style: italic; color: #777; display: block; margin-top: 0.5mm; }}
    .pm-article {{ page-break-before: always; }}
    .pm-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.15em; color: #888; margin-bottom: 3mm;
    }}
    .pm-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 22pt;
        font-weight: 700; line-height: 1.15; color: #1a1a1a;
        margin-bottom: 3mm; letter-spacing: -0.01em;
    }}
    .pm-author {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 9pt;
        font-style: italic; color: #666; margin-bottom: 4mm;
    }}
    .pm-rule-thin {{ height: 0.5pt; background: #ccc; margin-bottom: 5mm; }}
    .pm-hero-img {{ margin-bottom: 5mm; text-align: center; }}
    .pm-hero-img img {{ width: 100%; height: auto; max-height: 85mm; object-fit: cover; display: block; }}
    .pm-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; color: #999; font-style: italic; margin-top: 1.5mm;
        text-align: right;
    }}
    .pm-lead {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 11pt;
        font-weight: 600; line-height: 1.4; color: #333; margin-bottom: 5mm;
        padding-bottom: 4mm; border-bottom: 0.3pt solid #ddd;
    }}
    .pm-body {{
        column-count: 2; column-gap: 7mm; column-rule: 0.3pt solid #e5e5e5;
        font-size: 9.5pt; line-height: 1.55;
    }}
    .pm-body p {{ margin-bottom: 0.5em; text-indent: 1.2em; }}
    .pm-body p:first-child {{ text-indent: 0; }}
    .drop-cap {{
        float: left; font-family: "DejaVu Serif", Georgia, serif;
        font-size: 42pt; line-height: 0.75; padding-right: 2mm;
        padding-top: 2mm; color: #1a1a1a; font-weight: 700;
    }}
    .pm-body h2, .pm-body h3, .pm-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 10pt; font-weight: 700; margin-top: 1em;
        margin-bottom: 0.4em; text-indent: 0; column-span: none; color: #333;
    }}
    .pm-body blockquote {{
        margin: 0.8em 0; padding: 0.5em 0.8em;
        border-left: 2.5pt solid #d0d0d0; color: #444;
        font-style: italic; font-size: 9.5pt; background: #faf9f7;
    }}
    .pm-body blockquote p {{ text-indent: 0 !important; margin-bottom: 0.3em; }}
    .colophon {{
        page-break-before: always; display: flex; flex-direction: column;
        justify-content: center; align-items: center; text-align: center;
        height: 100%;
    }}
    .colophon-logo {{ width: 35mm; height: auto; margin-bottom: 8mm; opacity: 0.4; }}
    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt; color: #aaa; line-height: 1.8;
    }}
    .colophon-rule {{ width: 30mm; height: 0.5pt; background: #ccc; margin: 6mm auto; }}
</style>
</head>
<body>
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>
    {cover_content}
</div>
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    {toc_items}
</div>
{articles_html}
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

    print(f"  Génération PDF (A4 Premium)...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {output_path.name} ({size_mb:.1f} Mo)")


# ══════════════════════════════════════════════════════════════════════════
#  PDF GENERATION — A4 Éditorial (Kinfolk, single column)
# ══════════════════════════════════════════════════════════════════════════

def generate_editorial_pdf(articles, edition_title, date_str, output_path,
                           session, logo_light_uri, logo_dark_uri,
                           dessin_info, image_cache):
    """Generate a single-column A4 editorial PDF (Kinfolk style)."""
    from weasyprint import HTML

    print("  Préparation de l'édition A4 Éditorial...")

    # Build articles HTML
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

        image_html = ""
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            data_uri = image_cache.get(hires) or image_cache.get(img_url)
            if data_uri:
                cap = art.get("image_caption", "")
                cap_html = (f'<div class="ed-img-caption">{cap}</div>'
                            if cap else "")
                image_html = f'''
                <div class="ed-hero-img">
                    <img src="{data_uri}" alt="" />
                    {cap_html}
                </div>'''

        body_html = _add_drop_cap_html(art.get("content_html", ""))

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

    # Cover logo
    if logo_dark_uri:
        logo_html = f'''
        <div class="cover-banner">
            <img class="cover-logo" src="{logo_dark_uri}" alt="Antithèse" />
        </div>'''
    elif logo_light_uri:
        logo_html = f'<img class="cover-logo-light" src="{logo_light_uri}" alt="Antithèse" />'
    else:
        logo_html = '<h1 class="cover-title-fallback">ANTITHÈSE</h1>'

    if logo_light_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_light_uri}" alt="" />'
    elif logo_dark_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_dark_uri}" alt="" />'
    else:
        colophon_logo = ""

    # TOC
    toc_items = ""
    for idx, art in enumerate(articles):
        cat = (f'<span class="toc-cat">{art.get("category", "")}</span>'
               if art.get("category") else "")
        auth = (f'<span class="toc-author">{art.get("author", "")}</span>'
                if art.get("author") else "")
        toc_items += f"""
        <a class="toc-entry" href="#art-{idx}">
            <span class="toc-details">
                {cat}
                <span class="toc-title">{art.get("title", "")}</span>
                {auth}
            </span>
        </a>"""

    # Cover content
    cover_content = ""
    if dessin_info:
        dessin_uri = download_image_as_data_uri(session,
                                                 dessin_info["image_url"])
        if not dessin_uri and dessin_info.get("image_url_fallback"):
            dessin_uri = download_image_as_data_uri(
                session, dessin_info["image_url_fallback"])
        if dessin_uri:
            dt_html = ""
            if dessin_info.get("title"):
                dt_html = f'<div class="cover-dessin-title">{dessin_info["title"]}</div>'
            da_html = ""
            if dessin_info.get("artist"):
                da_html = f'<div class="cover-dessin-artist">{dessin_info["artist"]}</div>'
            cover_content = f"""
    <div class="cover-dessin">
        <div class="cover-dessin-label">Le dessin de la semaine</div>
        <img class="cover-dessin-img" src="{dessin_uri}" alt="" />
        {dt_html}
        {da_html}
    </div>"""

    if not cover_content:
        if articles:
            feat = articles[0]
            feat_cat = (f'<div class="cover-feat-cat">{feat.get("category", "")}</div>'
                        if feat.get("category") else "")
            feat_auth = (f'<div class="cover-feat-author">{feat.get("author", "")}</div>'
                         if feat.get("author") else "")
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

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: 210mm 297mm;
        margin: 28mm 30mm 30mm 30mm;
        @bottom-center {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 7pt; color: #b0b0b0; letter-spacing: 0.1em;
        }}
    }}
    @page :first {{
        margin: 0;
        @bottom-center {{ content: none; }}
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, "Times New Roman", serif;
        font-size: 11pt; line-height: 1.7; color: #2a2a2a;
        text-align: justify; hyphens: auto; -webkit-hyphens: auto;
        orphans: 3; widows: 3;
    }}
    .cover {{
        page-break-after: always; width: 210mm; height: 297mm;
        display: flex; flex-direction: column; justify-content: center;
        align-items: center; text-align: center; background: #ffffff;
        padding: 35mm 30mm; position: relative;
    }}
    .cover::before {{
        content: ""; position: absolute; top: 22mm; left: 30mm; right: 30mm;
        height: 0.5pt; background: #2a2a2a;
    }}
    .cover::after {{
        content: ""; position: absolute; bottom: 22mm; left: 30mm; right: 30mm;
        height: 0.5pt; background: #2a2a2a;
    }}
    .cover-banner {{
        background: #2a2a2a; padding: 6mm 10mm; margin-bottom: 12mm;
        width: 80mm; text-align: center;
    }}
    .cover-banner .cover-logo {{ width: 55mm; height: auto; }}
    .cover-logo-light {{ width: 55mm; height: auto; margin-bottom: 10mm; }}
    .cover-title-fallback {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 36pt;
        font-weight: 700; letter-spacing: 0.15em; color: #2a2a2a;
        margin-bottom: 3mm; text-transform: uppercase;
    }}
    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 11pt;
        font-style: italic; color: #888; letter-spacing: 0.08em;
        margin-bottom: 14mm;
    }}
    .cover-edition {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt; font-weight: 400; color: #555;
        text-transform: uppercase; letter-spacing: 0.25em;
        padding: 3mm 10mm; border-top: 0.4pt solid #2a2a2a;
        border-bottom: 0.4pt solid #2a2a2a; margin-bottom: 18mm;
    }}
    .cover-tagline {{
        font-size: 8.5pt; color: #aaa; font-style: italic;
        letter-spacing: 0.05em; margin-bottom: 14mm;
    }}
    .cover-featured {{ margin-top: 6mm; text-align: center; max-width: 130mm; }}
    .cover-feat-img {{
        max-width: 110mm; max-height: 80mm; width: auto; height: auto;
        object-fit: contain; margin-bottom: 6mm;
    }}
    .cover-feat-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.2em; color: #aaa; margin-bottom: 3mm;
    }}
    .cover-feat-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 16pt;
        font-weight: 700; line-height: 1.25; color: #2a2a2a; margin-bottom: 3mm;
    }}
    .cover-feat-author {{ font-size: 9pt; font-style: italic; color: #999; }}
    .cover-dessin {{ margin-top: 6mm; text-align: center; }}
    .cover-dessin-label {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.2em; color: #aaa; margin-bottom: 5mm;
    }}
    .cover-dessin-img {{ max-width: 115mm; max-height: 115mm; width: auto; height: auto; object-fit: contain; }}
    .cover-dessin-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 10pt;
        font-weight: 700; color: #2a2a2a; margin-top: 4mm; line-height: 1.3;
    }}
    .cover-dessin-artist {{ font-size: 8pt; font-style: italic; color: #999; margin-top: 1mm; }}
    .toc-page {{ page-break-after: always; padding-top: 8mm; }}
    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt; font-weight: 400; text-transform: uppercase;
        letter-spacing: 0.3em; color: #aaa; margin-bottom: 10mm;
        padding-bottom: 3mm; border-bottom: 0.5pt solid #2a2a2a;
    }}
    .toc-entry {{
        display: flex; align-items: baseline; margin-bottom: 5mm;
        padding-bottom: 5mm; border-bottom: 0.25pt solid #e8e8e8;
        text-decoration: none; color: inherit;
    }}
    .toc-entry:last-child {{ border-bottom: none; }}
    .toc-entry::before {{
        content: target-counter(attr(href), page);
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 16pt; font-weight: 300; color: #ccc; min-width: 14mm;
        line-height: 1;
    }}
    .toc-details {{ flex: 1; display: block; }}
    .toc-cat {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 6.5pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.15em; color: #b0b0b0; display: block; margin-bottom: 1mm;
    }}
    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 11pt;
        font-weight: 700; line-height: 1.3; color: #2a2a2a; display: block;
    }}
    .toc-author {{ font-size: 8.5pt; font-style: italic; color: #999; display: block; margin-top: 1mm; }}
    .ed-article {{ page-break-before: always; }}
    .ed-article-header {{ text-align: center; margin-bottom: 6mm; }}
    .ed-category {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.25em; color: #b0b0b0; margin-bottom: 5mm;
    }}
    .ed-title {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 26pt;
        font-weight: 700; line-height: 1.15; color: #2a2a2a;
        margin-bottom: 5mm; letter-spacing: -0.02em;
    }}
    .ed-author {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8.5pt; font-weight: 400; text-transform: uppercase;
        letter-spacing: 0.15em; color: #999;
    }}
    .ed-rule {{ width: 30mm; height: 0.5pt; background: #2a2a2a; margin: 0 auto 7mm auto; }}
    .ed-hero-img {{ margin-bottom: 7mm; text-align: center; }}
    .ed-hero-img img {{ width: 100%; height: auto; max-height: 100mm; object-fit: cover; display: block; }}
    .ed-img-caption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt; color: #b0b0b0; font-style: italic;
        margin-top: 2mm; text-align: right;
    }}
    .ed-lead {{
        font-family: "DejaVu Serif", Georgia, serif; font-size: 12pt;
        font-weight: 400; font-style: italic; line-height: 1.5; color: #555;
        margin-bottom: 7mm; padding-bottom: 5mm;
        border-bottom: 0.25pt solid #ddd; text-align: center;
    }}
    .ed-body {{ font-size: 11pt; line-height: 1.7; }}
    .ed-body p {{ margin-bottom: 0.6em; text-indent: 1.5em; }}
    .ed-body p:first-child {{ text-indent: 0; }}
    .drop-cap {{
        float: left; font-family: "DejaVu Serif", Georgia, serif;
        font-size: 48pt; line-height: 0.72; padding-right: 2.5mm;
        padding-top: 2.5mm; color: #2a2a2a; font-weight: 700;
    }}
    .ed-body h2, .ed-body h3, .ed-body h4 {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt; font-weight: 700; margin-top: 1.5em;
        margin-bottom: 0.5em; text-indent: 0; color: #2a2a2a;
        letter-spacing: 0.02em;
    }}
    .ed-body blockquote {{
        margin: 1.5em 10mm; padding: 1em 0; border-left: none;
        border-top: 0.5pt solid #ccc; border-bottom: 0.5pt solid #ccc;
        color: #555; font-style: italic; font-size: 12pt;
        line-height: 1.5; text-align: center;
    }}
    .ed-body blockquote p {{ text-indent: 0 !important; margin-bottom: 0.3em; }}
    .ed-article-end {{ text-align: center; margin-top: 8mm; font-size: 8pt; color: #ccc; letter-spacing: 0.3em; }}
    .colophon {{
        page-break-before: always; display: flex; flex-direction: column;
        justify-content: center; align-items: center; text-align: center;
        height: 100%;
    }}
    .colophon-logo {{ width: 30mm; height: auto; margin-bottom: 10mm; opacity: 0.3; }}
    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt; color: #b0b0b0; line-height: 2; letter-spacing: 0.05em;
    }}
    .colophon-rule {{ width: 25mm; height: 0.4pt; background: #ddd; margin: 8mm auto; }}
</style>
</head>
<body>
<div class="cover">
    {logo_html}
    <div class="cover-subtitle">Bon pour la tête</div>
    <div class="cover-edition">{edition_title}</div>
    <div class="cover-tagline">Un média indépendant et a-partisan</div>
    {cover_content}
</div>
<div class="toc-page">
    <div class="toc-header">Sommaire</div>
    {toc_items}
</div>
{articles_html}
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

    print(f"  Génération PDF (A4 Éditorial)...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {output_path.name} ({size_mb:.1f} Mo)")


# ══════════════════════════════════════════════════════════════════════════
#  EPUB GENERATION (built with zipfile — no external epub lib needed)
# ══════════════════════════════════════════════════════════════════════════

def _epub_uid():
    return str(uuid4())


def generate_epub(articles, edition_title, date_str, output_path,
                  session, image_cache):
    """Generate a well-formatted EPUB 3 ebook.

    Built manually with zipfile to avoid extra dependencies.
    Structure: mimetype, META-INF/container.xml, OEBPS/content.opf,
    OEBPS/toc.xhtml, OEBPS/style.css, OEBPS/chapter-N.xhtml, images.
    """
    print("  Préparation de l'EPUB...")

    book_uid = _epub_uid()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect images for embedding
    epub_images = {}  # filename -> (bytes, media_type)
    img_counter = 0

    def get_epub_image(img_url):
        """Download image and return epub filename, or None."""
        nonlocal img_counter
        if not img_url:
            return None
        hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
        for url in (hires, img_url):
            result = download_image_bytes(session, url)
            if result:
                img_data, ctype = result
                ext = "jpg"
                if "png" in ctype:
                    ext = "png"
                elif "gif" in ctype:
                    ext = "gif"
                elif "webp" in ctype:
                    ext = "webp"
                elif "svg" in ctype:
                    ext = "svg"
                img_counter += 1
                fname = f"img-{img_counter:03d}.{ext}"
                epub_images[fname] = (img_data, ctype)
                return fname
        return None

    # CSS for the ebook
    epub_css = """/* Antithèse EPUB Stylesheet */
body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.6;
    color: #1a1a1a;
    margin: 0;
    padding: 0;
}

h1 {
    font-size: 1.8em;
    font-weight: 700;
    line-height: 1.15;
    margin: 0 0 0.3em 0;
    text-align: left;
}

h2 {
    font-size: 1.4em;
    font-weight: 700;
    line-height: 1.2;
    margin: 1.2em 0 0.4em 0;
}

h3 {
    font-size: 1.1em;
    font-weight: 700;
    margin: 1em 0 0.3em 0;
}

p {
    margin: 0 0 0.6em 0;
    text-align: justify;
    text-indent: 1.2em;
}

p.first, p.lead {
    text-indent: 0;
}

p.lead {
    font-weight: 600;
    font-size: 1.05em;
    color: #333;
    margin-bottom: 1em;
    padding-bottom: 0.8em;
    border-bottom: 1px solid #ddd;
}

.category {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #888;
    margin-bottom: 0.3em;
}

.author {
    font-style: italic;
    font-size: 0.9em;
    color: #666;
    margin-bottom: 0.8em;
}

.separator {
    text-align: center;
    margin: 1em 0;
    color: #ccc;
    font-size: 0.8em;
    letter-spacing: 0.3em;
}

.hero-img {
    text-align: center;
    margin: 0.8em 0;
}

.hero-img img {
    max-width: 100%;
    height: auto;
}

.img-caption {
    font-size: 0.75em;
    color: #999;
    font-style: italic;
    text-align: right;
    margin-top: 0.3em;
    text-indent: 0;
}

blockquote {
    margin: 1em 1.5em;
    padding: 0.5em 0;
    border-top: 1px solid #ccc;
    border-bottom: 1px solid #ccc;
    font-style: italic;
    color: #555;
    text-align: center;
}

blockquote p {
    text-indent: 0;
    text-align: center;
}

.drop-cap {
    font-size: 2.8em;
    float: left;
    line-height: 0.8;
    padding-right: 0.08em;
    padding-top: 0.05em;
    font-weight: 700;
    color: #1a1a1a;
}

/* Title page */
.title-page {
    text-align: center;
    padding: 3em 1em;
}

.title-page h1 {
    font-size: 2em;
    text-align: center;
    margin-bottom: 0.5em;
}

.title-page .subtitle {
    font-style: italic;
    color: #666;
    font-size: 1.1em;
    margin-bottom: 1.5em;
}

.title-page .edition {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 0.9em;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: #555;
    padding: 0.4em 0;
    border-top: 1px solid #1a1a1a;
    border-bottom: 1px solid #1a1a1a;
    display: inline-block;
    margin-bottom: 2em;
}

.title-page .tagline {
    font-style: italic;
    color: #aaa;
    font-size: 0.85em;
}

/* TOC page */
.toc h2 {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: #999;
    border-bottom: 2px solid #1a1a1a;
    padding-bottom: 0.4em;
    margin-bottom: 1em;
}

.toc ol {
    list-style: none;
    padding: 0;
    margin: 0;
}

.toc li {
    margin-bottom: 0.8em;
    padding-bottom: 0.8em;
    border-bottom: 1px solid #eee;
}

.toc li:last-child {
    border-bottom: none;
}

.toc a {
    text-decoration: none;
    color: inherit;
}

.toc .toc-title {
    font-weight: 700;
    font-size: 1em;
    line-height: 1.3;
    display: block;
}

.toc .toc-cat {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 0.7em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #999;
    display: block;
    margin-bottom: 0.2em;
}

.toc .toc-author {
    font-size: 0.85em;
    font-style: italic;
    color: #777;
    display: block;
    margin-top: 0.2em;
}

.article-end {
    text-align: center;
    margin-top: 2em;
    font-size: 0.8em;
    color: #ccc;
    letter-spacing: 0.3em;
}
"""

    # ── Build chapter XHTML for each article ──────────────────────────
    chapters = []  # list of (filename, title, xhtml_content)

    for i, art in enumerate(articles):
        parts = []

        # Category
        if art.get("category"):
            parts.append(
                f'<p class="category">{xml_escape(art["category"])}</p>')

        # Title
        parts.append(
            f'<h1>{xml_escape(art.get("title", "Sans titre"))}</h1>')

        # Author
        if art.get("author"):
            parts.append(
                f'<p class="author">Par {xml_escape(art["author"])}</p>')

        parts.append('<div class="separator">---</div>')

        # Hero image
        img_url = art.get("image_url") or art.get("thumb_url")
        if img_url:
            img_fname = get_epub_image(img_url)
            if img_fname:
                parts.append(f'<div class="hero-img">'
                             f'<img src="{img_fname}" alt="" />'
                             f'</div>')
                if art.get("image_caption"):
                    parts.append(
                        f'<p class="img-caption">'
                        f'{xml_escape(art["image_caption"])}</p>')

        # Lead
        if art.get("lead"):
            parts.append(f'<p class="lead">{xml_escape(art["lead"])}</p>')

        # Body — convert from HTML fragments to clean XHTML
        body = art.get("content_html", "")
        if body:
            # Add drop cap to first <p>
            body = _add_drop_cap_html(body)
            # Mark first paragraph
            body = re.sub(r"<p>", '<p class="first">', body, count=1)
            parts.append(body)

        parts.append('<p class="article-end">&#9830;</p>')

        chapter_body = "\n".join(parts)
        fname = f"chapter-{i+1:02d}.xhtml"
        xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr" lang="fr">
<head>
<meta charset="UTF-8"/>
<title>{xml_escape(art.get("title", "Sans titre"))}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
{chapter_body}
</body>
</html>"""
        chapters.append((fname, art.get("title", "Sans titre"), xhtml))

    # ── Title page ────────────────────────────────────────────────────
    title_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr" lang="fr">
<head>
<meta charset="UTF-8"/>
<title>Antithèse</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<div class="title-page">
    <h1>ANTITHÈSE</h1>
    <p class="subtitle">Bon pour la tête</p>
    <p class="edition">{xml_escape(edition_title)}</p>
    <p class="tagline">Un média indépendant et a-partisan</p>
</div>
</body>
</html>"""

    # ── TOC page ──────────────────────────────────────────────────────
    toc_items = ""
    for i, (fname, title, _) in enumerate(chapters):
        art = articles[i]
        cat = ""
        if art.get("category"):
            cat = f'<span class="toc-cat">{xml_escape(art["category"])}</span>'
        auth = ""
        if art.get("author"):
            auth = f'<span class="toc-author">{xml_escape(art["author"])}</span>'
        toc_items += f"""<li><a href="{fname}">
            {cat}
            <span class="toc-title">{xml_escape(title)}</span>
            {auth}
        </a></li>\n"""

    toc_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="fr" lang="fr">
<head>
<meta charset="UTF-8"/>
<title>Sommaire</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<nav epub:type="toc" class="toc">
    <h2>Sommaire</h2>
    <ol>
        {toc_items}
    </ol>
</nav>
</body>
</html>"""

    # ── content.opf ───────────────────────────────────────────────────
    manifest_items = """    <item id="style" href="style.css" media-type="text/css"/>
    <item id="title-page" href="title.xhtml" media-type="application/xhtml+xml"/>
    <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>
"""
    spine_items = """    <itemref idref="title-page"/>
    <itemref idref="toc"/>
"""
    for i, (fname, _, _) in enumerate(chapters):
        manifest_items += f'    <item id="ch-{i+1}" href="{fname}" media-type="application/xhtml+xml"/>\n'
        spine_items += f'    <itemref idref="ch-{i+1}"/>\n'

    for fname, (_, ctype) in epub_images.items():
        safe_id = fname.replace(".", "-").replace(" ", "-")
        manifest_items += f'    <item id="{safe_id}" href="{fname}" media-type="{ctype}"/>\n'

    content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:{book_uid}</dc:identifier>
    <dc:title>Antithèse — {xml_escape(edition_title)}</dc:title>
    <dc:language>fr</dc:language>
    <dc:publisher>Antithèse / Bon pour la tête</dc:publisher>
    <dc:date>{date_str}</dc:date>
    <meta property="dcterms:modified">{datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>
</metadata>
<manifest>
{manifest_items}</manifest>
<spine>
{spine_items}</spine>
</package>"""

    # ── container.xml ─────────────────────────────────────────────────
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    # ── Write EPUB zip ────────────────────────────────────────────────
    with zipfile.ZipFile(str(output_path), "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype MUST be first and uncompressed
        zf.writestr("mimetype", "application/epub+zip",
                     compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", content_opf)
        zf.writestr("OEBPS/style.css", epub_css)
        zf.writestr("OEBPS/title.xhtml", title_xhtml)
        zf.writestr("OEBPS/toc.xhtml", toc_xhtml)
        for fname, _, xhtml in chapters:
            zf.writestr(f"OEBPS/{fname}", xhtml)
        for fname, (img_data, _) in epub_images.items():
            zf.writestr(f"OEBPS/{fname}", img_data)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {output_path.name} ({size_mb:.1f} Mo)")


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    if not sys.stdin.isatty():
        print("Ce script est interactif et nécessite un terminal.")
        sys.exit(1)

    clear_screen()
    print_banner()

    # 1. Credentials
    username, password = prompt_credentials()

    # 2. Output formats
    formats = prompt_format_selection()

    # 3. Output directory
    out_dir = prompt_output_dir()

    # 4. Session & login
    print("  ── Connexion ─────────────────────────────────────────────────")
    print()
    session = requests.Session()
    session.headers.update(HEADERS)

    if not login(session, username, password):
        retry = input("\n  Réessayer ? [O/n] : ").strip().lower()
        if retry in ("n", "non", "no"):
            sys.exit(1)
        username, password = prompt_credentials()
        if not login(session, username, password):
            print("  Échec de connexion. Abandon.")
            sys.exit(1)

    # 5. Download logo
    print()
    logo_dark_uri, logo_light_uri = download_logo(session)

    # 6. Scrape edition
    print()
    print("  ── Récupération de l'édition ──────────────────────────────────")
    print()
    date_str, article_list, dessin_info = get_edition_info(session)

    if not article_list:
        print("  Aucun article trouvé dans l'édition.")
        sys.exit(1)

    # Parse edition date for Pilet filtering
    try:
        edition_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        edition_date = datetime.now()

    # 7. Fetch articles
    print(f"\n  Téléchargement de {len(article_list)} articles...")
    full_articles = []
    pilet_filtered = 0
    for i, art_meta in enumerate(article_list, 1):
        print(f"    [{i}/{len(article_list)}] {art_meta['title'][:60]}...")
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
                print(f"      Contenu vide, ignoré.")
                continue

            if art_meta.get("is_pilet") and article.get("pub_date"):
                try:
                    pub = datetime.strptime(article["pub_date"], "%Y-%m-%d")
                    days_before = (edition_date - pub).days
                    if days_before > 7:
                        pilet_filtered += 1
                        print(f"      Pilet ancien ({article['pub_date']}), ignoré.")
                        continue
                except ValueError:
                    pass

            full_articles.append(article)
        except Exception as e:
            print(f"      Erreur: {e}")

    if pilet_filtered:
        print(f"  {pilet_filtered} article(s) Pilet antérieur(s) à 7 jours filtré(s)")

    if not full_articles:
        print("  Aucun article récupéré avec succès.")
        sys.exit(1)

    print(f"\n  {len(full_articles)} articles récupérés.\n")

    # 8. Interactive article selection
    full_articles = interactive_article_selector(full_articles)

    # 9. Build image cache (shared across formats)
    print()
    print("  ── Téléchargement des images ──────────────────────────────────")
    print()
    image_cache = build_image_cache(session, full_articles)

    # 10. Edition title
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

    # 11. Generate outputs
    print()
    print("  ── Génération des fichiers ────────────────────────────────────")
    print()
    generated = []

    for fmt_key in formats:
        if fmt_key == "a4premium":
            path = out_dir / f"{date_str}-antithese_A4_premium.pdf"
            generate_premium_pdf(
                full_articles, edition_title, date_str, path,
                session, logo_light_uri, logo_dark_uri,
                dessin_info, image_cache)
            generated.append(("A4 Premium", path))

        elif fmt_key == "a4editorial":
            path = out_dir / f"{date_str}-antithese_A4_editorial.pdf"
            generate_editorial_pdf(
                full_articles, edition_title, date_str, path,
                session, logo_light_uri, logo_dark_uri,
                dessin_info, image_cache)
            generated.append(("A4 Éditorial", path))

        elif fmt_key == "epub":
            path = out_dir / f"{date_str}-antithese.epub"
            generate_epub(
                full_articles, edition_title, date_str, path,
                session, image_cache)
            generated.append(("EPUB", path))

    # 12. Summary
    print()
    print("  ══════════════════════════════════════════════════════════════")
    print(f"  Terminé ! {len(generated)} fichier(s) généré(s) :")
    print()
    for label, path in generated:
        size = path.stat().st_size / (1024 * 1024)
        print(f"    {label}: {path.name} ({size:.1f} Mo)")
    print()
    print(f"  Dossier : {out_dir}")
    print("  ══════════════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    main()
