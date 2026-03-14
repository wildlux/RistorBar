# RistoBAR Tools

Utility scripts per lo sviluppo e manutenzione del progetto.

## Requisiti

```bash
# Attiva l'ambiente virtuale
source venv/bin/activate
```

## Script Disponibili

### update_readme.py

Aggiorna automaticamente il README.md con le info correnti del progetto:
- Firmware disponibili in `CORE_Tavoli_Eink/`
- Endpoint API rilevati in `ristobar/urls.py`
- Timestamp ultima aggiornamento

**Uso:**
```bash
python tools/update_readme.py
```

**Output:**
```
✅ README.md aggiornato!
   - 4 firmware rilevati
   - 7 endpoint API
```

## Installazione Hook Git (opzionale)

Per aggiornare automaticamente il README dopo ogni commit:

```bash
# Crea la cartella hooks se non esiste
mkdir -p .git/hooks

# Crea il hook post-commit
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash
python tools/update_readme.py
EOF

# Rendi eseguibile
chmod +x .git/hooks/post-commit
```

## Contribuire

Sentiti libero di aggiungere nuovi tool nella cartella `tools/`. Mantieni il codice pulito e documentato.


---
*README aggiornato automaticamente il 14/03/2026 16:09*