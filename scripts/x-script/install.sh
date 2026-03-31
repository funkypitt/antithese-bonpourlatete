#!/bin/bash
# Script d'installation X Daily Digest

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║           📱 X DAILY DIGEST - Installation                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Vérifier Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 non trouvé. Installe-le d'abord."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PYTHON_VERSION détecté"

# Créer l'environnement virtuel
echo ""
echo "📦 Création de l'environnement virtuel..."
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
echo ""
echo "📥 Installation des dépendances..."
pip install --upgrade pip
pip install -r requirements.txt

# Installer Playwright et les navigateurs
echo ""
echo "🌐 Installation de Playwright et Chromium..."
playwright install chromium

# Créer les dossiers
echo ""
echo "📁 Création des dossiers..."
mkdir -p ~/.x-digest
mkdir -p ~/x-digest/output

# Vérifier Ollama (optionnel)
echo ""
if command -v ollama &> /dev/null; then
    echo "✅ Ollama détecté"
    echo "   Modèles disponibles:"
    ollama list 2>/dev/null | head -5 || echo "   (aucun modèle ou ollama non lancé)"
else
    echo "ℹ️  Ollama non installé"
    echo "   Pour le résumé local gratuit, installe Ollama:"
    echo "   curl -fsSL https://ollama.com/install.sh | sh"
    echo "   ollama pull llama3.1:8b"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    ✅ Installation terminée                ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Prochaines étapes:"
echo ""
echo "1. Configure tes listes X dans config.yaml"
echo "   (remplace les XXXXXXXXXX par les IDs de tes listes)"
echo ""
echo "2. Première connexion (ouvre un navigateur):"
echo "   source venv/bin/activate"
echo "   python main.py --login"
echo ""
echo "3. Générer ton premier digest:"
echo "   python main.py"
echo ""
echo "4. Mode test (sans scraper X):"
echo "   python main.py --test"
echo ""
echo "5. Planification automatique (crontab):"
echo "   30 6 * * * cd $(pwd) && ./venv/bin/python main.py >> ~/x-digest/digest.log 2>&1"
echo ""
