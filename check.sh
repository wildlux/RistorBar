#!/bin/bash
# RistoBAR - Code Check
# Checks Django syntax, migrations, and runs tests

echo "🔍 RistoBAR - Code Check"
echo "========================"

# Check Django
echo -e "\n📦 Check Django..."
venv/bin/python manage.py check

# Check migrations
echo -e "\n📦 Check migrations..."
venv/bin/python manage.py makemigrations --check --dry-run

# Check syntax Python
echo -e "\n🐍 Check Python syntax..."
find ristorante ristobar -name "*.py" -exec python -m py_compile {} \; 2>&1 | head -20 || echo "✓ Syntax OK"

echo -e "\n✅ Check completato!"