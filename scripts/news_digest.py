#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║  📰  Multi-Source Daily News Digest  (v2)                ║
║  Scrapes 10 alternative media sources → single PDF       ║
║  Generates 4 formats: phone, ereader, tablet7, tablet10  ║
╚══════════════════════════════════════════════════════════╝

Changes v2:
    - Fix words glued together (clean_text helper)
    - Article images embedded in PDF
    - Improved CSS layout & typography
    - --no-images flag for faster generation

Dependencies:
    pip install feedparser requests beautifulsoup4 weasyprint cloudscraper

Usage:
    python3 news_digest.py              # today's digest, all 4 formats
    python3 news_digest.py --yesterday  # yesterday's digest
    python3 news_digest.py --dry-run    # test feeds without generating PDF
    python3 news_digest.py --no-content # summaries only (fast mode)
    python3 news_digest.py --no-images  # skip image download
    python3 news_digest.py --formats tablet7 ereader
"""

import feedparser
import requests
from bs4 import BeautifulSoup

from epub_generator import generate_epub
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sys
import time
import html
import argparse
import logging
import base64

# ── WeasyPrint import with helpful error ───────────────────────────────────

try:
    from weasyprint import HTML as WeasyHTML
except ImportError as e:
    print(f"❌ WeasyPrint non disponible : {e}")
    print("   pip install weasyprint")
    print("   Si ça ne suffit pas :")
    print("   sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0")
    sys.exit(1)

# ── Cloudscraper (anti-Cloudflare) ─────────────────────────────────────────

try:
    import cloudscraper
    _scraper_session = cloudscraper.create_scraper(
        browser={"browser": "firefox", "platform": "linux"}
    )
    HAS_CLOUDSCRAPER = True
except ImportError:
    _scraper_session = None
    HAS_CLOUDSCRAPER = False

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
POLITENESS_DELAY = 0.5
MAX_ARTICLES_PER_SOURCE = 10
MAX_PARAGRAPHS = 25

# ── Sources ────────────────────────────────────────────────────────────────

SOURCES = [
    {
        "name": "Children's Health Defense",
        "icon": "🛡️",
        "type": "rss",
        "urls": [
            "https://childrenshealthdefense.org/defender/feed/",
            "https://childrenshealthdefense.org/feed/",
        ],
        "content_selectors": [
            "div.entry-content",
            "div.post-content",
            "article .content",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "Epoch Times – Santé",
        "icon": "🏥",
        "type": "rss",
        "urls": [
            "https://www.theepochtimes.com/c-health/feed",
            "https://feed.theepochtimes.com/health",
        ],
        "fallback_html": {
            "url": "https://www.theepochtimes.com/health",
            "link_pattern": r"/health/|/article/.*health",
        },
        "content_selectors": [
            "div.post_content",
            "div[class*='article-content']",
            "article .body",
        ],
        "use_cloudscraper": True,
    },
    {
        "name": "Al Jazeera",
        "icon": "🌍",
        "type": "rss",
        "urls": [
            "https://www.aljazeera.com/xml/rss/all.xml",
        ],
        "content_selectors": [
            "main .wysiwyg",
            "div.article-p-wrapper",
            "div.article__body",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "RT – Russia Today",
        "icon": "🇷🇺",
        "type": "rss",
        "urls": [
            "https://www.rt.com/rss/news/",
            "https://www.rt.com/rss/",
        ],
        "content_selectors": [
            "div.article__text",
            "div.article-body",
            "article .text",
        ],
        "use_cloudscraper": True,
    },
    {
        "name": "CGTN",
        "icon": "🇨🇳",
        "type": "rss",
        "urls": [
            "https://www.cgtn.com/subscribe/rss/section/world.xml",
            "https://www.cgtn.com/subscribe/rss/section/china.xml",
        ],
        "content_selectors": [
            "div.website-content",
            "div.content-body",
            "article .text",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "UnHerd",
        "icon": "🎯",
        "type": "rss",
        "urls": [
            "https://unherd.com/feed/",
        ],
        "content_selectors": [
            "div.post-content",
            "article .entry-content",
            "div.article-body",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "The Grayzone",
        "icon": "🔍",
        "type": "rss",
        "urls": [
            "https://thegrayzone.com/feed/",
        ],
        "content_selectors": [
            "div.entry-content",
            "div.post-content",
            "article .content",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "Consortium News",
        "icon": "🕵️",
        "type": "rss",
        "urls": [
            "https://consortiumnews.com/feed/",
        ],
        "content_selectors": [
            "div.entry-content",
            "div.post-content",
            "article .entry-content",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "The American Conservative",
        "icon": "🦅",
        "type": "rss",
        "urls": [
            "https://www.theamericanconservative.com/feed/",
        ],
        "content_selectors": [
            "div.entry-content",
            "div.article-content",
            "article .post-content",
        ],
        "use_cloudscraper": False,
    },
    {
        "name": "AllSides",
        "icon": "⚖️",
        "type": "rss",
        "urls": [
            "https://www.allsides.com/news/rss",
        ],
        "content_selectors": [
            "div.story-id-page-description",
            "div.allsides-page",
            "article .content",
        ],
        "use_cloudscraper": False,
    },
]

# ── PDF Formats ────────────────────────────────────────────────────────────

FORMATS = {
    "phone": {
        "label": "Téléphone",
        "w": 65, "h": 130,
        "fs": "7pt", "ts": "10pt", "h2s": "9pt",
        "margin": "4mm",
        "suffix": "_telephone",
    },
    "ereader": {
        "label": "Liseuse 6\"",
        "w": 90, "h": 122,
        "fs": "8pt", "ts": "12pt", "h2s": "10pt",
        "margin": "6mm",
        "suffix": "_liseuse",
    },
    "tablet7": {
        "label": "Tablette 7\"",
        "w": 100, "h": 160,
        "fs": "9pt", "ts": "14pt", "h2s": "11pt",
        "margin": "7mm",
        "suffix": "_tablette7",
    },
    "tablet10": {
        "label": "Tablette 10\"",
        "w": 135, "h": 210,
        "fs": "8.5pt", "ts": "13pt", "h2s": "10.5pt",
        "margin": "8mm",
        "suffix": "_tablette10",
    },
}

OUTPUT_DIR = Path.home() / "kDrive" / "newspapers" / "journaux_du_jour"


# ═══════════════════════════════════════════════════════════════════════════
#  Text cleaning (fixes words glued across inline HTML tags)
# ═══════════════════════════════════════════════════════════════════════════

def clean_text(element) -> str:
    """Extract text preserving spaces between inline HTML tags.
    get_text(strip=True) causes 'on <a>Infosperber</a>' → 'onInfosperber'.
    """
    text = element.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


# ═══════════════════════════════════════════════════════════════════════════
#  Image downloading
# ═══════════════════════════════════════════════════════════════════════════

def download_image_data_uri(url, use_cloudscraper=False) -> str | None:
    """Download an image and return it as a base64 data URI."""
    try:
        resp = robust_get(url, use_cloudscraper=use_cloudscraper, timeout=10)
        if not resp:
            return None
        ct = resp.headers.get("Content-Type", "image/jpeg")
        if "image" not in ct:
            return None
        if len(resp.content) < 1500:  # skip tracking pixels
            return None
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{ct};base64,{b64}"
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP with retry & backoff
# ═══════════════════════════════════════════════════════════════════════════

def robust_get(url, use_cloudscraper=False, max_retries=MAX_RETRIES,
               timeout=REQUEST_TIMEOUT):
    """HTTP GET with cloudscraper, exponential backoff, and error recovery."""
    session = (
        _scraper_session
        if (use_cloudscraper and HAS_CLOUDSCRAPER)
        else requests.Session()
    )
    session.headers.update(HEADERS)

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout)

            if resp.status_code == 429:
                wait = POLITENESS_DELAY * (2 ** (attempt + 1))
                if attempt < max_retries:
                    log.info(
                        f"      🐌 Rate limited (429), pause {wait:.0f}s "
                        f"(tentative {attempt}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                else:
                    log.warning(f"      ⚠ Rate limited définitivement: {url}")
                    return None

            if resp.status_code >= 500:
                wait = POLITENESS_DELAY * (2 ** attempt)
                if attempt < max_retries:
                    log.info(
                        f"      🔄 Erreur {resp.status_code} "
                        f"(tentative {attempt}/{max_retries}), "
                        f"retry dans {wait:.0f}s"
                    )
                    time.sleep(wait)
                    continue
                else:
                    log.warning(
                        f"      ⚠ Erreur serveur persistante: "
                        f"{resp.status_code} pour {url}"
                    )
                    return None

            if resp.status_code == 403 and not use_cloudscraper and HAS_CLOUDSCRAPER:
                log.info("      🛡️ Cloudflare détecté, bascule sur cloudscraper…")
                return robust_get(
                    url, use_cloudscraper=True,
                    max_retries=max_retries - attempt + 1,
                    timeout=timeout,
                )

            resp.raise_for_status()
            return resp

        except requests.exceptions.Timeout:
            wait = POLITENESS_DELAY * (2 ** attempt)
            if attempt < max_retries:
                log.info(
                    f"      ⏳ Timeout (tentative {attempt}/{max_retries}), "
                    f"retry dans {wait:.0f}s…"
                )
                time.sleep(wait)
            else:
                log.warning(f"      ⚠ Timeout définitif pour {url}")

        except requests.exceptions.ConnectionError:
            wait = POLITENESS_DELAY * (2 ** attempt)
            if attempt < max_retries:
                log.info(
                    f"      🔌 Erreur connexion "
                    f"(tentative {attempt}/{max_retries}), "
                    f"retry dans {wait:.0f}s…"
                )
                time.sleep(wait)
            else:
                log.warning(f"      ⚠ Connexion impossible pour {url}")

        except requests.exceptions.HTTPError as e:
            log.warning(f"      ⚠ HTTP {e}")
            return None

        except requests.RequestException as e:
            log.warning(f"      ⚠ Erreur inattendue: {e}")
            return None

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  RSS Fetching
# ═══════════════════════════════════════════════════════════════════════════

def parse_entry_date(entry):
    """Extract publication date from an RSS entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, field, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).date()
            except Exception:
                pass

    for field in ("published", "updated"):
        ds = getattr(entry, field, None)
        if not ds:
            continue
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d %b %Y %H:%M:%S %z",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S+00:00",
        ):
            try:
                return datetime.strptime(ds.strip(), fmt).date()
            except ValueError:
                continue
    return None


def fetch_rss(source, target_date):
    """Fetch articles from RSS feed(s), filtered by date."""
    three_days_ago = target_date - timedelta(days=3)
    articles = []
    use_cs = source.get("use_cloudscraper", False)

    for url in source["urls"]:
        log.info(f"  📡 RSS: {url}")
        try:
            feed = feedparser.parse(url, agent=HEADERS["User-Agent"])

            if feed.bozo and not feed.entries:
                log.info("     ⚠ feedparser échoué, essai avec HTTP direct…")
                resp = robust_get(url, use_cloudscraper=use_cs)
                if resp and resp.status_code == 200:
                    feed = feedparser.parse(resp.text)

            if feed.bozo and not feed.entries:
                log.info("     ⚠ Invalide ou vide, essai suivant…")
                continue

            log.info(f"     ✅ {len(feed.entries)} entrées")

            undated_count = 0
            for entry in feed.entries:
                pub_date = parse_entry_date(entry)

                include = False
                if pub_date is None:
                    include = True
                    undated_count += 1
                elif pub_date >= three_days_ago:
                    include = True

                if include:
                    summary_raw = entry.get(
                        "summary", entry.get("description", "")
                    )
                    summary_soup = BeautifulSoup(summary_raw, "html.parser")
                    summary_text = clean_text(summary_soup)  # ← FIX

                    articles.append({
                        "title": html.unescape(
                            entry.get("title", "Sans titre")
                        ),
                        "url": entry.get("link", ""),
                        "date": pub_date.isoformat() if pub_date else "",
                        "summary": html.unescape(summary_text[:500]),
                        "content": "",
                        "image_data_uri": "",
                    })

            if articles:
                extra = f" ({undated_count} sans date)" if undated_count else ""
                log.info(f"     📰 {len(articles)} articles récents{extra}")
                return articles[:MAX_ARTICLES_PER_SOURCE]

        except Exception as e:
            log.info(f"     ❌ Erreur: {e}")
            continue

    if not articles and "fallback_html" in source:
        return fetch_html_fallback(source, target_date)

    return articles[:MAX_ARTICLES_PER_SOURCE]


def fetch_html_fallback(source, target_date):
    """Fallback: scrape article links from HTML page."""
    fb = source["fallback_html"]
    use_cs = source.get("use_cloudscraper", False)
    log.info(f"  📡 Fallback HTML: {fb['url']}")

    try:
        resp = robust_get(fb["url"], use_cloudscraper=use_cs)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        seen = set()
        pattern = re.compile(fb.get("link_pattern", r"/article/"))

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href or not pattern.search(href):
                continue
            if href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(fb["url"])
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            if href in seen:
                continue
            seen.add(href)

            title_el = a.select_one("h2, h3, h4, span")
            title = clean_text(title_el) if title_el else clean_text(a)  # ← FIX

            if title and len(title) > 15:
                articles.append({
                    "title": html.unescape(title),
                    "url": href,
                    "date": target_date.isoformat(),
                    "summary": "",
                    "content": "",
                    "image_data_uri": "",
                })

            if len(articles) >= MAX_ARTICLES_PER_SOURCE:
                break

        log.info(f"     📰 {len(articles)} articles trouvés")
        return articles

    except Exception as e:
        log.info(f"     ❌ Erreur: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  Article Content Fetching
# ═══════════════════════════════════════════════════════════════════════════

# Classes CSS de contenu non-éditorial à supprimer
NOISE_SELECTORS = (
    "script, style, noscript, "
    "nav, footer, header, "
    ".social-share, .share-buttons, .social-buttons, .share-bar, "
    ".social-links, [class*='share'], [class*='social-media'], "
    ".newsletter, .newsletter-signup, .newsletter-form, "
    ".cta, .CTA-container, .CTA-module, .end-of-article-cta, "
    "[class*='subscribe'], [class*='signup'], "
    ".ad, .ads, .advertisement, [class*='advert'], "
    "[class*='sponsor'], .promotion, "
    ".related, .related-articles, .recommended, .popular-posts, "
    ".more-stories, .read-next, [class*='related'], "
    ".comments, .comments-area, .comment-section, #comments, "
    "aside, .sidebar, "
    ".author-bio, .author-box, [class*='author-info'], "
    ".paywall, [class*='paywall'], [data-visible-if='non-subscriber'], "
    "[data-visible-if='over-paywall-limit'], "
    ".piano, [id*='piano'], "
    ".breadcrumb, .tags, .article-tags, .categories"
)


def fetch_article_content(url, selectors, use_cloudscraper=False):
    """Fetch full article content with robust cleaning.
    Returns (html_content, image_url_or_None)."""
    try:
        resp = robust_get(url, use_cloudscraper=use_cloudscraper)
        if not resp:
            return "<p><em>Contenu non disponible (erreur réseau)</em></p>", None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract og:image BEFORE cleaning
        image_url = None
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image_url = og["content"]

        # Find content container
        content_el = None
        for sel in selectors:
            content_el = soup.select_one(sel)
            if content_el:
                break
        if not content_el:
            content_el = soup.select_one("article")
        if not content_el:
            return "", image_url

        # Fallback image: first meaningful <img>
        if not image_url:
            for img in content_el.find_all("img"):
                src = img.get("src") or img.get("data-src", "")
                if src and not any(x in src.lower() for x in ("logo", "avatar", "icon", "pixel")):
                    if src.startswith("//"):
                        src = "https:" + src
                    image_url = src
                    break

        # ── Aggressive cleaning ──────────────────────────────────
        for tag in content_el.select(NOISE_SELECTORS):
            tag.decompose()

        # Strip all remaining media elements (after extracting image URL)
        for tag in content_el.find_all(["figure", "img", "video", "iframe", "picture"]):
            tag.decompose()

        for el in content_el.find_all(attrs={"data-visible-if": True}):
            vis = el.get("data-visible-if", "")
            if vis in ("non-subscriber", "over-paywall-limit"):
                el.decompose()

        for a in content_el.find_all("a"):
            text = a.get_text(strip=True).lower()
            if text in (
                "read more", "continue reading", "lire la suite",
                "subscribe", "sign up", "s'abonner",
            ):
                parent = a.find_parent("p") or a.find_parent("div")
                if parent:
                    parent.decompose()
                else:
                    a.decompose()

        # ── Extract paragraphs ───────────────────────────────────
        paragraphs = []
        for el in content_el.find_all(
            ["p", "h2", "h3", "h4", "blockquote", "li"]
        ):
            text = clean_text(el)              # ← FIX: was get_text(strip=True)
            if not text or len(text) < 20:
                continue

            text_lower = text.lower()
            if any(noise in text_lower for noise in (
                "subscribe to", "sign up for", "newsletter",
                "follow us on", "share this", "click here",
                "advertisement", "sponsored content",
                "related articles", "you may also like",
                "© 20", "all rights reserved",
                "cookie", "privacy policy",
            )):
                continue

            if el.name in ("h2", "h3", "h4"):
                paragraphs.append(f"<h3>{html.escape(text)}</h3>")
            elif el.name == "blockquote":
                paragraphs.append(
                    f"<blockquote>{html.escape(text)}</blockquote>"
                )
            else:
                paragraphs.append(f"<p>{html.escape(text)}</p>")

            if len(paragraphs) >= MAX_PARAGRAPHS:
                break

        return "\n".join(paragraphs), image_url

    except Exception as e:
        return f"<p><em>Contenu non disponible : {e}</em></p>", None


# ═══════════════════════════════════════════════════════════════════════════
#  HTML / PDF Generation
# ═══════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Digest multi-sources — {date}</title>
<style>
  @page {{
    size: {w}mm {h}mm;
    margin: {margin};
    @bottom-center {{
      content: counter(page) " / " counter(pages);
      font-size: 6pt;
      color: #999;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "DejaVu Serif", Georgia, serif;
    font-size: {fs};
    line-height: 1.55;
    color: #1a1a1a;
    orphans: 2; widows: 2;
  }}

  /* Cover */
  .cover {{
    text-align: center;
    page-break-after: always;
    padding-top: 18%;
  }}
  .cover h1 {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: {ts};
    font-weight: bold;
    margin-bottom: 0.2em;
    color: #1a5276;
  }}
  .cover .subtitle {{
    font-size: {h2s};
    color: #555;
    font-style: italic;
    margin-bottom: 0.5em;
  }}
  .cover .date {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: {h2s};
    color: #333;
    margin-bottom: 1.5em;
  }}
  .cover .stats {{
    font-size: {fs};
    color: #777;
    margin-bottom: 2em;
  }}
  .cover .source-list {{
    text-align: left;
    margin: 0 auto;
    display: inline-block;
    font-size: {fs};
    color: #555;
    line-height: 1.8;
  }}

  /* TOC */
  .toc {{
    page-break-after: always;
  }}
  .toc h2 {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: {h2s};
    border-bottom: 1.5px solid #1a5276;
    padding-bottom: 0.2em;
    margin-bottom: 0.6em;
    color: #1a5276;
  }}
  .toc ul {{ list-style: none; padding: 0; }}
  .toc li {{ margin: 0.4em 0; font-size: {fs}; }}
  .toc a {{ color: #333; text-decoration: none; }}

  /* Sections */
  h2 {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: {h2s};
    color: #1a5276;
    border-bottom: 2px solid #1a5276;
    padding-bottom: 0.2em;
    margin-top: 1.2em;
    page-break-after: avoid;
  }}

  /* Articles */
  .article {{
    margin: 0.8em 0;
    page-break-inside: avoid;
  }}
  .article h3 {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: calc({fs} + 0.5pt);
    font-weight: bold;
    color: #2c3e50;
    margin: 0.5em 0 0.2em 0;
    page-break-after: avoid;
  }}
  .article .hero-img {{
    width: 100%;
    max-height: 40mm;
    object-fit: cover;
    margin: 0.3em 0;
    display: block;
  }}
  .article .summary {{
    font-style: italic;
    color: #555;
    margin: 0.2em 0 0.3em 0;
  }}
  .article .content {{ margin: 0.3em 0; }}
  .article .content p {{ margin: 0.3em 0; text-align: justify; }}
  .article .content h3 {{
    font-size: {fs};
    font-weight: bold;
    margin: 0.6em 0 0.2em 0;
  }}
  .article .content blockquote {{
    border-left: 2px solid #1a5276;
    padding-left: 0.6em;
    margin: 0.4em 0;
    font-style: italic;
    color: #555;
  }}
  .meta {{
    font-family: "DejaVu Sans", Helvetica, sans-serif;
    font-size: calc({fs} - 1pt);
    color: #888;
    margin-top: 0.3em;
  }}
  .meta a {{ color: #1a5276; text-decoration: none; }}
  hr.article-sep {{
    border: none;
    border-top: 1px dotted #ccc;
    margin: 0.8em 0;
  }}
</style>
</head>
<body>

<!-- Cover -->
<div class="cover">
  <h1>📰 Digest Multi-Sources</h1>
  <p class="subtitle">Panorama quotidien de l'information alternative</p>
  <p class="date">{date}</p>
  <p class="stats">{total} articles · {source_count} sources</p>
  <div class="source-list">{source_icons}</div>
</div>

<!-- TOC -->
<div class="toc">
  <h2>Sommaire</h2>
  <ul>{toc}</ul>
</div>

<!-- Articles -->
{body}

</body>
</html>"""


def build_html(all_articles, date_str, fmt):
    """Build full HTML string for one format."""
    toc_items = []
    body_parts = []
    total = 0
    source_count = 0

    for source in SOURCES:
        name = source["name"]
        articles = all_articles.get(name, [])
        if not articles:
            continue

        source_count += 1
        total += len(articles)
        icon = source["icon"]
        sid = re.sub(r"[^a-z0-9]", "", name.lower())

        toc_items.append(
            f'<li><a href="#{sid}">{icon} {html.escape(name)}'
            f" ({len(articles)})</a></li>"
        )

        section = f'<h2 id="{sid}">{icon} {html.escape(name)}</h2>\n'

        for i, art in enumerate(articles):
            section += '<div class="article">\n'
            section += f'  <h3>{html.escape(art["title"])}</h3>\n'

            # ── Article image ──────────────────────────────────
            if art.get("image_data_uri"):
                section += (
                    f'  <img class="hero-img" src="{art["image_data_uri"]}" alt="" />\n'
                )

            if art.get("summary"):
                section += (
                    f'  <p class="summary">'
                    f'{html.escape(art["summary"])}</p>\n'
                )
            if art.get("content"):
                section += (
                    f'  <div class="content">{art["content"]}</div>\n'
                )
            section += (
                f'  <p class="meta">{art.get("date", "")} · '
                f'<a href="{html.escape(art["url"])}">Lire en ligne →</a>'
                f"</p>\n"
            )
            section += "</div>\n"
            if i < len(articles) - 1:
                section += '<hr class="article-sep">\n'

        body_parts.append(section)

    # Source icons for cover
    icons = [f'{s["icon"]} {s["name"]}' for s in SOURCES]
    icon_lines = []
    for i in range(0, len(icons), 3):
        icon_lines.append(" · ".join(icons[i : i + 3]))
    source_icons = "<br>".join(icon_lines)

    return HTML_TEMPLATE.format(
        date=date_str,
        w=fmt["w"],
        h=fmt["h"],
        fs=fmt["fs"],
        ts=fmt["ts"],
        h2s=fmt["h2s"],
        margin=fmt["margin"],
        total=total,
        source_count=source_count,
        source_icons=source_icons,
        toc="\n    ".join(toc_items),
        body="\n".join(body_parts),
    )


def generate_pdfs(all_articles, date_str, output_dir, formats=None):
    """Generate PDFs (and EPUB) for all (or selected) formats."""
    if formats is None:
        formats = list(FORMATS.keys()) + ["epub"]

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for fmt_key in formats:
        if fmt_key == "epub":
            log.info("  📖 EPUB…")
            # Flatten dict[source, list[dict]] → list[dict]
            epub_articles = []
            for source_name, articles in all_articles.items():
                for art in articles:
                    epub_articles.append({
                        "title": art.get("title", "Sans titre"),
                        "author": "",
                        "category": source_name,
                        "lead": art.get("summary", ""),
                        "content_html": art.get("content", ""),
                        "image_data_uri": art.get("image_data_uri", ""),
                    })
            if epub_articles:
                epub_path = output_dir / f"{date_str}-digest.epub"
                generate_epub(
                    epub_articles,
                    publication_title="News Digest",
                    edition_title=f"Digest du {date_str}",
                    date_str=date_str,
                    output_path=epub_path,
                    publisher="News Digest",
                )
                paths.append(epub_path)
            continue

        fmt = FORMATS[fmt_key]
        log.info(f"  🖨️  {fmt['label']}…")

        html_str = build_html(all_articles, date_str, fmt)
        filename = f"{date_str}-digest{fmt['suffix']}.pdf"
        output_path = output_dir / filename

        try:
            WeasyHTML(string=html_str).write_pdf(str(output_path))
            log.info(f"     ✅ {output_path}")
            paths.append(output_path)
        except Exception as e:
            log.error(f"     ❌ Erreur PDF: {e}")
            html_fallback = output_dir / f"{date_str}-digest{fmt['suffix']}.html"
            html_fallback.write_text(html_str, encoding="utf-8")
            log.info(f"     💾 HTML de secours sauvé: {html_fallback}")

    return paths


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    global MAX_ARTICLES_PER_SOURCE

    parser = argparse.ArgumentParser(
        description="📰 Multi-Source Daily News Digest"
    )
    parser.add_argument(
        "--yesterday", action="store_true",
        help="Generate digest for yesterday instead of today",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Test RSS feeds without generating PDF",
    )
    parser.add_argument(
        "--formats", nargs="+",
        choices=list(FORMATS.keys()) + ["epub"],
        default=list(FORMATS.keys()) + ["epub"],
        help="Which formats to generate (default: all including epub)",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-content", action="store_true",
        help="Skip fetching full article content (summaries only)",
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Skip downloading article images (faster)",
    )
    parser.add_argument(
        "--max-articles", type=int, default=MAX_ARTICLES_PER_SOURCE,
        help=f"Max articles per source (default: {MAX_ARTICLES_PER_SOURCE})",
    )
    parser.add_argument(
        "--min-words", type=int, default=150,
        help="Minimum word count to keep an article (default: 150)",
    )
    args = parser.parse_args()

    MAX_ARTICLES_PER_SOURCE = args.max_articles

    target_date = datetime.now(timezone.utc).date()
    if args.yesterday:
        target_date -= timedelta(days=1)

    date_str = target_date.isoformat()

    log.info("")
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║  📰  Digest Multi-Sources                       ║")
    log.info("╚══════════════════════════════════════════════════╝")
    log.info("")
    log.info(f"  Date cible  : {date_str}")
    log.info(f"  Sortie      : {args.output_dir}")
    log.info(f"  Formats     : {', '.join(args.formats)}")
    cs_status = "✅" if HAS_CLOUDSCRAPER else "⚠ non installé (pip install cloudscraper)"
    log.info(f"  Cloudscraper: {cs_status}")
    log.info(f"  Min. mots   : {args.min_words} (extraits < ce seuil seront exclus)")
    log.info(f"  Images      : {'❌ désactivées' if args.no_images else '✅ activées'}")
    log.info("")

    # ── Phase 1: Fetch article lists ──────────────────────────────────────
    log.info("━" * 55)
    log.info("Phase 1 : Récupération des listes d'articles")
    log.info("━" * 55)

    all_articles = {}

    for source in SOURCES:
        name = source["name"]
        log.info(f"\n🔹 {source['icon']} {name}")

        articles = fetch_rss(source, target_date)
        all_articles[name] = articles
        time.sleep(POLITENESS_DELAY)

    # Summary
    log.info("\n")
    log.info("━" * 55)
    log.info("Résumé Phase 1")
    log.info("━" * 55)
    total = 0
    active = 0
    for source in SOURCES:
        name = source["name"]
        articles = all_articles.get(name, [])
        n = len(articles)
        total += n
        if n > 0:
            active += 1
        st = "✅" if n > 0 else "❌"
        log.info(f"  {st} {source['icon']} {name}: {n}")

    log.info(f"\n  📊 Total: {total} articles de {active} sources")

    if total == 0:
        log.warning("\n  ⚠ Aucun article trouvé. Vérifiez la connexion.")
        sys.exit(1)

    if args.dry_run:
        log.info("\n  🏁 Dry run terminé (pas de PDF généré).")
        sys.exit(0)

    # ── Phase 2: Fetch content + images ───────────────────────────────────
    if not args.no_content:
        log.info("\n")
        log.info("━" * 55)
        log.info("Phase 2 : Récupération du contenu des articles")
        log.info("━" * 55)

        for source in SOURCES:
            name = source["name"]
            articles = all_articles.get(name, [])
            if not articles:
                continue

            selectors = source.get("content_selectors", ["article"])
            use_cs = source.get("use_cloudscraper", False)
            log.info(
                f"\n🔹 {source['icon']} {name} ({len(articles)} articles)"
            )

            for i, art in enumerate(articles):
                if not art["url"]:
                    continue
                log.info(
                    f"  [{i+1}/{len(articles)}] "
                    f"{art['title'][:50]}…"
                )
                content, image_url = fetch_article_content(
                    art["url"], selectors, use_cloudscraper=use_cs
                )
                art["content"] = content

                # Download image as data URI
                if not args.no_images and image_url:
                    data_uri = download_image_data_uri(
                        image_url, use_cloudscraper=use_cs
                    )
                    if data_uri:
                        art["image_data_uri"] = data_uri

                wc = len(
                    BeautifulSoup(
                        content, "html.parser"
                    ).get_text().split()
                ) if content else 0
                art["word_count"] = wc
                img_s = "🖼" if art.get("image_data_uri") else ""
                log.info(f"      → {wc} mots {img_s}")
                time.sleep(POLITENESS_DELAY)

        # ── Filter short extracts ─────────────────────────────────
        min_words = args.min_words
        log.info("\n")
        log.info("━" * 55)
        log.info(f"Filtrage : suppression des extraits < {min_words} mots")
        log.info("━" * 55)

        filtered_total = 0
        removed_total = 0
        for source in SOURCES:
            name = source["name"]
            before = all_articles.get(name, [])
            if not before:
                continue
            kept = [a for a in before if a.get("word_count", 0) >= min_words]
            removed = len(before) - len(kept)
            all_articles[name] = kept
            filtered_total += len(kept)
            removed_total += removed
            if removed:
                log.info(
                    f"  {source['icon']} {name}: "
                    f"{len(kept)} gardés, {removed} extraits supprimés"
                )
            else:
                log.info(
                    f"  {source['icon']} {name}: {len(kept)} ✓"
                )

        log.info(f"\n  📊 Après filtrage: {filtered_total} articles "
                 f"(−{removed_total} extraits)")

    # ── Phase 3: Generate outputs ──────────────────────────────────────────
    log.info("\n")
    log.info("━" * 55)
    log.info("Phase 3 : Génération des fichiers")
    log.info("━" * 55)

    paths = generate_pdfs(
        all_articles, date_str, args.output_dir, args.formats
    )

    log.info(f"\n✨ Terminé ! {len(paths)} fichier(s) généré(s).")
    for p in paths:
        log.info(f"   📄 {p}")


if __name__ == "__main__":
    main()
