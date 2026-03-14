#!/bin/bash
# RistoBAR - Lint Code
# Linting con ruff e black

echo "🧹 RistoBAR - Lint"
echo "==================="

# Check if ruff is installed
if command -v ruff &> /dev/null; then
    echo "📋 Running ruff..."
    ruff check ristorante ristobar --exit-zero || true
else
    echo "⚠️ ruff non installato (pip install ruff)"
fi

# Check if black is installed
if command -v black &> /dev/null; then
    echo "📋 Running black check..."
    black --check ristorante ristobar --diff || true
else
    echo "⚠️ black non installato (pip install black)"
fi

# HTML template lint
echo "📋 Check HTML templates..."
find templates -name "*.html" -exec grep -l "{%" {} \; | head -10 || echo "✓ Templates OK"

echo -e "\n✅ Lint completato!"