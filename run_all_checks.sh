#!/bin/bash
# RistoBAR - Run All Checks (Parallel Execution)
# Esegue tutti i controlli in parallelo per velocizzare

echo "🚀 RistoBAR - Full Check"
echo "========================="
echo "Esecuzione parallela di check, lint e test..."
echo ""

# File per risultati
RESULTS_DIR="/tmp/risto_check_$$"
mkdir -p "$RESULTS_DIR"

# Trap per pulizia
trap "rm -rf $RESULTS_DIR" EXIT

# Esegui in background in parallelo
(
    echo "[1/3] Check Django..." > "$RESULTS_DIR/check.out"
    venv/bin/python manage.py check >> "$RESULTS_DIR/check.out" 2>&1
    venv/bin/python manage.py makemigrations --check --dry-run >> "$RESULTS_DIR/check.out" 2>&1
    echo "DONE" >> "$RESULTS_DIR/check.out"
) &
PID_CHECK=$!

(
    echo "[2/3] Lint code..." > "$RESULTS_DIR/lint.out"
    find ristorante ristobar -name "*.py" -exec python -m py_compile {} \; 2>&1 | head -20 >> "$RESULTS_DIR/lint.out" || true
    echo "DONE" >> "$RESULTS_DIR/lint.out"
) &
PID_LINT=$!

(
    echo "[3/3] Run tests..." > "$RESULTS_DIR/test.out"
    venv/bin/python manage.py test ristorante.tests --verbosity=1 >> "$RESULTS_DIR/test.out" 2>&1
    echo "DONE" >> "$RESULTS_DIR/test.out"
) &
PID_TEST=$!

# Attendi completamento
echo "⏳ Esecuzione in corso..."

for pid in $PID_CHECK $PID_LINT $PID_TEST; do
    wait $pid 2>/dev/null || true
done

# Leggi risultati
echo ""
echo "═══════════════════════════════════════"
echo "📊 RISULTATI"
echo "═══════════════════════════════════════"

echo -e "\n🔍 CHECK (Django):"
tail -5 "$RESULTS_DIR/check.out"

echo -e "\n🧹 LINT:"
tail -5 "$RESULTS_DIR/lint.out"

echo -e "\n🧪 TESTS:"
tail -20 "$RESULTS_DIR/test.out"

# Check finale
FAILED=0
for f in check lint test; do
    if ! grep -q "DONE" "$RESULTS_DIR/${f}.out" 2>/dev/null; then
        FAILED=1
    fi
done

echo ""
if [ $FAILED -eq 0 ]; then
    echo "✅ Tutti i check completati!"
else
    echo "⚠️ Alcuni check hanno avuto problemi"
fi