"""
Scarica la lista dei comuni italiani da matteocontrini/comuni-json
e salva un JSON minimale in static/data/comuni.json.

Formato output: array di array [nome, sigla_provincia, nome_regione]
Es. ["Milano","MI","Lombardia"]

Utilizzo:
    venv/bin/python manage.py import_comuni
"""

import json
import os
import urllib.request
from django.core.management.base import BaseCommand

SOURCE_URL = 'https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json'
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'static', 'data', 'comuni.json')


class Command(BaseCommand):
    help = 'Scarica e salva la lista dei comuni italiani come JSON statico'

    def handle(self, *args, **options):
        self.stdout.write('Download comuni italiani...')
        with urllib.request.urlopen(SOURCE_URL) as r:
            data = json.loads(r.read().decode())

        # Formato minimale: [nome, sigla, regione]
        comuni = [
            [c['nome'], c['sigla'], c['regione']['nome']]
            for c in data
        ]

        os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
        with open(os.path.abspath(OUTPUT_PATH), 'w', encoding='utf-8') as f:
            json.dump(comuni, f, ensure_ascii=False, separators=(',', ':'))

        self.stdout.write(self.style.SUCCESS(f'OK — {len(comuni)} comuni salvati in static/data/comuni.json'))
