#!/usr/bin/env python3
"""
Tricycle Magazine Archive Downloader
=====================================
Télécharge tous les articles de l'archive Tricycle (1991-2025)
en utilisant un compte abonné.

Prérequis :
    pip install requests beautifulsoup4 lxml html2text weasyprint

    Sur Debian/Ubuntu, weasyprint a besoin de :
        sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0

Usage :
    python tricycle_downloader.py --email votre@email.com --password votreMotDePasse
    python tricycle_downloader.py --email votre@email.com --password votreMotDePasse --pdf
    python tricycle_downloader.py --email votre@email.com --password votreMotDePasse --pdf --merge
    python tricycle_downloader.py --cookies cookies.json --pdf --year 2020

Les articles sont sauvegardés dans : ./tricycle_archive/<année>/<saison>-<année>/
"""

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from epub_generator import generate_epub as _generate_epub

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False

try:
    from weasyprint import HTML as WeasyHTML
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

try:
    from pypdf import PdfWriter
    HAS_PYPDF = True
except ImportError:
    try:
        from PyPDF2 import PdfMerger  # fallback ancien nom
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False


# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "https://tricycle.org"
ARCHIVE_URL = f"{BASE_URL}/magazine-archive/"
LOGIN_URL = f"{BASE_URL}/wp-login.php"  # WordPress standard login

YEARS = list(range(1991, 2026))
SEASONS = ["spring", "summer", "fall", "winter"]

# Dossier par défaut pour copier les PDFs (kDrive)
DEFAULT_COPY_DIR = str(Path.home() / "kDrive" / "newspapers" / "tricycle")

# ── Profils écran ─────────────────────────────────────────────────────────────

SCREEN_PROFILES = {
    "phone":   {"w_mm": 62,  "h_mm": 110, "body_pt": 9,   "margin_cm": "0.8cm 0.8cm", "title_em": 1.3, "label": "📱 Téléphone"},
    "ereader": {"w_mm": 76,  "h_mm": 114, "body_pt": 11,  "margin_cm": "1.0cm 1.2cm", "title_em": 1.4, "label": "📖 Liseuse 6 pouces"},
    "tablet":  {"w_mm": 176, "h_mm": 250, "body_pt": 14,  "margin_cm": "1.5cm 1.8cm", "title_em": 1.6, "label": "📱 Tablette 7 pouces"},
}
DEFAULT_SCREEN = "tablet"


def select_screen_profile() -> tuple[str, dict]:
    """Menu interactif pour choisir le format d'écran."""
    profiles = list(SCREEN_PROFILES.items())
    print("\n┌─────────────────────────────────────┐")
    print("│   Format de sortie PDF              │")
    print("├─────────────────────────────────────┤")
    for i, (key, p) in enumerate(profiles, 1):
        print(f"│  {i}. {p['label']:<32s}│")
    print("└─────────────────────────────────────┘")
    while True:
        choice = input(f"Choix [1-{len(profiles)}, défaut={len(profiles)}]: ").strip()
        if not choice:
            return profiles[-1]
        try:
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                key, prof = profiles[idx - 1]
                print(f"  → {prof['label']}")
                return (key, prof)
        except ValueError:
            pass
        print("  ⚠ Choix invalide, réessayez.")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Délai entre les requêtes (en secondes) — soyez poli avec le serveur
REQUEST_DELAY = 1.5


# ── Helpers ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Transforme un texte en nom de fichier sûr."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:120]


def clean_content(content_el):
    """Supprime le contenu non-éditorial de l'article Tricycle.

    Basé sur la structure réelle des pages magazine de tricycle.org.
    Modifie l'élément BeautifulSoup en place.
    """
    # ── 1. Supprimer des blocs entiers par classe CSS ──────────────────────────
    REMOVE_CLASSES = [
        # Boutons de partage social (apparaissent 2× : article-top + article-bottom)
        "share-buttons",
        # CTAs (newsletter, courses, subscribe)
        "CTA-container", "CTA-module", "end-of-article-cta",
        # Paywall
        "paywall",
        # Commentaires
        "comments-area", "comments-toggle", "comments-subscribe",
        # Sidebar (pubs Google, etc.)
        "sidebar",
        # Modules promotionnels
        "popular-posts", "top-courses", "featured-dharma-talks",
        # Tags "Related:"
        "article-tags",
        # Piano (analytics/paywall)
        "piano",
    ]
    for cls in REMOVE_CLASSES:
        for el in content_el.find_all(class_=re.compile(re.escape(cls), re.IGNORECASE)):
            el.decompose()

    # ── 2. Supprimer par ID ────────────────────────────────────────────────────
    REMOVE_IDS = ["piano-sharebot", "piano-sharebotsocial", "comments", "respond"]
    for id_val in REMOVE_IDS:
        el = content_el.find(id=id_val)
        if el:
            el.decompose()

    # ── 3. Supprimer par attribut data-visible-if ──────────────────────────────
    #    Ces divs conditionnelles contiennent les CTAs abonné/non-abonné et paywall
    for el in content_el.find_all(attrs={"data-visible-if": True}):
        vis = el.get("data-visible-if", "")
        if vis in ("non-subscriber", "over-paywall-limit", "under-paywall-limit-or-subscriber"):
            el.decompose()
        elif vis == "subscriber":
            # Garder le contenu éditorial à l'intérieur (si c'est le contenu de l'article)
            # mais supprimer les CTAs de remerciement
            for sub in el.find_all(class_=re.compile(r"end-of-article|cta|donate", re.IGNORECASE)):
                sub.decompose()
            # Supprimer les "Thank you for subscribing" + icône
            for img in el.find_all("img", src=re.compile(r"site-icon")):
                # Remonter au parent si c'est un bloc CTA
                parent = img.find_parent("div", class_=re.compile(r"cta|end-of-article"))
                if parent:
                    parent.decompose()
                else:
                    img.decompose()

    # ── 4. Supprimer le breadcrumb catégorie ("Ideas · Magazine | Feature") ────
    for el in content_el.find_all("p", class_="eyebrow"):
        el.decompose()

    # ── 5. Supprimer les scripts, formulaires, iframes ─────────────────────────
    for tag in content_el.find_all(["script", "noscript", "iframe", "form",
                                      "input", "button", "select", "textarea"]):
        tag.decompose()

    # ── 6. Supprimer les SVG (icônes de partage, paywall, etc.) ────────────────
    for svg in content_el.find_all("svg"):
        svg.decompose()

    # ── 7. Supprimer les images promotionnelles / site chrome ──────────────────
    for img in content_el.find_all("img", src=True):
        src = img.get("src", "")
        if any(x in src.lower() for x in [
            "site-icon", "tricycle-1modifs", "tricycle-2modifs",
            "daily-dharma-banner", "online-courses-cta",
            "modifs.png", "/themes/tricycle",
        ]):
            # Si l'image est dans un figure/div parent, supprimer le parent aussi
            parent = img.find_parent(["figure", "div"])
            if parent and not parent.find("p"):  # ne pas supprimer si du texte éditorial
                parent.decompose()
            else:
                img.decompose()

    # ── 8. Supprimer le footer article (auteur bio + tags) ─────────────────────
    #    On garde le contenu de <section class="content"> mais pas le footer
    for footer in content_el.find_all("footer"):
        # Conserver la bio auteur comme note de fin
        author_section = footer.find("section", class_="article-author")
        if author_section:
            # Garder juste le texte de la bio, pas les liens
            bio_text = author_section.get_text(strip=True)
            if bio_text:
                bio_html = f'<p style="font-size:0.85em; color:#666; margin-top:2em; font-style:italic;">{bio_text}</p>'
                bio_soup = BeautifulSoup(bio_html, "lxml")
                footer.replace_with(bio_soup.find("p"))
            else:
                footer.decompose()
        else:
            footer.decompose()

    # ── 9. Supprimer les blocs "Thank you for subscribing" textuels restants ───
    JUNK_MARKERS = [
        "Thank you for subscribing",
        "we depend on readers like you",
        "Subscribe Now", "Subscribe now",
        "Get Daily Dharma",
        "Start your day with a fresh perspective",
        "Comments are open to subscribers",
        "Explore timeless teachings",
        "See Our Courses",
        "Already a subscriber",
        "This article is only for Subscribers",
        "Take an online Buddhism course",
    ]
    for el in content_el.find_all(["p", "div", "span", "h1", "h2", "h3", "a"]):
        text = el.get_text(strip=True)
        if any(marker.lower() in text.lower() for marker in JUNK_MARKERS):
            # Ne pas supprimer si c'est un long paragraphe éditorial qui mentionne en passant
            if len(text) < 200:
                el.decompose()

    # ── 10. Nettoyer les <li> et <ul> vides ────────────────────────────────────
    for ul in content_el.find_all("ul"):
        if not ul.get_text(strip=True):
            ul.decompose()
    for ol in content_el.find_all("ol"):
        if not ol.get_text(strip=True):
            ol.decompose()

    # ── 11. Supprimer les divs vides résiduelles ──────────────────────────────
    for el in content_el.find_all("div"):
        if not el.get_text(strip=True) and not el.find("img"):
            el.decompose()

    # ── 12. Nettoyer les attributs inutiles (allège le HTML/PDF) ───────────────
    for el in content_el.find_all(True):
        # Garder src, alt, href, style (pour les pull-quotes) ; supprimer le reste
        KEEP_ATTRS = {"src", "alt", "href", "style", "class", "id"}
        attrs_to_remove = [attr for attr in el.attrs if attr not in KEEP_ATTRS]
        for attr in attrs_to_remove:
            del el[attr]
        # Supprimer srcset (on a téléchargé l'image, srcset pointe vers le serveur)
        if "srcset" in el.attrs:
            del el["srcset"]

    return content_el


def sanitize_html(content: str, title: str, url: str, for_pdf: bool = False,
                  screen: dict = None) -> str:
    """Emballe le contenu de l'article dans un document HTML complet.

    Si for_pdf=True, utilise une mise en page optimisée pour lecture sur écran,
    avec dimensions et police adaptées au profil choisi.
    """
    pdf_extras = ""
    if for_pdf:
        if screen is None:
            screen = SCREEN_PROFILES[DEFAULT_SCREEN]
        w = screen["w_mm"]
        h = screen["h_mm"]
        body_pt = screen["body_pt"]
        margin = screen["margin_cm"]
        title_em = screen["title_em"]
        pdf_extras = f"""
        @page {{
            size: {w}mm {h}mm;
            margin: {margin};
            @bottom-center {{
                content: counter(page);
                font-size: 8pt;
                color: #aaa;
            }}
        }}
        body {{
            font-size: {body_pt}pt !important;
            line-height: 1.65 !important;
            max-width: none !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        h1 {{
            font-size: {title_em}em !important;
            page-break-after: avoid;
            margin-top: 0;
        }}
        h2, h3 {{ page-break-after: avoid; }}
        img {{
            page-break-inside: avoid;
            max-width: 100% !important;
            height: auto !important;
        }}
        p {{ orphans: 3; widows: 3; }}
        blockquote {{ font-size: {max(9, body_pt - 1)}pt; }}
        .meta {{ font-size: {max(8, body_pt - 3)}pt !important; }}
        """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <meta name="source" content="{html.escape(url)}">
    <style>
        {pdf_extras}
        body {{
            font-family: Georgia, 'Times New Roman', serif;
            max-width: 800px;
            margin: 2em auto;
            padding: 0 1em;
            line-height: 1.7;
            color: #333;
            font-size: 12pt;
        }}
        h1 {{ font-size: 1.8em; margin-bottom: 0.3em; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 2em; }}
        img {{ max-width: 100%; height: auto; }}
        blockquote {{
            border-left: 3px solid #ccc;
            margin-left: 0;
            padding-left: 1.5em;
            color: #555;
        }}
    </style>
</head>
<body>
{content}
</body>
</html>"""


# ── Session & Login ────────────────────────────────────────────────────────────

class TricycleDownloader:
    def __init__(self, email: str, password: str, output_dir: str = "tricycle_archive",
                 save_markdown: bool = False, save_pdf: bool = False,
                 merge_pdf: bool = False, copy_dir: str | None = None,
                 delay: float = REQUEST_DELAY, screen: dict = None,
                 save_epub: bool = False):
        self.email = email
        self.password = password
        self.output_dir = Path(output_dir)
        self.save_markdown = save_markdown and HAS_HTML2TEXT
        self.save_pdf = save_pdf
        self.save_epub = save_epub
        self.merge_pdf = merge_pdf
        self.copy_dir = Path(copy_dir) if copy_dir else None
        self.delay = delay
        self.screen = screen or SCREEN_PROFILES[DEFAULT_SCREEN]
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.stats = {"issues": 0, "articles": 0, "errors": 0, "skipped": 0, "pdfs": 0, "copied": 0, "epubs": 0}
        self._epub_buffer = []  # collects article dicts for current issue

        if save_markdown and not HAS_HTML2TEXT:
            print("⚠  html2text non installé — les fichiers .md ne seront pas générés.")
            print("   Installez-le avec : pip install html2text")

        if save_pdf and not HAS_WEASYPRINT:
            print("❌ weasyprint est requis pour la génération PDF.")
            print("   pip install weasyprint")
            print("   Sur Debian/Ubuntu : sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0")
            sys.exit(1)

        if merge_pdf and not HAS_PYPDF:
            print("⚠  pypdf non installé — la fusion PDF par numéro ne sera pas disponible.")
            print("   pip install pypdf")

        if self.copy_dir:
            self.copy_dir.mkdir(parents=True, exist_ok=True)
            print(f"📂 Les PDFs seront copiés vers : {self.copy_dir}")

    def _copy_pdf(self, pdf_path: Path, year: int, issue_slug: str):
        """Copie le PDF fusionné vers le dossier de destination (kDrive, etc.)."""
        if not self.copy_dir:
            return
        try:
            self.copy_dir.mkdir(parents=True, exist_ok=True)
            # Nommer clairement : "Tricycle - Winter 2024.pdf"
            nice_name = issue_slug.replace("-", " ").title()
            dest_file = self.copy_dir / f"Tricycle - {nice_name}.pdf"
            if not dest_file.exists():
                shutil.copy2(pdf_path, dest_file)
                self.stats["copied"] += 1
                print(f"   📋 Copié → {dest_file.name}")
        except Exception as e:
            print(f"      ⚠ Erreur copie vers {self.copy_dir}: {e}")

    def login(self) -> bool:
        """Se connecte au site Tricycle via WordPress."""
        print(f"🔐 Connexion avec {self.email}...")

        # 1. Récupérer la page de login pour les tokens CSRF
        resp = self.session.get(LOGIN_URL, allow_redirects=True)

        # 2. Tentative de login WordPress standard
        login_data = {
            "log": self.email,
            "pwd": self.password,
            "wp-submit": "Log In",
            "redirect_to": f"{BASE_URL}/my-account/",
            "testcookie": "1",
        }

        resp = self.session.post(LOGIN_URL, data=login_data, allow_redirects=True)

        # Vérifier si on est connecté
        if "log" in resp.url and "login" in resp.url.lower():
            # Peut-être que le site utilise un autre mécanisme (WooCommerce, etc.)
            print("   ↳ Tentative alternative via WooCommerce...")
            woo_login_data = {
                "username": self.email,
                "password": self.password,
                "woocommerce-login-nonce": "",
                "login": "Log in",
                "redirect": f"{BASE_URL}/my-account/",
            }

            # Chercher le nonce WooCommerce
            acct_resp = self.session.get(f"{BASE_URL}/my-account/")
            soup = BeautifulSoup(acct_resp.text, "lxml")
            nonce_field = soup.find("input", {"name": "woocommerce-login-nonce"})
            if nonce_field:
                woo_login_data["woocommerce-login-nonce"] = nonce_field["value"]
                resp = self.session.post(
                    f"{BASE_URL}/my-account/",
                    data=woo_login_data,
                    allow_redirects=True,
                )

        # Vérification finale : tester l'accès à un article réservé
        check = self.session.get(f"{BASE_URL}/magazine-archive/")
        is_logged_in = "Log Out" in check.text or "log-out" in check.text

        if is_logged_in:
            print("✅ Connecté avec succès !")
            return True
        else:
            print("❌ Échec de la connexion. Vérifiez vos identifiants.")
            print("   Si le site utilise un autre système d'auth, il faudra adapter le script.")
            print("\n💡 Alternative : exportez vos cookies de navigateur (voir ci-dessous).")
            print("   1. Connectez-vous manuellement dans votre navigateur")
            print("   2. Utilisez l'extension 'Cookie-Editor' ou 'EditThisCookie'")
            print("   3. Exportez les cookies en JSON")
            print(f"   4. Relancez avec : --cookies cookies.json")
            return False

    def load_cookies(self, cookie_file: str) -> bool:
        """Charge des cookies depuis un fichier JSON exporté du navigateur."""
        print(f"🍪 Chargement des cookies depuis {cookie_file}...")
        try:
            with open(cookie_file) as f:
                cookies = json.load(f)

            for cookie in cookies:
                self.session.cookies.set(
                    cookie.get("name", ""),
                    cookie.get("value", ""),
                    domain=cookie.get("domain", ".tricycle.org"),
                    path=cookie.get("path", "/"),
                )

            # Vérifier
            check = self.session.get(f"{BASE_URL}/magazine-archive/")
            if "Log Out" in check.text or "log-out" in check.text:
                print("✅ Cookies chargés — session active !")
                return True
            else:
                print("❌ Les cookies ne semblent pas valides ou expirés.")
                return False
        except Exception as e:
            print(f"❌ Erreur lors du chargement des cookies : {e}")
            return False

    def _get(self, url: str, max_retries: int = 3) -> requests.Response | None:
        """GET avec délai, retries et backoff exponentiel."""
        for attempt in range(1, max_retries + 1):
            time.sleep(self.delay)
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.exceptions.Timeout:
                wait = self.delay * (2 ** attempt)  # backoff exponentiel
                if attempt < max_retries:
                    print(f"      ⏳ Timeout (tentative {attempt}/{max_retries}), nouvelle tentative dans {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    print(f"   ⚠ Timeout définitif après {max_retries} tentatives pour {url}")
                    self.stats["errors"] += 1
                    return None
            except requests.exceptions.ConnectionError:
                wait = self.delay * (2 ** attempt)
                if attempt < max_retries:
                    print(f"      🔌 Erreur connexion (tentative {attempt}/{max_retries}), nouvelle tentative dans {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    print(f"   ⚠ Connexion impossible après {max_retries} tentatives pour {url}")
                    self.stats["errors"] += 1
                    return None
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 429:  # Rate limited
                    wait = self.delay * (2 ** (attempt + 1))
                    if attempt < max_retries:
                        print(f"      🐌 Rate limited (429), pause de {wait:.0f}s...")
                        time.sleep(wait)
                    else:
                        print(f"   ⚠ Rate limited définitivement pour {url}")
                        self.stats["errors"] += 1
                        return None
                elif resp.status_code >= 500:
                    wait = self.delay * (2 ** attempt)
                    if attempt < max_retries:
                        print(f"      🔄 Erreur serveur {resp.status_code} (tentative {attempt}/{max_retries}), retry dans {wait:.0f}s...")
                        time.sleep(wait)
                    else:
                        print(f"   ⚠ Erreur serveur persistante pour {url}: {e}")
                        self.stats["errors"] += 1
                        return None
                else:
                    print(f"   ⚠ Erreur HTTP {resp.status_code} pour {url}: {e}")
                    self.stats["errors"] += 1
                    return None
            except requests.RequestException as e:
                print(f"   ⚠ Erreur inattendue pour {url}: {e}")
                self.stats["errors"] += 1
                return None
        return None

    # ── Discovery ──────────────────────────────────────────────────────────────

    def get_all_issue_urls(self, years: list[int] | None = None) -> list[dict]:
        """Parcourt les pages d'archive par année pour collecter les URLs des numéros."""
        years = years or YEARS
        issues = []

        print(f"\n📚 Exploration des archives ({years[0]}–{years[-1]})...")

        for year in years:
            url = f"{ARCHIVE_URL}{year}"
            resp = self._get(url)
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Les numéros sont des liens vers /magazine-issue/<slug>/
            for link in soup.find_all("a", href=re.compile(r"/magazine-issue/")):
                issue_url = urljoin(BASE_URL, link["href"])

                # Extraire le titre depuis le lien ou l'image alt
                title_el = link.find_next("h1") or link.find("img")
                if title_el:
                    title = title_el.get_text(strip=True) if title_el.name == "h1" else title_el.get("alt", "")
                else:
                    title = link.get_text(strip=True)

                if not title:
                    # Déduire du slug
                    title = link["href"].rstrip("/").split("/")[-1].replace("-", " ").title()

                issue = {"url": issue_url, "title": title, "year": year}

                # Éviter les doublons
                if issue_url not in [i["url"] for i in issues]:
                    issues.append(issue)
                    print(f"   📖 {title} ({year})")

        print(f"\n   Total : {len(issues)} numéros trouvés.")
        return issues

    def get_issue_articles(self, issue_url: str) -> list[dict]:
        """Récupère la liste des articles d'un numéro donné."""
        resp = self._get(issue_url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        articles = []

        # Les articles sont typiquement des liens vers /article/ ou /magazine/
        # avec un pattern reconnaissable
        seen_urls = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            full_url = urljoin(BASE_URL, href)

            # Filtrer les liens d'articles (patterns courants sur Tricycle)
            if not re.search(r"/(article|magazine)/[^/]+/?$", href):
                continue

            # Ignorer les liens de navigation, catégories, etc.
            if any(skip in href for skip in [
                "/magazine-issue/", "/magazine-archive/", "/topic/",
                "/subscribe", "/donate", "/my-account", "/about",
                "/ebooks/", "/dharmatalks/", "/filmclub/", "/podcast/",
            ]):
                continue

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Titre de l'article
            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                h_tag = link.find(["h1", "h2", "h3", "h4"])
                title = h_tag.get_text(strip=True) if h_tag else ""
            if not title or len(title) < 3:
                title = href.rstrip("/").split("/")[-1].replace("-", " ").title()

            articles.append({"url": full_url, "title": title})

        return articles

    # ── Download ───────────────────────────────────────────────────────────────

    def download_article(self, article_url: str, save_dir: Path) -> bool:
        """Télécharge un article et le sauvegarde en HTML (+ markdown optionnel)."""
        resp = self._get(article_url)
        if not resp:
            return False

        soup = BeautifulSoup(resp.text, "lxml")

        # Extraire le titre
        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else "Sans titre"

        # Extraire le contenu principal
        # Tricycle utilise typiquement une div avec la classe article-content ou entry-content
        content_el = (
            soup.find("div", class_=re.compile(r"article[-_]?content|entry[-_]?content"))
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"post[-_]?content|main[-_]?content"))
        )

        if not content_el:
            print(f"      ⚠ Pas de contenu trouvé pour : {title}")
            self.stats["errors"] += 1
            return False

        # ── Nettoyer le contenu (supprimer promos, nav, comments, etc.) ────────
        content_el = clean_content(content_el)

        # Extraire les métadonnées
        author_el = soup.find(class_=re.compile(r"author|byline"))
        author = author_el.get_text(strip=True) if author_el else ""
        date_el = soup.find("time") or soup.find(class_=re.compile(r"date|published"))
        date = date_el.get_text(strip=True) if date_el else ""

        # Télécharger les images de l'article
        for img in content_el.find_all("img", src=True):
            img_url = urljoin(BASE_URL, img["src"])
            img_filename = slugify(Path(urlparse(img_url).path).stem) + Path(urlparse(img_url).path).suffix
            img_path = save_dir / "images" / img_filename

            if not img_path.exists():
                img_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    time.sleep(0.5)
                    img_resp = self.session.get(img_url, timeout=20)
                    if img_resp.ok:
                        img_path.write_bytes(img_resp.content)
                        img["src"] = f"images/{img_filename}"
                except Exception:
                    pass

        # Construire le HTML de l'article
        meta_html = f"<h1>{html.escape(title)}</h1>\n"
        if author or date:
            meta_html += f'<p class="meta">{html.escape(author)}'
            if author and date:
                meta_html += " · "
            meta_html += f"{html.escape(date)}</p>\n"

        article_html = meta_html + str(content_el)
        full_html = sanitize_html(article_html, title, article_url)

        # Sauvegarder en HTML
        filename = slugify(title) or "article"
        html_path = save_dir / f"{filename}.html"

        # Éviter les collisions de noms
        counter = 1
        base_filename = filename
        while html_path.exists():
            filename = f"{base_filename}-{counter}"
            html_path = save_dir / f"{filename}.html"
            counter += 1

        html_path.write_text(full_html, encoding="utf-8")

        # Collect data for EPUB generation
        if self.save_epub:
            # Convert local image paths to data URIs for EPUB
            epub_content = str(content_el)
            for img in content_el.find_all("img", src=True):
                src = img["src"]
                if src.startswith("images/"):
                    img_path_local = save_dir / src
                    if img_path_local.exists():
                        import base64 as b64mod
                        img_bytes = img_path_local.read_bytes()
                        ext = img_path_local.suffix.lower().lstrip(".")
                        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                                "png": "image/png", "gif": "image/gif",
                                "webp": "image/webp", "svg": "image/svg+xml"
                                }.get(ext, "image/jpeg")
                        data_uri = f"data:{mime};base64,{b64mod.b64encode(img_bytes).decode()}"
                        epub_content = epub_content.replace(f'src="{src}"', f'src="{data_uri}"')
            self._epub_buffer.append({
                "title": title,
                "author": author,
                "category": "",
                "lead": "",
                "content_html": epub_content,
            })

        # Optionnel : générer le PDF
        if self.save_pdf:
            pdf_path = save_dir / f"{filename}.pdf"
            if not pdf_path.exists():
                try:
                    # Utiliser des chemins absolus pour les images (weasyprint en a besoin)
                    pdf_html = sanitize_html(article_html, title, article_url,
                                             for_pdf=True, screen=self.screen)
                    base_dir = save_dir.resolve().as_uri() + "/"
                    WeasyHTML(string=pdf_html, base_url=base_dir).write_pdf(str(pdf_path))
                    self.stats["pdfs"] += 1
                except Exception as e:
                    print(f"      ⚠ Erreur PDF pour {title[:40]}: {e}")

        # Optionnel : sauvegarder en Markdown
        if self.save_markdown:
            converter = html2text.HTML2Text()
            converter.body_width = 0
            converter.ignore_links = False
            md_content = f"# {title}\n\n"
            if author:
                md_content += f"*{author}*"
            if date:
                md_content += f" — {date}"
            if author or date:
                md_content += "\n\n---\n\n"
            md_content += converter.handle(str(content_el))
            md_content += f"\n\n---\n*Source : {article_url}*\n"

            md_path = save_dir / f"{filename}.md"
            md_path.write_text(md_content, encoding="utf-8")

        return True

    def merge_issue_pdfs(self, save_dir: Path, issue_title: str):
        """Fusionne tous les PDFs d'un numéro en un seul fichier."""
        pdf_files = sorted(save_dir.glob("*.pdf"))
        # Exclure un éventuel fichier fusionné déjà existant
        merged_name = f"__{slugify(issue_title)}-complet.pdf"
        pdf_files = [p for p in pdf_files if p.name != merged_name]

        if len(pdf_files) < 2:
            return

        merged_path = save_dir / merged_name
        if merged_path.exists():
            print(f"   ⏭ PDF fusionné déjà existant")
            return

        try:
            # Essayer avec pypdf (moderne)
            try:
                from pypdf import PdfWriter
                writer = PdfWriter()
                for pdf_file in pdf_files:
                    writer.append(str(pdf_file))
                writer.write(str(merged_path))
                writer.close()
            except ImportError:
                from PyPDF2 import PdfMerger
                merger = PdfMerger()
                for pdf_file in pdf_files:
                    merger.append(str(pdf_file))
                merger.write(str(merged_path))
                merger.close()

            print(f"   📕 PDF fusionné : {merged_name} ({len(pdf_files)} articles)")
        except Exception as e:
            print(f"   ⚠ Erreur fusion PDF : {e}")

    # ── Main orchestration ─────────────────────────────────────────────────────

    def download_all(self, years: list[int] | None = None):
        """Télécharge tous les articles de toutes les années spécifiées."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        issues = self.get_all_issue_urls(years)

        if not issues:
            print("❌ Aucun numéro trouvé. Vérifiez la connexion.")
            return

        for i, issue in enumerate(issues, 1):
            year = issue["year"]
            title = issue["title"]
            issue_slug = slugify(title) or f"issue-{i}"

            print(f"\n{'='*60}")
            print(f"📖 [{i}/{len(issues)}] {title} ({year})")
            print(f"   {issue['url']}")

            # Dossier de sortie
            save_dir = self.output_dir / str(year) / issue_slug
            save_dir.mkdir(parents=True, exist_ok=True)

            # Récupérer les articles
            articles = self.get_issue_articles(issue["url"])

            if not articles:
                print(f"   ⚠ Aucun article trouvé pour ce numéro.")
                continue

            print(f"   → {len(articles)} articles trouvés")
            self.stats["issues"] += 1

            for j, article in enumerate(articles, 1):
                # Vérifier si déjà téléchargé
                expected_file = save_dir / f"{slugify(article['title']) or 'article'}.html"
                if expected_file.exists():
                    print(f"      ⏭ [{j}/{len(articles)}] Déjà téléchargé : {article['title'][:50]}")
                    self.stats["skipped"] += 1
                    continue

                print(f"      📄 [{j}/{len(articles)}] {article['title'][:60]}...")

                if self.download_article(article["url"], save_dir):
                    self.stats["articles"] += 1
                else:
                    self.stats["errors"] += 1

            # Fusionner les PDFs du numéro en un seul fichier
            if self.save_pdf and self.merge_pdf and HAS_PYPDF:
                self.merge_issue_pdfs(save_dir, title)

            # Copier le PDF fusionné vers le dossier de destination (kDrive, etc.)
            if self.save_pdf and self.merge_pdf and self.copy_dir:
                merged_name = f"__{slugify(title)}-complet.pdf"
                merged_path = save_dir / merged_name
                if merged_path.exists():
                    self._copy_pdf(merged_path, year, issue_slug)

            # Generate EPUB for this issue
            if self.save_epub and self._epub_buffer:
                epub_path = save_dir / f"__{issue_slug}.epub"
                _generate_epub(
                    self._epub_buffer,
                    publication_title="Tricycle",
                    edition_title=title,
                    date_str=str(year),
                    output_path=epub_path,
                    language="en",
                    publisher="Tricycle: The Buddhist Review",
                )
                self.stats["epubs"] += 1
                # Copy EPUB to destination if configured
                if self.copy_dir:
                    nice_name = issue_slug.replace("-", " ").title()
                    dest_epub = self.copy_dir / f"Tricycle - {nice_name}.epub"
                    if not dest_epub.exists():
                        shutil.copy2(epub_path, dest_epub)
                self._epub_buffer = []

        self.print_summary()

    def print_summary(self):
        """Affiche le résumé du téléchargement."""
        print(f"\n{'='*60}")
        print(f"✅ Téléchargement terminé !")
        print(f"   📚 Numéros traités : {self.stats['issues']}")
        print(f"   📄 Articles sauvés : {self.stats['articles']}")
        if self.save_pdf:
            print(f"   📕 PDFs générés    : {self.stats['pdfs']}")
        if self.save_epub:
            print(f"   📖 EPUBs générés   : {self.stats['epubs']}")
        if self.copy_dir:
            print(f"   📋 PDFs copiés     : {self.stats['copied']}")
            print(f"   📂 Destination     : {self.copy_dir.resolve()}")
        print(f"   ⏭  Déjà existants  : {self.stats['skipped']}")
        print(f"   ⚠  Erreurs          : {self.stats['errors']}")
        print(f"   📁 Dossier          : {self.output_dir.resolve()}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="📚 Télécharge l'archive complète de Tricycle Magazine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  %(prog)s --cookies cookies.json --pdf --merge
  %(prog)s --email you@mail.com --password secret --pdf
  %(prog)s --cookies cookies.json --pdf --year 2020
        """,
    )

    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--email", help="Email du compte abonné Tricycle")
    auth.add_argument("--cookies", help="Fichier JSON de cookies exportés du navigateur")

    parser.add_argument("--password", help="Mot de passe du compte")
    parser.add_argument("--output", default="tricycle_archive", help="Dossier de sortie (défaut: tricycle_archive)")
    parser.add_argument("--year", type=int, action="append", dest="years",
                        help="Année(s) à télécharger (peut être répété, défaut: toutes)")
    parser.add_argument("--pdf", action="store_true",
                        help="Générer un PDF pour chaque article (requiert weasyprint)")
    parser.add_argument("--epub", action="store_true",
                        help="Générer un EPUB par numéro")
    parser.add_argument("--merge", action="store_true",
                        help="Fusionner les PDFs par numéro en un seul fichier (requiert pypdf)")
    parser.add_argument("--markdown", action="store_true", help="Sauvegarder aussi en Markdown (.md)")
    parser.add_argument("--copy-to", default=None, dest="copy_dir",
                        help=f"Copier les PDFs vers ce dossier (défaut: ~/kDrive/newspapers/tricycle). "
                             f"Utiliser --no-copy pour désactiver.")
    parser.add_argument("--no-copy", action="store_true",
                        help="Ne pas copier les PDFs vers le dossier de destination")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY,
                        help=f"Délai entre requêtes en secondes (défaut: {REQUEST_DELAY})")
    parser.add_argument("--format", "-f", choices=["phone", "ereader", "tablet"],
                        default=None, help="Format écran (sinon: menu interactif)")

    args = parser.parse_args()

    # --- Interactive auth ---
    use_cookies = False
    cookie_file = args.cookies
    email = args.email or ""
    password = args.password or ""

    if not cookie_file and not email:
        print("\n┌─────────────────────────────────────┐")
        print("│   Authentification Tricycle          │")
        print("├─────────────────────────────────────┤")
        print("│  1. Fichier cookies (recommandé)     │")
        print("│  2. Email / mot de passe             │")
        print("└─────────────────────────────────────┘")
        auth_choice = input("Choix [1/2, défaut=1]: ").strip()
        if auth_choice == "2":
            email = input("📧 Email Tricycle: ").strip()
            import getpass
            password = getpass.getpass("🔑 Mot de passe: ")
        else:
            default_cookie = Path("cookies.json")
            cookie_file = input(f"🍪 Chemin du fichier cookies [{default_cookie}]: ").strip()
            if not cookie_file:
                cookie_file = str(default_cookie)
            use_cookies = True
    elif cookie_file:
        use_cookies = True

    if not use_cookies and not email:
        print("❌ Authentification requise.")
        sys.exit(1)
    if email and not password:
        import getpass
        password = getpass.getpass("🔑 Mot de passe Tricycle: ")

    # --- Screen profile ---
    if args.format:
        screen = SCREEN_PROFILES[args.format]
    elif args.pdf:
        _, screen = select_screen_profile()
    else:
        screen = SCREEN_PROFILES[DEFAULT_SCREEN]

    # --- Copy dir ---
    copy_dir = None if args.no_copy else (args.copy_dir or DEFAULT_COPY_DIR)

    # Initialiser le downloader
    downloader = TricycleDownloader(
        email=email,
        password=password,
        output_dir=args.output,
        save_markdown=args.markdown,
        save_pdf=args.pdf,
        save_epub=args.epub,
        merge_pdf=args.merge,
        copy_dir=copy_dir,
        delay=args.delay,
        screen=screen,
    )

    # Authentification
    if use_cookies:
        if not downloader.load_cookies(cookie_file):
            sys.exit(1)
    else:
        if not downloader.login():
            sys.exit(1)

    # Lancer le téléchargement
    downloader.download_all(years=args.years)


if __name__ == "__main__":
    main()
