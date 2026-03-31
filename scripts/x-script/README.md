# 📱 X Daily Digest

**Reprends le contrôle de ton temps.** Génère un résumé PDF quotidien de ton feed X (Twitter) optimisé pour tablette 7 pouces.

## 🎯 Pourquoi ce projet ?

Le doom scrolling sur X est conçu pour être addictif. Ce pipeline te permet de :
- **Consommer l'essentiel** sans te perdre dans le scroll infini
- **Lire hors-ligne** sur ta tablette, sans notifications
- **Filtrer le bruit** avec des règles personnalisées
- **Garder le contrôle** sur ton temps d'écran

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  X (Twitter)    │────▶│   Scraper    │────▶│  Summarizer  │────▶│     PDF     │
│  - For You      │     │  (Playwright)│     │ (Claude/     │     │  (ReportLab)│
│  - Listes       │     │              │     │  Ollama)     │     │             │
└─────────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
```

## ⚡ Installation rapide

```bash
# Cloner ou copier le projet
cd x-digest

# Lancer l'installation
chmod +x install.sh
./install.sh
```

## 🔧 Configuration

Édite `config.yaml` pour personnaliser :

### Sources
```yaml
sources:
  for_you:
    enabled: true
    max_posts: 50
    
  lists:
    - name: "Tech & IA"
      url: "https://x.com/i/lists/1234567890"  # Ton ID de liste
      max_posts: 30
```

💡 **Trouver l'ID d'une liste** : Ouvre ta liste sur X, l'URL contient l'ID.

### Filtrage
```yaml
filtering:
  min_engagement: 10  # Ignorer les posts < 10 interactions
  
  priority_keywords:   # Boost ces sujets
    - "IA"
    - "podcast"
    
  exclude_keywords:    # Filtrer ces sujets
    - "crypto"
    - "NFT"
```

### Résumé IA
```yaml
summarizer:
  # "ollama" = gratuit et local (recommandé)
  # "claude" = API Anthropic (payant mais meilleur)
  provider: "ollama"
  
  ollama:
    model: "llama3.1:8b"  # Ou mistral, phi3...
```

## 🚀 Utilisation

### Première connexion
```bash
source venv/bin/activate
python main.py --login
```
→ Un navigateur s'ouvre, connecte-toi manuellement à X.

### Générer un digest
```bash
python main.py
```

### Mode test (sans scraper)
```bash
python main.py --test
```

### Options
```
--config, -c    Fichier de configuration (défaut: config.yaml)
--test, -t      Mode test avec données simulées
--login         Forcer une nouvelle connexion
--skip-scrape   Utiliser le cache (à implémenter)
```

## ⏰ Planification automatique

Ajoute à ton crontab (`crontab -e`) :

```bash
# Générer le digest tous les matins à 6h30
30 6 * * * cd /chemin/vers/x-digest && ./venv/bin/python main.py >> ~/x-digest/digest.log 2>&1
```

## 📄 Format PDF

Le PDF est optimisé pour :
- **Tablette 7 pouces** (100×170mm)
- **Lecture confortable** (police 9pt minimum)
- **Mode portrait** idéal pour le texte
- **Structure claire** : sommaire, sections, highlights

## 🔒 Sécurité & Confidentialité

- **Session locale** : Tes cookies X sont stockés dans `~/.x-digest/session.json`
- **Pas de serveur** : Tout tourne en local sur ta machine
- **Ollama** : Le résumé peut être 100% local (aucune donnée envoyée)

## ⚠️ Limitations & Avertissements

1. **Zone grise ToS** : Le scraping automatisé de X n'est pas officiellement autorisé
2. **Fragilité** : Les sélecteurs CSS peuvent changer si X modifie son interface
3. **Rate limiting** : Ne pas abuser (1-2 fois par jour max)
4. **Session** : Peut expirer, nécessitant une reconnexion manuelle

## 🛠️ Dépannage

### "Session expirée"
```bash
python main.py --login
```

### "Ollama connection refused"
```bash
# Lancer le serveur Ollama
ollama serve

# Dans un autre terminal, vérifier
curl http://localhost:11434/api/tags
```

### "Aucun post récupéré"
- Vérifie ta connexion internet
- Vérifie que la session X est valide
- Essaie en mode non-headless (modifier `headless=False` dans `scraper.py`)

## 📁 Structure du projet

```
x-digest/
├── config.yaml       # Configuration principale
├── main.py           # Script d'orchestration
├── scraper.py        # Module de scraping X
├── summarizer.py     # Module de résumé IA
├── pdf_generator.py  # Génération PDF
├── requirements.txt  # Dépendances Python
├── install.sh        # Script d'installation
└── README.md         # Ce fichier
```

## 🔮 Améliorations futures

- [ ] Cache des posts (éviter de re-scraper)
- [ ] Support des threads complets
- [ ] Export vers e-reader (ePub)
- [ ] Interface web de configuration
- [ ] Notifications push quand le digest est prêt

## ☁️ Synchronisation kDrive

Le PDF est automatiquement copié vers ton kDrive après génération :

```yaml
# Dans config.yaml
kdrive:
  enabled: true
  sync_path: "/home/freedomfighter/kDrive/X-Digest"
  keep_last: 30  # Garde les 30 derniers (0 = tous)
```

Le dossier est créé automatiquement. Les anciens digests sont purgés selon `keep_last`.

## 📜 Licence

Usage personnel. Respecte les ToS de X.

---

*Fait avec 🧠 et un peu de FOMO assumé.*
