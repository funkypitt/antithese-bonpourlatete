#!/usr/bin/env bash
# build_antithese.sh — Build standalone antithese_scraper executable via PyInstaller
# Requires: conda env "newspapers", system Pango/Cairo/GDK-Pixbuf libraries
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRY="$SCRIPT_DIR/antithese_scraper.py"
CONDA_ENV="newspapers"

echo "┌──────────────────────────────────────────────┐"
echo "│  🔨 Build antithese_scraper (PyInstaller)     │"
echo "└──────────────────────────────────────────────┘"
echo

# ── Check entry script exists ─────────────────────────────────────────────
if [[ ! -f "$ENTRY" ]]; then
    echo "❌ $ENTRY introuvable."
    exit 1
fi

# ── Ensure PyInstaller is installed ───────────────────────────────────────
if ! conda run -n "$CONDA_ENV" python -c "import PyInstaller" 2>/dev/null; then
    echo "📦 Installation de PyInstaller dans l'env $CONDA_ENV…"
    conda run -n "$CONDA_ENV" python -m pip install pyinstaller
fi

# ── Build ─────────────────────────────────────────────────────────────────
echo "🔧 Compilation en cours…"
conda run -n "$CONDA_ENV" pyinstaller \
    --onefile \
    --name antithese_scraper \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR/build" \
    --hidden-import=weasyprint \
    --hidden-import=bs4 \
    --hidden-import=requests \
    --hidden-import=lxml \
    --hidden-import=lxml.etree \
    --hidden-import=lxml.html \
    "$ENTRY"

echo
if [[ -f "$SCRIPT_DIR/dist/antithese_scraper" ]]; then
    echo "✅ Build réussi : $SCRIPT_DIR/dist/antithese_scraper"
    ls -lh "$SCRIPT_DIR/dist/antithese_scraper"
else
    echo "❌ Le binaire n'a pas été trouvé."
    exit 1
fi

echo
echo "⚠  Note : le système cible doit avoir Pango, Cairo et GDK-Pixbuf installés"
echo "   (requis par WeasyPrint pour le rendu PDF)."
