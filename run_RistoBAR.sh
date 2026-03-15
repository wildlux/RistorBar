#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║            RistoBAR — Avvio server di sviluppo              ║
# ╚══════════════════════════════════════════════════════════════╝
# Uso: ./run_RistoBAR.sh [porta]
# Es.: ./run_RistoBAR.sh        → http://127.0.0.1:8000
#      ./run_RistoBAR.sh 9000   → http://127.0.0.1:9000

set -e

# ── Cartella del progetto ────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Porta (default 8000) ─────────────────────────────────────────
PORT="${1:-8000}"

# ── Colori ANSI ──────────────────────────────────────────────────
GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'
BLU='\033[0;34m'; CYN='\033[0;36m'; RST='\033[0m'

banner() {
  echo -e "${BLU}"
  echo "  ██████╗ ██╗███████╗████████╗ ██████╗ ██████╗  █████╗ ██████╗"
  echo "  ██╔══██╗██║██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗██╔══██╗██╔══██╗"
  echo "  ██████╔╝██║███████╗   ██║   ██║   ██║██████╔╝███████║██████╔╝"
  echo "  ██╔══██╗██║╚════██║   ██║   ██║   ██║██╔══██╗██╔══██║██╔══██╗"
  echo "  ██║  ██║██║███████║   ██║   ╚██████╔╝██████╔╝██║  ██║██║  ██║"
  echo "  ╚═╝  ╚═╝╚═╝╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝"
  echo -e "${RST}"
}

log()  { echo -e "${GRN}✔${RST}  $*"; }
warn() { echo -e "${YLW}⚠${RST}  $*"; }
err()  { echo -e "${RED}✖${RST}  $*" >&2; }
info() { echo -e "${CYN}→${RST}  $*"; }

# ────────────────────────────────────────────────────────────────
banner
echo -e "${YLW}  Avvio server di sviluppo RistoBAR${RST}"
echo "  $(date '+%d/%m/%Y %H:%M:%S')"
echo "  Progetto: $SCRIPT_DIR"
echo ""

# ── 1. Verifica virtualenv ───────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

if [ ! -f "$PYTHON" ]; then
  err "Virtualenv non trovato in: $VENV"
  info "Crea il venv con:  python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi
PYVER=$("$PYTHON" --version 2>&1)
log "Virtualenv trovato — $PYVER"

# ── 2. Carica variabili ambiente (.env) ──────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | grep -v '^$' | xargs)
  log ".env caricato"
else
  warn ".env non trovato — variabili Stripe/Telegram potrebbero mancare"
fi

# ── 3. Verifica porta libera ─────────────────────────────────────
if lsof -Pi :"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  warn "La porta $PORT è già in uso. Prova: ./run_RistoBAR.sh $((PORT+1))"
  read -rp "  Continuare comunque? [s/N] " ans
  [[ "$ans" =~ ^[Ss]$ ]] || exit 1
fi

# ── 4. Applica migrazioni pendenti ──────────────────────────────
info "Controllo migrazioni..."
MIGRATE_OUT=$("$PYTHON" manage.py showmigrations --list 2>&1 | grep '\[ \]' || true)
if [ -n "$MIGRATE_OUT" ]; then
  warn "Migrazioni pendenti rilevate — applico..."
  "$PYTHON" manage.py migrate --run-syncdb
  log "Migrazioni applicate"
else
  log "Database aggiornato"
fi

# ── 5. Colleziona file statici se necessario ────────────────────
# (solo se la cartella staticfiles è vuota o mancante)
STATIC_DIR="$SCRIPT_DIR/staticfiles"
if [ ! -d "$STATIC_DIR" ] || [ -z "$(ls -A "$STATIC_DIR" 2>/dev/null)" ]; then
  info "Raccolta file statici..."
  "$PYTHON" manage.py collectstatic --noinput --clear -v 0
  log "File statici collezionati"
fi

# ── 6. Riepilogo URL ─────────────────────────────────────────────
echo ""
echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  ${YLW}Server attivo su:${RST}  http://127.0.0.1:${PORT}"
echo ""
echo -e "  ${CYN}Vetrina pubblica${RST}   http://127.0.0.1:${PORT}/homepage"
echo -e "  ${CYN}Login staff${RST}        http://127.0.0.1:${PORT}/login/"
echo -e "  ${CYN}Dashboard${RST}          http://127.0.0.1:${PORT}/sala/capo/"
echo -e "  ${CYN}Admin Django${RST}       http://127.0.0.1:${PORT}/amministrazione/"
echo -e "  ${CYN}Dev panel${RST}          http://127.0.0.1:${PORT}/dev/"
echo ""
echo -e "  ${YLW}Credenziali demo:${RST}"
echo -e "    admin / admin123   •  titolare / titolare123"
echo -e "    capo_area / capo123   •  cameriere1 / cam123"
echo -e "    cassa1 / cassa123     •  cuoco1 / cuoco123"
echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""
echo -e "  ${RED}Premi Ctrl+C per fermare il server${RST}"
echo ""

# ── 7. Avvia server ──────────────────────────────────────────────
exec "$PYTHON" manage.py runserver "127.0.0.1:${PORT}"
