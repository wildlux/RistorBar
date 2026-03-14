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
  "timestamp": "2026-03-14T12:00:00Z"
}
```

**Firmware:** `firmware/esp32/tavolo_display/`

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