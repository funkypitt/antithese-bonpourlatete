#!/usr/bin/env python3
"""
Le Temps Daily Edition Scraper & PDF Generator (v3 — Enhanced)
================================================================
Downloads today's articles from letemps.ch and generates beautifully
formatted PDF digests for phone, e-reader, tablet (7" & 10") and
a premium A4 "magazine" edition with photos and New Yorker-style layout.

Requirements:
    pip install playwright beautifulsoup4 weasyprint requests lxml
    playwright install chromium

Usage:
    export LETEMPS_USER="your_email@example.com"
    export LETEMPS_PASS="your_password"
    python3 letemps_scraper.py

    python3 letemps_scraper.py --user EMAIL --password PASS
    python3 letemps_scraper.py --date 2026-02-10
    python3 letemps_scraper.py --format a4premium
    python3 letemps_scraper.py --no-headless   # debug: show browser
"""

import base64
import os
import sys
import re
import json
import time
import logging
import argparse
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests as req_lib
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path.home() / "kDrive" / "newspapers" / "journaux_du_jour"

# ---------------------------------------------------------------------------
# Format profiles (all dimensions in mm / pt)
# ---------------------------------------------------------------------------
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
        "logo_size": "13pt",
        "logo_subtitle_size": "6pt",
        "banner_rule_width": "22mm",
        "img_max_height": "35mm",
        "drop_cap_size": "22pt",
        "drop_cap_padding": "1mm",
        "toc_num_size": "11pt",
        "toc_num_width": "7mm",
        "toc_title_size": "8pt",
        "toc_sec_size": "6pt",
        "toc_author_size": "7pt",
        "cover_date_size": "7pt",
        "cover_hl_title_size": "8pt",
        "cover_hl_sec_size": "6pt",
        "cover_padding": "8mm 6mm",
        "colophon_logo_size": "10pt",
        "colophon_font_size": "6.5pt",
        "caption_size": "6pt",
        "meta_size": "6.5pt",
        "lead_size": "8pt",
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
        "logo_size": "16pt",
        "logo_subtitle_size": "6.5pt",
        "banner_rule_width": "28mm",
        "img_max_height": "42mm",
        "drop_cap_size": "26pt",
        "drop_cap_padding": "1.2mm",
        "toc_num_size": "13pt",
        "toc_num_width": "8mm",
        "toc_title_size": "9pt",
        "toc_sec_size": "6.5pt",
        "toc_author_size": "7.5pt",
        "cover_date_size": "8pt",
        "cover_hl_title_size": "9pt",
        "cover_hl_sec_size": "6.5pt",
        "cover_padding": "10mm 8mm",
        "colophon_logo_size": "12pt",
        "colophon_font_size": "7pt",
        "caption_size": "6.5pt",
        "meta_size": "7pt",
        "lead_size": "9pt",
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
        "logo_size": "19pt",
        "logo_subtitle_size": "7pt",
        "banner_rule_width": "35mm",
        "img_max_height": "55mm",
        "drop_cap_size": "30pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "14pt",
        "toc_num_width": "9mm",
        "toc_title_size": "9.5pt",
        "toc_sec_size": "6.5pt",
        "toc_author_size": "8pt",
        "cover_date_size": "8.5pt",
        "cover_hl_title_size": "9.5pt",
        "cover_hl_sec_size": "6.5pt",
        "cover_padding": "15mm 10mm",
        "colophon_logo_size": "14pt",
        "colophon_font_size": "7pt",
        "caption_size": "6.5pt",
        "meta_size": "7pt",
        "lead_size": "9.5pt",
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
        "logo_size": "22pt",
        "logo_subtitle_size": "7.5pt",
        "banner_rule_width": "42mm",
        "img_max_height": "70mm",
        "drop_cap_size": "34pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "16pt",
        "toc_num_width": "10mm",
        "toc_title_size": "10pt",
        "toc_sec_size": "7pt",
        "toc_author_size": "8pt",
        "cover_date_size": "9pt",
        "cover_hl_title_size": "10pt",
        "cover_hl_sec_size": "7pt",
        "cover_padding": "18mm 12mm",
        "colophon_logo_size": "16pt",
        "colophon_font_size": "7.5pt",
        "caption_size": "7pt",
        "meta_size": "7.5pt",
        "lead_size": "9pt",
    },
    "a4premium": {
        "label": "🖨️  A4 Premium (magazine)",
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
    "a4landscape": {
        "label": "🖨️  A4 Premium Paysage",
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

BASE_URL = "https://www.letemps.ch"

SECTIONS = [
    ("Suisse", "/suisse"),
    ("Monde", "/monde"),
    ("Économie", "/economie"),
    ("Opinions", "/opinions"),
    ("Sciences", "/sciences"),
    ("Société", "/societe"),
    ("Culture", "/culture"),
    ("Sport", "/sport"),
    ("Cyber", "/cyber"),
]

# Le Temps signature red
LETEMPS_RED = "#c62828"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("letemps")


@dataclass
class Article:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    date_published: str = ""
    section: str = ""
    body: str = ""
    lead: str = ""
    url: str = ""
    reading_time: str = ""
    image_url: str = ""
    image_caption: str = ""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def download_image_as_data_uri(url: str, session=None) -> Optional[str]:
    """Download an image and return it as a base64 data URI."""
    try:
        s = session or req_lib
        resp = s.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "svg" in content_type or url.endswith(".svg"):
            content_type = "image/svg+xml"
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        return None


def download_logo(session=None) -> Optional[str]:
    """Try to download Le Temps logo. Returns data URI or None."""
    logo_urls = [
        "https://www.letemps.ch/sites/default/files/media/2019/07/11/file72ov42p3pf81a2axxzrd.svg",
        "https://www.letemps.ch/themes/letemps/images/letemps.svg",
        "https://www.letemps.ch/themes/custom/flavor_letemps/logo.svg",
    ]
    for url in logo_urls:
        data = download_image_as_data_uri(url, session)
        if data:
            log.info("  ✅ Logo téléchargé")
            return data
    log.info("  ℹ️  Logo non trouvé, utilisation du texte.")
    return None


# ---------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------

class LeTempsSession:
    def __init__(self, email: str, password: str, headless: bool = True):
        self.email = email
        self.password = password
        self.headless = headless
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self.page = self.context.new_page()

    def close(self):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def login(self) -> bool:
        log.info("Connexion à letemps.ch...")
        try:
            self.page.goto(f"{BASE_URL}/compte/connexion",
                           wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)

            # Cookie banner
            self._dismiss_cookies()

            # Wait for form inputs (JS-rendered)
            log.info("  Attente du formulaire...")
            try:
                self.page.wait_for_selector('input', timeout=15000)
            except PWTimeout:
                log.error("  Aucun input trouvé")
                self._debug("login_no_input")
                return False

            time.sleep(1)

            # Debug: enumerate inputs
            inputs = self.page.evaluate("""
                () => Array.from(document.querySelectorAll('input')).map(i => ({
                    type: i.type, name: i.name, id: i.id,
                    placeholder: i.placeholder,
                    visible: i.offsetParent !== null,
                    autocomplete: i.autocomplete,
                }))
            """)
            log.info(f"  Inputs: {json.dumps(inputs, ensure_ascii=False)}")

            # Fill email
            if not self._fill_field([
                'input[type="email"]', 'input[name="email"]',
                'input[autocomplete="email"]', 'input[name="user[email]"]',
                'input[placeholder*="mail" i]', 'input[id*="email" i]',
            ], self.email, "email"):
                # Fallback: first visible text/email input
                vis = self.page.locator(
                    'input[type="text"]:visible, input[type="email"]:visible, '
                    'input:not([type]):visible'
                )
                if vis.count() > 0:
                    vis.first.click()
                    vis.first.fill(self.email)
                    log.info("  ✓ Email (fallback générique)")
                else:
                    log.error("  ✗ Champ email introuvable")
                    self._debug("login_no_email")
                    return False

            time.sleep(0.5)

            # Fill password
            if not self._fill_field([
                'input[type="password"]', 'input[name="password"]',
                'input[name="user[password]"]',
                'input[autocomplete="current-password"]',
            ], self.password, "mot de passe"):
                log.error("  ✗ Champ mot de passe introuvable")
                self._debug("login_no_pass")
                return False

            time.sleep(0.5)

            # Submit
            submitted = False
            for sel in [
                'button[type="submit"]', 'input[type="submit"]',
                'button:has-text("Connexion")', 'button:has-text("Se connecter")',
                'form button',
            ]:
                try:
                    btn = self.page.locator(sel).first
                    if btn.is_visible(timeout=1000):
                        btn.click()
                        submitted = True
                        log.info(f"  ✓ Submit via: {sel}")
                        break
                except Exception:
                    continue
            if not submitted:
                self.page.keyboard.press("Enter")
                log.info("  ✓ Submit via Enter")

            # Wait for result
            time.sleep(4)
            try:
                self.page.wait_for_load_state("networkidle", timeout=15000)
            except PWTimeout:
                pass

            url = self.page.url
            log.info(f"  URL après login: {url}")

            # Check for error
            body_text = self.page.evaluate("() => document.body.innerText")
            if any(err in body_text for err in [
                "Identifiants incorrects", "mot de passe incorrect",
                "Email ou mot de passe", "Invalid"
            ]):
                log.error("  ✗ Identifiants incorrects!")
                return False

            # If redirected away from login page → success
            if "/connexion" not in url:
                log.info("  ✓ Connexion réussie!")
                return True

            # Verify by navigating to a subscriber page
            self.page.goto(f"{BASE_URL}/compte", wait_until="networkidle",
                           timeout=15000)
            time.sleep(2)
            if "/connexion" not in self.page.url:
                log.info("  ✓ Connexion vérifiée via /compte")
                return True

            log.warning("  ⚠ État de connexion incertain")
            self._debug("login_uncertain")
            return True  # Try anyway

        except PWTimeout:
            log.error("  Timeout")
            self._debug("login_timeout")
            return False
        except Exception as e:
            log.error(f"  Erreur: {e}")
            self._debug("login_error")
            return False

    def _fill_field(self, selectors: list, value: str, label: str) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=1000):
                    loc.click()
                    loc.fill(value)
                    log.info(f"  ✓ {label} via: {sel}")
                    return True
            except Exception:
                continue
        return False

    def _dismiss_cookies(self):
        for sel in [
            "#didomi-notice-agree-button",
            'button:has-text("Tout accepter")',
            'button:has-text("Accepter")',
        ]:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    log.info("  ✓ Cookies acceptés")
                    time.sleep(1)
                    return
            except Exception:
                continue

    def _debug(self, name: str):
        try:
            path = f"/tmp/letemps_{name}.png"
            self.page.screenshot(path=path)
            log.info(f"  Screenshot: {path}")
        except Exception:
            pass

    def get_soup(self, url: str, wait_sel: str = None) -> Optional[BeautifulSoup]:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except PWTimeout:
                pass
            time.sleep(1.5)
            if wait_sel:
                try:
                    self.page.wait_for_selector(wait_sel, timeout=5000)
                except PWTimeout:
                    pass
            return BeautifulSoup(self.page.content(), "html.parser")
        except Exception as e:
            log.warning(f"  Erreur: {url} → {e}")
            return None


# ---------------------------------------------------------------------------
# Article discovery & parsing
# ---------------------------------------------------------------------------

def _extract_from_soup(soup: BeautifulSoup, target_date: date) -> list[str]:
    """Extract article URLs from a Le Temps page."""
    target_str = target_date.isoformat()
    urls = []

    for article in soup.find_all("article", class_=re.compile(r"post")):
        title_tag = article.find("h2", class_="post__title")
        if not title_tag:
            continue
        link = title_tag.find("a", href=True)
        if not link:
            continue

        href = link["href"]

        # Filter by publication date
        time_tag = article.find("time", class_="post__publication-date")
        if time_tag and time_tag.get("datetime", ""):
            if not time_tag["datetime"].startswith(target_str):
                continue

        slug = href.rstrip("/").split("/")[-1]
        if slug.count("-") < 2:
            continue

        if href.startswith("/"):
            href = f"{BASE_URL}{href}"

        if href not in urls:
            urls.append(href)
            log.debug(f"    + {link.get_text(strip=True)[:65]}")

    return urls


def find_article_urls(session: LeTempsSession, section_path: str,
                       target_date: date) -> list[str]:
    url = f"{BASE_URL}{section_path}"
    log.info(f"  Scan: {url}")
    soup = session.get_soup(url)
    if not soup:
        return []

    urls = _extract_from_soup(soup, target_date)

    log.info(f"    → {len(urls)} articles")
    return urls


def find_homepage_urls(session: LeTempsSession, target_date: date) -> list[str]:
    log.info("Scan page d'accueil + 'En continu'...")
    urls = []

    for page_url in [BASE_URL, f"{BASE_URL}/en-continu"]:
        soup = session.get_soup(page_url)
        if not soup:
            continue
        for u in _extract_from_soup(soup, target_date):
            if u not in urls:
                urls.append(u)

    log.info(f"  → {len(urls)} articles du jour")
    return urls


def parse_article(session: LeTempsSession, url: str,
                   section: str = "") -> Optional[Article]:
    soup = session.get_soup(url, wait_sel="h1")
    if not soup:
        return None

    art = Article(url=url, section=section)

    # --- JSON-LD (best source) ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("NewsArticle", "Article"):
                art.title = data.get("headline", "")
                art.subtitle = data.get("description", "")
                art.date_published = data.get("datePublished", "")
                authors = data.get("author", [])
                if isinstance(authors, dict):
                    authors = [authors]
                if isinstance(authors, list):
                    art.author = ", ".join(
                        a.get("name", "") for a in authors
                        if isinstance(a, dict) and a.get("name")
                    )
                # Extract image from JSON-LD
                img = data.get("image")
                if isinstance(img, list) and img:
                    img = img[0]
                if isinstance(img, dict):
                    art.image_url = img.get("url", "")
                elif isinstance(img, str):
                    art.image_url = img
                break
        except Exception:
            continue

    # --- Fallbacks ---
    if not art.title:
        h1 = soup.find("h1")
        if h1:
            art.title = h1.get_text(strip=True)
    if not art.title:
        return None

    if not art.subtitle:
        md = soup.find("meta", attrs={"name": "description"})
        if md:
            art.subtitle = md.get("content", "")

    # --- Image fallbacks ---
    if not art.image_url:
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            art.image_url = og_img["content"]

    if not art.image_url:
        twitter_img = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_img and twitter_img.get("content"):
            art.image_url = twitter_img["content"]

    # Try to find image caption
    for cap_el in soup.find_all(class_=re.compile(
            r"article.*caption|figure.*caption|image.*caption|credit|legend|photo.*credit",
            re.IGNORECASE)):
        text = cap_el.get_text(strip=True)
        if text and len(text) > 5:
            art.image_caption = text
            break

    # Reading time
    page_text = soup.get_text()
    rt = re.search(r'(\d+)\s*min\.?\s*de\s*lecture', page_text)
    if rt:
        art.reading_time = f"{rt.group(1)} min"

    # --- Body ---
    body_parts = []
    container = (
        soup.find("article") or
        soup.select_one('[class*="article-body"]') or
        soup.select_one('[class*="article__body"]') or
        soup.select_one('[class*="article-content"]') or
        soup.find("body")
    )

    SKIP_CLASS = {"newsletter", "widget", "ad", "pub", "related", "tag",
                  "share", "social", "comment", "footer", "sidebar",
                  "navigation", "menu", "nav", "header", "partage",
                  "inscription", "signup"}
    SKIP_TEXT = {"Créez-vous un compte", "Créer mon compte", "S'inscrire",
                 "Déjà un compte", "Se connecter", "Newsletter",
                 "Partager", "Lire plus tard", "Copier le lien",
                 "Pour recevoir notre newsletter", "Si vous êtes un humain",
                 "If you are a human", "ignore this field",
                 "possibilité d'offrir", "restera actif pendant"}

    if container:
        for el in container.find_all(["p", "blockquote", "h2", "h3"]):
            cls = " ".join(el.get("class", []))
            if any(s in cls.lower() for s in SKIP_CLASS):
                continue
            parent = el.parent
            if parent:
                pcls = " ".join(parent.get("class", []))
                if any(s in pcls.lower() for s in SKIP_CLASS):
                    continue

            text = el.get_text(strip=True)
            if not text or len(text) < 15:
                continue
            if any(s in text for s in SKIP_TEXT):
                continue
            if text == art.title or text == art.subtitle:
                continue

            if el.name in ("h2", "h3"):
                body_parts.append(f"**{text}**")
            elif el.name == "blockquote":
                body_parts.append(f"«QUOTE»{text}«/QUOTE»")
            else:
                body_parts.append(text)

    art.body = "\n\n".join(body_parts)

    if not art.reading_time and art.body:
        w = len(art.body.split())
        art.reading_time = f"{max(1, round(w/250))} min"

    return art


# ---------------------------------------------------------------------------
# HTML escape helper
# ---------------------------------------------------------------------------

def escape_html(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Body text → HTML converter
# ---------------------------------------------------------------------------

def body_to_html(body: str, add_drop_cap: bool = True) -> str:
    """Convert the text body (with **headings** and «QUOTE» markers) to HTML."""
    if not body:
        return ""

    paragraphs = []
    for p in body.split("\n\n"):
        p = p.strip()
        if not p:
            continue
        if p.startswith("**") and p.endswith("**"):
            clean = p[2:-2]
            paragraphs.append(f"<h3>{escape_html(clean)}</h3>")
        elif p.startswith("«QUOTE»"):
            inner = p.replace("«QUOTE»", "").replace("«/QUOTE»", "")
            paragraphs.append(
                f'<blockquote><p>{escape_html(inner)}</p></blockquote>')
        else:
            paragraphs.append(f"<p>{escape_html(p)}</p>")

    html = "\n".join(paragraphs)

    # Add drop cap to first paragraph
    if add_drop_cap and paragraphs:
        def _drop_cap(match):
            inner = match.group(1)
            if inner and len(inner) > 1:
                first_char = inner[0]
                rest = inner[1:]
                return f'<p><span class="drop-cap">{first_char}</span>{rest}</p>'
            return match.group(0)
        html = re.sub(r"<p>(.+?)</p>", _drop_cap, html, count=1, flags=re.DOTALL)

    return html


# ---------------------------------------------------------------------------
# French date formatting
# ---------------------------------------------------------------------------

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def format_date_fr(d: date) -> str:
    return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month]} {d.year}"


# ---------------------------------------------------------------------------
# PDF Generation — Standard formats (WeasyPrint, single-column, with images)
# ---------------------------------------------------------------------------

def generate_pdf(
    articles: dict[str, list[Article]],
    target_date: date,
    fmt: str,
    output_path: Path,
    image_cache: dict[str, str],
    logo_uri: Optional[str] = None,
):
    """Generate an enhanced digest PDF using WeasyPrint.

    Single-column layout for readability on small screens.
    Includes: cover, hero images, numbered TOC, drop caps, colophon.
    """
    from weasyprint import HTML

    profile = FORMATS[fmt]
    p = profile
    date_fr = format_date_fr(target_date)
    total = sum(len(arts) for arts in articles.values())

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    article_num = 0
    for section_name, section_arts in articles.items():
        for art in section_arts:
            article_num += 1

            section_html = f'<div class="art-section">{escape_html(section_name)}</div>'

            author_html = ""
            if art.author:
                parts = [art.author]
                if art.reading_time:
                    parts.append(art.reading_time)
                author_html = f'<div class="art-meta">{escape_html(" · ".join(parts))}</div>'

            lead_html = ""
            if art.subtitle:
                lead_html = f'<div class="art-lead">{escape_html(art.subtitle)}</div>'

            # Hero image
            image_html = ""
            if art.image_url and art.image_url in image_cache:
                cap_html = ""
                if art.image_caption:
                    cap_html = f'<div class="art-img-caption">{escape_html(art.image_caption)}</div>'
                image_html = f'''
                <div class="art-hero-img">
                    <img src="{image_cache[art.image_url]}" alt="" />
                    {cap_html}
                </div>'''

            body_html = body_to_html(art.body, add_drop_cap=True)

            articles_html += f"""
            <article class="art-article">
                {section_html}
                <h2 class="art-title">{escape_html(art.title)}</h2>
                {author_html}
                <div class="art-rule"></div>
                {image_html}
                {lead_html}
                <div class="article-body">
                    {body_html}
                </div>
            </article>
            """

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    idx = 0
    for section_name, section_arts in articles.items():
        if not section_arts:
            continue
        toc_items += f'<div class="toc-section-header">{escape_html(section_name)}</div>'
        for art in section_arts:
            idx += 1
            auth = ""
            if art.author:
                auth = f'<span class="toc-author">{escape_html(art.author)}</span>'
            toc_items += f"""
            <div class="toc-entry">
                <div class="toc-num">{idx:02d}</div>
                <div class="toc-details">
                    <div class="toc-title">{escape_html(art.title)}</div>
                    {auth}
                </div>
            </div>"""

    # ── Cover highlights (first 4 articles from first sections) ────────
    cover_highlights = ""
    hl_count = 0
    for section_name, section_arts in articles.items():
        for art in section_arts:
            if hl_count >= 4:
                break
            sec_hl = f'<div class="cover-hl-sec">{escape_html(section_name)}</div>'
            cover_highlights += f"""
            <div class="cover-hl">
                {sec_hl}
                <div class="cover-hl-title">{escape_html(art.title)}</div>
            </div>"""
            hl_count += 1
        if hl_count >= 4:
            break

    # ── Cover logo (text masthead) ─────────────────────────────────────
    if logo_uri:
        logo_html = f'<img class="cover-logo-img" src="{logo_uri}" alt="Le Temps" />'
    else:
        logo_html = '<div class="cover-masthead">LE TEMPS</div>'

    # ── Full HTML ──────────────────────────────────────────────────────
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       LE TEMPS — {p['label'].upper()}
       Mise en page enrichie (images, sommaire, colophon)
       ================================================================ */

    @page {{
        size: {p["width_mm"]}mm {p["height_mm"]}mm;
        margin: {p["margin"]};
        @bottom-center {{
            content: "— " counter(page) " —";
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 6pt;
            color: #bbb;
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
        justify-content: flex-start;
        align-items: center;
        text-align: center;
        background: #fff;
        padding: {p["cover_padding"]};
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: {p["margin"]};
        left: {p["margin"]};
        right: {p["margin"]};
        height: 2pt;
        background: {LETEMPS_RED};
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: {p["margin"]};
        left: {p["margin"]};
        right: {p["margin"]};
        height: 0.5pt;
        background: #ccc;
    }}

    .cover-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: {p["logo_size"]};
        font-weight: 700;
        letter-spacing: 0.22em;
        color: #1a1a1a;
        margin-top: 8mm;
        margin-bottom: 1.5mm;
        text-transform: uppercase;
    }}

    .cover-logo-img {{
        height: {p["logo_size"]};
        width: auto;
        margin-top: 8mm;
        margin-bottom: 1.5mm;
    }}

    .cover-red-rule {{
        width: {p["banner_rule_width"]};
        height: 1.5pt;
        background: {LETEMPS_RED};
        margin: 0 auto 3mm auto;
    }}

    .cover-date {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["cover_date_size"]};
        font-weight: 400;
        color: #555;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        margin-bottom: 2mm;
    }}

    .cover-count {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["meta_size"]};
        color: #999;
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
        border-bottom: 0.3pt solid #e0e0e0;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-sec {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["cover_hl_sec_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {LETEMPS_RED};
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
        font-size: {p["toc_sec_size"]};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: #999;
        margin-bottom: 3mm;
        padding-bottom: 1.5mm;
        border-bottom: 1.5pt solid {LETEMPS_RED};
    }}

    .toc-section-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_sec_size"]};
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: {LETEMPS_RED};
        margin-top: 3mm;
        margin-bottom: 1.5mm;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 2mm;
        padding-bottom: 2mm;
        border-bottom: 0.25pt solid #e8e8e8;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_num_size"]};
        font-weight: 300;
        color: #ddd;
        min-width: {p["toc_num_width"]};
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
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
        color: #888;
        display: block;
        margin-top: 0.3mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .art-article {{
        page-break-before: always;
    }}

    .art-section {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["toc_sec_size"]};
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: {LETEMPS_RED};
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

    .art-meta {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["meta_size"]};
        color: #888;
        margin-bottom: 2.5mm;
    }}

    .art-rule {{
        height: 0.4pt;
        background: #ddd;
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
        font-size: {p["lead_size"]};
        font-weight: 600;
        line-height: 1.35;
        color: #333;
        margin-bottom: 3mm;
        padding-bottom: 2.5mm;
        border-bottom: 0.25pt solid #e0e0e0;
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
        color: {LETEMPS_RED};
        font-weight: 700;
    }}

    .article-body h3 {{
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
        border-left: 2pt solid {LETEMPS_RED};
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

    .colophon-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: {p["colophon_logo_size"]};
        font-weight: 700;
        letter-spacing: 0.2em;
        color: #ccc;
        margin-bottom: 3mm;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: {p["colophon_font_size"]};
        color: #bbb;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 20mm;
        height: 0.4pt;
        background: #ddd;
        margin: 4mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-red-rule"></div>
    <div class="cover-date">{escape_html(date_fr)}</div>
    <div class="cover-count">{total} articles</div>

    <div class="cover-highlights">
        {cover_highlights}
    </div>
</div>

<!-- ═══════════ TABLE OF CONTENTS ═══════════ -->
<div class="toc-page">
    <div class="toc-header">Sommaire — {total} articles</div>
    {toc_items}
</div>

<!-- ═══════════ ARTICLES ═══════════ -->
{articles_html}

<!-- ═══════════ COLOPHON ═══════════ -->
<div class="colophon">
    <div class="colophon-masthead">LE TEMPS</div>
    <div class="colophon-text">
        Le quotidien suisse de référence<br/>
        letemps.ch
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        {escape_html(date_fr)}<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    log.info(f"  📄 Génération PDF ({profile['label']})…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ---------------------------------------------------------------------------
# PDF Generation — A4 Premium (New Yorker style, 2-column)
# ---------------------------------------------------------------------------

def generate_premium_pdf(
    articles: dict[str, list[Article]],
    target_date: date,
    output_path: Path,
    image_cache: dict[str, str],
    logo_uri: Optional[str] = None,
):
    """Generate a premium A4 magazine-style PDF with images and rich layout.

    Design: two-column body, drop caps, full-width hero images,
    elegant serif typography, thin decorative rules, Le Temps red accents.
    """
    from weasyprint import HTML

    log.info("  🎨 Préparation de l'édition premium A4…")

    date_fr = format_date_fr(target_date)
    total = sum(len(arts) for arts in articles.values())

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for section_name, section_arts in articles.items():
        for art in section_arts:
            section_html = f'<div class="pm-section">{escape_html(section_name)}</div>'

            author_html = ""
            if art.author:
                parts = [f"Par {art.author}"]
                if art.reading_time:
                    parts.append(art.reading_time)
                author_html = f'<div class="pm-author">{escape_html(" · ".join(parts))}</div>'

            lead_html = ""
            if art.subtitle:
                lead_html = f'<div class="pm-lead">{escape_html(art.subtitle)}</div>'

            # Hero image
            image_html = ""
            if art.image_url and art.image_url in image_cache:
                cap_html = ""
                if art.image_caption:
                    cap_html = f'<div class="pm-img-caption">{escape_html(art.image_caption)}</div>'
                image_html = f'''
                <div class="pm-hero-img">
                    <img src="{image_cache[art.image_url]}" alt="" />
                    {cap_html}
                </div>'''

            body_html = body_to_html(art.body, add_drop_cap=True)

            articles_html += f"""
            <article class="pm-article">
                {section_html}
                <h2 class="pm-title">{escape_html(art.title)}</h2>
                {author_html}
                <div class="pm-rule-thin"></div>
                {image_html}
                {lead_html}
                <div class="pm-body">
                    {body_html}
                </div>
            </article>
            """

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    idx = 0
    for section_name, section_arts in articles.items():
        if not section_arts:
            continue
        toc_items += f'<div class="toc-section-header">{escape_html(section_name)}</div>'
        for art in section_arts:
            idx += 1
            auth = ""
            if art.author:
                auth = f'<span class="toc-author">{escape_html(art.author)}</span>'
            toc_items += f"""
            <div class="toc-entry">
                <div class="toc-num">{idx:02d}</div>
                <div class="toc-details">
                    <div class="toc-title">{escape_html(art.title)}</div>
                    {auth}
                </div>
            </div>"""

    # ── Cover highlights (first 5 articles) ────────────────────────────
    cover_highlights = ""
    hl_count = 0
    for section_name, section_arts in articles.items():
        for art in section_arts:
            if hl_count >= 5:
                break
            sec_hl = f'<div class="cover-hl-sec">{escape_html(section_name)}</div>'
            auth_hl = ""
            if art.author:
                auth_hl = f'<div class="cover-hl-author">{escape_html(art.author)}</div>'
            cover_highlights += f"""
            <div class="cover-hl">
                {sec_hl}
                <div class="cover-hl-title">{escape_html(art.title)}</div>
                {auth_hl}
            </div>"""
            hl_count += 1
        if hl_count >= 5:
            break

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_uri:
        logo_html = f'<img class="cover-logo-img" src="{logo_uri}" alt="Le Temps" />'
    else:
        logo_html = '<div class="cover-masthead">LE TEMPS</div>'

    # ── Full HTML ──────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       LE TEMPS — ÉDITION PREMIUM A4
       Mise en page inspirée du New Yorker
       ================================================================ */

    @page {{
        size: 210mm 297mm;
        margin: 22mm 25mm 25mm 25mm;

        @bottom-right {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 8pt;
            color: #bbb;
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
        justify-content: flex-start;
        align-items: center;
        text-align: center;
        background: #fff;
        padding: 30mm 30mm;
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: 18mm;
        left: 25mm;
        right: 25mm;
        height: 2.5pt;
        background: {LETEMPS_RED};
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: 18mm;
        left: 25mm;
        right: 25mm;
        height: 0.5pt;
        background: #ccc;
    }}

    .cover-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: 36pt;
        font-weight: 700;
        letter-spacing: 0.25em;
        color: #1a1a1a;
        margin-top: 12mm;
        margin-bottom: 3mm;
        text-transform: uppercase;
    }}

    .cover-logo-img {{
        height: 30pt;
        width: auto;
        margin-top: 12mm;
        margin-bottom: 3mm;
    }}

    .cover-red-rule {{
        width: 55mm;
        height: 2pt;
        background: {LETEMPS_RED};
        margin: 0 auto 5mm auto;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-style: italic;
        color: #666;
        letter-spacing: 0.06em;
        margin-bottom: 10mm;
    }}

    .cover-date {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt;
        font-weight: 400;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        padding: 2.5mm 8mm;
        border-top: 0.5pt solid #1a1a1a;
        border-bottom: 0.5pt solid #1a1a1a;
        margin-bottom: 4mm;
    }}

    .cover-count {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        color: #999;
        font-style: italic;
        margin-bottom: 12mm;
    }}

    .cover-highlights {{
        margin-top: 6mm;
        text-align: left;
        max-width: 130mm;
    }}

    .cover-hl {{
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-sec {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: {LETEMPS_RED};
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
        color: #888;
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
        margin-bottom: 5mm;
        padding-bottom: 2mm;
        border-bottom: 2pt solid {LETEMPS_RED};
    }}

    .toc-section-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {LETEMPS_RED};
        margin-top: 5mm;
        margin-bottom: 2mm;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 3.5mm;
        padding-bottom: 3.5mm;
        border-bottom: 0.3pt solid #e8e8e8;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt;
        font-weight: 300;
        color: #ddd;
        min-width: 12mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-weight: 700;
        line-height: 1.3;
        color: #1a1a1a;
    }}

    .toc-author {{
        font-size: 8.5pt;
        font-style: italic;
        color: #888;
        display: block;
        margin-top: 0.5mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .pm-article {{
        page-break-before: always;
    }}

    .pm-section {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: {LETEMPS_RED};
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
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8.5pt;
        color: #888;
        margin-bottom: 4mm;
    }}

    .pm-rule-thin {{
        height: 0.5pt;
        background: #ddd;
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
        border-bottom: 0.3pt solid #e0e0e0;
    }}

    /* Two-column body */
    .pm-body {{
        column-count: 2;
        column-gap: 7mm;
        column-rule: 0.3pt solid #e8e8e8;
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
        color: {LETEMPS_RED};
        font-weight: 700;
    }}

    .pm-body h3 {{
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
        border-left: 2.5pt solid {LETEMPS_RED};
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

    .colophon-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: 18pt;
        font-weight: 700;
        letter-spacing: 0.2em;
        color: #ccc;
        margin-bottom: 4mm;
    }}

    .colophon-rule-red {{
        width: 25mm;
        height: 1.5pt;
        background: {LETEMPS_RED};
        margin: 0 auto 6mm auto;
        opacity: 0.3;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #bbb;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 30mm;
        height: 0.5pt;
        background: #ddd;
        margin: 6mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-red-rule"></div>
    <div class="cover-subtitle">Le quotidien suisse de référence</div>
    <div class="cover-date">{escape_html(date_fr)}</div>
    <div class="cover-count">{total} articles</div>

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
    <div class="colophon-masthead">LE TEMPS</div>
    <div class="colophon-rule-red"></div>
    <div class="colophon-text">
        Le quotidien suisse de référence<br/>
        <em>letemps.ch</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        {escape_html(date_fr)}<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    log.info(f"  📄 Génération PDF (🖨️  A4 Premium)…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ---------------------------------------------------------------------------
# PDF Generation — A4 Premium Landscape (3-column, 297×210mm)
# ---------------------------------------------------------------------------

def generate_premium_landscape_pdf(
    articles: dict[str, list[Article]],
    target_date: date,
    output_path: Path,
    image_cache: dict[str, str],
    logo_uri: Optional[str] = None,
):
    """Generate a premium A4 landscape magazine-style PDF with images and rich layout.

    Design: three-column body, drop caps, full-width hero images,
    elegant serif typography, thin decorative rules, Le Temps red accents.
    Landscape orientation: 297mm x 210mm.
    """
    from weasyprint import HTML

    log.info("  🎨 Préparation de l'édition premium A4 paysage…")

    date_fr = format_date_fr(target_date)
    total = sum(len(arts) for arts in articles.values())

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for section_name, section_arts in articles.items():
        for art in section_arts:
            section_html = f'<div class="pm-section">{escape_html(section_name)}</div>'

            author_html = ""
            if art.author:
                parts = [f"Par {art.author}"]
                if art.reading_time:
                    parts.append(art.reading_time)
                author_html = f'<div class="pm-author">{escape_html(" · ".join(parts))}</div>'

            lead_html = ""
            if art.subtitle:
                lead_html = f'<div class="pm-lead">{escape_html(art.subtitle)}</div>'

            # Hero image
            image_html = ""
            if art.image_url and art.image_url in image_cache:
                cap_html = ""
                if art.image_caption:
                    cap_html = f'<div class="pm-img-caption">{escape_html(art.image_caption)}</div>'
                image_html = f'''
                <div class="pm-hero-img">
                    <img src="{image_cache[art.image_url]}" alt="" />
                    {cap_html}
                </div>'''

            body_html = body_to_html(art.body, add_drop_cap=True)

            articles_html += f"""
            <article class="pm-article">
                {section_html}
                <h2 class="pm-title">{escape_html(art.title)}</h2>
                {author_html}
                <div class="pm-rule-thin"></div>
                {image_html}
                {lead_html}
                <div class="pm-body">
                    {body_html}
                </div>
            </article>
            """

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    idx = 0
    for section_name, section_arts in articles.items():
        if not section_arts:
            continue
        toc_items += f'<div class="toc-section-header">{escape_html(section_name)}</div>'
        for art in section_arts:
            idx += 1
            auth = ""
            if art.author:
                auth = f'<span class="toc-author">{escape_html(art.author)}</span>'
            toc_items += f"""
            <div class="toc-entry">
                <div class="toc-num">{idx:02d}</div>
                <div class="toc-details">
                    <div class="toc-title">{escape_html(art.title)}</div>
                    {auth}
                </div>
            </div>"""

    # ── Cover highlights (first 5 articles) ────────────────────────────
    cover_highlights = ""
    hl_count = 0
    for section_name, section_arts in articles.items():
        for art in section_arts:
            if hl_count >= 5:
                break
            sec_hl = f'<div class="cover-hl-sec">{escape_html(section_name)}</div>'
            auth_hl = ""
            if art.author:
                auth_hl = f'<div class="cover-hl-author">{escape_html(art.author)}</div>'
            cover_highlights += f"""
            <div class="cover-hl">
                {sec_hl}
                <div class="cover-hl-title">{escape_html(art.title)}</div>
                {auth_hl}
            </div>"""
            hl_count += 1
        if hl_count >= 5:
            break

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_uri:
        logo_html = f'<img class="cover-logo-img" src="{logo_uri}" alt="Le Temps" />'
    else:
        logo_html = '<div class="cover-masthead">LE TEMPS</div>'

    # ── Full HTML ──────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       LE TEMPS — ÉDITION PREMIUM A4 PAYSAGE
       Mise en page inspirée du New Yorker — orientation paysage
       ================================================================ */

    @page {{
        size: 297mm 210mm;
        margin: 18mm 22mm 20mm 22mm;

        @bottom-right {{
            content: counter(page);
            font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
            font-size: 8pt;
            color: #bbb;
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
        justify-content: flex-start;
        align-items: center;
        text-align: center;
        background: #fff;
        padding: 22mm 40mm;
        position: relative;
    }}

    .cover::before {{
        content: "";
        position: absolute;
        top: 14mm;
        left: 22mm;
        right: 22mm;
        height: 2.5pt;
        background: {LETEMPS_RED};
    }}

    .cover::after {{
        content: "";
        position: absolute;
        bottom: 14mm;
        left: 22mm;
        right: 22mm;
        height: 0.5pt;
        background: #ccc;
    }}

    .cover-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: 36pt;
        font-weight: 700;
        letter-spacing: 0.25em;
        color: #1a1a1a;
        margin-top: 8mm;
        margin-bottom: 3mm;
        text-transform: uppercase;
    }}

    .cover-logo-img {{
        height: 30pt;
        width: auto;
        margin-top: 8mm;
        margin-bottom: 3mm;
    }}

    .cover-red-rule {{
        width: 55mm;
        height: 2pt;
        background: {LETEMPS_RED};
        margin: 0 auto 4mm auto;
    }}

    .cover-subtitle {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 11pt;
        font-style: italic;
        color: #666;
        letter-spacing: 0.06em;
        margin-bottom: 6mm;
    }}

    .cover-date {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 11pt;
        font-weight: 400;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        padding: 2.5mm 8mm;
        border-top: 0.5pt solid #1a1a1a;
        border-bottom: 0.5pt solid #1a1a1a;
        margin-bottom: 3mm;
    }}

    .cover-count {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        color: #999;
        font-style: italic;
        margin-bottom: 6mm;
    }}

    .cover-highlights {{
        margin-top: 4mm;
        text-align: left;
        max-width: 180mm;
        column-count: 2;
        column-gap: 10mm;
    }}

    .cover-hl {{
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
        break-inside: avoid;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
    }}

    .cover-hl-sec {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: {LETEMPS_RED};
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
        color: #888;
        margin-top: 1mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       TABLE OF CONTENTS
       ════════════════════════════════════════════════════════════════ */
    .toc-page {{
        page-break-after: always;
        padding-top: 5mm;
        column-count: 3;
        column-gap: 8mm;
    }}

    .toc-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 9pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: #999;
        margin-bottom: 5mm;
        padding-bottom: 2mm;
        border-bottom: 2pt solid {LETEMPS_RED};
        column-span: all;
    }}

    .toc-section-header {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {LETEMPS_RED};
        margin-top: 5mm;
        margin-bottom: 2mm;
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 3mm;
        padding-bottom: 3mm;
        border-bottom: 0.3pt solid #e8e8e8;
        break-inside: avoid;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 16pt;
        font-weight: 300;
        color: #ddd;
        min-width: 10mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
    }}

    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: 10pt;
        font-weight: 700;
        line-height: 1.3;
        color: #1a1a1a;
    }}

    .toc-author {{
        font-size: 8pt;
        font-style: italic;
        color: #888;
        display: block;
        margin-top: 0.5mm;
    }}

    /* ════════════════════════════════════════════════════════════════
       ARTICLES
       ════════════════════════════════════════════════════════════════ */
    .pm-article {{
        page-break-before: always;
    }}

    .pm-section {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: {LETEMPS_RED};
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
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8.5pt;
        color: #888;
        margin-bottom: 4mm;
    }}

    .pm-rule-thin {{
        height: 0.5pt;
        background: #ddd;
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
        font-size: 11pt;
        font-weight: 600;
        line-height: 1.4;
        color: #333;
        margin-bottom: 5mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
    }}

    /* Three-column body */
    .pm-body {{
        column-count: 3;
        column-gap: 6mm;
        column-rule: 0.3pt solid #e8e8e8;
        font-size: 10pt;
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
        color: {LETEMPS_RED};
        font-weight: 700;
    }}

    .pm-body h3 {{
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
        border-left: 2.5pt solid {LETEMPS_RED};
        color: #444;
        font-style: italic;
        font-size: 10pt;
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

    .colophon-masthead {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: 18pt;
        font-weight: 700;
        letter-spacing: 0.2em;
        color: #ccc;
        margin-bottom: 4mm;
    }}

    .colophon-rule-red {{
        width: 25mm;
        height: 1.5pt;
        background: {LETEMPS_RED};
        margin: 0 auto 6mm auto;
        opacity: 0.3;
    }}

    .colophon-text {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #bbb;
        line-height: 1.8;
    }}

    .colophon-rule {{
        width: 30mm;
        height: 0.5pt;
        background: #ddd;
        margin: 6mm auto;
    }}
</style>
</head>
<body>

<!-- ═══════════ COVER ═══════════ -->
<div class="cover">
    {logo_html}
    <div class="cover-red-rule"></div>
    <div class="cover-subtitle">Le quotidien suisse de référence</div>
    <div class="cover-date">{escape_html(date_fr)}</div>
    <div class="cover-count">{total} articles</div>

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
    <div class="colophon-masthead">LE TEMPS</div>
    <div class="colophon-rule-red"></div>
    <div class="colophon-text">
        Le quotidien suisse de référence<br/>
        <em>letemps.ch</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
        {escape_html(date_fr)}<br/>
        Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}
    </div>
</div>

</body>
</html>"""

    # ── Generate PDF ───────────────────────────────────────────────────
    log.info(f"  📄 Génération PDF (🖨️  A4 Premium Paysage)…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Le Temps → PDF (5 formats, édition enrichie)"
    )
    ap.add_argument("--user", "-u", default=os.environ.get("LETEMPS_USER", ""))
    ap.add_argument("--password", "-p", default=os.environ.get("LETEMPS_PASS", ""))
    ap.add_argument("--date", "-d", default=None, help="YYYY-MM-DD")
    ap.add_argument("--no-headless", action="store_true", help="Voir le navigateur")
    ap.add_argument("--output-dir", "-o", default=None)
    ap.add_argument("--format", "-f",
                    choices=list(FORMATS.keys()) + ["all"],
                    default="all",
                    help="Format écran ou 'all' pour les 5 (défaut: all)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  📰  Le Temps — Édition du jour                          ║")
    print("║  📱 phone · 📖 liseuse · 📱 tablette 7 & 10             ║")
    print("║  🖨️  A4 Premium (magazine style)                         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # --- Interactive credentials ---
    user = args.user
    password = args.password
    if not user:
        user = input("📧 Email Le Temps: ").strip()
    if not password:
        import getpass
        password = getpass.getpass("🔑 Mot de passe Le Temps: ")
    if not user or not password:
        log.error("Identifiants requis.")
        sys.exit(1)

    # --- Formats to generate ---
    if args.format == "all":
        formats_to_gen = list(FORMATS.keys())
    else:
        formats_to_gen = [args.format]

    td = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"=== Le Temps — {td.isoformat()} ===")

    # --- Download logo ---
    log.info("  🎨 Recherche du logo…")
    logo_uri = download_logo()

    with LeTempsSession(user, password,
                         headless=not args.no_headless) as s:
        if not s.login():
            log.error("Connexion échouée.")
            sys.exit(1)

        all_arts: dict[str, list[Article]] = {}
        seen: set[str] = set()

        # Homepage + en continu
        home_urls = find_homepage_urls(s, td)
        seen.update(home_urls)

        # Sections
        for sname, spath in SECTIONS:
            log.info(f"Section: {sname}")
            sarts = []

            surls = find_article_urls(s, spath, td)
            # Add homepage URLs matching this section
            for u in home_urls:
                if spath in u and u not in surls:
                    surls.append(u)

            for url in surls:
                if url in seen and url not in home_urls:
                    continue
                seen.add(url)

                art = parse_article(s, url, section=sname)
                if art and art.body and len(art.body) > 100:
                    sarts.append(art)
                    log.info(f"    ✓ {art.title[:65]}")
                time.sleep(0.8)

            if sarts:
                all_arts[sname] = sarts

        # Uncategorized from homepage
        uncat = []
        for url in home_urls:
            if not any(url in [a.url for a in arts] for arts in all_arts.values()):
                art = parse_article(s, url, section="À la une")
                if art and art.body and len(art.body) > 100:
                    uncat.append(art)
                    log.info(f"    ✓ [À la une] {art.title[:60]}")
                time.sleep(0.8)
        if uncat:
            all_arts = {"À la une": uncat, **all_arts}

    total = sum(len(a) for a in all_arts.values())
    if total == 0:
        log.error(
            "Aucun article trouvé.\n"
            "  → Essayez --no-headless pour voir le navigateur\n"
            "  → Vérifiez vos identifiants\n"
            "  → Le journal est publié lun-sam"
        )
        sys.exit(1)

    # --- Download article images ---
    log.info(f"\n  🖼️  Téléchargement des images ({total} articles)…")
    image_cache: dict[str, str] = {}
    img_session = req_lib.Session()
    img_session.headers.update(HEADERS)

    img_count = 0
    for section_arts in all_arts.values():
        for art in section_arts:
            if art.image_url and art.image_url not in image_cache:
                data_uri = download_image_as_data_uri(art.image_url, img_session)
                if data_uri:
                    image_cache[art.image_url] = data_uri
                    img_count += 1
                    log.info(f"     ✓ {art.title[:55]}…")
                else:
                    log.debug(f"     — {art.title[:55]}… (image non disponible)")

    log.info(f"  ✅ {img_count} images téléchargées.\n")

    # --- Generate PDFs ---
    generated = []
    for fmt_key in formats_to_gen:
        profile = FORMATS[fmt_key]
        suffix = profile["suffix"]
        op = out_dir / f"{td:%Y-%m-%d}-letemps_{suffix}.pdf"

        if fmt_key == "a4premium":
            generate_premium_pdf(all_arts, td, op, image_cache, logo_uri)
        elif fmt_key == "a4landscape":
            generate_premium_landscape_pdf(all_arts, td, op, image_cache, logo_uri)
        else:
            generate_pdf(all_arts, td, fmt_key, op, image_cache, logo_uri)

        generated.append((profile['label'], op))

    print()
    print(f"  🎉 Terminé — {len(generated)} PDFs générés !")
    for label, path in generated:
        print(f"     {label}: {path.name}")
    print()


if __name__ == "__main__":
    main()
