#!/usr/bin/env python3
"""
Script per aggiornare automaticamente il README.md in base allo stato del progetto.
Esegue: python update_readme.py
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"


def scan_firmware():
    """Rileva firmware disponibili."""
    firmware = []
    core_path = ROOT / "CORE_Tavoli_Eink"
    
    if core_path.exists():
        for vendor in core_path.iterdir():
            if vendor.is_dir():
                for project in vendor.iterdir():
                    if project.is_dir():
                        firmware.append({
                            'vendor': vendor.name,
                            'project': project.name,
                            'path': f"CORE_Tavoli_Eink/{vendor.name}/{project.name}"
                        })
    return firmware


def scan_api_endpoints():
    """Rileva endpoint API nel codice."""
    endpoints = []
    urls_path = ROOT / "ristobar" / "urls.py"
    
    if urls_path.exists():
        content = urls_path.read_text()
        # Cerca pattern come path('api/... con variabili <int:...>
        pattern = r"path\(['\"](api/[\w/<>:_\-]+)['\"]"
        matches = re.findall(pattern, content)
        for m in matches:
            # Semplifica le variabili
            m_clean = re.sub(r'<int:\w+>', '<id>', m)
            if m_clean not in endpoints:
                endpoints.append(m_clean)
    
    return endpoints


def scan_models():
    """Rileva modelli Django."""
    models = []
    models_path = ROOT / "ristorante" / "models.py"
    
    if models_path.exists():
        content = models_path.read_text()
        pattern = r"class (\w+)\(models\.Model\):"
        matches = re.findall(pattern, content)
        models = matches
    
    return models


def update_readme():
    """Aggiorna il README.md con le info correnti."""
    if not README.exists():
        print("README.md non trovato")
        return
    
    content = README.read_text()
    
    # Rileva firmware
    firmware = scan_firmware()
    firmware_section = "## Firmware Disponibili\n\n"
    for fw in firmware:
        firmware_section += f"- **{fw['vendor'].upper()}** - {fw['project']}\n"
    firmware_section += "\n"
    
    # Rileva API
    endpoints = scan_api_endpoints()
    api_section = "## API Rilevate\n\n| Endpoint | Descrizione |\n|----------|-------------|\n"
    for ep in endpoints:
        desc = "API endpoint"
        if 'tavolo' in ep:
            desc = "Stato tavolo"
        elif 'dispositivo' in ep:
            desc = "Dispositivo hardware"
        elif 'chef' in ep:
            desc = "Chat AI Chef"
        elif 'webhooks' in ep:
            desc = "Webhook"
        api_section += f"| `{ep}` | {desc} |\n"
    api_section += "\n"
    
    # Aggiorna sezioni
    # Trova la sezione firmware e sostituisci
    if "## Firmware Disponibili" in content:
        start = content.find("## Firmware Disponibili")
        end = content.find("\n## ", start + 1)
        if end == -1:
            end = len(content)
        content = content[:start] + firmware_section + content[end:]
    else:
        # Aggiungi alla fine prima di Roadmap
        if "## Roadmap" in content:
            pos = content.find("## Roadmap")
            content = content[:pos] + firmware_section + content[pos:]
    
    # Aggiorna API - inserisci dopo firmware
    if "## API Rilevate" in content:
        start = content.find("## API Rilevate")
        end = content.find("\n## ", start + 1)
        if end == -1:
            end = content.find("\n\n## ", start + 1)
        if end == -1:
            end = len(content)
        content = content[:start] + api_section + content[end:]
    elif firmware_section and endpoints:
        # Aggiungi sezione API dopo firmware
        if "## Roadmap" in content:
            pos = content.find("## Roadmap")
            content = content[:pos] + "\n" + api_section + content[pos:]
    
    # Aggiungi timestamp
    from datetime import datetime
    timestamp = f"\n\n---\n*README aggiornato automaticamente il {datetime.now().strftime('%d/%m/%Y %H:%M')}*"
    
    if "*README aggiornato automaticamente" in content:
        content = re.sub(r'\n\*README aggiornato automaticamente.*', timestamp, content)
    else:
        content += timestamp
    
    README.write_text(content)
    print("✅ README.md aggiornato!")
    print(f"   - {len(firmware)} firmware rilevati")
    print(f"   - {len(endpoints)} endpoint API")


if __name__ == "__main__":
    update_readme()
