#!/usr/bin/env python3
"""
Courrier International — Weekly/Daily Scraper & PDF Generator
==============================================================
Downloads articles from courrierinternational.com via RSS feed + 
authenticated scraping, and generates formatted PDF digests for 
phone, e-reader (6"), tablet (7" & 10") and A4 premium.

Based on the Calibre recipe by Mathieu Godlewski & Rémi Vanicat,
adapted to Pierre's newspapers project architecture.

Authentication (for subscriber content):
    For Google OAuth accounts (recommended methods):
        1. Cookie file:    --cookies ci_cookies.json
           → Export with Cookie-Editor extension from Chrome
        2. Chrome profile: --chrome-profile  (or just run without args)
           → Reuses your existing Chrome session where you're logged in
           → Close Chrome first, then run the script

    For direct email/password accounts:
        3. Credentials:    --user EMAIL --password PASS
           → Does NOT work with Google OAuth accounts

Usage:
    python courrier_international_scraper.py --cookies ci_cookies.json
    python courrier_international_scraper.py --chrome-profile
    python courrier_international_scraper.py --format all
    python courrier_international_scraper.py --format phone --max-articles 20
    python courrier_international_scraper.py --sections geopolitique,economie
    python courrier_international_scraper.py --min-length 1200  # articles de fond uniquement

Environment variables:
    CI_USER      — subscriber email (direct login only)
    CI_PASS      — subscriber password (direct login only)

Dependencies:
    pip install playwright beautifulsoup4 weasyprint requests lxml feedparser
    playwright install chromium
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup, NavigableString

from epub_generator import generate_epub

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

BASE_URL = "https://www.courrierinternational.com"
RSS_FEEDS = {
    "all": f"{BASE_URL}/feed/all/rss.xml",
    # Uncomment/add specific feeds as needed:
    # "enquetes": f"{BASE_URL}/feed/enquetes/rss.xml",
    # "expat": f"{BASE_URL}/feed/expat/rss.xml",
    # "reveil": f"{BASE_URL}/feed/reveil-courrier/rss.xml",
}
LOGIN_URL = f"{BASE_URL}/login"

OUTPUT_BASE = Path.home() / "kDrive" / "newspapers" / "journaux_du_jour"

# Section mapping — extracted from URL slugs
SECTION_MAP = {
    "geopolitique": "Géopolitique",
    "politique": "Politique",
    "economie": "Économie",
    "societe": "Société",
    "sciences": "Sciences & Environnement",
    "science": "Sciences & Environnement",
    "environnement": "Sciences & Environnement",
    "culture": "Culture",
    "expat": "Courrier Expat",
    "france": "France vue de l'étranger",
    "sport": "Sport",
    "histoire": "Histoire",
    "reportage": "Reportage",
    "analyse": "Analyse",
    "editorial": "Éditorial",
    "enquete": "Enquête",
    "immigration": "Société",
    "guerre": "Géopolitique",
    "technologie": "Sciences & Environnement",
    "la-lettre-tech": "Sciences & Environnement",
    "pendant-que-vous-dormiez": "En bref",
    "vu-du-royaume-uni": "France vue de l'étranger",
    "vu-de": "France vue de l'étranger",
    "temoignage": "Société",
    "infographie": "Infographie",
    "dessin": "Dessin de presse",
}

# ══════════════════════════════════════════════════════════════════════════════
#  FORMAT PROFILES (matching project standards)
# ══════════════════════════════════════════════════════════════════════════════

FORMAT_PROFILES = {
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
        "logo_width": "25mm",
        "banner_padding": "3mm 5mm",
        "img_max_height": "35mm",
        "drop_cap_size": "22pt",
        "drop_cap_padding": "1mm",
        "toc_num_size": "11pt",
        "toc_num_width": "7mm",
        "toc_title_size": "8pt",
        "toc_cat_size": "6pt",
        "toc_author_size": "7pt",
        "cover_title_size": "16pt",
        "cover_subtitle_size": "8pt",
        "cover_edition_size": "8pt",
        "cover_hl_title_size": "8pt",
        "cover_hl_cat_size": "6pt",
        "cover_padding": "8mm 6mm",
        "colophon_font_size": "6.5pt",
        "caption_size": "6pt",
        "columns": 1,
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
        "logo_width": "30mm",
        "banner_padding": "3.5mm 6mm",
        "img_max_height": "42mm",
        "drop_cap_size": "26pt",
        "drop_cap_padding": "1.2mm",
        "toc_num_size": "13pt",
        "toc_num_width": "8mm",
        "toc_title_size": "9pt",
        "toc_cat_size": "6.5pt",
        "toc_author_size": "7.5pt",
        "cover_title_size": "20pt",
        "cover_subtitle_size": "9pt",
        "cover_edition_size": "8.5pt",
        "cover_hl_title_size": "9pt",
        "cover_hl_cat_size": "6.5pt",
        "cover_padding": "10mm 8mm",
        "colophon_font_size": "7pt",
        "caption_size": "6.5pt",
        "columns": 1,
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
        "logo_width": "35mm",
        "banner_padding": "4mm 7mm",
        "img_max_height": "52mm",
        "drop_cap_size": "30pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "14pt",
        "toc_num_width": "9mm",
        "toc_title_size": "9.5pt",
        "toc_cat_size": "7pt",
        "toc_author_size": "8pt",
        "cover_title_size": "24pt",
        "cover_subtitle_size": "10pt",
        "cover_edition_size": "9pt",
        "cover_hl_title_size": "10pt",
        "cover_hl_cat_size": "7pt",
        "cover_padding": "12mm 10mm",
        "colophon_font_size": "7.5pt",
        "caption_size": "7pt",
        "columns": 1,
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
        "logo_width": "42mm",
        "banner_padding": "5mm 8mm",
        "img_max_height": "70mm",
        "drop_cap_size": "34pt",
        "drop_cap_padding": "1.5mm",
        "toc_num_size": "16pt",
        "toc_num_width": "10mm",
        "toc_title_size": "10pt",
        "toc_cat_size": "7pt",
        "toc_author_size": "8pt",
        "cover_title_size": "28pt",
        "cover_subtitle_size": "10.5pt",
        "cover_edition_size": "9.5pt",
        "cover_hl_title_size": "10pt",
        "cover_hl_cat_size": "7pt",
        "cover_padding": "15mm 12mm",
        "colophon_font_size": "8pt",
        "caption_size": "7.5pt",
        "columns": 1,
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
        "line_height": "1.55",
        "logo_width": "55mm",
        "banner_padding": "6mm 10mm",
        "img_max_height": "85mm",
        "drop_cap_size": "42pt",
        "drop_cap_padding": "2mm",
        "toc_num_size": "18pt",
        "toc_num_width": "12mm",
        "toc_title_size": "11pt",
        "toc_cat_size": "8pt",
        "toc_author_size": "9pt",
        "cover_title_size": "36pt",
        "cover_subtitle_size": "12pt",
        "cover_edition_size": "11pt",
        "cover_hl_title_size": "12pt",
        "cover_hl_cat_size": "8pt",
        "cover_padding": "30mm 25mm",
        "colophon_font_size": "8pt",
        "caption_size": "8pt",
        "columns": 2,
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
        "logo_width": "55mm",
        "banner_padding": "6mm 10mm",
        "img_max_height": "70mm",
        "drop_cap_size": "42pt",
        "drop_cap_padding": "2mm",
        "toc_num_size": "16pt",
        "toc_num_width": "10mm",
        "toc_title_size": "10pt",
        "toc_cat_size": "7.5pt",
        "toc_author_size": "8.5pt",
        "cover_title_size": "34pt",
        "cover_subtitle_size": "12pt",
        "cover_edition_size": "11pt",
        "cover_hl_title_size": "11pt",
        "cover_hl_cat_size": "7.5pt",
        "cover_padding": "22mm 30mm",
        "colophon_font_size": "8pt",
        "caption_size": "7.5pt",
        "columns": 3,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Article:
    title: str
    url: str
    section: str = "Actualité"
    author: str = ""
    source_journal: str = ""  # Original source (e.g., "The Guardian", "El País")
    date: str = ""
    summary: str = ""
    content: str = ""
    image_url: str = ""
    image_data: str = ""  # base64 data URI
    image_caption: str = ""


# ══════════════════════════════════════════════════════════════════════════════
#  TEXT UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Normalize whitespace — prevent word concatenation from HTML parsing."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_text(element) -> str:
    """Extract text from BS4 element with proper spacing between inline elements."""
    if element is None:
        return ""
    return clean_text(element.get_text(separator=" "))


def guess_section(url: str, rss_category: str = "") -> str:
    """Guess article section from URL slug or RSS category."""
    path = urlparse(url).path.lower()
    
    # Try RSS category first
    if rss_category:
        cat_lower = rss_category.lower().strip()
        for key, label in SECTION_MAP.items():
            if key in cat_lower:
                return label
    
    # Parse from URL: /article/{section-slug}-{rest}_{id}
    match = re.search(r'/article/([^/]+)', path)
    if match:
        slug = match.group(1)
        # Try matching the beginning of the slug against known sections
        for key, label in SECTION_MAP.items():
            if slug.startswith(key):
                return label
    
    return rss_category.strip() if rss_category else "Actualité"


# ══════════════════════════════════════════════════════════════════════════════
#  AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

def login_with_playwright(user: str, password: str) -> dict:
    """Login to Courrier International using Playwright and return cookies.
    
    NOTE: This only works with direct email/password accounts.
    For Google OAuth accounts, use --cookies or --chrome-profile instead.
    """
    print("  🔐 Connexion avec Playwright (login direct)...")
    print("  ⚠  Si vous utilisez un compte Google, préférez --cookies ou --chrome-profile")
    
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # Try multiple login form patterns (Drupal-based site)
            login_selectors = [
                {"user": "#edit-name", "pass": "#edit-pass", "submit": "#edit-submit"},
                {"user": "input[name='name']", "pass": "input[name='pass']", "submit": "input[type='submit']"},
                {"user": "input[name='email']", "pass": "input[name='password']", "submit": "button[type='submit']"},
                {"user": "input[type='email']", "pass": "input[type='password']", "submit": "button[type='submit']"},
                {"user": "#email", "pass": "#password", "submit": ".login-submit, .form-submit, button.btn"},
            ]
            
            logged_in = False
            for sel in login_selectors:
                try:
                    if page.locator(sel["user"]).count() > 0:
                        print(f"    → Formulaire trouvé : {sel['user']}")
                        page.fill(sel["user"], user)
                        page.fill(sel["pass"], password)
                        page.click(sel["submit"])
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        time.sleep(2)
                        logged_in = True
                        break
                except Exception:
                    continue
            
            if not logged_in:
                print("    ⚠  Formulaire standard non trouvé, tentative générique...")
                inputs = page.locator("input[type='text'], input[type='email']")
                if inputs.count() > 0:
                    inputs.first.fill(user)
                    page.locator("input[type='password']").first.fill(password)
                    page.locator("button[type='submit'], input[type='submit']").first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    time.sleep(2)
                    logged_in = True
            
            cookies = context.cookies()
            cookie_list = [{"name": c["name"], "value": c["value"],
                            "domain": c.get("domain", ""), "path": c.get("path", "/"),
                            "secure": c.get("secure", False),
                            "httpOnly": c.get("httpOnly", False)}
                           for c in cookies]
            
            current_url = page.url
            page_content = page.content()
            
            if "logout" in page_content.lower() or "déconnexion" in page_content.lower() or "mon-compte" in current_url:
                print("  ✅ Connexion réussie !")
            else:
                print("  ⚠  Connexion incertaine — vérifiez vos identifiants.")
                print(f"    URL actuelle : {current_url}")
            
            return cookie_list
            
        except Exception as e:
            print(f"  ❌ Erreur de connexion : {e}")
            traceback.print_exc()
            return []
        finally:
            browser.close()


def extract_cookies_from_chrome_profile(profile_path: str = "") -> list:
    """Extract Courrier International cookies from a Chrome/Chromium user profile.
    
    This is the easiest method for Google OAuth subscribers:
    just point to your existing Chrome profile where you're already logged in.
    
    Default profile paths:
      Linux:   ~/.config/google-chrome/Default
      macOS:   ~/Library/Application Support/Google/Chrome/Default
    """
    print("  🔐 Extraction des cookies depuis le profil Chrome...")
    
    from playwright.sync_api import sync_playwright
    
    # Resolve default profile path
    if not profile_path:
        home = Path.home()
        candidates = [
            home / ".config" / "google-chrome",          # Linux Chrome
            home / ".config" / "chromium",                # Linux Chromium
            home / "snap" / "chromium" / "common" / "chromium",  # Snap Chromium
        ]
        for candidate in candidates:
            if candidate.exists():
                profile_path = str(candidate)
                break
        
        if not profile_path:
            print("  ❌ Profil Chrome non trouvé. Spécifiez le chemin avec --chrome-profile.")
            return []
    
    print(f"    → Profil : {profile_path}")
    
    with sync_playwright() as p:
        try:
            # Launch Chromium using the existing user data directory
            # This reuses the existing session including Google OAuth cookies
            browser = p.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=True,
                channel="chromium",
                args=["--disable-blink-features=AutomationControlled"],
            )
            
            page = browser.new_page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            
            cookies = browser.cookies()
            cookie_list = [{"name": c["name"], "value": c["value"],
                            "domain": c.get("domain", ""), "path": c.get("path", "/"),
                            "secure": c.get("secure", False),
                            "httpOnly": c.get("httpOnly", False)}
                           for c in cookies
                           if "courrierinternational" in c.get("domain", "")]
            
            # Check login status
            page_content = page.content()
            if "logout" in page_content.lower() or "déconnexion" in page_content.lower() or "mon-compte" in page_content.lower():
                print(f"  ✅ Session Google active ! ({len(cookie_list)} cookies)")
            else:
                print("  ⚠  Session non détectée — connectez-vous d'abord dans Chrome.")
                print("     Ouvrez Chrome, allez sur courrierinternational.com, connectez-vous via Google,")
                print("     puis relancez ce script.")
            
            browser.close()
            return cookie_list
            
        except Exception as e:
            print(f"  ❌ Erreur extraction profil : {e}")
            print("     Fermez Chrome avant de lancer le script (le profil ne peut pas")
            print("     être utilisé par deux processus simultanément).")
            return []


def load_cookies_from_file(cookie_file: str) -> list:
    """Load cookies from a JSON file (Cookie-Editor format).
    
    Returns the RAW cookie list (not a dict) so Playwright can use
    full domain/path/secure/httpOnly attributes for proper auth.
    """
    print(f"  🍪 Chargement des cookies depuis {cookie_file}...")
    
    with open(cookie_file, 'r') as f:
        data = json.load(f)
    
    if isinstance(data, list):
        # Cookie-Editor format: list of {name, value, domain, path, secure, ...}
        # Keep ALL cookies (not just courrierinternational) — Google OAuth
        # sets auth cookies on multiple domains
        ci_count = sum(1 for c in data if "courrierinternational" in c.get("domain", ""))
        print(f"    → {len(data)} cookies chargés ({ci_count} Courrier International)")
        return data
    elif isinstance(data, dict):
        # Simple {name: value} dict — convert to list format
        cookie_list = [{"name": k, "value": v, "domain": ".courrierinternational.com", "path": "/"}
                       for k, v in data.items()]
        print(f"    → {len(cookie_list)} cookies chargés")
        return cookie_list
    
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  RSS FEED PARSING
# ══════════════════════════════════════════════════════════════════════════════

def fetch_rss_articles(max_articles: int = 50, sections_filter: list = None) -> list[Article]:
    """Fetch article metadata from RSS feed."""
    print("  📡 Récupération du flux RSS...")
    
    articles = []
    seen_urls = set()
    
    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and not feed.entries:
                print(f"    ⚠  Flux '{feed_name}' : erreur de parsing")
                continue
            
            print(f"    → Flux '{feed_name}' : {len(feed.entries)} entrées")
            
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                
                # Extract category from RSS
                rss_category = ""
                if entry.get("tags"):
                    rss_category = entry.tags[0].get("term", "")
                
                section = guess_section(url, rss_category)
                
                # Apply section filter
                if sections_filter:
                    section_lower = section.lower()
                    if not any(f.lower() in section_lower for f in sections_filter):
                        continue
                
                # Parse date
                date_str = ""
                if entry.get("published_parsed"):
                    try:
                        dt = datetime(*entry.published_parsed[:6])
                        date_str = dt.strftime("%d/%m/%Y")
                    except Exception:
                        pass
                
                # Get summary
                summary = ""
                if entry.get("summary"):
                    summary_soup = BeautifulSoup(entry.summary, "html.parser")
                    summary = extract_text(summary_soup)
                
                # Get image from RSS enclosure or media:content
                image_url = ""
                if entry.get("enclosures"):
                    for enc in entry.enclosures:
                        if enc.get("type", "").startswith("image"):
                            image_url = enc.get("href", "")
                            break
                if not image_url and entry.get("media_content"):
                    for media in entry.media_content:
                        if media.get("medium") == "image" or media.get("type", "").startswith("image"):
                            image_url = media.get("url", "")
                            break
                
                article = Article(
                    title=clean_text(entry.get("title", "Sans titre")),
                    url=url,
                    section=section,
                    author=entry.get("author", ""),
                    date=date_str,
                    summary=summary[:300] if summary else "",
                    image_url=image_url,
                )
                articles.append(article)
                
                if len(articles) >= max_articles:
                    break
            
        except Exception as e:
            print(f"    ❌ Erreur flux '{feed_name}' : {e}")
    
    print(f"  📰 {len(articles)} articles trouvés dans le RSS")
    return articles


# ══════════════════════════════════════════════════════════════════════════════
#  ARTICLE SCRAPING (Playwright-based for JS paywall support)
# ══════════════════════════════════════════════════════════════════════════════

def cookies_to_playwright(cookies_raw: list) -> list:
    """Convert Cookie-Editor cookie list to Playwright's expected format."""
    pw_cookies = []
    for c in cookies_raw:
        cookie = {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
        }
        # Playwright requires url OR (domain + path)
        # Fix domain: Cookie-Editor may have leading dot, Playwright accepts both
        if not cookie["domain"]:
            continue
        
        # Optional attributes
        if c.get("secure"):
            cookie["secure"] = True
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("sameSite") and c["sameSite"] is not None:
            # Cookie-Editor uses "no_restriction" / "lax" / "strict" / null
            ss_map = {
                "no_restriction": "None",
                "none": "None",
                "lax": "Lax",
                "strict": "Strict",
            }
            ss = ss_map.get(str(c["sameSite"]).lower(), None)
            if ss:
                cookie["sameSite"] = ss
                # sameSite=None requires secure=True
                if ss == "None":
                    cookie["secure"] = True
        if c.get("expirationDate"):
            cookie["expires"] = float(c["expirationDate"])
        
        pw_cookies.append(cookie)
    
    return pw_cookies


def create_playwright_context(cookies_raw: list):
    """Create a Playwright browser context with cookies injected.
    
    Returns (playwright_instance, browser, context, page) — caller must close.
    """
    from playwright.sync_api import sync_playwright
    
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="fr-FR",
        viewport={"width": 1280, "height": 900},
    )
    
    # Inject cookies
    if cookies_raw:
        pw_cookies = cookies_to_playwright(cookies_raw)
        if pw_cookies:
            try:
                context.add_cookies(pw_cookies)
                print(f"    → {len(pw_cookies)} cookies injectés dans le navigateur")
            except Exception as e:
                print(f"    ⚠  Erreur injection cookies : {e}")
                # Try injecting one by one, skipping bad ones
                ok = 0
                for c in pw_cookies:
                    try:
                        context.add_cookies([c])
                        ok += 1
                    except Exception:
                        pass
                print(f"    → {ok}/{len(pw_cookies)} cookies injectés (fallback)")
    
    page = context.new_page()
    
    # ── Session warmup: visit homepage to activate cookies/session ──
    # Some sites (especially those using Piano/paywall systems) need the session
    # to be "activated" by visiting the main page first before article access works.
    if cookies_raw:
        print("    → Activation de la session (visite homepage)...", end=" ", flush=True)
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            
            # Check authentication status
            html = page.content()
            if "subscriber" in html.lower() or "abonné" in html.lower() or "mon-compte" in html.lower():
                print("✅ abonné")
            elif "se connecter" in html.lower() or "s'abonner" in html.lower():
                print("⚠ non connecté")
                print("    ⚠  La session semble inactive. Refaites l'export Cookie-Editor")
                print("       depuis courrierinternational.com (après vous être connecté).")
            else:
                print("? (statut incertain)")
        except Exception as e:
            print(f"⚠ erreur: {e}")
    
    return pw, browser, context, page


def scrape_article_playwright(article: Article, page, include_images: bool = True) -> Article:
    """Scrape full article content using Playwright (handles JS paywalls)."""
    try:
        page.goto(article.url, wait_until="domcontentloaded", timeout=30000)
        # Wait for article content to render (paywall JS needs a moment)
        try:
            page.wait_for_selector(".article-text, .article-content, article.article",
                                   timeout=8000)
        except Exception:
            pass  # Selector not found, proceed with what we have
        time.sleep(0.5)
        
        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        
        # ── Extract source journal (original newspaper name) ──
        # Courrier International translates articles from foreign press
        source_selectors = [
            ".article-source",               # <a class="article-source">
            ".source-journal",
            "[class*='source-logo']",
        ]
        for sel in source_selectors:
            source_el = soup.select_one(sel)
            if source_el:
                text = extract_text(source_el)
                # Skip "Courrier international" — we want the original source
                if text and "courrier international" not in text.lower():
                    article.source_journal = text
                    break
        
        # Fallback: look for source in kicker or header
        if not article.source_journal:
            kicker = soup.select_one(".article-kicker, [class*='kicker']")
            if kicker:
                kicker_text = extract_text(kicker)
                source_match = re.search(r'(?:Vu d[e\']|Source\s*:\s*|Paru dans\s+)(.+?)(?:\.|$)', kicker_text)
                if source_match:
                    article.source_journal = source_match.group(1).strip()
        
        # ── Extract author ──
        if not article.author:
            author_selectors = [
                ".article-authors-vo",          # Actual selector from MHTML
                ".article-authors",
                ".article-author",
                "meta[name='author']",
            ]
            for sel in author_selectors:
                author_el = soup.select_one(sel)
                if author_el:
                    if author_el.name == "meta":
                        article.author = author_el.get("content", "")
                    else:
                        article.author = extract_text(author_el)
                    break
        
        # ── Extract hero image ──
        if include_images and not article.image_url:
            img_selectors = [
                "meta[property='og:image']",
                "figure.is-clickable img",      # Actual selector from MHTML
                ".article-content figure img",
                ".article-image img",
                "figure img",
            ]
            for sel in img_selectors:
                img_el = soup.select_one(sel)
                if img_el:
                    if img_el.name == "meta":
                        article.image_url = img_el.get("content", "")
                    else:
                        article.image_url = img_el.get("src", "") or img_el.get("data-src", "")
                    if article.image_url:
                        break
        
        # ── Extract image caption ──
        caption_selectors = [
            "figure.is-clickable figcaption",   # Actual selector from MHTML
            ".article-content figcaption",
            "figure figcaption",
        ]
        for sel in caption_selectors:
            cap_el = soup.select_one(sel)
            if cap_el:
                article.image_caption = extract_text(cap_el)
                break
        
        # ── Extract main content ──
        # Priority order based on MHTML analysis:
        #   .article-text (6774 chars) = just the body paragraphs
        #   .article-content (13394 chars) = broader container (includes images, read-more)
        content_selectors = [
            ".article-text",                    # ✅ Best: just body text
            ".article-content",                 # Good: broader container
            ".field--name-body",                # Drupal fallback
            ".article-body",
            "article.article",                  # Last resort: whole article
        ]
        
        content_el = None
        for sel in content_selectors:
            content_el = soup.select_one(sel)
            if content_el and len(extract_text(content_el)) > 200:
                break
            content_el = None
        
        if content_el:
            # Clean content: remove unwanted elements
            unwanted_selectors = [
                "aside",
                ".asset.asset-read-more",       # "À lire aussi" boxes
                "div.asset",                     # Other asset boxes
                ".article-sitesocial",
                ".article-ad",
                ".article-tertiary",
                ".article-secondary",           # Sidebar content
                ".article-aside",               # Aside
                "[class*='social-share']",
                "[class*='newsletter']",
                "[class*='pub-']",
                "[class*='ad-']",
                ".paywall-message",
                ".premium-cta",
                "script",
                "style",
                "iframe",
                "button",
                "form",
                "[class*='related']",
                "[class*='recommand']",
                ".article-readmore",
                ".tags",
                ".article-footer",
                "figure",                        # Remove figures (hero image handled separately)
            ]
            for sel in unwanted_selectors:
                for el in content_el.select(sel):
                    el.decompose()
            
            # Extract clean text with paragraph structure
            paragraphs = []
            for p in content_el.find_all(["p", "h2", "h3", "h4", "blockquote"]):
                text = extract_text(p)
                if text and len(text) > 5:
                    tag = p.name
                    if tag == "blockquote":
                        paragraphs.append(f'<blockquote><p>{text}</p></blockquote>')
                    elif tag in ("h2", "h3", "h4"):
                        # h2.ci-subtitle = inter-titles
                        paragraphs.append(f'<{tag}>{text}</{tag}>')
                    else:
                        paragraphs.append(f'<p>{text}</p>')
            
            article.content = "\n".join(paragraphs)
            
            if not article.content:
                raw = extract_text(content_el)
                if raw and len(raw) > 50:
                    article.content = f"<p>{raw}</p>"
        
        # ── Detect paywall truncation ──
        # Check for subscriber status badge
        subscriber_el = soup.select_one(".status.subscriber, [class*='subscriber']")
        is_subscriber = bool(subscriber_el and "abonné" in extract_text(subscriber_el).lower())
        
        is_paywalled = False
        paywall_indicators = [
            ".paywall", ".premium-only", ".subscriber-only",
            "[class*='paywall']", "[class*='subscribe']",
            "[class*='abon']",
        ]
        for sel in paywall_indicators:
            if soup.select_one(sel):
                is_paywalled = True
                break
        
        # Also check text content for paywall messages
        if not is_paywalled:
            body_text = extract_text(soup.select_one("body") or soup)
            if re.search(r'pour lire la suite.*abonnez', body_text, re.IGNORECASE):
                is_paywalled = True
        
        if is_paywalled and not is_subscriber and len(article.content or "") < 500:
            article.content += '\n<p class="paywall-notice"><em>[Article réservé aux abonnés — contenu tronqué]</em></p>'
        
        # ── Summary fallback ──
        if not article.summary:
            # Try header standfirst
            standfirst = soup.select_one(".article-header p, .article-standfirst")
            if standfirst:
                article.summary = extract_text(standfirst)[:300]
            else:
                desc = soup.select_one("meta[property='og:description']")
                if desc:
                    article.summary = desc.get("content", "")[:300]
        
    except Exception as e:
        print(f"❌ {e}")
    
    return article


def download_image_playwright(url: str, page, timeout: int = 10000) -> str:
    """Download image via Playwright (uses same authenticated session)."""
    if not url:
        return ""
    try:
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = BASE_URL + url
        
        resp = page.request.get(url, timeout=timeout)
        if resp.ok:
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if "image" not in content_type:
                content_type = "image/jpeg"
            b64 = base64.b64encode(resp.body()).decode("utf-8")
            return f"data:{content_type};base64,{b64}"
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  HTML & PDF GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def format_date_french(date_str: str = "") -> str:
    """Return a nicely formatted French date string."""
    mois = [
        "", "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"
    ]
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    
    now = datetime.now()
    return f"{jours[now.weekday()]} {now.day} {mois[now.month]} {now.year}"


def build_cover_html(articles: list[Article], fmt: dict) -> str:
    """Build cover page HTML."""
    date_fr = format_date_french()
    
    # Select up to 4 highlight articles
    highlights = articles[:4]
    
    hl_html = ""
    for art in highlights:
        source_info = f' — <span class="hl-source">{art.source_journal}</span>' if art.source_journal else ""
        hl_html += f'''
        <div class="cover-highlight">
            <span class="hl-cat">{art.section}</span>
            <span class="hl-title">{art.title}</span>{source_info}
        </div>'''
    
    return f'''
    <div class="cover">
        <div class="cover-brand">COURRIER</div>
        <div class="cover-brand-sub">INTERNATIONAL</div>
        <div class="cover-tagline">Le meilleur de la presse mondiale</div>
        <div class="cover-rule"></div>
        <div class="cover-date">{date_fr}</div>
        <div class="cover-edition">Digest numérique</div>
        <div class="cover-highlights">{hl_html}</div>
    </div>'''


def build_toc_html(articles: list[Article], fmt: dict) -> str:
    """Build table of contents HTML."""
    toc = '<div class="toc"><h2 class="toc-title">Sommaire</h2>'
    
    # Group by section
    sections = {}
    for i, art in enumerate(articles, 1):
        sec = art.section
        if sec not in sections:
            sections[sec] = []
        sections[sec].append((i, art))
    
    for sec_name, sec_articles in sections.items():
        toc += f'<div class="toc-section">'
        toc += f'<div class="toc-section-name">{sec_name}</div>'
        for num, art in sec_articles:
            source = f' <span class="toc-source">({art.source_journal})</span>' if art.source_journal else ""
            toc += f'''
            <div class="toc-entry">
                <span class="toc-num">{num:02d}</span>
                <span class="toc-article-title">{art.title}</span>{source}
            </div>'''
        toc += '</div>'
    
    toc += '</div>'
    return toc


def build_article_html(article: Article, index: int, fmt: dict, include_images: bool = True) -> str:
    """Build HTML for a single article."""
    content = article.content
    
    # Add drop cap to first paragraph
    if content:
        content = re.sub(
            r'<p>(\s*[A-ZÀ-ÖÙ-Ü«"])',
            r'<p><span class="drop-cap">\1</span>',
            content, count=1
        )
    
    # Hero image
    img_html = ""
    if include_images and article.image_data:
        caption = f'<div class="img-caption">{article.image_caption}</div>' if article.image_caption else ""
        img_html = f'''
        <div class="hero-img-container">
            <img class="hero-img" src="{article.image_data}" alt="" />
            {caption}
        </div>'''
    
    # Source info
    source_html = ""
    if article.source_journal:
        source_html = f'<div class="article-source-journal">📰 {article.source_journal}</div>'
    
    # Author and date
    meta_parts = []
    if article.author:
        meta_parts.append(article.author)
    if article.date:
        meta_parts.append(article.date)
    meta_html = f'<div class="article-meta">{" · ".join(meta_parts)}</div>' if meta_parts else ""
    
    # Summary / chapô
    summary_html = ""
    if article.summary and article.summary not in (article.content or ""):
        summary_html = f'<div class="article-summary">{article.summary}</div>'
    
    return f'''
    <article class="article" id="article-{index}">
        <div class="article-header">
            <div class="article-section">{article.section}</div>
            <h1 class="article-title">{article.title}</h1>
            {source_html}
            {meta_html}
        </div>
        {img_html}
        {summary_html}
        <div class="article-body">
            {content if content else '<p class="no-content"><em>[Contenu non disponible — vérifiez votre abonnement]</em></p>'}
        </div>
    </article>
    <div class="article-separator"></div>'''


def build_css(fmt: dict) -> str:
    """Build CSS for the given format profile."""
    num_columns = fmt.get("columns", 1)
    margin = fmt["margin"]

    # Column styles for multi-column layouts (A4 premium, A4 landscape, etc.)
    columns_css = ""
    if num_columns > 1:
        columns_css = f"""
        .article-body {{
            column-count: {num_columns};
            column-gap: 6mm;
            column-rule: 0.3pt solid #ddd;
        }}
        .article-body h2, .article-body h3 {{
            column-span: all;
        }}
        .hero-img-container {{
            column-span: all;
        }}
        """
    
    return f'''
    @page {{
        size: {fmt["width_mm"]}mm {fmt["height_mm"]}mm;
        margin: {margin};
        @bottom-right {{
            content: counter(page);
            font-family: "DejaVu Sans", Helvetica, sans-serif;
            font-size: 7pt;
            color: #999;
        }}
    }}
    @page :first {{
        margin: 0;
        @bottom-right {{ content: none; }}
    }}
    
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    
    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: {fmt["font_size"]};
        line-height: {fmt["line_height"]};
        color: #1a1a1a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
        orphans: 3;
        widows: 3;
    }}
    
    /* ── COVER ── */
    .cover {{
        page-break-after: always;
        width: {fmt["width_mm"]}mm;
        height: {fmt["height_mm"]}mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        background: #faf9f7;
        padding: {fmt["cover_padding"]};
        position: relative;
    }}
    .cover::before, .cover::after {{
        content: "";
        position: absolute;
        left: 10%;
        right: 10%;
        height: 0.8pt;
        background: #c0392b;
    }}
    .cover::before {{ top: 8%; }}
    .cover::after {{ bottom: 8%; }}
    
    .cover-brand {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["cover_title_size"]};
        font-weight: 700;
        letter-spacing: 0.2em;
        color: #c0392b;
        text-transform: uppercase;
    }}
    .cover-brand-sub {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: calc({fmt["cover_title_size"]} * 0.55);
        font-weight: 400;
        letter-spacing: 0.35em;
        color: #1a1a1a;
        text-transform: uppercase;
        margin-bottom: 3mm;
    }}
    .cover-tagline {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["cover_subtitle_size"]};
        font-style: italic;
        color: #666;
        margin-bottom: 5mm;
    }}
    .cover-rule {{
        width: 30%;
        height: 0.5pt;
        background: #c0392b;
        margin: 3mm auto;
    }}
    .cover-date {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["cover_edition_size"]};
        color: #333;
        text-transform: capitalize;
        margin-bottom: 1mm;
    }}
    .cover-edition {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: calc({fmt["cover_edition_size"]} * 0.85);
        color: #999;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-bottom: 6mm;
    }}
    .cover-highlights {{
        text-align: left;
        width: 80%;
        border-top: 0.5pt solid #ddd;
        padding-top: 3mm;
    }}
    .cover-highlight {{
        margin-bottom: 2.5mm;
        line-height: 1.3;
    }}
    .hl-cat {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["cover_hl_cat_size"]};
        text-transform: uppercase;
        color: #c0392b;
        letter-spacing: 0.05em;
        display: block;
        margin-bottom: 0.5mm;
    }}
    .hl-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["cover_hl_title_size"]};
        font-weight: 600;
        color: #1a1a1a;
    }}
    .hl-source {{
        font-style: italic;
        color: #888;
        font-size: calc({fmt["cover_hl_title_size"]} * 0.8);
    }}
    
    /* ── TOC ── */
    .toc {{
        page-break-after: always;
        padding-top: 4mm;
    }}
    .toc-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["h1_size"]};
        font-weight: 700;
        color: #1a1a1a;
        margin-bottom: 4mm;
        padding-bottom: 2mm;
        border-bottom: 1.5pt solid #c0392b;
    }}
    .toc-section {{
        margin-bottom: 3mm;
    }}
    .toc-section-name {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["toc_cat_size"]};
        text-transform: uppercase;
        color: #c0392b;
        letter-spacing: 0.08em;
        font-weight: 600;
        margin-bottom: 1.5mm;
        padding-top: 2mm;
        border-top: 0.3pt solid #eee;
    }}
    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 1mm;
        line-height: 1.3;
    }}
    .toc-num {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["toc_num_size"]};
        color: #ddd;
        font-weight: 700;
        width: {fmt["toc_num_width"]};
        flex-shrink: 0;
    }}
    .toc-article-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["toc_title_size"]};
        color: #333;
    }}
    .toc-source {{
        font-size: {fmt["toc_author_size"]};
        color: #999;
        font-style: italic;
    }}
    
    /* ── ARTICLES ── */
    .article {{
        page-break-inside: avoid;
        margin-bottom: 4mm;
    }}
    .article-header {{
        margin-bottom: 3mm;
    }}
    .article-section {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["toc_cat_size"]};
        text-transform: uppercase;
        color: #c0392b;
        letter-spacing: 0.08em;
        font-weight: 600;
        margin-bottom: 1mm;
    }}
    .article-title {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["h1_size"]};
        font-weight: 700;
        color: #1a1a1a;
        line-height: 1.2;
        margin-bottom: 2mm;
    }}
    .article-source-journal {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["toc_author_size"]};
        color: #666;
        font-style: italic;
        margin-bottom: 1mm;
    }}
    .article-meta {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["caption_size"]};
        color: #999;
        margin-bottom: 2mm;
    }}
    .article-summary {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: calc({fmt["font_size"]} * 1.05);
        font-style: italic;
        color: #444;
        padding: 2mm 0;
        margin-bottom: 2mm;
        border-left: 2pt solid #c0392b;
        padding-left: 3mm;
    }}
    
    .hero-img-container {{
        margin: 2mm 0 3mm 0;
        text-align: center;
    }}
    .hero-img {{
        max-width: 100%;
        max-height: {fmt["img_max_height"]};
        object-fit: cover;
        border-radius: 1mm;
    }}
    .img-caption {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["caption_size"]};
        color: #888;
        font-style: italic;
        margin-top: 1mm;
        text-align: center;
    }}
    
    .article-body p {{
        margin-bottom: 2mm;
        text-indent: 3mm;
    }}
    .article-body p:first-child {{
        text-indent: 0;
    }}
    .article-body h2 {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["h2_size"]};
        font-weight: 700;
        color: #1a1a1a;
        margin: 3mm 0 2mm 0;
    }}
    .article-body h3 {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["h3_size"]};
        font-weight: 600;
        color: #333;
        margin: 2mm 0 1.5mm 0;
    }}
    .article-body blockquote {{
        border-left: 2pt solid #c0392b;
        padding-left: 3mm;
        margin: 2mm 0;
        font-style: italic;
        color: #555;
    }}
    
    .drop-cap {{
        float: left;
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: {fmt["drop_cap_size"]};
        font-weight: 700;
        color: #c0392b;
        line-height: 0.8;
        padding-right: {fmt["drop_cap_padding"]};
        padding-top: 1mm;
    }}
    
    .article-separator {{
        height: 0.5pt;
        background: linear-gradient(to right, #c0392b 30%, transparent 100%);
        margin: 4mm 0;
        page-break-after: auto;
    }}
    
    .no-content {{
        color: #999;
        text-align: center;
        padding: 4mm;
    }}
    .paywall-notice {{
        color: #c0392b;
        text-align: center;
        padding: 2mm;
        border: 0.3pt dashed #c0392b;
        border-radius: 2mm;
        margin-top: 3mm;
    }}
    
    /* ── COLOPHON ── */
    .colophon {{
        page-break-before: always;
        padding-top: 20mm;
        text-align: center;
    }}
    .colophon-brand {{
        font-family: "DejaVu Serif", Georgia, serif;
        font-size: calc({fmt["h1_size"]} * 0.8);
        font-weight: 700;
        color: #c0392b;
        letter-spacing: 0.15em;
        text-transform: uppercase;
    }}
    .colophon-rule {{
        width: 20%;
        height: 0.5pt;
        background: #c0392b;
        margin: 3mm auto;
    }}
    .colophon-text {{
        font-family: "DejaVu Sans", Helvetica, sans-serif;
        font-size: {fmt["colophon_font_size"]};
        color: #999;
        line-height: 1.6;
    }}
    
    {columns_css}
    '''


def build_colophon_html(article_count: int) -> str:
    """Build colophon / end page."""
    date_fr = format_date_french()
    return f'''
    <div class="colophon">
        <div class="colophon-brand">Courrier International</div>
        <div class="colophon-rule"></div>
        <div class="colophon-text">
            Digest numérique — {date_fr}<br/>
            {article_count} articles sélectionnés<br/><br/>
            Généré automatiquement pour lecture hors-ligne<br/>
            courrierinternational.com
        </div>
    </div>'''


def generate_pdf(articles: list[Article], fmt_name: str, output_dir: Path,
                 date_str: str, include_images: bool = True) -> Optional[Path]:
    """Generate a PDF for the given format."""
    from weasyprint import HTML
    
    fmt = FORMAT_PROFILES[fmt_name]
    print(f"    {fmt['label']}...", end=" ", flush=True)
    
    css = build_css(fmt)
    cover = build_cover_html(articles, fmt)
    toc = build_toc_html(articles, fmt)
    
    articles_html = ""
    for i, art in enumerate(articles, 1):
        articles_html += build_article_html(art, i, fmt, include_images)
    
    colophon = build_colophon_html(len(articles))
    
    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8"/>
    <title>Courrier International — {date_str}</title>
    <style>{css}</style>
</head>
<body>
    {cover}
    {toc}
    {articles_html}
    {colophon}
</body>
</html>'''
    
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_str}-courrier_international_{fmt['suffix']}.pdf"
    output_path = output_dir / filename
    
    try:
        doc = HTML(string=html_content)
        doc.write_pdf(str(output_path))
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"✅ ({size_mb:.1f} Mo)")
        return output_path
    except Exception as e:
        print(f"❌ {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Courrier International — Scraper & PDF Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cookies", default="",
                        help="Fichier cookies JSON (Cookie-Editor ou dict)")
    parser.add_argument("--chrome-profile", default="",
                        help="Chemin du profil Chrome pour réutiliser la session Google "
                             "(défaut: détection auto ~/.config/google-chrome)")
    parser.add_argument("--user", default=os.environ.get("CI_USER", ""),
                        help="Email abonné pour login direct (ou env CI_USER) — "
                             "ne fonctionne PAS avec les comptes Google")
    parser.add_argument("--password", default=os.environ.get("CI_PASS", ""),
                        help="Mot de passe pour login direct (ou env CI_PASS)")
    parser.add_argument("--format", default="all",
                        help="Format(s) : phone, ereader, tablet7, tablet10, a4premium, a4landscape, epub, all")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Date pour le nom de fichier (YYYY-MM-DD)")
    parser.add_argument("--max-articles", type=int, default=30,
                        help="Nombre max d'articles (défaut: 30)")
    parser.add_argument("--sections", default="",
                        help="Filtrer par sections (séparées par virgules)")
    parser.add_argument("--min-length", type=int, default=800,
                        help="Longueur min. du contenu en caractères pour filtrer les dépêches (défaut: 800)")
    parser.add_argument("--no-images", action="store_true",
                        help="Désactiver le téléchargement des images")
    parser.add_argument("--output-dir", default="",
                        help="Dossier de sortie (défaut: ~/kDrive/newspapers/journaux_du_jour/)")
    parser.add_argument("--rss-only", action="store_true",
                        help="Ne pas scraper les articles, utiliser seulement le RSS")
    
    args = parser.parse_args()
    
    date_str = args.date
    include_images = not args.no_images
    output_dir = Path(args.output_dir) if args.output_dir else OUTPUT_BASE
    sections_filter = [s.strip() for s in args.sections.split(",") if s.strip()] if args.sections else None
    
    # Determine formats
    valid_formats = set(FORMAT_PROFILES.keys()) | {"epub"}
    if args.format == "all":
        formats = list(FORMAT_PROFILES.keys()) + ["epub"]
    else:
        formats = [f.strip() for f in args.format.split(",")]
        for f in formats:
            if f not in valid_formats:
                print(f"❌ Format inconnu : '{f}'")
                print(f"   Formats disponibles : {', '.join(sorted(valid_formats))}")
                sys.exit(1)
    
    print("╔══════════════════════════════════════════════════╗")
    print("║  📰  Courrier International — Digest            ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  📅 Date : {date_str}")
    print(f"  📐 Formats : {', '.join(formats)}")
    print(f"  📂 Sortie : {output_dir}")
    if sections_filter:
        print(f"  🏷️  Sections : {', '.join(sections_filter)}")
    print()
    
    # ── Step 1: Authentication ──
    # Priority: cookies file > Chrome profile > direct login
    cookies = []
    if args.cookies:
        cookies = load_cookies_from_file(args.cookies)
    elif args.chrome_profile or (not args.user and not args.password):
        # Try Chrome profile (best for Google OAuth accounts)
        cookies = extract_cookies_from_chrome_profile(args.chrome_profile)
        if not cookies and not args.user:
            print("  ⚠  Pas d'authentification — seul le contenu gratuit sera accessible.")
            print("     Options pour le contenu abonné (compte Google) :")
            print("       1. --cookies ci_cookies.json  (export Cookie-Editor)")
            print("       2. --chrome-profile            (réutilise votre session Chrome)")
            print("       3. --user/--password            (login direct, pas pour Google)")
    
    if not cookies and args.user and args.password:
        cookies = login_with_playwright(args.user, args.password)
    print()
    
    # ── Step 2: Fetch article list from RSS ──
    articles = fetch_rss_articles(
        max_articles=args.max_articles,
        sections_filter=sections_filter,
    )
    
    if not articles:
        print("  ❌ Aucun article trouvé. Vérifiez la connexion.")
        sys.exit(1)
    
    # ── Step 3: Scrape full article content (Playwright) ──
    if not args.rss_only:
        print(f"\n  🌐 Lancement du navigateur pour scraper {len(articles)} articles...")
        pw, browser, context, page = create_playwright_context(cookies)
        
        try:
            scraped = 0
            for i, article in enumerate(articles, 1):
                print(f"    [{i:2d}/{len(articles)}] {article.title[:60]}...", end=" ", flush=True)
                
                scrape_article_playwright(article, page, include_images)
                
                if article.content:
                    scraped += 1
                    print("✅")
                else:
                    print("⚠ (vide)")
                
                # Rate limiting — be respectful
                time.sleep(1.0)
            
            print(f"\n  📊 {scraped}/{len(articles)} articles avec contenu")
            
            # Filter out empty articles
            articles = [a for a in articles if a.content or a.summary]
            
            # Filter out short articles (dépêches, brèves)
            min_len = args.min_length
            before_filter = len(articles)
            articles = [a for a in articles if a.content and len(a.content) >= min_len]
            filtered_out = before_filter - len(articles)
            if filtered_out:
                print(f"  🔍 {filtered_out} articles courts filtrés (< {min_len} car.)")
            
            if not articles:
                print("  ❌ Aucun article avec du contenu. Vérifiez l'authentification.")
                sys.exit(1)
            
            # ── Step 4: Download images ──
            if include_images:
                print(f"\n  🖼️  Téléchargement des images...")
                img_count = 0
                for art in articles:
                    if art.image_url and not art.image_data:
                        art.image_data = download_image_playwright(art.image_url, page)
                        if art.image_data:
                            img_count += 1
                print(f"    → {img_count} images téléchargées")
        
        finally:
            browser.close()
            pw.stop()
    
    # ── Step 5: Sort articles by section ──
    section_order = [
        "Éditorial", "France vue de l'étranger", "Géopolitique", "Politique",
        "Économie", "Société", "Sciences & Environnement", "Culture",
        "Reportage", "Enquête", "Analyse", "Sport", "Courrier Expat",
        "En bref", "Dessin de presse", "Infographie", "Actualité",
    ]
    
    def section_sort_key(article):
        sec = article.section
        try:
            return section_order.index(sec)
        except ValueError:
            return len(section_order)
    
    articles.sort(key=section_sort_key)
    
    # ── Step 6: Generate outputs ──
    print(f"\n  🖨️  Génération des fichiers ({len(articles)} articles)...")
    generated = []
    for fmt_name in formats:
        if fmt_name == "epub":
            epub_articles = []
            for art in articles:
                author = art.author
                if art.source_journal:
                    author = f"{author} ({art.source_journal})" if author else art.source_journal
                epub_articles.append({
                    "title": art.title,
                    "author": author,
                    "category": art.section,
                    "lead": art.summary,
                    "content_html": art.content,
                    "image_data_uri": art.image_data,
                    "image_url": art.image_url if not art.image_data else "",
                    "image_caption": art.image_caption,
                })
            epub_path = output_dir / f"{date_str}-courrier.epub"
            generate_epub(
                epub_articles,
                publication_title="Courrier International",
                edition_title=f"Édition du {date_str}",
                date_str=date_str,
                output_path=epub_path,
                publisher="Courrier International",
            )
            generated.append(epub_path)
            continue

        result = generate_pdf(articles, fmt_name, output_dir, date_str, include_images)
        if result:
            generated.append(result)

    # ── Summary ──
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  ✅  Terminé !                                   ║")
    print("╚══════════════════════════════════════════════════╝")
    for path in generated:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  📄 {path.name} ({size_mb:.1f} Mo)")
    
    if not generated:
        print("  ⚠  Aucun PDF généré.")
        sys.exit(1)
    
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
