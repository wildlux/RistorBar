# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical: Python environment

**Always use the virtualenv**, never the system Python 3.14 (it lacks `_sqlite3`):

```bash
venv/bin/python manage.py <command>
venv/bin/pip install <package>
```

## Common commands

```bash
# Development server
venv/bin/python manage.py runserver

# Database
venv/bin/python manage.py makemigrations ristorante
venv/bin/python manage.py migrate

# Populate demo data (users, rooms, tables, full menu)
venv/bin/python manage.py demo_data

# Django shell
venv/bin/python manage.py shell

# Collect static files (production)
venv/bin/python manage.py collectstatic
```

## Architecture overview

Single Django project (`ristobar/`) with one app (`ristorante/`). No separate frontend framework — all UI is server-rendered Django templates with vanilla JS for real-time interactions.

### URL structure and access control

| Path prefix | Who | Auth |
|---|---|---|
| `/homepage` | Clienti (public) | None |
| `/menu/`, `/prenota/` | Clienti (public) | None |
| `/login/`, `/logout/` | Everyone | — |
| `/sala/` | Dispatch → redirects by role | `@login_required` |
| `/sala/cameriere/` | Camerieri | Group: `cameriere` |
| `/sala/cucina/` | Cuochi (KDS) | Group: `cuoco` |
| `/sala/capo/` | Dashboard completa | Group: `capo_area` / `titolare` |
| `/sala/editor/<id>/` | Planimetria SVG | Group: `capo_area` / `titolare` |
| `/amministrazione/` | Django admin | `is_staff` |
| `/api/` | REST API | DRF auth |
| `/api/tavolo/<sala>/<num>/` | STM32 BLE Hub | Public read |

### Role permission system

Roles are Django **Groups**. Use the custom decorator, not `@login_required` directly for staff views:

```python
# In ristorante/views.py
@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA)
def my_view(request): ...

# Helper
ha_ruolo(request.user, RUOLO_CUOCO)  # also returns True for superuser
```

Constants: `RUOLO_CAMERIERE`, `RUOLO_CUOCO`, `RUOLO_CAPO_AREA`, `RUOLO_TITOLARE`

### Data models

```
Sala ──< Tavolo ──< Prenotazione
      ──< TavoloUnione >──< Tavolo   (M2M, unione temporanea)

Categoria ──< Piatto

Tavolo ──< Ordine ──< OrdineItem ──> Piatto
```

**Tavolo** stato: `L` Libero · `P` Prenotato · `O` Occupato · `C` Conto
**Tavolo** forma: `R` Rotondo · `Q` Quadrato · `T` Rettangolare
**Tavolo** saves auto-generate a QR code PNG via `genera_qr()` on first save.

**OrdineItem** stato: `A` Attesa → `C` In cucina → `P` Pronto → `S` Servito
When all items of an `Ordine` reach stato `P`, the order auto-transitions to `STATO_SERVITO`.

**Prenotazione** has Stripe integration: `stripe_payment_intent_id` is set before payment; `caparra_pagata=True` is set by the Stripe webhook at `/webhooks/stripe/`.

### SVG floor plan editor (`/sala/editor/<id>/`)

The editor renders tables as draggable SVG `<g>` elements on top of an optional client-uploaded SVG background (`Sala.svg_sfondo`). If no SVG is uploaded, a procedural demo room is rendered inline. Positions are saved via POST to `/sala/editor/<id>/salva/` as `{tavoli: [{id, x, y}]}`. Table unions (`TavoloUnione`) are drawn as dashed purple rectangles around the member tables.

### KDS (Kitchen Display System) — `/sala/cucina/`

Polls via `location.reload()` every 20 seconds. Each `OrdineItem` has its own state button. When all items of an order are `P` (Pronto), the server sets the order to `STATO_SERVITO` and the card fades out client-side. Orders older than 15 minutes get a red pulse animation.

### PWA

`manifest.json` is served by a plain view in `ristobar/urls.py` (not django-pwa, which was removed). The service worker at `/static/js/serviceworker.js` caches the shell on install.

### API for STM32 / BLE Hub

`/api/tavolo/<sala_id>/<numero>/` returns a compressed JSON:
```json
{"t": 5, "s": "O", "n": "Rossi", "p": 4, "h": "20:00"}
```
Keys are single letters to minimize BLE payload and save battery on E-paper displays.

### Template layout

```
templates/
  base.html              # Navbar + i18n switcher (staff/admin nav)
  auth/login.html        # Custom login (no django.contrib.auth templates)
  registration/login.html # Fallback (unused but present)
  ristorante/            # Public-facing + manager views
    vetrina.html         # Landing page (standalone, no base.html)
    dashboard.html       # Capo area/titolare
    mappa_sala.html      # Read-only room map
    editor_sala.html     # SVG drag-drop editor (standalone JS)
    prenota.html / conferma_prenotazione.html / menu_tavolo.html
  sala/                  # Staff interfaces (no base.html, standalone)
    cameriere.html
    ordine.html          # Waiter comanda view
    cucina_kds.html      # Dark-theme KDS
```

`vetrina.html`, `cameriere.html`, `cucina_kds.html`, `ordine.html` are **standalone** (no `{% extends "base.html" %}`).

### Static files

```
static/css/style.css       # Global variables + shared components
static/css/vetrina.css     # Public landing page only
static/css/sala_staff.css  # All staff interfaces (cameriere, ordine, KDS)
static/js/serviceworker.js # PWA cache
static/js/app.js           # SW registration only
```

## Environment variables

```bash
STRIPE_PUBLIC_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
TELEGRAM_BOT_TOKEN=...
```

## Demo credentials

| Username | Password | Role |
|---|---|---|
| admin | admin123 | Superuser → `/amministrazione/` |
| titolare | titolare123 | Group titolare → dashboard + admin |
| capo_area | capo123 | Group capo_area → dashboard + editor |
| cameriere1 | cam123 | Group cameriere → sala/cameriere |
| cuoco1 | cuoco123 | Group cuoco → sala/cucina |
