# RistoBAR

**La piattaforma all-in-one per ristoranti moderni**

---

## Cosa è Stato Aggiunto

| Data | Funzionalità | Descrizione |
|------|-------------|-------------|
| 2026-03 | Display e-ink | Integrazione completa con ESP32 per stato tavolo, piatto del giorno, note chef |
| 2026-03 | AI Chef Chat | Chatbot multilingua (55+ lingue) con Ollama locale via `/chef/` |
| 2026-03 | WhatsApp Business | Webhook per conferme, notifiche, questionari |
| 2026-03 | Telegram Bot | Bot esistente migliorato con integrazione completa |
| 2026-03 | Fatturazione Elettronica | Formato FatturaPA/SDI per Italia |
| 2026-03 | Questionario + Coupon | Sistema feedback con generazione coupon sconto |
| 2026-03 | Magazzino | Scanner barcode, tracciamento scadenze, notifiche |
| 2026-03 | Chiusura Giornaliera | Input avanzi → lista spesa automatica |
| 2026-03 | Report AI | Analisi costi/benefici con Ollama |
| 2026-03 | Abbonamenti | Tracciamento scadenze dominio, costi software |
| 2026-03 | Social Media | Link Facebook, X, Instagram, YouTube, TikTok, Pinterest |
| 2026-03 | GPS/WiFi/BLE | Posizionamento automatico tavoli |
| 2026-03 | Storico Ordini | Salvato al momento pagamento per integrità dati |

---

## Architettura del Progetto

## Architettura del Progetto

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENTI                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │
│  │   Mobile    │  │   Menu QR   │  │  WhatsApp   │  │    Telegram     │   │
│  │    (PWA)    │  │   (menu/)   │  │  Business   │  │      Bot        │   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘   │
└─────────┼────────────────┼────────────────┼──────────────────┼────────────┘
          │                │                │                  │
          └────────────────┴────────┬───────┴──────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DJANGO SERVER                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        URL Router                                   │   │
│  │  /menu/*  /prenota/*  /chef/*  /sala/*  /api/*  /webhooks/*        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────────────────┐ │
│  │  Views     │ │  API REST   │ │  WebSocket  │ │   Ollama (AI)          │ │
│  │  (HTML)    │ │  (DRF)      │ │  (asgi)     │ │   llama3.2:3b         │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └────────────────────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        MODELS                                        │   │
│  │  Sala │ Tavolo │ Prenotazione │ Ordine │ OrdineItem │ Piatto        │   │
│  │  Categoria │ Questionario │ CouponSconto │ ProdottoMagazzino       │   │
│  │  CiboRimasto │ ListaSpesaGenerata │ ReportPeriodico │ Promemoria   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   DATABASE       │    │   HARDWARE       │    │   EXTERNAL       │
│   SQLite/PG      │    │   (ESP32)        │    │   SERVICES       │
│                  │    │                  │    │                  │
│  ┌────────────┐  │    │  ┌────────────┐  │    │  ┌────────────┐  │
│  │  Orders    │  │    │  │  e-ink     │  │    │  │  Stripe    │  │
│  │  Menu      │  │    │  │  display   │  │    │  │  (payment) │  │
│  │  Inventory │  │    │  │  (status)  │  │    │  └────────────┘  │
│  │  Reports   │  │    │  └────────────┘  │    │                  │
│  └────────────┘  │    │                   │    │  ┌────────────┐  │
└──────────────────┘    │  ┌────────────┐   │    │  │  Ollama   │  │
                        │  │   BLE/     │   │    │  │  (local)  │  │
                        │  │   WiFi     │   │    │  └────────────┘  │
                        │  └────────────┘   │    │                  │
                        └──────────────────┘    └──────────────────┘
```

### Stack Tecnologica

| Componente | Tecnologia | Versione |
|------------|------------|----------|
| Backend | Django | 5.x |
| Database | SQLite (demo) / PostgreSQL (produzione) | - |
| AI | Ollama + llama3.2:3b-instruct-q4_K_M | 0.5+ |
| API | Django REST Framework | 3.15+ |
| Frontend | Django Templates + Vanilla JS | - |
| PWA | Service Worker + Manifest | - |
| Hardware | ESP32, Arduino, STM32 | - |
| Pagamenti | Stripe | - |

### Struttura Directory

```
RistoBAR/
├── ristobar/                 # Progetto Django
│   ├── settings.py          # Configurazione
│   ├── urls.py              # URL routing principale
│   └── wsgi.py              # WSGI entry point
├── ristorante/               # App principale
│   ├── models.py            # Modelli database
│   ├── views.py             # Viste HTML
│   ├── api.py               # API REST
│   ├── admin.py             # Django admin
│   └── templatetags/        # Tag template personalizzati
├── templates/               # Template HTML
│   ├── base.html            # Layout base
│   ├── ristorante/          # Template ristorante
│   │   ├── chef_chat.html   # Chat AI
│   │   ├── magazzino.html   # Inventario
│   │   └── ...
│   └── sala/                # Interfacce staff
│       ├── cameriere.html
│       ├── cucina_kds.html
│       └── ...
├── static/                  # File statici
│   ├── css/
│   ├── js/
│   └── images/
├── CORE_Tavoli_Eink/        # Firmware hardware
│   ├── esp32/
│   │   ├── tavolo_display/  # Display e-ink
│   │   ├── tavolo_ble/      # BLE beacon
│   │   └── tavolo_multimode/
│   └── arduino/
├── tools/                   # Script utility
│   └── update_readme.py
├── requirements.txt         # Dipendenze Python
├── README.md                # Documentazione
├── HARDWARE.md              # Documentazione hardware
└── RistoBAR_Vendita.md      # Documento commerciale
```

### Flussi Dati

```
1. Prenotazione Cliente:
   QR Code → /prenota/ → Prenotazione.create() → Stripe (caparra) → WhatsApp (conferma)

2. Ordine Cameriere:
   /sala/cameriere/ → Ordine.create() → OrdineItem.create() → KDS (/sala/cucina/)

3. Pagamento:
   Tavolo.conto() → Stripe Payment → Ordine.stato = 'PAGATO' → Storico.save()

4. Chiusura Giornaliera:
   /sala/capo/chiusura/ → CiboRimasto.create() → ListaSpesaGenerata.create()

5. AI Chef:
   /chef/chat → Ollama (llama3.2:3b) → Risposta multilingua
```

---

## Perché RistoBAR è Diverso

RistoBAR non è l'ennesimo software di gestione ristorante. È stato pensato **dal basso**, da ristoratori veri, per risolvere problemi veri.

### La Filosofia

1. **Open Source e Trasparenza**
   - Il codice è visibile a tutti
   - Nessun lock-in: i tuoi dati sono tuoi
   - Puoi farlo funzionare dove vuoi

2. **Niente Abbonamenti Ossessivi**
   - Parcheggiato con abbonamento mensile che sale ogni anno? No.
   - RistoBAR ha un costo una tantum per l'installazione
   - Supporto a lungo periodo senza sorprese

3. **Hardware Aperto**
   - Non sei obbligato a comprare nostro hardware
   - Schede ESP32, Arduino, STM32: scegli tu
   - Display e-ink economici e personalizzabili

4. **AI Locale (nessun cloud proprietario)**
   - Chef AI parla con i clienti in 55+ lingue
   - Tutto gira sul tuo server o Raspberry Pi
   - Nessun dato va a terze parti

---

## Cosa Fa RistoBAR

### Per il Cliente

- **Menu digitale** sul proprio smartphone (no app da scaricare)
- **Prenotazione** con conferma istantanea
- **Pagamento caparra** tramite Stripe
- **Stato tavolo** su display e-ink al tavolo
- **Chat con Chef AI** per consigli e richieste
- **Questionario post-pasto** con coupon sconto

### Per il Personale

| Ruolo | Cosa può fare |
|-------|---------------|
| Cameriere | Prende ordini al tavolo via app, gestisce comande |
| Cuoco | KDS (Kitchen Display System), monitora ordini in tempo reale |
| Capo area | Dashboard completa, gestisce sale, magazzino, promemoria |
| Titolare | Tutto + report AI + gestione costi/abbonamenti |

### Per il Capo Area (Gestione Quotidiana)

- **Dashboard vendite** in tempo reale
- **Magazzino intelligente**:
  - Scannerizza barcode con la fotocamera del telefono
  - Tracciamento automatico delle scadenze
  - Notifica prodotti che stanno per scadere
  - Dopo l'apertura, conta giorni fino a scadenza
- **Promemoria** settimanali/mensili/bimestrali
- **Report automatici** con analisi AI dei costi/benefici

---

## Tecnologia

### Hardware

```
Tavolo → Display e-ink ←→ Scheda ESP32/Arduino ←→ WiFi/BLE ←→ Server Django
```

- Display e-ink: mostra stato tavolo, piatto del giorno, note chef
- QR code sul tavolo: il cliente scansiona e apre menu/prenotazione
- GPS/WiFi/BLE: posizionamento automatico dei tavoli nella sala

### Software

- **Backend**: Django (Python)
- **Database**: SQLite (demo) / PostgreSQL (produzione)
- **AI**: Ollama locale - nessun cloud
- **PWA**: Accesso da smartphone senza installare nulla
- **API REST**: Per integrazioni future

---

## Funzionalità Unique

### 1. Display e-ink con Piatto del Giorno

Il piatto del giorno viene mostrato automaticamente su tutti i display e-ink dei tavoli. Il cliente lo vede senza dover chiedere al cameriere.

### 2. Chat AI Chef Multilingua

Il cliente può chattare con lo chef via WhatsApp, Telegram o web. Lo chef AI:
- Consiglia piatti in base al menu
- Risponde in 55+ lingue
- È sempre disponibile

### 3. Questionario con Coupon

Dopo il pasto, il cliente riceve un questionario (via WhatsApp/Telegram/QR). Completandolo riceve un coupon sconto per la prossima visita.

### 4. Magazzino con Scanner

Il capo area può:
- Scannerizzare il barcode del prodotto con la fotocamera
- Inserire data di scadenza
- Segnare quando apre un prodotto (conta alla rovescia)
- Vedere lista scaduti / in scadenza

### 5. Chiusura Giornaliera e Lista Spesa Automatica

Ogni sera il capo inserisce gli avanzi. Il sistema:
- Calcola cosa è stato consumato (dagli ordini)
- Sottrae gli avanzi
- Genera la lista della spesa per il giorno dopo

### 6. Report AI Automatici

Ogni settimana/mese/bimestre:
- Il sistema genera un report con incassi, ordini, piatti più venduti
- AI analizza i dati e suggerisce miglioramenti
- Tiene traccia dei costi (abbonamento software, dominio)

---

## Installazione

```bash
# Clona il repository
git clone https://github.com/tuo-repo/ristobar.git
cd ristobar

# Crea ambiente virtuale
python -m venv venv
source venv/bin/activate

# Installa dipendenze
pip install -r requirements.txt

# Migrazioni
python manage.py migrate

# Dati demo
python manage.py demo_data

# Esegui
python manage.py runserver
```

### Ollama (AI Chef)

```bash
# Installa Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Avvia Ollama
ollama serve

# Scarica modello
ollama pull llama3.2:3b
```

---

## Credenziali Demo

| Username | Password | Ruolo |
|----------|----------|-------|
| admin | admin123 | Superuser |
| titolare | titolare123 | Titolare |
| capo_area | capo123 | Capo area |
| cameriere1 | cam123 | Cameriere |
| cuoco1 | cuoco123 | Cuoco |

---

## Link Utili

| Servizio | URL |
|----------|-----|
| Homepage | `/homepage` |
| Menu | `/menu/<sala_id>/<tavolo>/` |
| Prenota | `/prenota/<sala_id>/<tavolo>/` |
| Chat Chef AI | `/chef/` |
| Questionario | `/questionario/` |
| Dashboard | `/sala/capo/` |
| Magazzino | `/sala/capo/magazzino/` |
| Chiusura | `/sala/capo/chiusura/` |
| Lista Spesa | `/sala/capo/lista-spesa/` |
| Statistiche | `/sala/capo/statistiche/` |

---

## Differenze rispetto ai competitor

| Caratteristica | RistoBAR | Software Commerciali |
|----------------|----------|---------------------|
| Costo | Una tantum + supporto | Abbonamento mensile crescente |
| Codice | Open source | Proprietario |
| Dati | Tuoi, ovunque | Sul loro cloud |
| AI | Locale (Ollama) | Cloud proprietario |
| Hardware | Qualsiasi | Solo il loro |
| Personalizzazione | Totale | Limitata |
| Funzionalità | Su richiesta | Calendarizzate |

---

## Firmware Disponibili

- **ESP32** - tavolo_multimode
- **ESP32** - tavolo_ble
- **ESP32** - tavolo_display
- **ARDUINO** - tavolo_display


## API Rilevate

| Endpoint | Descrizione |
|----------|-------------|
| `api/tavolo/<id>/<id>/` | Stato tavolo |
| `api/sala/<id>/` | API endpoint |
| `api/esp32/tavolo/<id>/<id>/` | Stato tavolo |
| `api/esp32/sala/<id>/` | API endpoint |
| `api/dispositivo/status/` | Dispositivo hardware |
| `api/dispositivo/config/<id>/` | Dispositivo hardware |
| `api/tavolo/nota/<id>/` | Stato tavolo |

## Roadmap

Le funzionalità vengono sviluppate quando i clienti le richiedono. Niente feature inutili, tutto quello che serve davvero.

---

**RistoBAR** — Open source, supporto professionale, evolve con te.

Il tuo ristorante, il tuo software, i tuoi dati.


---
*README aggiornato automaticamente il 14/03/2026 17:15*