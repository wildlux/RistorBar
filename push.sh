#!/bin/bash
# RistoBAR - Push to GitHub
# Usage: ./push.sh ["commit message"]

set -e

# Leggi il token dal file locale
TOKEN_FILE=".github_token"
if [ ! -f "$TOKEN_FILE" ]; then
    echo "Errore: file '$TOKEN_FILE' non trovato."
    echo "Crea il file con il tuo token GitHub (sarà ignorato da git)"
    echo "Esempio: echo 'ghp_xxxxxxxxxxxx' > .github_token"
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE")

# Configura remote con token (una tantum)
git remote set-url origin "https://wildlux:${TOKEN}@github.com/wildlux/RistorBar.git" 2>/dev/null || \
git remote add origin "https://wildlux:${TOKEN}@github.com/wildlux/RistorBar.git"

# Messaggio di commit
MSG="${1:-Aggiornamento RistoBAR}"

# Co-autori AI
COAUTHORS="Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Co-Authored-By: opencode (qwen3.5) <opencode[bot]@users.noreply.github.com>"

# Push
echo "📦 Commit: $MSG"
git add -A
git commit -m "$MSG

$COAUTHORS"
git push origin master

echo "✅ Push completato!"