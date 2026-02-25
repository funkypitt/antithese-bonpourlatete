# Antithèse — Lecteur hors-ligne

Téléchargez l'édition du jour d'**Antithèse / Bon pour la tête** en PDF ou EPUB, prête à lire ou à imprimer.

---

## Installation sur macOS

### 1. Télécharger le programme

1. Rendez-vous sur la page des builds :
   **https://github.com/funkypitt/newspapers/actions**
2. Cliquez sur le **dernier build vert** (celui avec une coche verte).
3. En bas de la page, dans la section **Artifacts**, téléchargez
   **`antithese_interactive-macos-arm64`**.
4. Un fichier `.zip` est téléchargé. **Double-cliquez** dessus pour le décompresser.
5. Vous obtenez un fichier nommé `antithese_interactive` — déplacez-le par exemple
   dans votre dossier **Applications** ou sur le **Bureau**.

### 2. Autoriser l'exécution (une seule fois)

macOS bloque par défaut les programmes téléchargés hors de l'App Store.
Pour lever ce blocage :

1. Ouvrez **Terminal** (cherchez « Terminal » dans Spotlight avec `Cmd + Espace`).
2. Tapez la commande suivante, puis appuyez sur **Entrée** :
   ```
   chmod +x ~/Desktop/antithese_interactive
   ```
   *(Adaptez le chemin si vous avez placé le fichier ailleurs.)*
3. **Première exécution** : faites un clic droit sur le fichier > **Ouvrir**.
   macOS affichera un avertissement — cliquez sur **Ouvrir** pour confirmer.
   Cette manipulation n'est nécessaire qu'une seule fois.

### 3. Lancer le programme

1. Ouvrez **Terminal**.
2. Glissez-déposez le fichier `antithese_interactive` dans la fenêtre du Terminal
   (cela écrit automatiquement le chemin), puis appuyez sur **Entrée**.

   Ou tapez directement :
   ```
   ~/Desktop/antithese_interactive
   ```

### 4. Utilisation

Le programme vous guide pas à pas :

| Étape | Ce qui se passe |
|-------|----------------|
| **Email / mot de passe** | Entrez vos identifiants Antithèse (votre abonnement). Le mot de passe ne s'affiche pas quand vous tapez — c'est normal. |
| **Formats de sortie** | Choisissez parmi : `1` PDF Premium (2 colonnes), `2` PDF Éditorial (1 colonne), `3` EPUB, ou `4` pour tout générer. Appuyez sur Entrée sans rien taper pour tout générer. |
| **Dossier de sortie** | Par défaut, les fichiers sont enregistrés sur votre **Bureau** dans un dossier `antithese`. Appuyez sur Entrée pour accepter, ou tapez un autre chemin. |
| **Génération** | Le programme télécharge les articles et génère les fichiers. Cela prend environ 1 à 2 minutes. |

Une fois terminé, retrouvez vos fichiers dans le dossier `antithese` sur votre Bureau.

---

## Installation sur Linux

1. Téléchargez l'artifact **`antithese_interactive-linux-x86_64`** depuis la
   [page des builds](https://github.com/funkypitt/newspapers/actions).
2. Rendez le fichier exécutable :
   ```bash
   chmod +x antithese_interactive
   ```
3. Lancez-le :
   ```bash
   ./antithese_interactive
   ```

Les fichiers sont enregistrés par défaut dans `~/kDrive/newspapers/antithese`.

---

## Formats disponibles

| Format | Description |
|--------|-------------|
| **A4 Premium** | Mise en page deux colonnes, style New Yorker. Idéal pour imprimer. |
| **A4 Éditorial** | Mise en page une colonne, style Kinfolk. Lecture confortable à l'écran. |
| **EPUB** | Livre numérique pour liseuse (Kindle, Kobo) ou application de lecture. |
