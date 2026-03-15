#!/bin/bash
# RistoBAR - Push to GitHub
# Usage: ./push.sh ["commit message"]
#
# Le credenziali GitHub vengono gestite dal git credential manager di sistema.
# Non serve nessun file .github_token.

set -e

# Assicura che il remote punti al repository corretto (senza token in chiaro nell'URL)
git remote set-url origin "https://github.com/wildlux/RistorBar.git" 2>/dev/null || \
git remote add origin "https://github.com/wildlux/RistorBar.git"

# Messaggio di commit
MSG="${1:-Aggiornamento RistoBAR}"

# Co-autori AI
COAUTHORS="Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Co-Authored-By: opencode (qwen3.5) <opencode[bot]@users.noreply.github.com>"

# Commit e push
echo "📦 Commit: $MSG"
git add -A
git commit -m "$MSG

$COAUTHORS"
git push origin master

echo "✅ Push completato!"
