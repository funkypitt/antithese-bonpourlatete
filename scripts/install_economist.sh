#!/bin/bash
# Installation des dépendances pour economist_downloader.py

echo "📦 Installation des dépendances Python..."
pip install --user requests beautifulsoup4 weasyprint cloudscraper

echo ""
echo "✅ Installation terminée !"
echo ""
echo "Si cloudscraper ne suffit pas contre Cloudflare :"
echo "  pip install --user playwright && playwright install chromium"
echo ""
echo "Usage:"
echo "  python3 economist_downloader.py                    # Dernière édition"
echo "  python3 economist_downloader.py --date 2025-02-07  # Édition spécifique"
echo "  python3 economist_downloader.py --list-only        # Sommaire uniquement"
echo "  python3 economist_downloader.py --no-images        # PDF léger"
echo ""
echo "Le PDF sera rangé dans ~/kDrive/newspapers/economist/"
