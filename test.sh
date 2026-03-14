#!/bin/bash
# RistoBAR - Test Suite
# Esegue i test Django

echo "🧪 RistoBAR - Tests"
echo "===================="

venv/bin/python manage.py test ristorante.tests --verbosity=1

echo -e "\n✅ Tests completati!"