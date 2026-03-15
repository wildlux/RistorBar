"""
Servizio bot Telegram — polling in background thread.
Avviato automaticamente da RistoranteConfig.ready() con Django.
"""
import time
import threading
import logging
import requests

logger = logging.getLogger(__name__)

_bot_thread = None
_messaggi_recenti = []   # buffer ultimi 50 messaggi ricevuti
MAX_MESSAGGI = 50


def send_message(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def handle_message(token, chat_id, text):
    # Nei gruppi i comandi arrivano come /menu@botname — rimuove il suffisso
    if '@' in text:
        text = text.split('@')[0]
    tl = text.lower().strip()

    # ── Saluto ──────────────────────────────────────────────────────
    if tl in ['/start', 'start', 'ciao', 'salve', 'buongiorno', 'buonasera',
              'hello', 'hi', 'hola', 'bonjour', '👋']:
        imp = _get_imp()
        nome = imp.nome if imp else 'il ristorante'
        risposta = (
            f"Ciao! 👋 Sono il bot di *{nome}* 🍽️\n\n"
            "Ecco cosa posso fare:\n"
            "• /menu — Menu del giorno\n"
            "• /prenota — Come prenotare\n"
            "• /orari — Orari di apertura\n"
            "• /dove — Come raggiungerci\n"
            "• /contatti — Telefono ed email\n"
            "• /aiuto — Questo messaggio"
        )

    # ── Aiuto ────────────────────────────────────────────────────────
    elif tl in ['/aiuto', '/help', 'aiuto', 'help', 'comandi', '?']:
        imp = _get_imp()
        nome = imp.nome if imp else 'il ristorante'
        risposta = (
            f"*{nome}* — Comandi disponibili:\n\n"
            "• /menu — Menu del giorno\n"
            "• /prenota — Come prenotare\n"
            "• /orari — Orari di apertura\n"
            "• /dove — Indirizzo e mappa\n"
            "• /contatti — Telefono ed email\n"
            "• /aiuto — Questo messaggio"
        )

    # ── Menu ─────────────────────────────────────────────────────────
    elif tl in ['/menu', 'menu', 'carta', 'cosa mangiate', 'cosa servite',
                'cosa avete', 'menù', 'piatti']:
        risposta = _genera_menu()

    # ── Prenotazione ─────────────────────────────────────────────────
    elif any(k in tl for k in ['/prenota', 'prenotar', 'prenota', 'tavolo',
                                'posto', 'posti', 'riservare', 'riserva', 'book']):
        imp = _get_imp()
        tel = imp.telefono if imp else ''
        sito = imp.sito if imp else ''
        righe = ["📅 *Prenotazioni*\n"]
        if tel:
            righe.append(f"📞 Chiama: {tel}")
        if sito:
            righe.append(f"🌐 Online: {sito}")
        righe.append("\nScrivi /orari per gli orari di apertura.")
        risposta = '\n'.join(righe)

    # ── Orari ────────────────────────────────────────────────────────
    elif any(k in tl for k in ['/orari', 'orari', 'orario', 'aperto', 'aprite',
                                'chiudete', 'quando apre', 'quando chiude',
                                'che ore', 'a che ora', 'apertura', 'chiusura']):
        imp = _get_imp()
        if imp and imp.orari:
            risposta = f"🕐 *Orari di apertura*\n\n{imp.orari}"
        else:
            tel = imp.telefono if imp else ''
            risposta = "🕐 Gli orari non sono ancora stati configurati."
            if tel:
                risposta += f"\nPer info chiama: {tel}"

    # ── Dove siamo ───────────────────────────────────────────────────
    elif any(k in tl for k in ['/dove', 'dove', 'indirizzo', 'come arrivo',
                                'come si arriva', 'mappa', 'dove siete',
                                'dove si trova', 'location', 'posizione']):
        imp = _get_imp()
        if imp:
            parti = [p for p in [imp.indirizzo, imp.citta] if p]
            addr = ', '.join(parti)
            risposta = f"📍 *Dove siamo*\n\n{addr}" if addr else "📍 Indirizzo non ancora configurato."
            if addr:
                query = addr.replace(' ', '+')
                risposta += f"\n\n🗺️ [Apri in Google Maps](https://maps.google.com/?q={query})"
        else:
            risposta = "📍 Indirizzo non ancora configurato."

    # ── Contatti ─────────────────────────────────────────────────────
    elif any(k in tl for k in ['/contatti', 'contatti', 'contatto', 'telefono',
                                'numero', 'email', 'chiamare', 'chiamate',
                                'call', 'tel']):
        imp = _get_imp()
        righe = ["📞 *Contatti*\n"]
        if imp and imp.telefono:
            righe.append(f"📞 Tel: {imp.telefono}")
        if imp and imp.email:
            righe.append(f"✉️ Email: {imp.email}")
        if imp and imp.sito:
            righe.append(f"🌐 Sito: {imp.sito}")
        if len(righe) == 1:
            righe.append("Contatti non ancora configurati.")
        risposta = '\n'.join(righe)

    # ── Prezzi ───────────────────────────────────────────────────────
    elif any(k in tl for k in ['prezzo', 'prezzi', 'quanto costa', 'costo',
                                'economico', 'fascia', 'euro', '€']):
        risposta = "💶 Per i prezzi consulta il /menu oppure contattaci ai /contatti."

    # ── Allergie / intolleranze ───────────────────────────────────────
    elif any(k in tl for k in ['allergi', 'intolleranz', 'glutine', 'lattosio',
                                'vegano', 'vegetariano', 'celiac', 'senza']):
        risposta = (
            "🌿 Per informazioni su allergeni e intolleranze\n"
            "contatta direttamente il nostro staff ai /contatti.\n"
            "Faremo del nostro meglio per accontentarti!"
        )

    # ── Grazie ───────────────────────────────────────────────────────
    elif any(k in tl for k in ['grazie', 'thank', 'perfetto', 'ottimo', '🙏', '👍']):
        from .models import ImpostazioniRistorante
        imp = ImpostazioniRistorante.get()
        nome = imp.nome if imp else 'noi'
        risposta = f"Prego! 😊 A presto da *{nome}* 🍽️"

    else:
        risposta = (
            "Non ho capito. 😅 Prova uno di questi comandi:\n"
            "/menu · /prenota · /orari · /dove · /contatti · /aiuto"
        )

    send_message(token, chat_id, risposta)


def _get_imp():
    try:
        from ristorante.models import ImpostazioniRistorante
        return ImpostazioniRistorante.get()
    except Exception:
        return None


def _genera_menu():
    try:
        from ristorante.models import Categoria
        categorie = Categoria.objects.prefetch_related('piatti').all()
        if not categorie.exists():
            return "Menu non disponibile al momento."
        testo = "*Menu del Giorno* 🍽️\n\n"
        for cat in categorie:
            piatti = cat.piatti.all()
            if piatti.exists():
                testo += f"*{cat.nome}*\n"
                for p in piatti:
                    prezzo = f" — €{p.prezzo:.2f}" if p.prezzo else ""
                    testo += f"• {p.nome}{prezzo}\n"
                testo += "\n"
        return testo
    except Exception as e:
        logger.error(f"Errore generazione menu: {e}")
        return "Errore nel recupero del menu."


def _polling_loop(token):
    logger.info("Bot Telegram: polling avviato.")

    # Breve attesa per non bloccare il boot di Django
    time.sleep(2)

    # Recupera username del bot (usato per il filtro nei gruppi)
    bot_username = ''
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        bot_username = r.json().get('result', {}).get('username', '').lower()
        logger.info(f"Bot username: @{bot_username}")
    except Exception:
        pass

    # Rimuovi webhook se presente
    try:
        requests.post(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=5)
    except Exception:
        pass

    # Salta messaggi già presenti
    offset = None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                         params={'offset': -1}, timeout=5)
        result = r.json().get('result', [])
        if result:
            offset = result[-1]['update_id'] + 1
    except Exception:
        pass

    while True:
        try:
            params = {'timeout': 30}
            if offset is not None:
                params['offset'] = offset

            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params=params,
                timeout=40,
            )
            data = r.json()

            if data.get('ok'):
                for update in data.get('result', []):
                    offset = update['update_id'] + 1
                    msg = update.get('message', {})
                    chat_id = str(msg.get('chat', {}).get('id', ''))
                    text = msg.get('text', '')
                    nome = msg.get('from', {}).get('first_name', '?')
                    chat_type = msg.get('chat', {}).get('type', 'private')

                    if not chat_id or not text:
                        continue

                    # Nei gruppi risponde solo se menzionato (@bot) o comando diretto (/cmd@bot)
                    if chat_type in ('group', 'supergroup'):
                        menzione = f'@{bot_username}'.lower() if bot_username else ''
                        tl = text.lower()
                        if not menzione or menzione not in tl:
                            # salva nel buffer ma non risponde
                            _messaggi_recenti.append({
                                'da': nome + ' ' + msg.get('from', {}).get('last_name', ''),
                                'chat_id': chat_id,
                                'testo': text,
                                'ora': msg.get('date', 0),
                            })
                            if len(_messaggi_recenti) > MAX_MESSAGGI:
                                _messaggi_recenti.pop(0)
                            continue

                    if chat_id and text:
                        logger.info(f"Telegram [{nome}]: {text}")
                        # Salva nel buffer per il pannello dev
                        _messaggi_recenti.append({
                            'da': nome + ' ' + msg.get('from', {}).get('last_name', ''),
                            'chat_id': chat_id,
                            'testo': text,
                            'ora': msg.get('date', 0),
                        })
                        if len(_messaggi_recenti) > MAX_MESSAGGI:
                            _messaggi_recenti.pop(0)
                        handle_message(token, chat_id, text)

        except Exception as e:
            logger.warning(f"Bot Telegram errore polling: {e}")
            time.sleep(5)


def start_bot():
    """Avvia il bot in un daemon thread (sicuro da chiamare in AppConfig.ready)."""
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        return  # già in esecuzione

    from django.conf import settings
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN non impostato — bot non avviato.")
        return

    _bot_thread = threading.Thread(
        target=_polling_loop,
        args=(token,),
        daemon=True,
        name="telegram-bot",
    )
    _bot_thread.start()
    logger.info("Bot Telegram: thread avviato.")
