#!/usr/bin/env python3
"""
Shared EPUB 3 Generator
========================
Generates well-formatted EPUB 3 ebooks using only Python stdlib (zipfile, uuid,
xml.sax.saxutils). No external epub library required.

Extracted from antithese_interactive.py and generalized for all newspaper scripts.

Usage:
    from epub_generator import generate_epub

    generate_epub(
        articles=[{"title": "...", "content_html": "...", ...}],
        publication_title="Le Temps",
        edition_title="Edition du 9 mars 2026",
        date_str="2026-03-09",
        output_path=Path("2026-03-09-letemps.epub"),
    )
"""

import base64
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape


def _epub_uid():
    return str(uuid4())


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


def _decode_data_uri(data_uri: str) -> tuple[bytes, str] | None:
    """Decode a base64 data URI into (bytes, content_type)."""
    m = re.match(r"data:([^;]+);base64,(.+)", data_uri, re.DOTALL)
    if not m:
        return None
    content_type = m.group(1)
    try:
        img_data = base64.b64decode(m.group(2))
        return img_data, content_type
    except Exception:
        return None


def _ext_from_content_type(ctype: str) -> str:
    """Map content type to file extension."""
    if "png" in ctype:
        return "png"
    elif "gif" in ctype:
        return "gif"
    elif "webp" in ctype:
        return "webp"
    elif "svg" in ctype:
        return "svg"
    return "jpg"


# ── EPUB CSS ──────────────────────────────────────────────────────────────

EPUB_CSS = """/* EPUB Stylesheet */
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


def _internalize_inline_images(
    body_html: str,
    epub_images: dict,
    img_counter_start: int,
    image_fetcher: Callable[[str], tuple[bytes, str] | None] | None,
) -> tuple[str, int]:
    """Replace inline <img src="..."> with EPUB-local references.

    Handles both data URIs and http(s) URLs in src attributes.
    Returns (modified_html, updated_counter).
    """
    counter = img_counter_start

    def replace_img(match):
        nonlocal counter
        full_tag = match.group(0)
        src = match.group(1) or match.group(2)
        if not src:
            return full_tag

        img_data = None
        ctype = "image/jpeg"

        if src.startswith("data:"):
            result = _decode_data_uri(src)
            if result:
                img_data, ctype = result
        elif src.startswith("http") and image_fetcher:
            result = image_fetcher(src)
            if result:
                img_data, ctype = result

        if img_data is None:
            return full_tag

        ext = _ext_from_content_type(ctype)
        counter += 1
        fname = f"img-{counter:03d}.{ext}"
        epub_images[fname] = (img_data, ctype)
        return full_tag.replace(src, fname)

    result = re.sub(
        r'<img\s[^>]*src=["\']([^"\']+)["\'][^>]*/?>|<img\s[^>]*src=([^\s>]+)[^>]*/?>',
        replace_img, body_html
    )
    return result, counter


def generate_epub(
    articles: list[dict],
    publication_title: str,
    edition_title: str,
    date_str: str,
    output_path: Path,
    *,
    language: str = "fr",
    publisher: str = "",
    subtitle: str = "",
    tagline: str = "",
    image_fetcher: Callable[[str], tuple[bytes, str] | None] | None = None,
) -> Path:
    """Generate a well-formatted EPUB 3 ebook.

    Built manually with zipfile to avoid extra dependencies.

    Args:
        articles: List of article dicts with keys:
            - title, content_html (required)
            - author, category, lead (optional)
            - image_url (needs image_fetcher), image_data_uri (base64 data URI)
            - image_caption
        publication_title: e.g. "Le Temps", "The Economist"
        edition_title: e.g. "Edition du 9 mars 2026"
        date_str: ISO date "2026-03-09"
        output_path: Where to write the .epub file
        language: BCP 47 language tag (default "fr")
        publisher: Publisher name for metadata
        subtitle: Shown on title page under the title
        tagline: Shown at bottom of title page
        image_fetcher: Optional callable(url) -> (bytes, content_type) | None

    Returns:
        The output_path.
    """
    print(f"  Generating EPUB...")

    book_uid = _epub_uid()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect images for embedding
    epub_images = {}  # filename -> (bytes, media_type)
    img_counter = 0

    def get_epub_image(img_url=None, img_data_uri=None):
        """Resolve an image and return epub filename, or None.

        Resolution order: img_data_uri -> img_url (via image_fetcher) -> None
        """
        nonlocal img_counter

        img_data = None
        ctype = "image/jpeg"

        # Try data URI first
        if img_data_uri:
            result = _decode_data_uri(img_data_uri)
            if result:
                img_data, ctype = result

        # Try URL download
        if img_data is None and img_url and image_fetcher:
            # Try high-res variant first
            hires = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", img_url)
            for url in (hires, img_url) if hires != img_url else (img_url,):
                result = image_fetcher(url)
                if result:
                    img_data, ctype = result
                    break

        if img_data is None:
            return None

        ext = _ext_from_content_type(ctype)
        img_counter += 1
        fname = f"img-{img_counter:03d}.{ext}"
        epub_images[fname] = (img_data, ctype)
        return fname

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
                f'<p class="author">{xml_escape(art["author"])}</p>')

        parts.append('<div class="separator">---</div>')

        # Hero image (data URI takes priority over URL)
        img_fname = get_epub_image(
            img_url=art.get("image_url") or art.get("thumb_url"),
            img_data_uri=art.get("image_data_uri"),
        )
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

        # Body
        body = art.get("content_html", "")
        if body:
            # Internalize inline images
            body, img_counter = _internalize_inline_images(
                body, epub_images, img_counter, image_fetcher)
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
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}" lang="{language}">
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
    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<p class="subtitle">{xml_escape(subtitle)}</p>'
    tagline_html = ""
    if tagline:
        tagline_html = f'<p class="tagline">{xml_escape(tagline)}</p>'

    title_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}" lang="{language}">
<head>
<meta charset="UTF-8"/>
<title>{xml_escape(publication_title)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<div class="title-page">
    <h1>{xml_escape(publication_title.upper())}</h1>
    {subtitle_html}
    <p class="edition">{xml_escape(edition_title)}</p>
    {tagline_html}
</div>
</body>
</html>"""

    # ── TOC page ──────────────────────────────────────────────────────
    toc_label = "Table of Contents" if language == "en" else "Sommaire"
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
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{language}" lang="{language}">
<head>
<meta charset="UTF-8"/>
<title>{xml_escape(toc_label)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<nav epub:type="toc" class="toc">
    <h2>{xml_escape(toc_label)}</h2>
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

    dc_publisher = ""
    if publisher:
        dc_publisher = f"    <dc:publisher>{xml_escape(publisher)}</dc:publisher>"

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    full_title = f"{publication_title} — {edition_title}" if edition_title else publication_title

    content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:{book_uid}</dc:identifier>
    <dc:title>{xml_escape(full_title)}</dc:title>
    <dc:language>{language}</dc:language>
{dc_publisher}
    <dc:date>{date_str}</dc:date>
    <meta property="dcterms:modified">{now_utc}</meta>
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
        zf.writestr("OEBPS/style.css", EPUB_CSS)
        zf.writestr("OEBPS/title.xhtml", title_xhtml)
        zf.writestr("OEBPS/toc.xhtml", toc_xhtml)
        for fname, _, xhtml in chapters:
            zf.writestr(f"OEBPS/{fname}", xhtml)
        for fname, (img_data, _) in epub_images.items():
            zf.writestr(f"OEBPS/{fname}", img_data)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  {output_path.name} ({size_mb:.1f} MB)")
    return output_path
