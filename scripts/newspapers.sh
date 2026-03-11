#!/usr/bin/env bash
# ============================================================================
# newspapers.sh — Télécharge Le Temps + The Economist + Antithèse + CI + Substack + Digest
# ============================================================================
#
# Génère automatiquement 6 versions PDF par journal :
#   _telephone.pdf, _liseuse.pdf, _tablette7.pdf, _tablette10.pdf,
#   _A4_premium.pdf, _A4_premium_landscape.pdf
#
# Tout est placé dans ~/kDrive/newspapers/journaux_du_jour/
#
# Usage :
#   ./newspapers.sh                  # Menu interactif de sélection
#   ./newspapers.sh --all            # Toutes les sources, sans menu
#   ./newspapers.sh --date 2026-02-10
#   ./newspapers.sh --letemps-only   # Le Temps uniquement
#   ./newspapers.sh --economist-only # Economist uniquement
#   ./newspapers.sh --antithese-only # Antithèse uniquement
#   ./newspapers.sh --ci-only        # Courrier International uniquement
#   ./newspapers.sh --substack-only  # Substack uniquement
#   ./newspapers.sh --digest-only    # Digest multi-sources uniquement
#   ./newspapers.sh --no-ci          # Tout sauf Courrier International
#   ./newspapers.sh --no-substack    # Tout sauf Substack
#   ./newspapers.sh --no-digest      # Tout sauf le digest
#   ./newspapers.sh --format a4landscape  # Format spécifique uniquement
#   ./newspapers.sh --asia            # Economist : d'Asia à Obituary (sans Leaders/US/Americas)
#
# Les identifiants peuvent être fournis par variables d'env :
#   export LETEMPS_USER="email"     LETEMPS_PASS="pass"
#   export ANTITHESE_USER="email"   ANTITHESE_PASS="pass"
#
# Courrier International utilise des cookies (compte Google) :
#   export CI_COOKIES="~/kDrive/newspapers/scripts/ci_cookies.json"
#
# ============================================================================

set -euo pipefail

# ── Identifiants Le Temps ──────────────────────────────────────────────────
LETEMPS_USER="${LETEMPS_USER:-'lgallaz@gmail.com'}"
LETEMPS_PASS="${LETEMPS_PASS:-'xxx'}"
export LETEMPS_USER LETEMPS_PASS

# ── Identifiants Antithèse ────────────────────────────────────────────────
ANTITHESE_USER="${ANTITHESE_USER:-'pierre.crot@protonmail.com'}"
ANTITHESE_PASS="${ANTITHESE_PASS:-'xxx'}"
export ANTITHESE_USER ANTITHESE_PASS

# ── Courrier International (cookies Google OAuth) ─────────────────────────
CI_COOKIES="${CI_COOKIES:-${HOME}/kDrive/newspapers/scripts/ci_cookies.json}"
export CI_COOKIES

# ── Substack (cookies export navigateur) ─────────────────────────────────
SUBSTACK_COOKIES="${SUBSTACK_COOKIES:-${HOME}/kDrive/newspapers/scripts/substack/cookies.json}"
export SUBSTACK_COOKIES

# ── Python : utiliser conda (python) au lieu du système (python3) ──────────
PYTHON="python"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATE=""
LETEMPS=unset
ECONOMIST=unset
ANTITHESE=unset
CI=unset
SUBSTACK=unset
DIGEST=unset
INTERACTIVE=true
EXTRA_LT_ARGS=()
EXTRA_EC_ARGS=()
EXTRA_AT_ARGS=()
EXTRA_CI_ARGS=()
EXTRA_SS_ARGS=()
ECONOMIST_SECTIONS="all"
FORMAT_SELECTION="all"

# ── Parse arguments ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --date|-d)
            DATE="$2"; shift 2 ;;
        --all|-a)
            LETEMPS=true; ECONOMIST=true; ANTITHESE=true; CI=true; SUBSTACK=true; DIGEST=true
            INTERACTIVE=false; shift ;;
        --letemps-only)
            LETEMPS=true; ECONOMIST=false; ANTITHESE=false; CI=false; SUBSTACK=false; DIGEST=false
            INTERACTIVE=false; shift ;;
        --economist-only)
            LETEMPS=false; ECONOMIST=true; ANTITHESE=false; CI=false; SUBSTACK=false; DIGEST=false
            INTERACTIVE=false; shift ;;
        --antithese-only)
            LETEMPS=false; ECONOMIST=false; ANTITHESE=true; CI=false; SUBSTACK=false; DIGEST=false
            INTERACTIVE=false; shift ;;
        --ci-only)
            LETEMPS=false; ECONOMIST=false; ANTITHESE=false; CI=true; SUBSTACK=false; DIGEST=false
            INTERACTIVE=false; shift ;;
        --substack-only)
            LETEMPS=false; ECONOMIST=false; ANTITHESE=false; CI=false; SUBSTACK=true; DIGEST=false
            INTERACTIVE=false; shift ;;
        --digest-only)
            LETEMPS=false; ECONOMIST=false; ANTITHESE=false; CI=false; SUBSTACK=false; DIGEST=true
            INTERACTIVE=false; shift ;;
        --no-antithese)
            ANTITHESE=false; shift ;;
        --no-letemps)
            LETEMPS=false; shift ;;
        --no-economist)
            ECONOMIST=false; shift ;;
        --no-ci)
            CI=false; shift ;;
        --no-substack)
            SUBSTACK=false; shift ;;
        --no-digest)
            DIGEST=false; shift ;;
        --no-headless)
            EXTRA_LT_ARGS+=(--no-headless); shift ;;
        --no-images)
            EXTRA_EC_ARGS+=(--no-images)
            EXTRA_CI_ARGS+=(--no-images)
            EXTRA_SS_ARGS+=(--no-images); shift ;;
        --format)
            FORMAT_SELECTION="$2"; shift 2 ;;
        --asia)
            ECONOMIST_SECTIONS="asia"; shift ;;
        --verbose|-v)
            EXTRA_LT_ARGS+=(--verbose)
            EXTRA_AT_ARGS+=(--verbose)
            EXTRA_SS_ARGS+=(--verbose)
            shift ;;
        *)
            echo "⚠  Argument inconnu : $1"; shift ;;
    esac
done

# ── Date du jour par défaut ────────────────────────────────────────────────
if [[ -z "$DATE" ]]; then
    DATE=$(date +%Y-%m-%d)
fi

# ── Jour de la semaine (pour suggestions) ──────────────────────────────────
DOW=$(date -d "$DATE" +%u 2>/dev/null || date -j -f "%Y-%m-%d" "$DATE" +%u 2>/dev/null || echo "")

# ── Menu interactif ────────────────────────────────────────────────────────
show_interactive_menu() {
    # Defaults : quotidiens ON, hebdos OFF par défaut
    local sel_letemps=true
    local sel_economist=false
    local sel_antithese=true
    local sel_ci=true
    local sel_substack=true
    local sel_digest=true

    # Le samedi (6), on suggère l'Economist
    if [[ "$DOW" == "6" ]]; then
        sel_economist=true
    fi

    # Respecter les --no-xxx passés en CLI
    [[ "$LETEMPS"   == "false" ]] && sel_letemps=false
    [[ "$ECONOMIST" == "false" ]] && sel_economist=false
    [[ "$ANTITHESE" == "false" ]] && sel_antithese=false
    [[ "$CI"        == "false" ]] && sel_ci=false
    [[ "$SUBSTACK"  == "false" ]] && sel_substack=false
    [[ "$DIGEST"    == "false" ]] && sel_digest=false

    local items=("$sel_letemps" "$sel_economist" "$sel_antithese" "$sel_ci" "$sel_substack" "$sel_digest")
    local names=(
        "Le Temps              (quotidien)"
        "The Economist          (hebdo)"
        "Antithèse              (quotidien)"
        "Courrier International (hebdo)"
        "Substack               (newsletters)"
        "Digest multi-sources   (quotidien)"
    )
    local current=0
    local num_items=${#items[@]}

    # Sauvegarder les settings du terminal
    local saved_stty
    saved_stty=$(stty -g)

    draw_menu() {
        # Effacer les lignes du menu (num_items + header + footer)
        local total_lines=$((num_items + 5))
        for ((i = 0; i < total_lines; i++)); do
            tput cuu1 2>/dev/null || printf '\033[1A'
            tput el  2>/dev/null || printf '\033[2K'
        done

        echo "  Sélectionner les sources à télécharger :"
        echo "  ─────────────────────────────────────────"
        for ((i = 0; i < num_items; i++)); do
            local check="  "
            [[ "${items[$i]}" == "true" ]] && check="✓ "
            local marker="  "
            [[ $i -eq $current ]] && marker="▸ "
            # Highlight ligne active
            if [[ $i -eq $current ]]; then
                printf "  \033[1;36m%s[%s] %s\033[0m\n" "$marker" "$check" "${names[$i]}"
            else
                printf "  %s[%s] %s\n" "$marker" "$check" "${names[$i]}"
            fi
        done
        echo ""
        echo "  ↑↓ naviguer  ·  Espace cocher  ·  Entrée valider  ·  a tout  ·  n rien  ·  q quitter"
    }

    # Afficher le menu initial (avec placeholder pour le premier draw)
    echo "  Sélectionner les sources à télécharger :"
    echo "  ─────────────────────────────────────────"
    for ((i = 0; i < num_items; i++)); do
        local check="  "
        [[ "${items[$i]}" == "true" ]] && check="✓ "
        local marker="  "
        [[ $i -eq $current ]] && marker="▸ "
        if [[ $i -eq $current ]]; then
            printf "  \033[1;36m%s[%s] %s\033[0m\n" "$marker" "$check" "${names[$i]}"
        else
            printf "  %s[%s] %s\n" "$marker" "$check" "${names[$i]}"
        fi
    done
    echo ""
    echo "  ↑↓ naviguer  ·  Espace cocher  ·  Entrée valider  ·  a tout  ·  n rien  ·  q quitter"

    # Boucle de saisie
    while true; do
        # Lire un caractère sans echo
        stty raw -echo
        local key
        key=$(dd bs=1 count=1 2>/dev/null)
        stty "$saved_stty"

        case "$key" in
            # Flèche haut/bas : séquence escape
            $'\x1b')
                stty raw -echo
                local seq1 seq2
                seq1=$(dd bs=1 count=1 2>/dev/null)
                seq2=$(dd bs=1 count=1 2>/dev/null)
                stty "$saved_stty"
                if [[ "$seq1" == "[" ]]; then
                    case "$seq2" in
                        A) # Haut
                            current=$(( (current - 1 + num_items) % num_items ))
                            ;;
                        B) # Bas
                            current=$(( (current + 1) % num_items ))
                            ;;
                    esac
                fi
                ;;
            " ") # Espace : toggle
                if [[ "${items[$current]}" == "true" ]]; then
                    items[$current]="false"
                else
                    items[$current]="true"
                fi
                ;;
            $'\n'|$'\r'|"") # Entrée : valider
                break
                ;;
            "a"|"A") # Tout cocher
                for ((i = 0; i < num_items; i++)); do items[$i]="true"; done
                ;;
            "n"|"N") # Tout décocher
                for ((i = 0; i < num_items; i++)); do items[$i]="false"; done
                ;;
            "q"|"Q") # Quitter
                echo ""
                echo "  Annulé."
                exit 0
                ;;
            "k"|"K") # vim haut
                current=$(( (current - 1 + num_items) % num_items ))
                ;;
            "j"|"J") # vim bas
                current=$(( (current + 1) % num_items ))
                ;;
        esac

        draw_menu
    done

    # Appliquer les sélections
    LETEMPS="${items[0]}"
    ECONOMIST="${items[1]}"
    ANTITHESE="${items[2]}"
    CI="${items[3]}"
    SUBSTACK="${items[4]}"
    DIGEST="${items[5]}"

    # Si Economist sélectionné et pas déjà forcé par --asia, demander
    if [[ "$ECONOMIST" == "true" && "$ECONOMIST_SECTIONS" == "all" ]]; then
        echo ""
        echo "  ┌─────────────────────────────────────┐"
        echo "  │  📰  Sections Economist              │"
        echo "  ├─────────────────────────────────────┤"
        echo "  │  1. Toute l'édition                  │"
        echo "  │  2. D'Asia à Obituary                │"
        echo "  │     (sans Leaders/US/Americas)        │"
        echo "  └─────────────────────────────────────┘"
        read -rp "  Choix [1-2, défaut=1]: " sec_choice
        case "$sec_choice" in
            2) ECONOMIST_SECTIONS="asia"
               echo "  → D'Asia à Obituary"
               ;;
            *) echo "  → Toute l'édition"
               ;;
        esac
    fi

    echo ""
}

# ── Menu interactif : choix du format PDF ─────────────────────────────────
show_format_menu() {
    local fmt_names=(
        "Tous les formats (6 PDFs + EPUB)"
        "📱 Téléphone"
        "📖 Liseuse 6 pouces"
        "📱 Tablette 7 pouces"
        "📱 Tablette 10 pouces"
        "🖨️  A4 Premium (portrait)"
        "🖨️  A4 Premium Paysage (3 col.)"
        "📚 EPUB uniquement"
    )
    local fmt_keys=("all" "phone" "ereader" "tablet7" "tablet10" "a4premium" "a4landscape" "epub")
    local num_fmts=${#fmt_names[@]}
    local current=0

    local saved_stty
    saved_stty=$(stty -g)

    draw_format_menu() {
        local total_lines=$((num_fmts + 5))
        for ((i = 0; i < total_lines; i++)); do
            tput cuu1 2>/dev/null || printf '\033[1A'
            tput el  2>/dev/null || printf '\033[2K'
        done

        echo "  Sélectionner le format de sortie PDF :"
        echo "  ───────────────────────────────────────"
        for ((i = 0; i < num_fmts; i++)); do
            local marker="  "
            [[ $i -eq $current ]] && marker="▸ "
            if [[ $i -eq $current ]]; then
                printf "  \033[1;36m%s %s\033[0m\n" "$marker" "${fmt_names[$i]}"
            else
                printf "  %s %s\n" "$marker" "${fmt_names[$i]}"
            fi
        done
        echo ""
        echo "  ↑↓ naviguer  ·  Entrée valider  ·  q quitter"
    }

    # Initial draw
    echo "  Sélectionner le format de sortie PDF :"
    echo "  ───────────────────────────────────────"
    for ((i = 0; i < num_fmts; i++)); do
        local marker="  "
        [[ $i -eq $current ]] && marker="▸ "
        if [[ $i -eq $current ]]; then
            printf "  \033[1;36m%s %s\033[0m\n" "$marker" "${fmt_names[$i]}"
        else
            printf "  %s %s\n" "$marker" "${fmt_names[$i]}"
        fi
    done
    echo ""
    echo "  ↑↓ naviguer  ·  Entrée valider  ·  q quitter"

    while true; do
        stty raw -echo
        local key
        key=$(dd bs=1 count=1 2>/dev/null)
        stty "$saved_stty"

        case "$key" in
            $'\x1b')
                stty raw -echo
                local seq1 seq2
                seq1=$(dd bs=1 count=1 2>/dev/null)
                seq2=$(dd bs=1 count=1 2>/dev/null)
                stty "$saved_stty"
                if [[ "$seq1" == "[" ]]; then
                    case "$seq2" in
                        A) current=$(( (current - 1 + num_fmts) % num_fmts )) ;;
                        B) current=$(( (current + 1) % num_fmts )) ;;
                    esac
                fi
                ;;
            $'\n'|$'\r'|"")
                break
                ;;
            "q"|"Q")
                echo ""
                echo "  Annulé."
                exit 0
                ;;
            "k"|"K")
                current=$(( (current - 1 + num_fmts) % num_fmts ))
                ;;
            "j"|"J")
                current=$(( (current + 1) % num_fmts ))
                ;;
        esac

        draw_format_menu
    done

    FORMAT_SELECTION="${fmt_keys[$current]}"
    echo "  → ${fmt_names[$current]}"
    echo ""
}

# ── Lancer le menu si mode interactif ──────────────────────────────────────
if $INTERACTIVE; then
    # Vérifier qu'on est dans un terminal
    if [[ -t 0 ]]; then
        echo ""
        echo "╔══════════════════════════════════════════════╗"
        echo "║  📰  Newspapers Downloader — $DATE   ║"
        echo "╚══════════════════════════════════════════════╝"
        echo ""
        show_interactive_menu

        # Vérifier qu'au moins une source est sélectionnée
        if [[ "$LETEMPS" == "false" && "$ECONOMIST" == "false" && "$ANTITHESE" == "false" && "$CI" == "false" && "$SUBSTACK" == "false" && "$DIGEST" == "false" ]]; then
            echo "  ⚠  Aucune source sélectionnée. Fin."
            exit 0
        fi

        # ── Format selection (only if not already set via --format) ──
        if [[ "$FORMAT_SELECTION" == "all" ]]; then
            show_format_menu
        fi

        # Vérifier qu'au moins une source est sélectionnée (redundant safety)
        if [[ "$LETEMPS" == "false" && "$ECONOMIST" == "false" && "$ANTITHESE" == "false" && "$CI" == "false" && "$SUBSTACK" == "false" && "$DIGEST" == "false" ]]; then
            echo "  ⚠  Aucune source sélectionnée. Fin."
            exit 0
        fi
    else
        # Pas de terminal (cron, pipe…) → tout activer
        [[ "$LETEMPS"   == "unset" ]] && LETEMPS=true
        [[ "$ECONOMIST" == "unset" ]] && ECONOMIST=true
        [[ "$ANTITHESE" == "unset" ]] && ANTITHESE=true
        [[ "$CI"        == "unset" ]] && CI=true
        [[ "$SUBSTACK"  == "unset" ]] && SUBSTACK=true
        [[ "$DIGEST"    == "unset" ]] && DIGEST=true
    fi
else
    # Mode non-interactif avec flags explicites
    [[ "$LETEMPS"   == "unset" ]] && LETEMPS=true
    [[ "$ECONOMIST" == "unset" ]] && ECONOMIST=true
    [[ "$ANTITHESE" == "unset" ]] && ANTITHESE=true
    [[ "$CI"        == "unset" ]] && CI=true
    [[ "$SUBSTACK"  == "unset" ]] && SUBSTACK=true
    [[ "$DIGEST"    == "unset" ]] && DIGEST=true
fi

echo "╔══════════════════════════════════════════════╗"
echo "║  📰  Lancement — $DATE               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
# ── Résoudre le label du format sélectionné ──────────────────────────────
case "$FORMAT_SELECTION" in
    all)         FORMAT_LABEL="tous (6 PDFs + EPUB)" ;;
    phone)       FORMAT_LABEL="📱 téléphone" ;;
    ereader)     FORMAT_LABEL="📖 liseuse" ;;
    tablet7)     FORMAT_LABEL="📱 tablette 7\"" ;;
    tablet10)    FORMAT_LABEL="📱 tablette 10\"" ;;
    a4premium)   FORMAT_LABEL="🖨️  A4 premium" ;;
    a4landscape) FORMAT_LABEL="🖨️  A4 premium paysage" ;;
    epub)        FORMAT_LABEL="📚 EPUB" ;;
    *)           FORMAT_LABEL="$FORMAT_SELECTION" ;;
esac

echo "  📂 Sortie : ~/kDrive/newspapers/journaux_du_jour/"
echo "  📐 Format : ${FORMAT_LABEL}"
echo ""

# Résumé des sélections
echo "  Sources sélectionnées :"
$LETEMPS   && echo "    ✓ Le Temps"                || echo "    ✗ Le Temps"
$ECONOMIST && echo "    ✓ The Economist"           || echo "    ✗ The Economist"
$ANTITHESE && echo "    ✓ Antithèse"               || echo "    ✗ Antithèse"
$CI        && echo "    ✓ Courrier International"  || echo "    ✗ Courrier International"
$SUBSTACK  && echo "    ✓ Substack"                || echo "    ✗ Substack"
$DIGEST    && echo "    ✓ Digest"                  || echo "    ✗ Digest"
echo ""

# ── Le Temps ───────────────────────────────────────────────────────────────
if $LETEMPS; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  Le Temps                                │"
    echo "└──────────────────────────────────────────────┘"

    LT_ARGS=(--date "$DATE" --format "$FORMAT_SELECTION")

    if [[ -n "${LETEMPS_USER:-}" ]]; then
        LT_ARGS+=(--user "$LETEMPS_USER")
    fi
    if [[ -n "${LETEMPS_PASS:-}" ]]; then
        LT_ARGS+=(--password "$LETEMPS_PASS")
    fi

    LT_ARGS+=("${EXTRA_LT_ARGS[@]}")

    if $PYTHON "${SCRIPT_DIR}/letemps_scraper.py" "${LT_ARGS[@]}"; then
        echo ""
        echo "  ✅ Le Temps terminé."
    else
        echo ""
        echo "  ⚠  Le Temps échoué (code $?)."
    fi
    echo ""
fi

# ── The Economist ──────────────────────────────────────────────────────────
if $ECONOMIST; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  The Economist                           │"
    echo "└──────────────────────────────────────────────┘"

    EC_ARGS=(--format "$FORMAT_SELECTION" --sections "$ECONOMIST_SECTIONS")

    if [[ -n "${DATE:-}" ]] && [[ "${ECONOMIST_USE_DATE:-}" == "true" ]]; then
        EC_ARGS+=(--date "$DATE")
    fi

    EC_ARGS+=("${EXTRA_EC_ARGS[@]}")

    if $PYTHON "${SCRIPT_DIR}/economist_downloader.py" "${EC_ARGS[@]}"; then
        echo ""
        echo "  ✅ The Economist terminé."
    else
        echo ""
        echo "  ⚠  The Economist échoué (code $?)."
    fi
    echo ""
fi

# ── Antithèse ─────────────────────────────────────────────────────────────
if $ANTITHESE; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  Antithèse — Bon pour la tête            │"
    echo "└──────────────────────────────────────────────┘"

    AT_ARGS=(--format "$FORMAT_SELECTION" --batch)

    if [[ -n "${ANTITHESE_USER:-}" ]] && [[ -n "${ANTITHESE_PASS:-}" ]]; then
        AT_ARGS+=(--user "$ANTITHESE_USER" --password "$ANTITHESE_PASS")
    fi

    AT_ARGS+=("${EXTRA_AT_ARGS[@]}")

    if $PYTHON "${SCRIPT_DIR}/antithese_scraper.py" "${AT_ARGS[@]}"; then
        echo ""
        echo "  ✅ Antithèse terminé."
    else
        echo ""
        echo "  ⚠  Antithèse échoué (code $?)."
    fi
    echo ""
fi

# ── Courrier International ────────────────────────────────────────────────
if $CI; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  Courrier International                   │"
    echo "└──────────────────────────────────────────────┘"

    CI_ARGS=(--format "$FORMAT_SELECTION")

    # Cookies : variable d'env > fichier par défaut dans scripts/
    if [[ -f "${CI_COOKIES:-}" ]]; then
        CI_ARGS+=(--cookies "$CI_COOKIES")
    elif [[ -f "${SCRIPT_DIR}/ci_cookies.json" ]]; then
        CI_ARGS+=(--cookies "${SCRIPT_DIR}/ci_cookies.json")
    else
        echo "  ⚠  Aucun fichier cookies trouvé."
        echo "     Placez ci_cookies.json dans ${SCRIPT_DIR}/"
        echo "     ou exportez CI_COOKIES=/chemin/vers/ci_cookies.json"
        echo "     (Export Cookie-Editor depuis courrierinternational.com)"
    fi

    CI_ARGS+=("${EXTRA_CI_ARGS[@]}")

    if $PYTHON "${SCRIPT_DIR}/courrier_international_scraper.py" "${CI_ARGS[@]}"; then
        echo ""
        echo "  ✅ Courrier International terminé."
    else
        echo ""
        echo "  ⚠  Courrier International échoué (code $?)."
    fi
    echo ""
fi

# ── Substack ──────────────────────────────────────────────────────────────
if $SUBSTACK; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  Substack Newsletters                     │"
    echo "└──────────────────────────────────────────────┘"

    SS_ARGS=(--format "$FORMAT_SELECTION")

    # Cookies : variable d'env > fichier par défaut dans scripts/substack/
    if [[ -f "${SUBSTACK_COOKIES:-}" ]]; then
        SS_ARGS+=(--cookies "$SUBSTACK_COOKIES")
    elif [[ -f "${SCRIPT_DIR}/substack/cookies.json" ]]; then
        SS_ARGS+=(--cookies "${SCRIPT_DIR}/substack/cookies.json")
    else
        echo "  ⚠  Aucun fichier cookies trouvé."
        echo "     Placez cookies.json dans ${SCRIPT_DIR}/substack/"
        echo "     ou exportez SUBSTACK_COOKIES=/chemin/vers/cookies.json"
    fi

    SS_ARGS+=("${EXTRA_SS_ARGS[@]}")

    if $PYTHON "${SCRIPT_DIR}/substack/substack_scraper.py" "${SS_ARGS[@]}"; then
        echo ""
        echo "  ✅ Substack terminé."
    else
        echo ""
        echo "  ⚠  Substack échoué (code $?)."
    fi
    echo ""
fi

# ── Digest Multi-Sources ──────────────────────────────────────────────────
if $DIGEST; then
    echo "┌──────────────────────────────────────────────┐"
    echo "│  📰  Digest Multi-Sources (10 sources)       │"
    echo "└──────────────────────────────────────────────┘"

    if $PYTHON "${SCRIPT_DIR}/news_digest.py"; then
        echo ""
        echo "  ✅ Digest terminé."
    else
        echo ""
        echo "  ⚠  Digest échoué (code $?)."
    fi
    echo ""
fi

# ── Résumé ─────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Terminé — $DATE                  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  📂 Fichiers dans ~/kDrive/newspapers/journaux_du_jour/"
ls -1 ~/kDrive/newspapers/journaux_du_jour/*"${DATE}"* 2>/dev/null || echo "     (aucun fichier trouvé)"
echo ""
