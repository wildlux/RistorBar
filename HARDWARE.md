# RistoBAR - Integrazione Hardware

## Panoramica

RistoBAR supporta l'integrazione con diversi dispositivi embedded per visualizzare lo stato dei tavoli su display e-ink.

## Dispositivi Supportati

### 1. ESP32 (WiFi)

Display e-ink connessi via WiFi. Ideale per: tavoli singoli, menu digitali, segnaletica.

**Endpoint API:**
- `/api/esp32/tavolo/<sala_id>/<numero>/` - Singolo tavolo
- `/api/esp32/sala/<sala_id>/` - Tutti i tavoli della sala

**Esempio risposta:**
```json
{
  "tavolo": 1,
  "sala": "Sala Principale",
  "stato": "L",
  "stato_testo": "LIBERO",
  "posti": 4,
  "prenotato": {
    "nome": "Mario Rossi",
    "persone": 4,
    "ora": "20:00"
  },
  "ordine": null,
  "nota": "Oggi specials: Risotto ai funghi porcini!",
  "qr_url": "http://192.168.1.100:8000/media/qrcodes/tavolo_1_1.png",
  "site_url": "http://192.168.1.100:8000",
  "timestamp": "2026-03-14T12:00:00Z"
}
```

**Nota display:** Il campo `nota` contiene commenti/suggerimenti impostati dal capo ristorante o dallo chef, visibili sul display e-ink.

**API per impostare nota:**
```
POST /api/tavolo/nota/<tavolo_id>/
Authorization: Bearer <token>
Content-Type: application/json
{"nota": "Oggi specials: Risotto ai funghi!"}
```
Accesso: cuoco, capo_area, titolare

**Firmware:** `CORE_Tavoli_Eink/esp32/tavolo_display/`

**Hardware consigliato:**
- ESP32-WROOM-32
- Display Waveshare e-paper 2.9" (296x128)
- Batteria LiPo 3.7V (per autonomia)

### 2. STM32 (BLE)

Display e-ink connessi via Bluetooth Low Energy. Ideale per: basso consumo, tavoli senza alimentazione.

**Endpoint API:**
- `/api/tavolo/<sala_id>/<numero>/` - Singolo tavolo (formato compresso)
- `/api/sala/<sala_id>/` - Tutti i tavoli

**Esempio risposta (compresso):**
```json
{
  "t": 1,
  "s": "L",
  "n": "",
  "p": 0,
  "h": ""
}
```

**Note:**
- Campi compressi (t=tavolo, s=stato, n=nome, p=persone, h=ora)
- Progettato per minimizzare payload BLE
- Richiede un bridge HTTP per BLE (es. Raspberry Pi con dongle)

## Wiring ESP32

| ESP32 | E-Paper |
|-------|---------|
| GPIO15 | CS |
| GPIO4 | DC |
| GPIO2 | RST |
| GPIO16 | BUSY |
| 3.3V | VCC |
| GND | GND |

## Configurazione

1. Carica firmware su ESP32
2. Configura SSID/Password WiFi nel codice
3. Imposta indirizzo server Django
4. Compila e flasha

## Sleep

Il firmware usa deep sleep per risparmiare energia. Wakeup ogni 60 secondi (configurabile).

### 3. Arduino + ESP-01S (WiFi)

Display e-ink con Arduino classico + modulo ESP-01S. Ideale per: progetti economici, espansione display esistenti.

**Endpoint API:**
- `/api/esp32/tavolo/<sala_id>/<numero>/` (stesso formato ESP32)

**Firmware:** `CORE_Tavoli_Eink/arduino/tavolo_display/`

**Hardware consigliato:**
- Arduino UNO o Mega
- Modulo ESP-01S (WiFi)
- Display Waveshare e-paper 2.9"

**Wiring Arduino ↔ ESP-01S:**

| Arduino | ESP-01S |
|---------|---------|
| D10 (TX) | RX |
| D11 (TX) | TX |
| 3.3V | VCC |
| GND | GND |
| GND | GPIO0 (per flash) |

**Configurazione:**
1. Carica sketch su Arduino
2. Collega ESP-01S come da tabella
3. Configura SSID/Password WiFi nel codice
4. Imposta indirizzo server Django

**Note:**
- Usa SoftwareSerial per comunicare con ESP-01S
- L'ESP-01S deve avere firmware AT compatibile
- Refresh ogni 60 secondi

---

## Centro di Controllo

RistoBAR include un **Centro di Controllo** per gestire tutti i dispositivi hardware dalla dashboard Django.

### Accesso

- URL: `/sala/dispositivi/`
- Richiede login (capo area / titolare)

### Funzionalità

- Visualizzazione di tutti i dispositivi per piano/sala
- Statistiche online/offline
- Aggiunta/rimozione dispositivi
- Configurazione individuale
- Storico last seen e stati

### API Centro di Controllo

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/dispositivo/status/` | Dispositivo invia il proprio stato |
| `GET /api/dispositivo/config/<id>/` | Richiedi configurazione |

---

## Riepilogo endpoint API

| Dispositivo | Endpoint | Formato |
|--------------|----------|---------|
| ESP32/Arduino | `/api/esp32/tavolo/<sala>/<num>/` | Completo (+ nota + qr_url) |
| ESP32/Arduino | `/api/esp32/sala/<sala>/` | Array |
| STM32 | `/api/tavolo/<sala>/<num>/` | Compresso |
| STM32 | `/api/sala/<sala>/` | Array |
| Staff/Capo | `POST /api/tavolo/nota/<id>/` | Imposta nota display |
| Dispositivo | `/api/dispositivo/status/` | Status update |

---

## Modalità di funzionamento

### ESP32 Multi-Mode

Il firmware `tavolo_multimode` supporta tre modalità:

| Modalità | Descrizione | Uso |
|----------|-------------|-----|
| `WIFI_ONLY` | Solo WiFi, fetch periodico | Ristoranti con WiFi stabile |
| `BLE_ONLY` | Solo Bluetooth, dati da server/bridge | Basso consumo, no WiFi |
| `COMBINED` | Entrambi attivi | Ridondanza, massima affidabilità |

### Configurazione BLE

I dispositivi BLE usano:
- Service UUID: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- Characteristic: `6e400003-b5a3-f393-e0a9-e50e24dcca9e` (notify)

La configurazione avviene via BLE characteristic scrivendo:
```
SET:mode=2;ssid=MioWifi;pass=mypassword;server=192.168.1.100;sala=1;tavolo=1;refresh=60
```