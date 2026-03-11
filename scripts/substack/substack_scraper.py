#!/usr/bin/env python3
"""
Substack Newsletter Scraper & PDF Generator
============================================
Downloads the latest articles from any Substack newsletter and generates
formatted PDF digests for phone, e-reader (6"), tablet (7"), tablet (10")
and a premium A4 "magazine" edition with photos and New Yorker-style layout.

Authentication:
    Substack uses "magic link" email login by default. Password login is
    possible but fragile (may require 2FA). The recommended approach is to
    export your browser cookies from a logged-in Substack session.

    To export cookies:
    1. Install "Get cookies.txt LOCALLY" browser extension
    2. Log into Substack in your browser
    3. Click the extension on any Substack page → download cookies
    4. Pass the file with --cookies cookies.json

Usage:
    # Single newsletter
    python3 substack_scraper.py --url https://example.substack.com
    python3 substack_scraper.py --url https://example.substack.com --cookies cookies.json

    # Interactive mode: list all subscriptions, pick which ones to digest
    python3 substack_scraper.py --cookies cookies.json --select
    python3 substack_scraper.py --cookies cookies.json   # reuses last selection

    # List subscriptions without generating PDFs
    python3 substack_scraper.py --cookies cookies.json --list

Dependencies:
    pip install requests beautifulsoup4 weasyprint
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epub_generator import generate_epub as _generate_epub_shared

# ── Config persistence ─────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".config" / "substack_scraper"
CONFIG_FILE = CONFIG_DIR / "selection.json"

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

OUTPUT_DIR = Path.home() / "kDrive" / "newspapers" / "substack"
CONFIG_DIR = Path.home() / ".config" / "substack_scraper"
CONFIG_FILE = CONFIG_DIR / "selection.json"
REQUEST_DELAY = 1.5  # seconds between API requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}


# ── URL helpers ────────────────────────────────────────────────────────────
def parse_substack_url(url: str) -> tuple[str, str]:
    """Parse a Substack URL and return (base_url, publication_name).

    Handles both:
      - https://example.substack.com
      - https://www.example.com  (custom domain)
    """
    url = url.rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Standard substack.com subdomain
    if hostname.endswith(".substack.com"):
        name = hostname.replace(".substack.com", "").replace("www.", "")
    else:
        # Custom domain — use the hostname itself
        name = hostname.replace("www.", "").split(".")[0]

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, name


# ── Authentication ─────────────────────────────────────────────────────────
def load_cookies(session: requests.Session, cookies_path: str, base_url: str) -> bool:
    """Load cookies from a JSON file (browser extension export format).

    Supports two formats:
    1. Standard extension export: [{"name": "...", "value": "...", "domain": "..."}, ...]
    2. Netscape/txt format: auto-detected and parsed

    The critical cookie is 'substack.sid' — the session token.
    """
    print(f"  🍪 Chargement des cookies depuis {cookies_path}…")

    path = Path(cookies_path)
    if not path.exists():
        print(f"  ❌ Fichier non trouvé : {cookies_path}")
        return False

    text = path.read_text(encoding="utf-8", errors="replace").strip()

    # Try JSON format first
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                # Simple key-value dict
                for name, value in data.items():
                    session.cookies.set(name, str(value))
            elif isinstance(data, list):
                for cookie in data:
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    domain = cookie.get("domain", "")
                    if name and value:
                        session.cookies.set(name, value, domain=domain or None)
            print(f"  ✅ {len(session.cookies)} cookies chargés.")
        except json.JSONDecodeError as e:
            print(f"  ❌ Erreur de parsing JSON : {e}")
            return False
    else:
        # Netscape cookies.txt format
        count = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _, path_val, secure, _, name, value = parts[:7]
                session.cookies.set(name, value, domain=domain)
                count += 1
        if count == 0:
            print("  ❌ Aucun cookie valide trouvé dans le fichier.")
            return False
        print(f"  ✅ {count} cookies chargés (format Netscape).")

    # Verify session is valid
    has_sid = any("substack.sid" in c.name or "connect.sid" in c.name
                  for c in session.cookies)
    if not has_sid:
        print("  ⚠  Cookie 'substack.sid' non trouvé — le contenu payant")
        print("     ne sera peut-être pas accessible.")

    # Quick validation: try to access the API
    try:
        # For substack.com (multi-newsletter mode), test with subscriptions
        parsed = urlparse(base_url)
        if parsed.hostname in ("substack.com", "www.substack.com"):
            test_url = f"{base_url}/api/v1/subscriptions"
        else:
            test_url = f"{base_url}/api/v1/archive?sort=new&limit=1"

        test_resp = session.get(test_url, headers=HEADERS, timeout=15)
        if test_resp.status_code == 200:
            data = test_resp.json()
            if data:
                print("  ✅ Session valide — accès API confirmé.")
                return True
    except Exception:
        pass

    # Even without sid, public posts are accessible
    print("  ℹ️  Tentative de continuer (les articles gratuits restent accessibles).")
    return True


def login_with_password(session: requests.Session, email: str, password: str,
                        base_url: str) -> bool:
    """Attempt to log in to Substack with email/password.

    Note: Substack increasingly uses magic links and may require 2FA.
    This method works if you have a password set on your account.
    """
    print(f"  🔐 Connexion avec {email}…")

    login_url = "https://substack.com/api/v1/login"
    payload = {
        "email": email,
        "password": password,
        "captcha_response": None,
    }

    try:
        resp = session.post(
            login_url,
            json=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "Origin": "https://substack.com",
                "Referer": "https://substack.com/sign-in",
            },
            timeout=30,
        )

        if resp.status_code == 200:
            data = resp.json()
            # Substack may require email confirmation
            if data.get("requires_confirmation"):
                print("  ⚠  Substack demande une confirmation par email (magic link).")
                print("     Utilisez plutôt --cookies avec un export de vos cookies navigateur.")
                return False

            # Check if we got session cookies
            has_sid = any("substack.sid" in c.name or "connect.sid" in c.name
                          for c in session.cookies)
            if has_sid:
                print("  ✅ Connecté avec succès.")
                return True

        if resp.status_code == 401:
            print("  ❌ Identifiants incorrects.")
            return False

        # Could be 2FA, CAPTCHA, etc.
        print(f"  ⚠  Réponse inattendue (HTTP {resp.status_code}).")
        try:
            err = resp.json()
            if "errors" in err:
                for e in err["errors"]:
                    print(f"     → {e.get('msg', e)}")
        except Exception:
            pass

        print("  💡 Conseil : utilisez --cookies avec un export de vos cookies navigateur.")
        return False

    except Exception as e:
        print(f"  ❌ Erreur de connexion : {e}")
        return False


# ── Subscription listing ───────────────────────────────────────────────────
def fetch_subscriptions(session: requests.Session) -> list[dict]:
    """Fetch the list of newsletters the authenticated user subscribes to.

    Primary endpoint: GET https://substack.com/api/v1/subscriptions
    Returns:
      - subscriptions[]: id, publication_id, type (free/paid), etc.
      - publications[]: name, subdomain, custom_domain, logo_url, etc.

    We join the two arrays on publication_id to build the full list.
    """
    print("  📋 Récupération de vos abonnements Substack…")

    subscriptions = []

    # ── Primary method: /api/v1/subscriptions ──────────────────────────
    try:
        resp = session.get(
            "https://substack.com/api/v1/subscriptions",
            headers=HEADERS, timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()

            subs_list = data.get("subscriptions", [])
            pubs_list = data.get("publications", [])

            # Index publications by id for fast lookup
            pubs_by_id = {}
            for pub in pubs_list:
                pub_id = pub.get("id")
                if pub_id:
                    pubs_by_id[pub_id] = pub

            for sub in subs_list:
                pub_id = sub.get("publication_id")
                pub = pubs_by_id.get(pub_id, {})
                if not pub:
                    continue

                name = pub.get("name", "")
                subdomain = pub.get("subdomain", "")
                custom_domain = pub.get("custom_domain") or ""

                if custom_domain:
                    base_url = f"https://{custom_domain}"
                elif subdomain:
                    base_url = f"https://{subdomain}.substack.com"
                else:
                    continue

                if not name:
                    name = subdomain or custom_domain

                # Determine if paid subscription
                sub_type = sub.get("type", "free")
                is_paid = sub_type in ("paid", "premium", "founding")

                # Author name — try multiple fields
                author = (pub.get("author_name", "")
                          or pub.get("byline_name", "")
                          or "")

                # Description
                description = (pub.get("hero_text", "")
                               or pub.get("description", "")
                               or "")[:80]

                subscriptions.append({
                    "name": name,
                    "url": base_url,
                    "subdomain": subdomain,
                    "author": author,
                    "is_paid": is_paid,
                    "logo_url": pub.get("logo_url", ""),
                    "description": description,
                })

            if subscriptions:
                n_paid = sum(1 for s in subscriptions if s["is_paid"])
                n_free = len(subscriptions) - n_paid
                print(f"     ✅ {len(subscriptions)} abonnements trouvés "
                      f"({n_free} gratuits, {n_paid} payants).")
                return subscriptions

        elif resp.status_code == 403:
            print("  ⚠  Accès refusé (HTTP 403) — le cookie est peut-être "
                  "expiré.")
            print("     Reconnectez-vous à substack.com et ré-exportez "
                  "vos cookies.")
        elif resp.status_code == 401:
            print("  ⚠  Non authentifié (HTTP 401) — cookies invalides.")

    except Exception as e:
        print(f"  ⚠  Erreur endpoint subscriptions: {e}")

    # ── Fallback: parse reader inbox page ──────────────────────────────
    try:
        resp = session.get("https://substack.com/inbox",
                           headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                data = json.loads(script.string)
                page_props = data.get("props", {}).get("pageProps", {})

                # Try multiple locations in the page data
                for key in ("subscriptions", "feeds", "publications"):
                    items = page_props.get(key, [])
                    for item in items:
                        pub = item.get("publication", item)
                        name = pub.get("name", "")
                        subdomain = pub.get("subdomain", "")
                        custom_domain = pub.get("custom_domain") or ""
                        if custom_domain:
                            base_url = f"https://{custom_domain}"
                        elif subdomain:
                            base_url = f"https://{subdomain}.substack.com"
                        else:
                            continue
                        if name and base_url:
                            subscriptions.append({
                                "name": name,
                                "url": base_url,
                                "subdomain": subdomain,
                                "author": pub.get("author_name", ""),
                                "is_paid": item.get("type", "") in (
                                    "paid", "premium", "founding"),
                                "logo_url": pub.get("logo_url", ""),
                                "description": (pub.get("hero_text", "")
                                                or "")[:80],
                            })

                if subscriptions:
                    print(f"     ✅ {len(subscriptions)} abonnements "
                          f"trouvés (via inbox).")
                    return subscriptions
    except Exception:
        pass

    if not subscriptions:
        print("  ❌ Impossible de récupérer les abonnements.")
        print("     Vérifiez que vos cookies sont valides et à jour.")
    return subscriptions


# ── Config persistence ─────────────────────────────────────────────────────
def load_selection() -> list[str]:
    """Load the saved newsletter selection (list of URLs)."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return data.get("selected_urls", [])
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def save_selection(selected_urls: list[str]):
    """Save the newsletter selection for future runs."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "selected_urls": selected_urls,
        "updated": datetime.now().isoformat(),
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Interactive selector ───────────────────────────────────────────────────
def interactive_select(subscriptions: list[dict],
                       previous_selection: list[str]) -> list[dict]:
    """Display an interactive selector for newsletter selection.

    Designed for large lists (100+ newsletters):
    - Search/filter with /keyword
    - Paginated display (20 per page)
    - Toggle individual items or ranges
    - Show only selected items before confirming
    """
    # Build selection state from previous config
    selected = set()
    sub_urls = {s["url"]: i for i, s in enumerate(subscriptions)}
    for url in previous_selection:
        if url in sub_urls:
            selected.add(sub_urls[url])

    current_filter = ""
    page = 0
    PAGE_SIZE = 20

    def get_filtered():
        """Return indices matching current filter."""
        if not current_filter:
            return list(range(len(subscriptions)))
        kw = current_filter.lower()
        return [i for i, s in enumerate(subscriptions)
                if kw in s["name"].lower()
                or kw in s.get("author", "").lower()
                or kw in s.get("description", "").lower()]

    def show_page(filtered, pg):
        """Display one page of results."""
        total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
        pg = max(0, min(pg, total_pages - 1))

        start = pg * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(filtered))

        print()
        filter_info = (f'  🔍 Filtre: "{current_filter}"'
                       if current_filter else "  📋 Tous les abonnements")
        print(f"{filter_info}  —  "
              f"Page {pg+1}/{total_pages}  —  "
              f"{len(selected)} sélectionnés")
        print(f"  {'─' * 54}")

        for pos in range(start, end):
            idx = filtered[pos]
            sub = subscriptions[idx]
            check = "✓" if idx in selected else " "
            paid = " 💰" if sub.get("is_paid") else ""
            author = f" — {sub['author']}" if sub.get("author") else ""
            # Truncate name to fit terminal
            label = f"{sub['name']}{author}{paid}"
            if len(label) > 55:
                label = label[:52] + "…"
            print(f"    [{check}] {idx+1:3d}. {label}")

        print(f"  {'─' * 54}")
        return pg, total_pages

    def show_help():
        print()
        print("  ┌─────────────────────────────────────────────┐")
        print("  │  Commandes :                                 │")
        print("  │  3 ou 5,12,7   → cocher/décocher            │")
        print("  │  10-25         → cocher/décocher une plage  │")
        print("  │  /mot          → filtrer par mot-clé        │")
        print("  │  //            → effacer le filtre          │")
        print("  │  + ou -        → page suivante/précédente   │")
        print("  │  a             → tout sélectionner (filtrés)│")
        print("  │  n             → tout désélectionner        │")
        print("  │  v             → voir la sélection actuelle │")
        print("  │  ok            → valider et lancer          │")
        print("  │  q             → quitter                    │")
        print("  │  ?             → cette aide                 │")
        print("  └─────────────────────────────────────────────┘")

    # Initial display
    filtered = get_filtered()
    show_help()
    page, total_pages = show_page(filtered, page)

    while True:
        try:
            choice = input("\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Annulé.")
            sys.exit(0)

        if not choice:
            continue

        low = choice.lower()

        # ── Validate and go ────────────────────────────────────────
        if low in ("ok", "go", "start", "done"):
            if not selected:
                print("  ⚠  Aucune newsletter sélectionnée. "
                      "Tapez des numéros pour en cocher.")
                continue
            break

        # ── Quit ───────────────────────────────────────────────────
        elif low in ("q", "quit", "exit"):
            print("  Annulé.")
            sys.exit(0)

        # ── Help ───────────────────────────────────────────────────
        elif low == "?":
            show_help()
            page, total_pages = show_page(filtered, page)

        # ── Search ─────────────────────────────────────────────────
        elif choice.startswith("/"):
            kw = choice[1:].strip()
            if kw == "/":
                current_filter = ""
                print("  🔍 Filtre effacé.")
            else:
                current_filter = kw
            filtered = get_filtered()
            page = 0
            if current_filter:
                print(f"  🔍 {len(filtered)} résultats pour \"{current_filter}\"")
            page, total_pages = show_page(filtered, page)

        # ── Pagination ─────────────────────────────────────────────
        elif low in ("+", ">", "next", "p+"):
            page = min(page + 1, total_pages - 1)
            page, total_pages = show_page(filtered, page)
        elif low in ("-", "<", "prev", "p-"):
            page = max(page - 1, 0)
            page, total_pages = show_page(filtered, page)

        # ── Select all (filtered) ──────────────────────────────────
        elif low in ("a", "all", "tous", "tout"):
            for idx in filtered:
                selected.add(idx)
            print(f"  ✅ {len(filtered)} newsletters cochées. "
                  f"Total: {len(selected)}")

        # ── Deselect all ───────────────────────────────────────────
        elif low in ("n", "none", "aucun", "rien"):
            if current_filter:
                # Only deselect filtered items
                for idx in filtered:
                    selected.discard(idx)
                print(f"  ✅ Filtrés décochés. Reste: {len(selected)}")
            else:
                selected.clear()
                print("  ✅ Tout décochés.")

        # ── View selection ─────────────────────────────────────────
        elif low in ("v", "view", "voir", "sel"):
            if not selected:
                print("  (aucune sélection)")
            else:
                print(f"\n  📌 Sélection actuelle ({len(selected)}) :")
                for idx in sorted(selected):
                    sub = subscriptions[idx]
                    paid = " 💰" if sub.get("is_paid") else ""
                    print(f"    ✓ {idx+1:3d}. {sub['name']}{paid}")
                print()

        # ── Number toggles: "3", "5,12,7", "10-25" ────────────────
        else:
            toggled_on = []
            toggled_off = []
            tokens = re.split(r"[,\s]+", choice)
            for tok in tokens:
                range_match = re.match(r"^(\d+)-(\d+)$", tok)
                if range_match:
                    lo = int(range_match.group(1)) - 1
                    hi = int(range_match.group(2)) - 1
                    for j in range(lo, hi + 1):
                        if 0 <= j < len(subscriptions):
                            if j in selected:
                                selected.discard(j)
                                toggled_off.append(j)
                            else:
                                selected.add(j)
                                toggled_on.append(j)
                elif tok.isdigit():
                    idx = int(tok) - 1
                    if 0 <= idx < len(subscriptions):
                        if idx in selected:
                            selected.discard(idx)
                            toggled_off.append(idx)
                        else:
                            selected.add(idx)
                            toggled_on.append(idx)
                    else:
                        print(f"  ⚠  Numéro {tok} hors limites "
                              f"(1-{len(subscriptions)})")
                else:
                    print(f"  ⚠  \"{tok}\" non reconnu. Tapez ? pour l'aide.")

            # Immediate feedback
            for idx in toggled_on:
                print(f"    ✓ {subscriptions[idx]['name']}")
            for idx in toggled_off:
                print(f"    ✗ {subscriptions[idx]['name']}")
            if toggled_on or toggled_off:
                print(f"  ({len(selected)} sélectionnés au total)")

    # ── Confirmation ───────────────────────────────────────────────
    result = [subscriptions[i] for i in sorted(selected)]
    print(f"\n  📌 {len(result)} newsletters sélectionnées :")
    for s in result:
        paid = " 💰" if s.get("is_paid") else ""
        print(f"    • {s['name']}{paid}")

    # Save selection
    selected_urls = [s["url"] for s in result]
    save_selection(selected_urls)
    print(f"\n  💾 Sélection sauvegardée.")

    return result
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


def get_best_image_url(url: str, width: int = 1200) -> str:
    """Optimize a Substack CDN image URL for a specific width.

    Substack images on substackcdn.com support width transforms:
      https://substackcdn.com/image/fetch/w_1200,c_limit,f_auto,...
    """
    if not url:
        return url
    # If already a substackcdn URL with transforms, adjust width
    if "substackcdn.com" in url and "/fetch/" in url:
        url = re.sub(r"w_\d+", f"w_{width}", url)
    return url


# ── Substack API ───────────────────────────────────────────────────────────
def fetch_archive(session: requests.Session, base_url: str,
                  count: int = 10) -> list[dict]:
    """Fetch the latest posts from the newsletter's archive API.

    Endpoint: GET /api/v1/archive?sort=new&offset=0&limit=N

    Returns a list of post metadata dicts with keys like:
      id, title, subtitle, slug, post_date, cover_image,
      body_html (full article HTML), audience, etc.
    """
    print(f"  📰 Récupération des {count} derniers articles…")

    all_posts = []
    offset = 0
    batch_size = min(count, 12)

    while len(all_posts) < count:
        url = (f"{base_url}/api/v1/archive"
               f"?sort=new&offset={offset}&limit={batch_size}")

        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            posts = resp.json()
        except requests.exceptions.JSONDecodeError:
            print("  ⚠  Réponse non-JSON — le site utilise peut-être un domaine personnalisé.")
            print("     Tentative avec le parsing HTML…")
            return fetch_archive_html_fallback(session, base_url, count)
        except Exception as e:
            print(f"  ❌ Erreur API : {e}")
            return []

        if not posts:
            break

        for post in posts:
            # Skip podcasts, threads, and non-article content
            post_type = post.get("type", "newsletter")
            if post_type not in ("newsletter", ""):
                continue
            all_posts.append(post)
            if len(all_posts) >= count:
                break

        offset += batch_size
        if len(posts) < batch_size:
            break
        time.sleep(REQUEST_DELAY)

    print(f"     {len(all_posts)} articles trouvés.")
    return all_posts[:count]


def fetch_archive_html_fallback(session: requests.Session, base_url: str,
                                count: int) -> list[dict]:
    """Fallback: parse the /archive page HTML if the API is unavailable."""
    print("  📰 Fallback : parsing HTML de la page archive…")

    try:
        resp = session.get(f"{base_url}/archive?sort=new",
                           headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try to extract from __NEXT_DATA__ JSON
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag:
        try:
            data = json.loads(script_tag.string)
            posts = (data.get("props", {}).get("pageProps", {})
                     .get("posts", []))
            if posts:
                print(f"     {len(posts[:count])} articles trouvés (via __NEXT_DATA__).")
                return posts[:count]
        except (json.JSONDecodeError, KeyError):
            pass

    # Parse links to individual posts
    posts = []
    seen = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/p/" not in href:
            continue
        full_url = href if href.startswith("http") else base_url + href
        if full_url in seen:
            continue
        seen.add(full_url)

        title_el = a_tag.find(["h1", "h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else ""
        if not title or len(title) < 10:
            continue

        posts.append({
            "title": title,
            "slug": href.split("/p/")[-1].split("?")[0],
            "canonical_url": full_url,
            "_needs_fetch": True,
        })

        if len(posts) >= count:
            break

    print(f"     {len(posts)} articles trouvés (parsing HTML).")
    return posts


def fetch_post_content(session: requests.Session, base_url: str,
                       post: dict) -> dict:
    """Fetch the full content of a single post if not already in the archive data.

    The archive API usually includes body_html. If not (paywalled content
    without auth, or HTML fallback), we fetch the individual post page.
    """
    # If we already have body_html, we're good
    if post.get("body_html") and len(post["body_html"]) > 100:
        return post

    slug = post.get("slug", "")
    if not slug:
        return post

    # Try the post API endpoint first
    try:
        url = f"{base_url}/api/v1/posts/{slug}"
        resp = session.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            post.update(data)
            return post
    except Exception:
        pass

    # Fallback: parse the post HTML page
    try:
        post_url = post.get("canonical_url", f"{base_url}/p/{slug}")
        resp = session.get(post_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract from __NEXT_DATA__
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag:
            data = json.loads(script_tag.string)
            post_data = (data.get("props", {}).get("pageProps", {})
                         .get("post", {}))
            if post_data:
                post.update(post_data)
                return post

        # Direct HTML extraction as last resort
        body_div = soup.find("div", class_="body")
        if body_div:
            post["body_html"] = str(body_div)
    except Exception as e:
        print(f"           ⚠  Erreur de récupération : {e}")

    return post


# ── Content cleaning ──────────────────────────────────────────────────────
def _normalize_image_url(url: str) -> str:
    """Normalize a Substack CDN image URL for deduplication.

    Substack CDN URLs look like:
      https://substackcdn.com/image/fetch/w_1200,c_limit,f_auto,q_auto/https://...actual_image.jpg
    The transform parameters (w_, c_, f_, q_) vary per context but the
    actual image URL at the end is always the same. We extract that.

    For non-CDN URLs, strip query params as fallback.
    """
    # Substack CDN: extract the original URL after /fetch/.../
    if "substackcdn.com" in url and "/fetch/" in url:
        # Pattern: .../fetch/w_1200,c_limit,f_auto/https://...
        match = re.search(r'/fetch/[^/]+/(https?://.+)$', url)
        if match:
            return match.group(1)
        # Simpler pattern: .../fetch/w_1200,c_limit/filename.jpg
        match = re.search(r'/fetch/[^/]+/(.+)$', url)
        if match:
            return match.group(1)

    # Fallback: strip query params and fragments
    return url.split('?')[0].split('#')[0]


def clean_body_html(html: str) -> str:
    """Clean the Substack article HTML body.

    Removes subscription CTAs, share buttons, embedded subscribe forms,
    and other non-editorial elements while preserving images, text,
    blockquotes, and formatting.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Remove known non-content elements
    selectors_to_remove = [
        "div.subscription-widget-wrap",
        "div.subscribe-widget",
        "div.button-wrapper",
        "div.share-dialog",
        "div.post-footer",
        "div.pencraft",  # Substack UI elements
        "div.paywall",
        "div.paywall-jump",
        "form",
        "button",
        "div.captioned-button-wrap",
        "table.button-wrap",  # CTA buttons in table layout
    ]

    for selector in selectors_to_remove:
        for el in soup.select(selector):
            el.decompose()

    # Remove elements with subscription-related classes
    for el in soup.find_all(class_=re.compile(
            r"subscribe|subscription|paywall|share-button|social-share"
            r"|like-button|comment-button|post-ufi|footnote-anchor")):
        el.decompose()

    # Remove "Subscribe" / "Share" links and buttons
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text(strip=True).lower()
        if text in ("subscribe", "share", "like", "comment",
                     "s'abonner", "partager"):
            a_tag.decompose()

    # Clean remaining content
    cleaned_parts = []
    seen_images = set()  # Track image URLs to avoid duplicates

    for el in soup.find_all(["p", "blockquote", "h1", "h2", "h3", "h4",
                             "figure", "img", "ul", "ol", "pre"]):
        # Skip empty paragraphs
        if el.name == "p":
            text = el.get_text(separator=" ", strip=True)
            if not text or len(text) < 5:
                continue
            # Skip CTAs that survived cleaning
            if any(kw in text.lower() for kw in [
                "subscribe", "s'abonner", "thanks for reading",
                "merci de lire", "share this post", "partager",
                "leave a comment", "laisser un commentaire",
            ]):
                continue
            # Keep inner HTML (preserves <em>, <strong>, <a>, etc.)
            inner = "".join(str(child) for child in el.children)
            cleaned_parts.append(f"<p>{inner}</p>")

        elif el.name == "blockquote":
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if text and len(text) > 10:
                inner = "".join(str(child) for child in el.children)
                cleaned_parts.append(
                    f'<blockquote>{inner}</blockquote>')

        elif el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(separator=" ", strip=True)
            if text and len(text) > 3:
                cleaned_parts.append(f"<{el.name}>{text}</{el.name}>")

        elif el.name == "figure":
            img = el.find("img")
            if img and img.get("src"):
                src = img["src"]
                # Normalize URL for dedup: strip size/quality params
                # Substack CDN: /fetch/w_1200,c_limit,f_auto,q_auto/https://...
                # We keep only the original image URL after the transforms
                src_key = _normalize_image_url(src)
                if src_key in seen_images:
                    continue
                seen_images.add(src_key)
                figcap = el.find("figcaption")
                cap_text = (figcap.get_text(separator=" ", strip=True)
                            if figcap else "")
                cleaned_parts.append(
                    f'<figure><img src="{src}" />'
                    f'{"<figcaption>" + cap_text + "</figcaption>" if cap_text else ""}'
                    f'</figure>')

        elif el.name == "img" and el.get("src"):
            # Standalone images — skip if inside a <figure> (already handled)
            if el.parent and el.parent.name == "figure":
                continue
            src = el["src"]
            src_key = _normalize_image_url(src)
            if src_key in seen_images:
                continue
            if "substackcdn" in src or "substack" in src:
                seen_images.add(src_key)
                cleaned_parts.append(f'<figure><img src="{src}" /></figure>')

        elif el.name in ("ul", "ol"):
            items = []
            for li in el.find_all("li"):
                # Preserve inner HTML for list items
                inner = "".join(str(child) for child in li.children)
                text = li.get_text(separator=" ", strip=True)
                if text:
                    items.append(f"<li>{inner}</li>")
            if items:
                cleaned_parts.append(
                    f'<{el.name}>{"".join(items)}</{el.name}>')

        elif el.name == "pre":
            text = el.get_text()
            if text.strip():
                cleaned_parts.append(f"<pre>{text}</pre>")

    return "\n".join(cleaned_parts)


def extract_article(post: dict, fetch_images: bool = False,
                    session: requests.Session | None = None) -> dict:
    """Extract and normalize article data from a Substack post dict.

    Returns a standardized dict compatible with the PDF generators.
    """
    title = post.get("title", "Sans titre")
    subtitle = post.get("subtitle", "")

    # Author
    author_data = post.get("publishedBylines", [])
    if author_data:
        author = author_data[0].get("name", "")
    else:
        author = ""

    # Date
    post_date = post.get("post_date", "") or post.get("published_at", "")
    date_display = ""
    if post_date:
        try:
            dt = datetime.fromisoformat(post_date.replace("Z", "+00:00"))
            months_fr = [
                "", "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            ]
            date_display = f"{dt.day} {months_fr[dt.month]} {dt.year}"
        except (ValueError, IndexError):
            date_display = post_date[:10]

    # Cover image
    cover_image = post.get("cover_image", "")
    if cover_image:
        cover_image = get_best_image_url(cover_image, width=1200)

    # Also check for social_image as fallback
    if not cover_image:
        cover_image = post.get("social_image", "") or ""

    # Category / section
    section = post.get("section", {}) or {}
    category = section.get("name", "") if isinstance(section, dict) else ""

    # Audience (free / paid)
    audience = post.get("audience", "everyone")
    is_paid = audience not in ("everyone", "only_free")

    # Body HTML
    body_html = post.get("body_html", "")
    content_html = clean_body_html(body_html)
    content_text = BeautifulSoup(content_html, "html.parser").get_text(
        separator="\n\n").strip()

    # Truncation check (paywall)
    truncated = post.get("truncated_body_html")
    if truncated and not body_html:
        content_html = clean_body_html(truncated)
        content_text = BeautifulSoup(content_html, "html.parser").get_text(
            separator="\n\n").strip()
        if is_paid:
            content_html += (
                '<p class="paywall-notice"><em>[Contenu réservé aux abonnés '
                '— article tronqué]</em></p>')

    # Word count for filtering
    word_count = len(content_text.split())

    # Image data URI (for PDF embedding)
    image_data_uri = None
    if fetch_images and cover_image and session:
        image_data_uri = download_image_as_data_uri(session, cover_image)

    return {
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "category": category,
        "date": date_display,
        "lead": subtitle,  # Substack's subtitle serves as chapô
        "content_html": content_html,
        "content_text": content_text,
        "image_url": cover_image,
        "image_data_uri": image_data_uri,
        "image_caption": None,
        "word_count": word_count,
        "is_paid": is_paid,
        "url": post.get("canonical_url", ""),
        "slug": post.get("slug", ""),
    }


# ── Newsletter info ───────────────────────────────────────────────────────
def get_newsletter_info(session: requests.Session,
                        base_url: str) -> dict:
    """Fetch newsletter metadata (name, description, logo, etc.)."""
    print("  ℹ️  Récupération des infos de la newsletter…")

    info = {
        "name": "",
        "description": "",
        "author": "",
        "logo_url": "",
        "logo_data_uri": None,
    }

    try:
        # Try the main page and parse meta tags / JSON
        resp = session.get(base_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            info["name"] = og_title["content"]
        elif soup.title:
            info["name"] = soup.title.get_text(strip=True)

        # Description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            info["description"] = og_desc["content"]

        # Logo / icon
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            info["logo_url"] = og_image["content"]

        # Try __NEXT_DATA__ for richer info
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                pub = (data.get("props", {}).get("pageProps", {})
                       .get("publication", {}))
                if pub:
                    info["name"] = pub.get("name", info["name"])
                    info["description"] = pub.get("hero_text",
                                                   info["description"])
                    info["author"] = pub.get("author_name", "")
                    logo = pub.get("logo_url", "")
                    if logo:
                        info["logo_url"] = logo
            except (json.JSONDecodeError, KeyError):
                pass

        print(f"     📰 {info['name']}")
        if info["description"]:
            desc_short = info["description"][:80]
            print(f"     📝 {desc_short}…" if len(info["description"]) > 80
                  else f"     📝 {info['description']}")

    except Exception as e:
        print(f"  ⚠  Infos newsletter non disponibles ({e})")

    return info


# ── PDF Generation (standard formats) ─────────────────────────────────────
def generate_pdf(
    articles: list[dict],
    newsletter_name: str,
    newsletter_desc: str,
    date_str: str,
    fmt: str,
    output_path: Path,
):
    """Generate the digest PDF using WeasyPrint."""
    from weasyprint import HTML

    profile = FORMATS[fmt]

    # Build HTML content
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<p class="category">{art["category"]}</p>'

        author_html = ""
        if art.get("author"):
            author_html = f'<p class="author">{art["author"]}'
            if art.get("date"):
                author_html += f' — {art["date"]}'
            author_html += '</p>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<p class="lead">{art["lead"]}</p>'

        paid_badge = ""
        if art.get("is_paid"):
            paid_badge = ' <span class="paid-badge">★</span>'

        separator = '<div class="separator">✦</div>' if i > 0 else ""

        articles_html += f"""
        {separator}
        <article>
            {category_html}
            <h2>{art.get("title", "Sans titre")}{paid_badge}</h2>
            {author_html}
            {lead_html}
            <div class="article-body">
                {art.get("content_html", "")}
            </div>
        </article>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: {profile["width_mm"]}mm {profile["height_mm"]}mm;
        margin: {profile["margin"]};
        @bottom-center {{
            content: counter(page);
            font-size: 7pt;
            color: #999;
        }}
    }}

    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: "DejaVu Serif", "Noto Serif", Georgia, serif;
        font-size: {profile["font_size"]};
        line-height: {profile["line_height"]};
        color: #1a1a1a;
        text-align: justify;
        hyphens: auto;
        -webkit-hyphens: auto;
    }}

    /* ── Cover page ── */
    .cover {{
        page-break-after: always;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        height: 100%;
    }}
    .cover h1 {{
        font-size: {profile["h1_size"]};
        font-weight: 700;
        margin-bottom: 0.3em;
        color: #2c2c2c;
        letter-spacing: -0.02em;
    }}
    .cover .subtitle {{
        font-size: {profile["h3_size"]};
        color: #666;
        font-style: italic;
        margin-bottom: 1.5em;
        max-width: 90%;
    }}
    .cover .edition-date {{
        font-size: {profile["h2_size"]};
        color: #444;
        font-weight: 600;
    }}
    .cover .toc-title {{
        font-size: {profile["h3_size"]};
        margin-top: 2em;
        margin-bottom: 0.5em;
        font-weight: 700;
        color: #333;
    }}
    .cover .toc {{
        text-align: left;
        font-size: 8pt;
        line-height: 1.6;
        color: #555;
    }}
    .cover .toc .toc-item {{
        margin-bottom: 0.2em;
    }}
    .cover .toc .toc-category {{
        font-variant: small-caps;
        color: #888;
        font-size: 7pt;
    }}

    /* ── Articles ── */
    article {{
        page-break-before: always;
    }}
    article:first-of-type {{
        page-break-before: avoid;
    }}

    .category {{
        font-variant: small-caps;
        color: #888;
        font-size: 8pt;
        letter-spacing: 0.05em;
        margin-bottom: 0.3em;
    }}

    h2 {{
        font-size: {profile["h2_size"]};
        font-weight: 700;
        line-height: 1.2;
        margin-bottom: 0.4em;
        color: #1a1a1a;
    }}

    .paid-badge {{
        color: #e8912d;
        font-size: 80%;
    }}

    .author {{
        font-style: italic;
        color: #666;
        font-size: 8pt;
        margin-bottom: 0.8em;
    }}

    .lead {{
        font-weight: 600;
        font-size: {profile["font_size"]};
        line-height: 1.3;
        margin-bottom: 0.8em;
        color: #333;
    }}

    .article-body p {{
        margin-bottom: 0.6em;
        text-indent: 1em;
    }}
    .article-body p:first-child {{
        text-indent: 0;
    }}

    .article-body h2, .article-body h3, .article-body h4 {{
        font-size: {profile["h3_size"]};
        font-weight: 700;
        margin-top: 1em;
        margin-bottom: 0.4em;
        text-indent: 0;
    }}

    .article-body figure {{
        margin: 0.8em 0;
        text-align: center;
    }}
    .article-body figure img {{
        max-width: 100%;
        height: auto;
    }}
    .article-body figcaption {{
        font-size: 7pt;
        color: #888;
        font-style: italic;
        margin-top: 0.3em;
    }}

    .article-body ul, .article-body ol {{
        margin: 0.5em 0 0.5em 1.5em;
    }}
    .article-body li {{
        margin-bottom: 0.3em;
    }}

    .article-body pre {{
        font-family: "DejaVu Sans Mono", monospace;
        font-size: 7pt;
        background: #f5f5f5;
        padding: 0.5em;
        margin: 0.5em 0;
        overflow-wrap: break-word;
        white-space: pre-wrap;
    }}

    blockquote {{
        margin: 0.8em 0;
        padding-left: 0.8em;
        border-left: 2pt solid #ccc;
        color: #555;
        font-style: italic;
    }}
    blockquote p {{
        text-indent: 0 !important;
    }}

    .paywall-notice {{
        text-align: center;
        color: #999;
        font-size: 8pt;
        margin-top: 1em;
        padding: 0.5em;
        border: 0.5pt dashed #ccc;
    }}

    .separator {{
        text-align: center;
        color: #ccc;
        font-size: 12pt;
        margin: 1em 0;
        page-break-before: always;
    }}

    /* ── Footer ── */
    .footer {{
        page-break-before: always;
        text-align: center;
        padding-top: 40%;
        color: #999;
        font-size: 8pt;
        font-style: italic;
    }}
</style>
</head>
<body>

<!-- Cover -->
<div class="cover">
    <h1>{newsletter_name}</h1>
    <p class="subtitle">{newsletter_desc}</p>
    <p class="edition-date">{date_str}</p>
    <p class="toc-title">Sommaire</p>
    <div class="toc">
"""

    for art in articles:
        cat = (f'<span class="toc-category">{art.get("category", "")}</span> — '
               if art.get("category") else "")
        author = (f' <em>({art.get("author", "")})</em>'
                  if art.get("author") else "")
        paid = " ★" if art.get("is_paid") else ""
        html_content += (f'        <div class="toc-item">'
                         f'{cat}{art.get("title", "")}{author}{paid}</div>\n')

    html_content += f"""
    </div>
</div>

<!-- Articles -->
{articles_html}

<!-- Footer -->
<div class="footer">
    <p>Généré le {datetime.now().strftime("%d.%m.%Y à %H:%M")}</p>
    <p>{newsletter_name}</p>
</div>

</body>
</html>"""

    print(f"  📄 Génération PDF ({profile['label']})…")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content).write_pdf(str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ {output_path.name} ({size_mb:.1f} Mo)")


# ── PDF Generation (A4 Premium — New Yorker style) ────────────────────────
def generate_premium_pdf(
    articles: list[dict],
    newsletter_name: str,
    newsletter_desc: str,
    date_str: str,
    output_path: Path,
    session: requests.Session,
    logo_data_uri: str | None = None,
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
    """
    from weasyprint import HTML

    print("  🎨 Préparation de l'édition premium A4…")

    # ── Download images for articles ───────────────────────────────────
    print("  🖼️  Téléchargement des images…")
    image_cache = {}
    for i, art in enumerate(articles):
        img_url = art.get("image_url", "")
        if img_url and img_url not in image_cache:
            data_uri = art.get("image_data_uri")
            if not data_uri:
                data_uri = download_image_as_data_uri(session, img_url)
            if data_uri:
                image_cache[img_url] = data_uri
        img_status = "✓" if img_url and img_url in image_cache else "—"
        print(f"     [{i+1}/{len(articles)}] {img_status} "
              f"{art.get('title', '')[:55]}…")

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="pm-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="pm-author">Par {art["author"]}'
            if art.get("date"):
                author_html += f' — {art["date"]}'
            author_html += '</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="pm-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url", "")
        if img_url and img_url in image_cache:
            data_uri = image_cache[img_url]
            cap = art.get("image_caption", "")
            cap_html = (f'<div class="pm-img-caption">{cap}</div>'
                        if cap else "")
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
                    return (f'<p><span class="drop-cap">{first_char}'
                            f'</span>{rest}</p>')
                return match.group(0)

            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap,
                               body_html, count=1, flags=re.DOTALL)

        paid_badge = ""
        if art.get("is_paid"):
            paid_badge = ' <span class="pm-paid">★ Abonnés</span>'

        articles_html += f"""
        <article class="pm-article">
            {category_html}
            <h2 class="pm-title">{art.get("title", "Sans titre")}{paid_badge}</h2>
            {author_html}
            <div class="pm-rule-thin"></div>
            {image_html}
            {lead_html}
            <div class="pm-body">
                {body_html}
            </div>
        </article>
        """

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_data_uri:
        logo_html = f'<img class="cover-logo-img" src="{logo_data_uri}" alt="{newsletter_name}" />'
    else:
        logo_html = f'<h1 class="cover-title-fallback">{newsletter_name.upper()}</h1>'

    # Colophon logo
    if logo_data_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_data_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles, 1):
        cat = (f'<span class="toc-cat">{art.get("category", "")}</span>'
               if art.get("category") else "")
        auth = (f'<span class="toc-author">{art.get("author", "")}</span>'
                if art.get("author") else "")
        paid = ' <span class="toc-paid">★</span>' if art.get("is_paid") else ""
        toc_items += f"""
        <div class="toc-entry">
            <div class="toc-num">{idx:02d}</div>
            <div class="toc-details">
                {cat}
                <div class="toc-title">{art.get("title", "")}{paid}</div>
                {auth}
            </div>
        </div>"""

    # ── Cover highlights (first 4 articles) ────────────────────────────
    cover_highlights = ""
    for art in articles[:4]:
        cat_hl = (f'<div class="cover-hl-cat">{art.get("category", "")}</div>'
                  if art.get("category") else "")
        auth_hl = (f'<div class="cover-hl-author">{art.get("author", "")}</div>'
                   if art.get("author") else "")
        cover_highlights += f"""
        <div class="cover-hl">
            {cat_hl}
            <div class="cover-hl-title">{art.get("title", "")}</div>
            {auth_hl}
        </div>"""

    # ── Full HTML document ─────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       SUBSTACK — ÉDITION PREMIUM A4
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

    .cover-logo-img {{
        width: 55mm;
        height: auto;
        margin-bottom: 8mm;
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
        max-width: 130mm;
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
        max-width: 130mm;
    }}

    .cover-hl {{
        margin-bottom: 5mm;
        padding-bottom: 5mm;
        border-bottom: 0.3pt solid #ccc;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
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
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt;
        font-weight: 300;
        color: #ccc;
        min-width: 12mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
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
    }}

    .toc-paid {{
        color: #e8912d;
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

    .pm-paid {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #e8912d;
        font-weight: 600;
        letter-spacing: 0.05em;
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

    .pm-body figure {{
        margin: 0.8em 0;
        text-align: center;
        break-inside: avoid;
    }}
    .pm-body figure img {{
        max-width: 100%;
        height: auto;
        max-height: 60mm;
    }}
    .pm-body figcaption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        color: #999;
        font-style: italic;
        margin-top: 1mm;
    }}

    .pm-body ul, .pm-body ol {{
        margin: 0.5em 0 0.5em 1.5em;
    }}
    .pm-body li {{
        margin-bottom: 0.3em;
    }}

    .pm-body pre {{
        font-family: "DejaVu Sans Mono", monospace;
        font-size: 7.5pt;
        background: #f5f5f5;
        padding: 0.5em;
        margin: 0.5em 0;
        overflow-wrap: break-word;
        white-space: pre-wrap;
    }}

    .paywall-notice {{
        text-align: center;
        color: #999;
        font-size: 8pt;
        margin-top: 1em;
        padding: 0.5em;
        border: 0.5pt dashed #ccc;
        column-span: all;
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
    <div class="cover-subtitle">{newsletter_desc}</div>
    <div class="cover-edition">{date_str}</div>

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
        {newsletter_name}<br/>
        <em>{newsletter_desc}</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
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


# ── PDF Generation (A4 Premium Paysage — landscape) ───────────────────────
def generate_premium_landscape_pdf(
    articles: list[dict],
    newsletter_name: str,
    newsletter_desc: str,
    date_str: str,
    output_path: Path,
    session: requests.Session,
    logo_data_uri: str | None = None,
):
    """Generate a premium A4 landscape magazine-style PDF with images and rich layout.

    Same design philosophy as generate_premium_pdf but in landscape orientation
    with three-column body text for a newspaper-like reading experience.
    """
    from weasyprint import HTML

    print("  🎨 Préparation de l'édition A4 Premium Paysage…")

    # ── Download images for articles ───────────────────────────────────
    print("  🖼️  Téléchargement des images…")
    image_cache = {}
    for i, art in enumerate(articles):
        img_url = art.get("image_url", "")
        if img_url and img_url not in image_cache:
            data_uri = art.get("image_data_uri")
            if not data_uri:
                data_uri = download_image_as_data_uri(session, img_url)
            if data_uri:
                image_cache[img_url] = data_uri
        img_status = "✓" if img_url and img_url in image_cache else "—"
        print(f"     [{i+1}/{len(articles)}] {img_status} "
              f"{art.get('title', '')[:55]}…")

    # ── Build articles HTML ────────────────────────────────────────────
    articles_html = ""
    for i, art in enumerate(articles):
        category_html = ""
        if art.get("category"):
            category_html = f'<div class="pm-category">{art["category"]}</div>'

        author_html = ""
        if art.get("author"):
            author_html = f'<div class="pm-author">Par {art["author"]}'
            if art.get("date"):
                author_html += f' — {art["date"]}'
            author_html += '</div>'

        lead_html = ""
        if art.get("lead"):
            lead_html = f'<div class="pm-lead">{art["lead"]}</div>'

        # Hero image
        image_html = ""
        img_url = art.get("image_url", "")
        if img_url and img_url in image_cache:
            data_uri = image_cache[img_url]
            cap = art.get("image_caption", "")
            cap_html = (f'<div class="pm-img-caption">{cap}</div>'
                        if cap else "")
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
                    return (f'<p><span class="drop-cap">{first_char}'
                            f'</span>{rest}</p>')
                return match.group(0)

            body_html = re.sub(r"<p>(.+?)</p>", add_drop_cap,
                               body_html, count=1, flags=re.DOTALL)

        paid_badge = ""
        if art.get("is_paid"):
            paid_badge = ' <span class="pm-paid">★ Abonnés</span>'

        articles_html += f"""
        <article class="pm-article">
            {category_html}
            <h2 class="pm-title">{art.get("title", "Sans titre")}{paid_badge}</h2>
            {author_html}
            <div class="pm-rule-thin"></div>
            {image_html}
            {lead_html}
            <div class="pm-body">
                {body_html}
            </div>
        </article>
        """

    # ── Cover logo ─────────────────────────────────────────────────────
    if logo_data_uri:
        logo_html = f'<img class="cover-logo-img" src="{logo_data_uri}" alt="{newsletter_name}" />'
    else:
        logo_html = f'<h1 class="cover-title-fallback">{newsletter_name.upper()}</h1>'

    # Colophon logo
    if logo_data_uri:
        colophon_logo = f'<img class="colophon-logo" src="{logo_data_uri}" alt="" />'
    else:
        colophon_logo = ""

    # ── Build TOC ──────────────────────────────────────────────────────
    toc_items = ""
    for idx, art in enumerate(articles, 1):
        cat = (f'<span class="toc-cat">{art.get("category", "")}</span>'
               if art.get("category") else "")
        auth = (f'<span class="toc-author">{art.get("author", "")}</span>'
                if art.get("author") else "")
        paid = ' <span class="toc-paid">★</span>' if art.get("is_paid") else ""
        toc_items += f"""
        <div class="toc-entry">
            <div class="toc-num">{idx:02d}</div>
            <div class="toc-details">
                {cat}
                <div class="toc-title">{art.get("title", "")}{paid}</div>
                {auth}
            </div>
        </div>"""

    # ── Cover highlights (first 4 articles) ────────────────────────────
    cover_highlights = ""
    for art in articles[:4]:
        cat_hl = (f'<div class="cover-hl-cat">{art.get("category", "")}</div>'
                  if art.get("category") else "")
        auth_hl = (f'<div class="cover-hl-author">{art.get("author", "")}</div>'
                   if art.get("author") else "")
        cover_highlights += f"""
        <div class="cover-hl">
            {cat_hl}
            <div class="cover-hl-title">{art.get("title", "")}</div>
            {auth_hl}
        </div>"""

    # ── Full HTML document ─────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    /* ================================================================
       SUBSTACK — ÉDITION A4 PREMIUM PAYSAGE
       Mise en page paysage inspirée du New Yorker
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

    .cover-logo-img {{
        width: 55mm;
        height: auto;
        margin-bottom: 8mm;
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
        max-width: 130mm;
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
        column-count: 2;
        column-gap: 10mm;
        margin-top: 8mm;
        text-align: left;
        max-width: 200mm;
    }}

    .cover-hl {{
        margin-bottom: 5mm;
        padding-bottom: 5mm;
        border-bottom: 0.3pt solid #ccc;
        break-inside: avoid;
    }}
    .cover-hl:last-child {{
        border-bottom: none;
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
    }}

    .toc-entry {{
        display: flex;
        align-items: baseline;
        margin-bottom: 4mm;
        padding-bottom: 4mm;
        border-bottom: 0.3pt solid #e0e0e0;
        break-inside: avoid;
    }}
    .toc-entry:last-child {{
        border-bottom: none;
    }}

    .toc-num {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 18pt;
        font-weight: 300;
        color: #ccc;
        min-width: 12mm;
        line-height: 1;
    }}

    .toc-details {{
        flex: 1;
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
    }}

    .toc-paid {{
        color: #e8912d;
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

    .pm-paid {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 8pt;
        color: #e8912d;
        font-weight: 600;
        letter-spacing: 0.05em;
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

    .pm-body figure {{
        margin: 0.8em 0;
        text-align: center;
        break-inside: avoid;
    }}
    .pm-body figure img {{
        max-width: 100%;
        height: auto;
        max-height: 60mm;
    }}
    .pm-body figcaption {{
        font-family: "DejaVu Sans", "Noto Sans", Helvetica, sans-serif;
        font-size: 7pt;
        color: #999;
        font-style: italic;
        margin-top: 1mm;
    }}

    .pm-body ul, .pm-body ol {{
        margin: 0.5em 0 0.5em 1.5em;
    }}
    .pm-body li {{
        margin-bottom: 0.3em;
    }}

    .pm-body pre {{
        font-family: "DejaVu Sans Mono", monospace;
        font-size: 7.5pt;
        background: #f5f5f5;
        padding: 0.5em;
        margin: 0.5em 0;
        overflow-wrap: break-word;
        white-space: pre-wrap;
    }}

    .paywall-notice {{
        text-align: center;
        color: #999;
        font-size: 8pt;
        margin-top: 1em;
        padding: 0.5em;
        border: 0.5pt dashed #ccc;
        column-span: all;
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
    <div class="cover-subtitle">{newsletter_desc}</div>
    <div class="cover-edition">{date_str}</div>

    <div class="cover-highlights">
        {cover_highlights}
    </div>
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
        {newsletter_name}<br/>
        <em>{newsletter_desc}</em>
    </div>
    <div class="colophon-rule"></div>
    <div class="colophon-text">
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


# ── Single newsletter processing ───────────────────────────────────────────
def process_newsletter(
    session: requests.Session,
    base_url: str,
    pub_name: str,
    formats_to_gen: list[str],
    args,
):
    """Process a single newsletter: fetch articles, generate PDFs.

    Extracted from main() so it can be called in a loop for multi-newsletter mode.
    """
    need_images = ("a4premium" in formats_to_gen or "a4landscape" in formats_to_gen) and not args.no_images

    # ── Get newsletter info ────────────────────────────────────────────
    newsletter = get_newsletter_info(session, base_url)
    newsletter_name = newsletter.get("name", pub_name)
    newsletter_desc = newsletter.get("description", "")

    # ── Download logo if needed ────────────────────────────────────────
    logo_data_uri = None
    if need_images and newsletter.get("logo_url"):
        print("  🎨 Téléchargement du logo…")
        logo_data_uri = download_image_as_data_uri(
            session, newsletter["logo_url"])
        if logo_data_uri:
            print("  ✅ Logo récupéré.")
        else:
            print("  ⚠  Logo non disponible, utilisation du texte.")

    # ── Fetch archive ──────────────────────────────────────────────────
    raw_posts = fetch_archive(session, base_url, count=args.count)

    if not raw_posts:
        print("  ⚠  Aucun article trouvé.")
        return []

    # ── Fetch full content for each post ───────────────────────────────
    print(f"\n  📥 Récupération du contenu de {len(raw_posts)} articles…")
    full_articles = []
    for i, post in enumerate(raw_posts, 1):
        title = post.get("title", "?")[:60]
        print(f"     [{i}/{len(raw_posts)}] {title}…")

        try:
            if post.get("_needs_fetch") or not post.get("body_html"):
                post = fetch_post_content(session, base_url, post)
                time.sleep(REQUEST_DELAY)

            article = extract_article(post, fetch_images=need_images,
                                      session=session)

            if article["word_count"] < args.min_words:
                print(f"           ⚠  Trop court ({article['word_count']} "
                      f"mots), ignoré.")
                continue

            if article.get("content_html"):
                full_articles.append(article)
            else:
                print(f"           ⚠  Contenu vide, ignoré.")

        except Exception as e:
            print(f"           ❌ Erreur: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    if not full_articles:
        print("  ⚠  Aucun article récupéré avec succès.")
        return []

    print(f"\n  ✅ {len(full_articles)} articles récupérés.\n")

    # ── Date string ────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%Y-%m-%d")
    edition_label = f"Édition du {datetime.now().strftime('%d.%m.%Y')}"

    # ── Output directory ───────────────────────────────────────────────
    if args.output_dir:
        out_dir = args.output_dir
    else:
        out_dir = OUTPUT_DIR / pub_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Generate outputs ─────────────────────────────────────────────
    generated = []
    for fmt_key in formats_to_gen:
        if fmt_key == "epub":
            epub_path = out_dir / f"{date_str}-{pub_name}.epub"

            def _fetch_img(url):
                try:
                    resp = session.get(url, timeout=15)
                    resp.raise_for_status()
                    return resp.content, resp.headers.get("Content-Type", "image/jpeg")
                except Exception:
                    return None

            _generate_epub_shared(
                full_articles,
                publication_title=newsletter_name,
                edition_title=edition_label,
                date_str=date_str,
                output_path=epub_path,
                publisher=newsletter_name,
                subtitle=newsletter_desc or "",
                image_fetcher=_fetch_img,
            )
            generated.append(("EPUB", epub_path))
            continue

        suffix = FORMATS[fmt_key]["suffix"]
        output_path = out_dir / f"{date_str}-{pub_name}_{suffix}.pdf"

        if fmt_key == "a4premium":
            generate_premium_pdf(
                full_articles, newsletter_name, newsletter_desc,
                date_str, output_path, session, logo_data_uri,
            )
        elif fmt_key == "a4landscape":
            generate_premium_landscape_pdf(
                full_articles, newsletter_name, newsletter_desc,
                date_str, output_path, session, logo_data_uri,
            )
        else:
            generate_pdf(
                full_articles, newsletter_name, newsletter_desc,
                edition_label, fmt_key, output_path,
            )

        generated.append((FORMATS[fmt_key]['label'], output_path))

    return generated


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Substack Newsletter — Digest PDF Generator"
    )
    parser.add_argument(
        "--url", "-U",
        help=("URL de la newsletter Substack (ex: https://example.substack.com). "
              "Si omis, liste vos abonnements pour sélection interactive."),
    )
    parser.add_argument("--user", "-u", help="Email Substack (login par password)")
    parser.add_argument("--password", "-p", help="Mot de passe Substack")
    parser.add_argument(
        "--cookies", "-c",
        help="Fichier de cookies (JSON ou Netscape txt) — méthode recommandée",
    )
    parser.add_argument(
        "--count", "-n", type=int, default=10,
        help="Nombre d'articles à récupérer par newsletter (défaut: 10)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=list(FORMATS.keys()) + ["epub", "all"],
        default="all",
        help="Format de sortie ou 'all' pour tous les formats (défaut: all)",
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=None,
        help="Dossier de sortie (défaut: ~/kDrive/newspapers/substack/<nom>/)",
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Ne pas télécharger les images (plus rapide)",
    )
    parser.add_argument(
        "--min-words", type=int, default=100,
        help="Nombre minimum de mots par article (défaut: 100)",
    )
    parser.add_argument(
        "--select", "-s", action="store_true",
        help="Forcer la re-sélection interactive (ignorer la sélection sauvegardée)",
    )
    parser.add_argument(
        "--list", "-l", action="store_true",
        help="Lister les abonnements et quitter (sans générer de PDF)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  📰  Substack Newsletter Scraper                        ║")
    print("║  📱 phone · 📖 liseuse · 📱 tablette 7 & 10             ║")
    print("║  🖨️  A4 Premium (magazine style)                         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # ── Formats to generate ────────────────────────────────────────────
    if args.format == "all":
        formats_to_gen = list(FORMATS.keys()) + ["epub"]
    else:
        formats_to_gen = [args.format]

    # ── Session & authentication ───────────────────────────────────────
    session = requests.Session()
    session.headers.update(HEADERS)

    authenticated = False
    if args.cookies:
        # For multi-newsletter mode, validate against substack.com
        test_base = "https://substack.com"
        if args.url:
            test_base, _ = parse_substack_url(args.url)
        authenticated = load_cookies(session, args.cookies, test_base)
    elif args.user and args.password:
        base = "https://substack.com"
        if args.url:
            base, _ = parse_substack_url(args.url)
        authenticated = login_with_password(session, args.user,
                                            args.password, base)

    # ═══════════════════════════════════════════════════════════════════
    # MODE 1: Single newsletter (--url provided)
    # ═══════════════════════════════════════════════════════════════════
    if args.url:
        base_url, pub_name = parse_substack_url(args.url)
        print(f"  🔗 {base_url}")
        print()

        if not authenticated and not args.cookies and not args.user:
            print("  ℹ️  Pas d'authentification — seuls les articles gratuits")
            print("     seront accessibles en intégralité.")
            print()

        generated = process_newsletter(session, base_url, pub_name,
                                       formats_to_gen, args)

        if generated:
            print()
            print(f"  🎉 Terminé — {len(generated)} PDFs générés !")
            for label, path in generated:
                print(f"     {label}: {path.name}")
            print(f"\n  📂 Dossier : {generated[0][1].parent}")
            print()
        return

    # ═══════════════════════════════════════════════════════════════════
    # MODE 2: Multi-newsletter (list subscriptions, select, loop)
    # ═══════════════════════════════════════════════════════════════════
    if not authenticated:
        print("  ❌ L'authentification est requise pour lister vos abonnements.")
        print("     Utilisez --cookies cookies.json ou --user/--password")
        print()
        print("  💡 Pour exporter vos cookies :")
        print("     1. Installez l'extension 'Get cookies.txt LOCALLY'")
        print("     2. Connectez-vous à substack.com dans votre navigateur")
        print("     3. Cliquez l'extension → téléchargez le fichier")
        print("     4. Lancez : python3 substack_scraper.py --cookies cookies.txt")
        print()
        sys.exit(1)

    # Fetch subscriptions
    subscriptions = fetch_subscriptions(session)
    if not subscriptions:
        sys.exit(1)

    # Sort alphabetically
    subscriptions.sort(key=lambda s: s["name"].lower())

    # --list mode: just display and exit
    if args.list:
        print()
        print(f"  📋 Vos {len(subscriptions)} abonnements Substack :")
        print()
        for i, sub in enumerate(subscriptions, 1):
            paid = " 💰" if sub.get("is_paid") else ""
            author = f" — {sub['author']}" if sub.get("author") else ""
            print(f"    {i:2d}. {sub['name']}{author}{paid}")
            print(f"        {sub['url']}")
        print()
        return

    # Load previous selection (unless --select forces re-selection)
    previous_selection = [] if args.select else load_selection()

    # If we have a saved selection and --select was not passed,
    # use it directly without showing the menu
    if previous_selection and not args.select:
        # Filter to only still-valid subscriptions
        valid_urls = {s["url"] for s in subscriptions}
        selected_urls = [u for u in previous_selection if u in valid_urls]

        if selected_urls:
            selected = [s for s in subscriptions
                        if s["url"] in set(selected_urls)]
            print(f"  💾 Utilisation de la sélection sauvegardée "
                  f"({len(selected)} newsletters) :")
            for s in selected:
                print(f"     • {s['name']}")
            print()
            print("  💡 Utilisez --select pour modifier la sélection.")
            print()
        else:
            # Saved selection is stale, show interactive menu
            selected = interactive_select(subscriptions, previous_selection)
    else:
        # Interactive selection
        selected = interactive_select(subscriptions, previous_selection)

    # ── Process each selected newsletter ───────────────────────────────
    total_generated = []
    total_errors = 0

    for idx, sub in enumerate(selected, 1):
        base_url = sub["url"]
        _, pub_name = parse_substack_url(base_url)

        print()
        print(f"  ╔═══════════════════════════════════════════════════╗")
        print(f"  ║  [{idx}/{len(selected)}] {sub['name'][:45]:45s} ║")
        print(f"  ╚═══════════════════════════════════════════════════╝")
        print(f"  🔗 {base_url}")
        print()

        try:
            generated = process_newsletter(session, base_url, pub_name,
                                           formats_to_gen, args)
            if generated:
                total_generated.extend(generated)
                print(f"  ✅ {len(generated)} PDFs générés pour {sub['name']}.")
            else:
                print(f"  ⚠  Aucun PDF généré pour {sub['name']}.")
        except Exception as e:
            print(f"  ❌ Erreur pour {sub['name']}: {e}")
            total_errors += 1
            if args.verbose:
                import traceback
                traceback.print_exc()

        # Pause between newsletters
        if idx < len(selected):
            time.sleep(2)

    # ── Final summary ──────────────────────────────────────────────────
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║  📊  Résumé                                             ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  📰 Newsletters traitées : {len(selected)}")
    print(f"  📄 PDFs générés : {len(total_generated)}")
    if total_errors:
        print(f"  ❌ Erreurs : {total_errors}")
    print(f"  📂 Dossier racine : {OUTPUT_DIR}")
    print()

    if total_generated:
        # Group by newsletter
        by_dir = {}
        for label, path in total_generated:
            d = str(path.parent)
            by_dir.setdefault(d, []).append((label, path))

        for d, files in by_dir.items():
            dirname = Path(d).name
            print(f"  📁 {dirname}/")
            for label, path in files:
                print(f"     {label}: {path.name}")
        print()


if __name__ == "__main__":
    main()
