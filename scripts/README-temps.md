# Le Temps — Scraper & PDF Tablette

Télécharge les articles du jour depuis [letemps.ch](https://www.letemps.ch) 
et génère un PDF formaté pour lecture confortable sur tablette 7 pouces.

## Installation rapide

```bash
chmod +x install.sh
./install.sh
```

## Utilisation

```bash
# Avec variables d'environnement (recommandé)
export LETEMPS_USER="votre_email@example.com"
export LETEMPS_PASS="votre_mot_de_passe"
python3 letemps_scraper.py

# Avec arguments
python3 letemps_scraper.py --user email@example.com --password motdepasse

# Date spécifique
python3 letemps_scraper.py --date 2026-02-10

# Mode debug (navigateur visible)
python3 letemps_scraper.py --no-headless
```

## Sortie

Les PDF sont sauvegardés dans :
```
/home/freedomfighter/kDrive/newspapers/letemps/YYYY-MM-DD-letemps.pdf
```

## Automatisation (cron)

Pour télécharger automatiquement chaque matin :
```bash
crontab -e
# Ajouter:
0 7 * * 1-6 LETEMPS_USER="email" LETEMPS_PASS="mdp" python3 ~/.local/bin/letemps_scraper.py
```

## Dépendances

- Python 3.10+
- playwright (+ chromium)
- beautifulsoup4
- reportlab
- requests
- fonts-noto (pour un rendu typographique soigné)

## Notes

- Le PDF est optimisé pour un écran 7" (~100×160mm) avec police serif 9pt
- Les articles sont organisés par section (Suisse, Monde, Économie, etc.)
- Un sommaire est généré automatiquement en première page
- Le script est respectueux du serveur (délai entre requêtes)
- La structure du site peut évoluer — les sélecteurs CSS pourraient nécessiter 
  une mise à jour occasionnelle
