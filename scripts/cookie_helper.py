#!/usr/bin/env python3
"""
Cookie Helper — Playwright-based cookie exporter.

Opens a browser window for a target site, lets you log in manually,
then saves cookies to a JSON file (Cookie-Editor format) when you're done.

Usage:
    python cookie_helper.py tricycle          # → cookies.json
    python cookie_helper.py courrier          # → ci_cookies.json
    python cookie_helper.py --url https://example.com --output cookies.json

Requirements:
    pip install playwright
    playwright install chromium
"""

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Pre-configured sites
SITES = {
    "tricycle": {
        "url": "https://tricycle.org/wp-login.php",
        "output": SCRIPT_DIR / "cookies.json",
        "check_domain": "tricycle.org",
        "description": "Tricycle Magazine (Piano paywall)",
    },
    "courrier": {
        "url": "https://www.courrierinternational.com/login",
        "output": SCRIPT_DIR / "ci_cookies.json",
        "check_domain": "courrierinternational.com",
        "description": "Courrier International (Google OAuth)",
    },
}


def save_cookies(context, output_path: Path) -> int:
    """Extract cookies from Playwright context, save in Cookie-Editor format."""
    pw_cookies = context.cookies()

    cookies = []
    for c in pw_cookies:
        cookie = {
            "domain": c.get("domain", ""),
            "expirationDate": c.get("expires", -1),
            "hostOnly": not c.get("domain", "").startswith("."),
            "httpOnly": c.get("httpOnly", False),
            "name": c.get("name", ""),
            "path": c.get("path", "/"),
            "sameSite": {
                "Strict": "strict",
                "Lax": "lax",
                "None": "no_restriction",
            }.get(c.get("sameSite", "Lax"), "lax"),
            "secure": c.get("secure", False),
            "session": c.get("expires", -1) == -1,
            "storeId": None,
            "value": c.get("value", ""),
        }
        cookies.append(cookie)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    return len(cookies)


def run(url: str, output: Path, check_domain: str | None = None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright n'est pas installé.")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    print(f"🌐 Ouverture de {url}")
    print(f"📁 Les cookies seront enregistrés dans : {output}")
    print()
    print("👉 Connectez-vous dans la fenêtre du navigateur.")
    print("   Quand vous avez terminé, fermez simplement le navigateur.")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        # Wait for the user to close the browser
        try:
            while True:
                try:
                    # Check if page/browser is still open
                    page.evaluate("1")
                    time.sleep(0.5)
                except Exception:
                    break
        except KeyboardInterrupt:
            print("\n⏹  Interrompu par l'utilisateur.")

        # Save cookies before cleanup
        n = save_cookies(context, output)

        if check_domain:
            domain_cookies = [
                c for c in json.loads(output.read_text())
                if check_domain in c.get("domain", "")
            ]
            print(f"✅ {n} cookies sauvegardés ({len(domain_cookies)} pour {check_domain})")
        else:
            print(f"✅ {n} cookies sauvegardés")

        print(f"   → {output}")

        try:
            context.close()
            browser.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Ouvre un navigateur pour exporter des cookies après connexion manuelle.",
        epilog="Sites préconfigurés : " + ", ".join(SITES.keys()),
    )
    parser.add_argument(
        "site",
        nargs="?",
        choices=list(SITES.keys()),
        help="Site préconfigué (tricycle, courrier)",
    )
    parser.add_argument("--url", help="URL de connexion personnalisée")
    parser.add_argument("--output", "-o", type=Path, help="Fichier de sortie (défaut: cookies.json)")
    parser.add_argument("--list", "-l", action="store_true", help="Lister les sites préconfigurés")

    args = parser.parse_args()

    if args.list:
        print("Sites préconfigurés :")
        for name, cfg in SITES.items():
            print(f"  {name:12s}  {cfg['description']}")
            print(f"               URL: {cfg['url']}")
            print(f"               → {cfg['output']}")
            print()
        return

    if args.site:
        cfg = SITES[args.site]
        url = args.url or cfg["url"]
        output = args.output or cfg["output"]
        check_domain = cfg.get("check_domain")
    elif args.url:
        url = args.url
        output = args.output or Path("cookies.json")
        check_domain = None
    else:
        parser.print_help()
        print()
        print("Exemples :")
        print("  python cookie_helper.py tricycle")
        print("  python cookie_helper.py courrier")
        print("  python cookie_helper.py --url https://example.com -o my_cookies.json")
        sys.exit(1)

    run(url, output, check_domain)


if __name__ == "__main__":
    main()
