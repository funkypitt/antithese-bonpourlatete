#!/bin/bash
# ============================================================
# Installation script for Le Temps Scraper
# Run: chmod +x install.sh && ./install.sh
# ============================================================

set -e

echo "=== Installation du scraper Le Temps ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 non trouvé. Installez-le avec:"
    echo "   sudo apt install python3 python3-pip"
    exit 1
fi

echo "✓ Python $(python3 --version | cut -d' ' -f2) trouvé"

# Install system dependencies for Playwright and WeasyPrint
echo ""
echo "→ Installation des dépendances système..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    fonts-noto-core \
    fonts-noto-extra \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 2>/dev/null || \
sudo apt-get install -y -qq \
    fonts-noto-core \
    fonts-noto-extra \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2

echo "✓ Dépendances système installées"

# Install Python packages
echo ""
echo "→ Installation des paquets Python..."
pip3 install --user --break-system-packages \
    playwright \
    beautifulsoup4 \
    reportlab \
    requests \
    2>/dev/null || \
pip3 install --user \
    playwright \
    beautifulsoup4 \
    reportlab \
    requests

echo "✓ Paquets Python installés"

# Install Playwright browsers
echo ""
echo "→ Installation de Chromium pour Playwright..."
python3 -m playwright install chromium
echo "✓ Chromium installé"

# Create output directory
echo ""
mkdir -p /home/freedomfighter/kDrive/newspapers/letemps
echo "✓ Dossier de sortie créé: /home/freedomfighter/kDrive/newspapers/letemps"

# Copy script
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
cp letemps_scraper.py "$INSTALL_DIR/letemps_scraper.py"
chmod +x "$INSTALL_DIR/letemps_scraper.py"
echo "✓ Script copié dans $INSTALL_DIR"

# Setup credentials
echo ""
echo "=== Configuration des identifiants ==="
echo ""
echo "Pour ne pas avoir à taper votre mot de passe à chaque fois,"
echo "ajoutez ces lignes à votre ~/.bashrc ou ~/.profile :"
echo ""
echo '  export LETEMPS_USER="votre_email@example.com"'
echo '  export LETEMPS_PASS="votre_mot_de_passe"'
echo ""

# Create convenience alias
ALIAS_LINE='alias letemps="python3 $HOME/.local/bin/letemps_scraper.py"'
if ! grep -q "alias letemps=" "$HOME/.bashrc" 2>/dev/null; then
    echo "" >> "$HOME/.bashrc"
    echo "# Le Temps scraper" >> "$HOME/.bashrc"
    echo "$ALIAS_LINE" >> "$HOME/.bashrc"
    echo "✓ Alias 'letemps' ajouté à .bashrc"
fi

# Setup daily cron job (optional)
echo ""
echo "=== Tâche automatique quotidienne (optionnel) ==="
read -p "Voulez-vous télécharger automatiquement chaque matin à 7h? (o/N) " CRON_ANSWER
if [[ "$CRON_ANSWER" == "o" || "$CRON_ANSWER" == "O" ]]; then
    CRON_CMD="0 7 * * 1-6 LETEMPS_USER=\"\$LETEMPS_USER\" LETEMPS_PASS=\"\$LETEMPS_PASS\" python3 $INSTALL_DIR/letemps_scraper.py >> /tmp/letemps_cron.log 2>&1"
    (crontab -l 2>/dev/null | grep -v "letemps_scraper"; echo "$CRON_CMD") | crontab -
    echo "✓ Tâche cron configurée (lun-sam à 7h00)"
    echo "  ⚠ N'oubliez pas de configurer LETEMPS_USER et LETEMPS_PASS dans votre crontab"
    echo "  Éditez avec: crontab -e"
fi

echo ""
echo "=== Installation terminée! ==="
echo ""
echo "Utilisation:"
echo "  python3 letemps_scraper.py --user EMAIL --password MOT_DE_PASSE"
echo "  python3 letemps_scraper.py  # si variables d'environnement configurées"
echo "  python3 letemps_scraper.py --date 2026-02-10  # date spécifique"
echo ""
