import json
import stripe
from datetime import date, timedelta
from functools import wraps
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.utils import timezone
from django.db.models import Sum, Q
from django.db import models
from django.core.mail import send_mail, EmailMessage
from django.template.loader import render_to_string
from rest_framework import viewsets, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import Sala, Tavolo, TavoloUnione, Categoria, Piatto, Prenotazione, Ordine, OrdineItem, Fattura, ImpostazioniRistorante, Sede, Contatto
from .serializers import (
    TavoloSerializer, PrenotazioneSerializer,
    OrdineSerializer, PiattoSerializer
)

stripe.api_key = settings.STRIPE_SECRET_KEY


# ─── Helpers ruoli ────────────────────────────────────────────────────────────

RUOLO_CAMERIERE  = 'cameriere'
RUOLO_CUOCO      = 'cuoco'
RUOLO_CAPO_AREA  = 'capo_area'
RUOLO_TITOLARE   = 'titolare'

def ha_ruolo(user, *ruoli):
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=ruoli).exists()

def ruolo_richiesto(*ruoli):
    """Decoratore: accesso solo per i ruoli indicati (o superuser)."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url='/login/')
        def wrapper(request, *args, **kwargs):
            if ha_ruolo(request.user, *ruoli):
                return view_func(request, *args, **kwargs)
            return redirect('sala_dispatch')
        return wrapper
    return decorator


# ─── Login / Logout ──────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('sala_dispatch')
    errore = None
    if request.method == 'POST':
        user = authenticate(request,
                            username=request.POST.get('username'),
                            password=request.POST.get('password'))
        if user:
            login(request, user)
            return redirect(request.POST.get('next') or 'sala_dispatch')
        errore = _('Credenziali non valide.')
    return render(request, 'auth/login.html', {
        'errore': errore,
        'next': request.GET.get('next', ''),
    })


def logout_view(request):
    logout(request)
    return redirect('homepage')


# ─── Dispatch ruolo ──────────────────────────────────────────────────────────

@login_required(login_url='/login/')
def sala_dispatch(request):
    """Reindirizza all'interfaccia corretta in base al ruolo."""
    u = request.user
    if u.is_superuser or ha_ruolo(u, RUOLO_TITOLARE, RUOLO_CAPO_AREA):
        return redirect('dashboard')
    if ha_ruolo(u, RUOLO_CAMERIERE):
        return redirect('cameriere')
    if ha_ruolo(u, RUOLO_CUOCO):
        return redirect('cucina_kds')
    # Fallback: dashboard base
    return redirect('dashboard')


# ─── Dashboard capo area / titolare ──────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def dashboard(request):
    sale = Sala.objects.filter(attiva=True).prefetch_related('tavoli')
    prenotazioni_oggi = Prenotazione.objects.filter(
        data_ora__date=timezone.now().date(),
        stato__in=[Prenotazione.STATO_ATTESA, Prenotazione.STATO_CONFERMATA]
    ).order_by('data_ora')
    ordini_aperti = Ordine.objects.filter(
        stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
    ).select_related('tavolo')
    return render(request, 'ristorante/dashboard.html', {
        'sale': sale,
        'prenotazioni_oggi': prenotazioni_oggi,
        'ordini_aperti': ordini_aperti,
    })


# ─── Mappa tavoli (vista sala) ───────────────────────────────────────────────

@login_required
def mappa_sala(request, sala_id):
    sala = get_object_or_404(Sala, pk=sala_id, attiva=True)
    tavoli = sala.tavoli.filter(attivo=True)
    return render(request, 'ristorante/mappa_sala.html', {
        'sala': sala,
        'tavoli': tavoli,
    })


# ─── Interfaccia Cameriere ────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def cameriere_view(request):
    sale = Sala.objects.filter(attiva=True).prefetch_related('tavoli')
    prenotazioni_oggi = Prenotazione.objects.filter(
        data_ora__date=timezone.now().date(),
        stato=Prenotazione.STATO_CONFERMATA,
    ).select_related('tavolo').order_by('data_ora')
    return render(request, 'sala/cameriere.html', {
        'sale': sale,
        'prenotazioni_oggi': prenotazioni_oggi,
    })


@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def cameriere_ordine(request, tavolo_id):
    """Pagina ordine per un tavolo specifico (prendere/aggiornare comanda)."""
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id)
    ordine_aperto = tavolo.ordini.filter(
        stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
    ).first()
    categorie = Categoria.objects.prefetch_related('piatti').all()

    if request.method == 'POST':
        data = json.loads(request.body)
        azione = data.get('azione')

        if azione == 'nuovo_ordine':
            ordine = Ordine.objects.create(
                tavolo=tavolo,
                cameriere=request.user,
            )
            tavolo.stato = Tavolo.STATO_OCCUPATO
            tavolo.save(update_fields=['stato'])
            return JsonResponse({'ok': True, 'ordine_id': ordine.pk})

        if azione == 'aggiungi_piatto':
            ordine = get_object_or_404(Ordine, pk=data['ordine_id'], tavolo=tavolo)
            piatto = get_object_or_404(Piatto, pk=data['piatto_id'])
            item, creato = OrdineItem.objects.get_or_create(
                ordine=ordine, piatto=piatto,
                defaults={'prezzo_unitario': piatto.prezzo, 'quantita': 1}
            )
            if not creato:
                item.quantita += 1
                item.save(update_fields=['quantita'])
            ordine.calcola_totale()
            return JsonResponse({'ok': True, 'subtotale': str(item.subtotale), 'qty': item.quantita})

        if azione == 'rimuovi_piatto':
            item = get_object_or_404(OrdineItem, pk=data['item_id'])
            ordine = item.ordine
            if item.quantita > 1:
                item.quantita -= 1
                item.save(update_fields=['quantita'])
            else:
                item.delete()
            ordine.calcola_totale()
            return JsonResponse({'ok': True})

        if azione == 'invia_cucina':
            ordine = get_object_or_404(Ordine, pk=data['ordine_id'], tavolo=tavolo)
            ordine.stato = Ordine.STATO_IN_PREPARAZIONE
            ordine.save(update_fields=['stato'])
            ordine.items.filter(stato=OrdineItem.STATO_ATTESA).update(stato=OrdineItem.STATO_IN_CUCINA)
            return JsonResponse({'ok': True})

        if azione == 'chiedi_conto':
            tavolo.stato = Tavolo.STATO_CONTO
            tavolo.save(update_fields=['stato'])
            return JsonResponse({'ok': True})

    return render(request, 'sala/ordine.html', {
        'tavolo': tavolo,
        'ordine': ordine_aperto,
        'categorie': categorie,
    })


# ─── KDS — Interfaccia Cuoco ─────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def cucina_kds(request):
    """Kitchen Display System: tutti gli ordini in preparazione."""
    ordini = Ordine.objects.filter(
        stato=Ordine.STATO_IN_PREPARAZIONE
    ).prefetch_related('items__piatto', 'tavolo').order_by('creato_il')
    return render(request, 'sala/cucina_kds.html', {'ordini': ordini})


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
@require_POST
def aggiorna_item_kds(request, item_id):
    """Il cuoco aggiorna lo stato di una singola voce dell'ordine."""
    item = get_object_or_404(OrdineItem, pk=item_id)
    data = json.loads(request.body)
    nuovo = data.get('stato')
    stati_validi = [s[0] for s in OrdineItem.STATO_CHOICES]
    if nuovo not in stati_validi:
        return JsonResponse({'errore': 'Stato non valido'}, status=400)
    item.stato = nuovo
    item.save(update_fields=['stato'])
    # Se tutti i piatti dell'ordine sono pronti → aggiorna ordine
    ordine = item.ordine
    if not ordine.items.exclude(stato=OrdineItem.STATO_PRONTO).exists():
        ordine.stato = Ordine.STATO_SERVITO
        ordine.save(update_fields=['stato'])
    return JsonResponse({'ok': True, 'ordine_completato': ordine.stato == Ordine.STATO_SERVITO})


# ─── Gestione tavolo ─────────────────────────────────────────────────────────

@login_required(login_url='/login/')
@require_POST
def aggiorna_stato_tavolo(request, tavolo_id):
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id)
    data = json.loads(request.body)
    nuovo_stato = data.get('stato')
    stati_validi = [s[0] for s in Tavolo.STATO_CHOICES]
    if nuovo_stato not in stati_validi:
        return JsonResponse({'errore': 'Stato non valido'}, status=400)
    tavolo.stato = nuovo_stato
    tavolo.save(update_fields=['stato'])
    return JsonResponse({
        'successo': True,
        'stato': tavolo.get_stato_display(),
        'colore': tavolo.colore_stato,
    })


# ─── Menu cliente (via QR) ───────────────────────────────────────────────────

def menu_tavolo(request, sala_id, numero_tavolo):
    sala = get_object_or_404(Sala, pk=sala_id)
    tavolo = get_object_or_404(Tavolo, sala=sala, numero=numero_tavolo, attivo=True)
    categorie = Categoria.objects.prefetch_related('piatti').all()
    return render(request, 'ristorante/menu_tavolo.html', {
        'sala': sala,
        'tavolo': tavolo,
        'categorie': categorie,
    })


# ─── Prenotazione pubblica ───────────────────────────────────────────────────

def prenota(request, sala_id, numero_tavolo):
    sala = get_object_or_404(Sala, pk=sala_id)
    tavolo = get_object_or_404(Tavolo, sala=sala, numero=numero_tavolo, attivo=True)

    if request.method == 'POST':
        data = request.POST
        prenotazione = Prenotazione.objects.create(
            tavolo=tavolo,
            nome_cliente=data.get('nome', ''),
            telefono=data.get('telefono', ''),
            num_persone=int(data.get('persone', 2)),
            data_ora=data.get('data_ora'),
            note=data.get('note', ''),
        )
        if prenotazione.caparra_richiesta:
            return redirect('pagamento_caparra', prenotazione_id=prenotazione.pk)
        return redirect('conferma_prenotazione', prenotazione_id=prenotazione.pk)

    return render(request, 'ristorante/prenota.html', {
        'sala': sala,
        'tavolo': tavolo,
        'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
    })


# ─── Pagamento caparra Stripe ─────────────────────────────────────────────────

def pagamento_caparra(request, prenotazione_id):
    prenotazione = get_object_or_404(Prenotazione, pk=prenotazione_id)
    if request.method == 'POST':
        try:
            intent = stripe.PaymentIntent.create(
                amount=int(prenotazione.caparra_importo * 100),  # centesimi
                currency='eur',
                metadata={'prenotazione_id': prenotazione.pk},
            )
            prenotazione.stripe_payment_intent_id = intent.id
            prenotazione.save(update_fields=['stripe_payment_intent_id'])
            return JsonResponse({'client_secret': intent.client_secret})
        except Exception as e:
            return JsonResponse({'errore': str(e)}, status=400)

    return render(request, 'ristorante/pagamento_caparra.html', {
        'prenotazione': prenotazione,
        'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
    })


def conferma_prenotazione(request, prenotazione_id):
    prenotazione = get_object_or_404(Prenotazione, pk=prenotazione_id)
    return render(request, 'ristorante/conferma_prenotazione.html', {
        'prenotazione': prenotazione,
    })


# ─── Webhook Stripe ──────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def stripe_webhook(request):
    import logging
    logger = logging.getLogger(__name__)
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe webhook secret not configured")
        return HttpResponse(status=400)
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("Invalid payload in Stripe webhook")
        return HttpResponse(status=400)
    except Exception:
        logger.error("Stripe signature verification failed")
        return HttpResponse(status=400)

    event_type = event['type']
    data = event['data']['object']
    
    logger.info(f"Stripe webhook received: {event_type}")
    
    if event_type == 'payment_intent.succeeded':
        prenotazione_id = data.get('metadata', {}).get('prenotazione_id')
        if prenotazione_id:
            Prenotazione.objects.filter(pk=prenotazione_id).update(
                caparra_pagata=True,
                stato=Prenotazione.STATO_CONFERMATA,
            )
            logger.info(f"Prenotazione {prenotazione_id} confermata")
    
    elif event_type == 'payment_intent.payment_failed':
        prenotazione_id = data.get('metadata', {}).get('prenotazione_id')
        if prenotazione_id:
            Prenotazione.objects.filter(pk=prenotazione_id).update(
                stato=Prenotazione.STATO_ANNULLATA,
            )
            logger.warning(f"Pagamento fallito per prenotazione {prenotazione_id}")
    
    elif event_type == 'checkout.session.completed':
        metadata = data.get('metadata', {})
        prenotazione_id = metadata.get('prenotazione_id')
        if prenotazione_id:
            Prenotazione.objects.filter(pk=prenotazione_id).update(
                caparra_pagata=True,
                stato=Prenotazione.STATO_CONFERMATA,
            )
            logger.info(f"Checkout completato per prenotazione {prenotazione_id}")
    
    elif event_type == 'charge.refunded':
        payment_intent_id = data.get('payment_intent')
        if payment_intent_id:
            Prenotazione.objects.filter(
                stripe_payment_intent_id=payment_intent_id
            ).update(
                caparra_pagata=False,
                stato=Prenotazione.STATO_ANNULLATA,
            )
            logger.info(f"Refund elaborato per payment intent {payment_intent_id}")
    
    elif event_type == 'customer.subscription.created':
        logger.info(f"Subscription creata: {data.get('id')}")
    
    elif event_type == 'customer.subscription.deleted':
        logger.info(f"Subscription cancellata: {data.get('id')}")
    
    return HttpResponse(status=200)


# ─── Webhook Telegram ─────────────────────────────────────────────────────────

TELEGRAM_COMANDI = {
    '/start': 'Benvenuto! Sono il bot di RistoBAR. Usa /aiuto per vedere tutti i comandi.',
    '/aiuto': (
        "*Comandi disponibili:*\n\n"
        "📋 *Clienti:*\n"
        "/menu - Visualizza il menu del giorno\n"
        "/prenota - Prenota un tavolo\n"
        "/prenotazioni - Le tue prenotazioni\n\n"
        "👨‍🍳 *Staff:*\n"
        "/ordini - Visualizza ordini attivi\n"
        "/cucina - Visualizza ordini in cucina\n"
    ),
    '/menu': lambda: genera_menu_telegram(),
    '/prenota': (
        "Per prenotare un tavolo clicca sul pulsante qui sotto oppure vai su:\n"
        "[Prenota tavolo](https://ristobar.it/prenota/1/1)\n\n"
        "Oppure invia i dettagli:\n"
        "• Nome\n"
        "• Numero persone\n"
        "• Data e ora\n"
        "• Numero tavolo (opzionale)"
    ),
    '/ordini': lambda: genera_ordini_telegram(),
    '/cucina': lambda: genera_ordini_cucina_telegram(),
}


@csrf_exempt
@require_POST
def telegram_webhook(request):
    try:
        data = json.loads(request.body)
        
        callback_query = data.get('callback_query')
        if callback_query:
            return handle_callback_query(callback_query)
        
        message = data.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', ''))
        testo = message.get('text', '').strip()
        
        risposta = gestisci_messaggio_telegram(chat_id, testo)
        if risposta:
            invia_messaggio_telegram(chat_id, risposta)
    except Exception:
        pass
    return HttpResponse(status=200)


def handle_callback_query(callback_query):
    from django.utils import timezone
    chat_id = str(callback_query.get('message', {}).get('chat', {}).get('id', ''))
    data = callback_query.get('data', '')
    
    if data.startswith('conferma_prenotazione_'):
        Prenotazione.objects.filter(pk=int(data.split('_')[-1])).update(
            stato=Prenotazione.STATO_CONFERMATA
        )
        invia_messaggio_telegram(chat_id, "✅ Prenotazione confermata!")
    
    rispondi_callback(callback_query.get('id'), '')
    return HttpResponse(status=200)


def rispondi_callback(callback_id, testo):
    import requests
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    requests.post(url, json={'callback_query_id': callback_id, 'text': testo})


def gestisci_messaggio_telegram(chat_id, testo):
    testo_lower = testo.lower().strip()
    
    if testo_lower in TELEGRAM_COMANDI:
        cmd = TELEGRAM_COMANDI[testo_lower]
        if callable(cmd):
            return cmd()
        return cmd
    
    for cmd in TELEGRAM_COMANDI:
        if cmd in testo_lower:
            return TELEGRAM_COMANDI[cmd]
    
    if 'prenota' in testo_lower:
        return TELEGRAM_COMANDI['/prenota']
    
    return "Usa /aiuto per vedere i comandi disponibili."


def genera_menu_telegram():
    try:
        categorie = Categoria.objects.prefetch_related('piatti').all()
        if not categorie:
            return "Menu non disponibile al momento."
        
        menu = "*🍽️ Menu del Giorno*\n\n"
        for cat in categorie:
            piatti = cat.piatto_set.all()
            if piatti:
                menu += f"*{cat.nome}*\n"
                for piatto in piatti:
                    prezzo = f"€{piatto.prezzo:.2f}" if piatto.prezzo else ""
                    menu += f"• {piatto.nome} {prezzo}\n"
                menu += "\n"
        return menu
    except Exception:
        return "Errore nel recupero del menu."


def genera_ordini_telegram():
    try:
        from django.utils import timezone
        ordini = Ordine.objects.filter(
            stato__in=[Ordine.STATO_IN_ATTESA, Ordine.STATO_IN_CUCINA]
        ).select_related('tavolo').prefetch_related('items__piatto')[:10]
        
        if not ordini:
            return "Nessun ordine attivo."
        
        msg = "*📋 Ordini Attivi*\n\n"
        for ordine in ordini:
            msg += f"Tavolo {ordine.tavolo.numero} - {ordine.get_stato_display()}\n"
            for item in ordine.items.all():
                msg += f"  • {item.piatto.nome} x{item.quantita}\n"
            msg += "\n"
        return msg
    except Exception:
        return "Errore nel recupero ordini."


def genera_ordini_cucina_telegram():
    try:
        from django.utils import timezone
        items = OrdineItem.objects.filter(
            stato__in=[OrdineItem.STATO_IN_CUCINA, OrdineItem.STATO_IN_ATTESA]
        ).select_related('ordine__tavolo', 'piatto').order_by('ordine__data_creazione')[:15]
        
        if not items:
            return "Nessun ordine in cucina."
        
        msg = "*👨‍🍳 Cucina - Ordini*\n\n"
        current_ordine = None
        for item in items:
            if current_ordine != item.ordine_id:
                current_ordine = item.ordine_id
                msg += f"--- Tavolo {item.ordine.tavolo.numero} ---\n"
            stato_emoji = "⏳" if item.stato == OrdineItem.STATO_IN_ATTESA else "🔥"
            msg += f"{stato_emoji} {item.piatto.nome} x{item.quantita}\n"
        return msg
    except Exception:
        return "Errore nel recupero cucina."


def invia_messaggio_telegram(chat_id, testo, inline_keyboard=None):
    import requests
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    payload = {
        'chat_id': chat_id,
        'text': testo,
        'parse_mode': 'Markdown',
    }
    if inline_keyboard:
        payload['reply_markup'] = json.dumps({'inline_keyboard': inline_keyboard})
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)


# ─── API per dispositivi STM32 (display e-paper) ─────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_stato_tavolo(request, sala_id, numero_tavolo):
    """
    API leggera per l'Hub STM32.
    Risponde con JSON compresso per minimizzare il consumo radio BLE.
    """
    try:
        tavolo = Tavolo.objects.get(sala_id=sala_id, numero=numero_tavolo)
        prenotazione_attiva = tavolo.prenotazioni.filter(
            stato=Prenotazione.STATO_CONFERMATA,
            data_ora__date=timezone.now().date()
        ).first()
        return Response({
            't': tavolo.numero,
            's': tavolo.stato,
            'n': prenotazione_attiva.nome_cliente if prenotazione_attiva else '',
            'p': prenotazione_attiva.num_persone if prenotazione_attiva else 0,
            'h': prenotazione_attiva.data_ora.strftime('%H:%M') if prenotazione_attiva else '',
        })
    except Tavolo.DoesNotExist:
        return Response({'errore': 'Tavolo non trovato'}, status=404)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_sala_completa(request, sala_id):
    """Tutti i tavoli della sala per aggiornamento bulk dell'Hub."""
    tavoli = Tavolo.objects.filter(sala_id=sala_id, attivo=True)
    return Response([
        {
            't': t.numero,
            's': t.stato,
            'f': t.forma,
            'c': t.capacita,
        }
        for t in tavoli
    ])


# ─── API per ESP32 (display e-ink WiFi) ───────────────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_esp32_tavolo(request, sala_id, numero_tavolo):
    """
    API per display e-ink ESP32 via WiFi.
    Più verbose di quella STM32 per sfruttare la memoria disponibile.
    """
    try:
        tavolo = Tavolo.objects.get(sala_id=sala_id, numero=numero_tavolo)
        sala = tavolo.sala
        
        prenotazione_attiva = tavolo.prenotazioni.filter(
            stato=Prenotazione.STATO_CONFERMATA,
            data_ora__date=timezone.now().date()
        ).first()
        
        ordine_attivo = tavolo.ordini.filter(
            stato__in=[Ordine.STATO_IN_ATTESA, Ordine.STATO_IN_CUCINA]
        ).prefetch_related('items__piatto').first()
        
        items = []
        if ordine_attivo:
            for item in ordine_attivo.items.all():
                items.append({
                    'n': item.piatto.nome[:20],
                    'q': item.quantita,
                    's': item.stato,
                })
        
        stato_testi = {
            'L': 'LIBERO',
            'P': 'PRENOTATO',
            'O': 'OCCUPATO',
            'C': 'CONTO',
        }
        
        return Response({
            'tavolo': tavolo.numero,
            'sala': sala.nome[:15],
            'stato': tavolo.stato,
            'stato_testo': stato_testi.get(tavolo.stato, '?'),
            'posti': tavolo.capacita,
            'prenotato': {
                'nome': prenotazione_attiva.nome_cliente[:20] if prenotazione_attiva else '',
                'persone': prenotazione_attiva.num_persone if prenotazione_attiva else 0,
                'ora': prenotazione_attiva.data_ora.strftime('%H:%M') if prenotazione_attiva else '',
            } if prenotazione_attiva else None,
            'ordine': {
                'id': ordine_attivo.id,
                'items': items,
                'note': ordine_attivo.note[:50] if ordine_attivo.note else '',
            } if ordine_attivo else None,
            'timestamp': timezone.now().isoformat(),
        })
    except Tavolo.DoesNotExist:
        return Response({'errore': 'Tavolo non trovato'}, status=404)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_esp32_sala(request, sala_id):
    """
    API bulk per ESP32 - tutti i tavoli della sala.
    Ideale per dashboard e-ink multipli.
    """
    try:
        sala = Sala.objects.get(pk=sala_id)
        tavoli = Tavolo.objects.filter(sala=sala, attivo=True).prefetch_related(
            'prenotazioni',
            'ordini'
        )
        
        stati = {'L': 'Libero', 'P': 'Prenotato', 'O': 'Occupato', 'C': 'Conto'}
        
        return Response({
            'sala': sala.nome,
            'tavoli': [
                {
                    'numero': t.numero,
                    'stato': t.stato,
                    'stato_testo': stati.get(t.stato, '?'),
                    'posti': t.capacita,
                    'prenotato': t.prenotazioni.filter(
                        stato=Prenotazione.STATO_CONFERMATA,
                        data_ora__date=timezone.now().date()
                    ).exists(),
                    'ordine_attivo': t.ordini.filter(
                        stato__in=[Ordine.STATO_IN_ATTESA, Ordine.STATO_IN_CUCINA]
                    ).exists(),
                }
                for t in tavoli
            ],
            'timestamp': timezone.now().isoformat(),
        })
    except Sala.DoesNotExist:
        return Response({'errore': 'Sala non trovata'}, status=404)


# ─── Editor sala (drag & drop / unione tavoli) ────────────────────────────────

@login_required
def editor_sala(request, sala_id):
    """Editor visivo della planimetria: drag, unione, aggiunta/modifica tavoli."""
    sala = get_object_or_404(Sala, pk=sala_id)
    tavoli = list(sala.tavoli.filter(attivo=True).values(
        'id', 'numero', 'forma', 'capacita', 'stato', 'pos_x', 'pos_y'
    ))
    # Carica SVG sfondo se presente
    svg_content = ''
    if sala.svg_sfondo:
        try:
            svg_content = sala.svg_sfondo.read().decode('utf-8')
        except Exception:
            svg_content = ''

    unioni = []
    for u in sala.unioni.filter(attiva=True).prefetch_related('tavoli'):
        unioni.append({
            'id': u.pk,
            'etichetta': u.etichetta,
            'tavoli_ids': list(u.tavoli.values_list('id', flat=True)),
            'capacita_totale': u.capacita_totale,
        })

    return render(request, 'ristorante/editor_sala.html', {
        'sala': sala,
        'tavoli_json': json.dumps(tavoli),
        'unioni_json': json.dumps(unioni),
        'svg_content': svg_content,
    })


@login_required
@require_POST
def salva_layout(request, sala_id):
    """Salva posizioni X/Y di tutti i tavoli dopo drag & drop."""
    sala = get_object_or_404(Sala, pk=sala_id)
    data = json.loads(request.body)
    for item in data.get('tavoli', []):
        Tavolo.objects.filter(pk=item['id'], sala=sala).update(
            pos_x=int(item['x']),
            pos_y=int(item['y']),
        )
    return JsonResponse({'ok': True})


@login_required
@require_POST
def unisci_tavoli(request, sala_id):
    """Crea un'unione tra i tavoli selezionati."""
    sala = get_object_or_404(Sala, pk=sala_id)
    data = json.loads(request.body)
    ids = data.get('ids', [])
    if len(ids) < 2:
        return JsonResponse({'errore': 'Seleziona almeno 2 tavoli.'}, status=400)
    tavoli_qs = Tavolo.objects.filter(pk__in=ids, sala=sala)
    if tavoli_qs.count() != len(ids):
        return JsonResponse({'errore': 'Tavoli non validi.'}, status=400)

    unione = TavoloUnione.objects.create(sala=sala)
    unione.tavoli.set(tavoli_qs)
    unione.save()  # genera etichetta automatica

    return JsonResponse({
        'ok': True,
        'id': unione.pk,
        'etichetta': unione.etichetta,
        'tavoli_ids': list(tavoli_qs.values_list('id', flat=True)),
        'capacita_totale': unione.capacita_totale,
    })


@login_required
@require_POST
def separa_tavoli(request, sala_id):
    """Elimina un'unione di tavoli."""
    sala = get_object_or_404(Sala, pk=sala_id)
    data = json.loads(request.body)
    unione_id = data.get('unione_id')
    TavoloUnione.objects.filter(pk=unione_id, sala=sala).delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def aggiungi_tavolo_editor(request, sala_id):
    """Aggiunge un nuovo tavolo alla sala dall'editor."""
    sala = get_object_or_404(Sala, pk=sala_id)
    data = json.loads(request.body)
    numero = data.get('numero')
    if Tavolo.objects.filter(sala=sala, numero=numero).exists():
        return JsonResponse({'errore': f'Tavolo {numero} già esistente.'}, status=400)
    tavolo = Tavolo(
        sala=sala,
        numero=numero,
        forma=data.get('forma', Tavolo.FORMA_QUADRATO),
        capacita=int(data.get('capacita', 4)),
        pos_x=int(data.get('x', 100)),
        pos_y=int(data.get('y', 100)),
    )
    tavolo.save()
    return JsonResponse({
        'ok': True,
        'id': tavolo.pk,
        'numero': tavolo.numero,
        'forma': tavolo.forma,
        'capacita': tavolo.capacita,
        'pos_x': tavolo.pos_x,
        'pos_y': tavolo.pos_y,
        'stato': tavolo.stato,
    })


@login_required
@require_POST
def modifica_tavolo_editor(request, sala_id, tavolo_id):
    """Modifica proprietà di un tavolo dall'editor."""
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id, sala_id=sala_id)
    data = json.loads(request.body)
    if 'numero' in data:
        nuovo_num = int(data['numero'])
        if nuovo_num != tavolo.numero and Tavolo.objects.filter(sala_id=sala_id, numero=nuovo_num).exists():
            return JsonResponse({'errore': f'Tavolo {nuovo_num} già esistente.'}, status=400)
        tavolo.numero = nuovo_num
    if 'forma' in data:
        tavolo.forma = data['forma']
    if 'capacita' in data:
        tavolo.capacita = int(data['capacita'])
    tavolo.save()
    return JsonResponse({'ok': True, 'numero': tavolo.numero, 'forma': tavolo.forma, 'capacita': tavolo.capacita})


@login_required
@require_POST
def elimina_tavolo_editor(request, sala_id, tavolo_id):
    """Elimina (disattiva) un tavolo dall'editor."""
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id, sala_id=sala_id)
    tavolo.attivo = False
    tavolo.save(update_fields=['attivo'])
    return JsonResponse({'ok': True})


# ─── Vetrina pubblica ─────────────────────────────────────────────────────────

def vetrina(request):
    """Pagina pubblica del ristorante: info, menu, prenotazione."""
    categorie = Categoria.objects.prefetch_related('piatti').all()
    return render(request, 'ristorante/vetrina.html', {'categorie': categorie})


# ─── API REST standard ─────────────────────────────────────────────────────────

class TavoloViewSet(viewsets.ModelViewSet):
    queryset = Tavolo.objects.all()
    serializer_class = TavoloSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class PrenotazioneViewSet(viewsets.ModelViewSet):
    queryset = Prenotazione.objects.all()
    serializer_class = PrenotazioneSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class OrdineViewSet(viewsets.ModelViewSet):
    queryset = Ordine.objects.all()
    serializer_class = OrdineSerializer
    permission_classes = [permissions.IsAuthenticated]


class PiattoViewSet(viewsets.ModelViewSet):
    queryset = Piatto.objects.filter(disponibile=True)
    serializer_class = PiattoSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


# ─── Lista Spesa Cuochi ──────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def lista_spesa(request):
    """Aggrega le voci ordinate in un intervallo di date per creare la lista spesa."""
    oggi = date.today()
    data_da_str = request.GET.get('da', str(oggi))
    data_a_str  = request.GET.get('a',  str(oggi + timedelta(days=1)))

    try:
        data_da = date.fromisoformat(data_da_str)
        data_a  = date.fromisoformat(data_a_str)
    except ValueError:
        data_da = oggi
        data_a  = oggi + timedelta(days=1)

    # Aggrega OrdineItem per piatto nel periodo selezionato
    voci = (
        OrdineItem.objects
        .filter(ordine__creato_il__date__range=[data_da, data_a])
        .values(
            'piatto__id',
            'piatto__nome',
            'piatto__ingredienti',
            'piatto__categoria__nome',
            'piatto__categoria__icona',
            'piatto__categoria__ordine',
        )
        .annotate(totale_qty=Sum('quantita'))
        .order_by('piatto__categoria__ordine', 'piatto__nome')
    )

    # Raggruppa per categoria
    categorie_spesa = {}
    for v in voci:
        cat_nome = v['piatto__categoria__nome']
        if cat_nome not in categorie_spesa:
            categorie_spesa[cat_nome] = {
                'icona': v['piatto__categoria__icona'],
                'voci': [],
            }
        categorie_spesa[cat_nome]['voci'].append(v)

    # Recupera email di invio dal settings (fallback)
    email_default = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ristobar.it')

    return render(request, 'sala/lista_spesa.html', {
        'categorie_spesa': categorie_spesa,
        'data_da': data_da,
        'data_a': data_a,
        'totale_voci': voci.count(),
        'email_default': email_default,
    })


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
@require_POST
def invia_lista_spesa_email(request):
    """Invia la lista spesa via email a un indirizzo specificato."""
    destinatario = request.POST.get('email', '').strip()
    data_da_str  = request.POST.get('da', str(date.today()))
    data_a_str   = request.POST.get('a',  str(date.today() + timedelta(days=1)))

    if not destinatario:
        return JsonResponse({'ok': False, 'errore': 'Inserisci un indirizzo email.'})

    try:
        data_da = date.fromisoformat(data_da_str)
        data_a  = date.fromisoformat(data_a_str)
    except ValueError:
        data_da = date.today()
        data_a  = date.today() + timedelta(days=1)

    voci = (
        OrdineItem.objects
        .filter(ordine__creato_il__date__range=[data_da, data_a])
        .values(
            'piatto__nome', 'piatto__ingredienti',
            'piatto__categoria__nome', 'piatto__categoria__icona',
            'piatto__categoria__ordine',
        )
        .annotate(totale_qty=Sum('quantita'))
        .order_by('piatto__categoria__ordine', 'piatto__nome')
    )

    categorie_spesa = {}
    for v in voci:
        cat_nome = v['piatto__categoria__nome']
        if cat_nome not in categorie_spesa:
            categorie_spesa[cat_nome] = {'icona': v['piatto__categoria__icona'], 'voci': []}
        categorie_spesa[cat_nome]['voci'].append(v)

    corpo_html = render_to_string('sala/lista_spesa_email.html', {
        'categorie_spesa': categorie_spesa,
        'data_da': data_da,
        'data_a': data_a,
        'totale_voci': voci.count(),
    })
    corpo_txt = '\n'.join(
        f"{v['piatto__categoria__nome']} — {v['piatto__nome']}: {v['totale_qty']} pz"
        for v in voci
    )

    try:
        send_mail(
            subject=f'📋 Lista Spesa RistoBAR — {data_da.strftime("%d/%m")} / {data_a.strftime("%d/%m")}',
            message=corpo_txt,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destinatario],
            html_message=corpo_html,
            fail_silently=False,
        )
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'errore': str(e)})


# ─── ePrint Gestione ─────────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def gestione_eprint(request):
    """Sezione di configurazione ePrint: assegna email stampante a ogni tavolo."""
    sale = Sala.objects.prefetch_related('tavoli').filter(attiva=True)
    messaggio = None

    if request.method == 'POST':
        for key, val in request.POST.items():
            if key.startswith('eprint_'):
                try:
                    tavolo_id = int(key.split('_')[1])
                    Tavolo.objects.filter(pk=tavolo_id).update(eprint_email=val.strip())
                except (ValueError, IndexError):
                    pass
        messaggio = 'Configurazione ePrint salvata.'

    return render(request, 'sala/gestione_eprint.html', {
        'sale': sale,
        'messaggio': messaggio,
    })


@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
@require_POST
def eprint_ordine(request, ordine_id):
    """Invia l'ordine/comanda via email alla stampante ePrint del tavolo."""
    ordine = get_object_or_404(Ordine, pk=ordine_id)
    tavolo = ordine.tavolo

    if not tavolo.eprint_email:
        return JsonResponse({'ok': False, 'errore': f'Nessuna stampante ePrint configurata per il Tavolo {tavolo.numero}.'})

    corpo_html = render_to_string('sala/eprint_ordine.html', {'ordine': ordine, 'tavolo': tavolo})
    corpo_txt  = (
        f"COMANDA — Tavolo {tavolo.numero}\n"
        f"Ordine #{ordine.pk} — {ordine.creato_il.strftime('%d/%m/%Y %H:%M')}\n\n"
    )
    for item in ordine.items.all():
        corpo_txt += f"  {item.quantita}x {item.piatto.nome}  €{item.subtotale}\n"
    corpo_txt += f"\nTOTALE: €{ordine.totale}"

    try:
        send_mail(
            subject=f'Comanda Tavolo {tavolo.numero} — #{ordine.pk}',
            message=corpo_txt,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[tavolo.eprint_email],
            html_message=corpo_html,
            fail_silently=False,
        )
        return JsonResponse({'ok': True, 'stampante': tavolo.eprint_email})
    except Exception as e:
        return JsonResponse({'ok': False, 'errore': str(e)})


# ─── Gestione Contatti ───────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def gestione_contatti(request):
    """Rubrica contatti: ristorante principale + tutte le sedi."""
    imp   = ImpostazioniRistorante.get()
    sedi  = Sede.objects.filter(ristorante=imp).prefetch_related('contatti')
    tipi  = Contatto.TIPO_CHOICES

    errore  = None
    ok_msg  = None

    if request.method == 'POST':
        azione = request.POST.get('azione')

        if azione == 'aggiungi':
            tipo       = request.POST.get('tipo', Contatto.TEL)
            valore     = request.POST.get('valore', '').strip()
            etichetta  = request.POST.get('etichetta', '').strip()
            sede_id    = request.POST.get('sede_id', '').strip()
            principale = bool(request.POST.get('principale'))
            pubblico   = bool(request.POST.get('pubblico', True))
            ordine     = int(request.POST.get('ordine', 10) or 10)

            if not valore:
                errore = 'Il campo valore è obbligatorio.'
            else:
                kwargs = dict(
                    tipo=tipo, valore=valore, etichetta=etichetta,
                    principale=principale, pubblico=pubblico, ordine=ordine,
                )
                if sede_id:
                    kwargs['sede'] = get_object_or_404(Sede, pk=sede_id, ristorante=imp)
                else:
                    kwargs['ristorante'] = imp
                Contatto.objects.create(**kwargs)
                ok_msg = 'Contatto aggiunto.'

        elif azione == 'elimina':
            cid = request.POST.get('contatto_id')
            Contatto.objects.filter(
                pk=cid
            ).filter(
                models.Q(ristorante=imp) | models.Q(sede__ristorante=imp)
            ).delete()
            ok_msg = 'Contatto eliminato.'

        elif azione == 'toggle_pubblico':
            cid = request.POST.get('contatto_id')
            c = Contatto.objects.filter(
                pk=cid
            ).filter(
                models.Q(ristorante=imp) | models.Q(sede__ristorante=imp)
            ).first()
            if c:
                c.pubblico = not c.pubblico
                c.save(update_fields=['pubblico'])
            return JsonResponse({'ok': True, 'pubblico': c.pubblico if c else False})

        elif azione == 'aggiorna_ordine':
            # AJAX: [{id, ordine}, ...]
            data = json.loads(request.body)
            for row in data:
                Contatto.objects.filter(
                    pk=row['id']
                ).filter(
                    models.Q(ristorante=imp) | models.Q(sede__ristorante=imp)
                ).update(ordine=row['ordine'])
            return JsonResponse({'ok': True})

    # Raggruppa contatti: ristorante principale + per sede
    contatti_ristorante = Contatto.objects.filter(ristorante=imp).order_by('ordine', 'tipo')
    contatti_per_sede   = {
        s.pk: Contatto.objects.filter(sede=s).order_by('ordine', 'tipo')
        for s in sedi
    }

    return render(request, 'sala/gestione_contatti.html', {
        'imp': imp,
        'sedi': sedi,
        'tipi': tipi,
        'contatti_ristorante': contatti_ristorante,
        'contatti_per_sede': contatti_per_sede,
        'errore': errore,
        'ok_msg': ok_msg,
    })


# ─── Impostazioni ristorante ─────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def impostazioni_ristorante(request):
    """Form per i dati fiscali del ristorante (usati in scontrini e fatture)."""
    imp = ImpostazioniRistorante.get()
    messaggio = None
    if request.method == 'POST':
        campi = [
            'nome', 'slogan', 'indirizzo', 'cap', 'citta', 'provincia',
            'telefono', 'email', 'sito', 'piva', 'cf', 'regime_fiscale',
            'iban', 'note_scontrino', 'note_fattura',
        ]
        for c in campi:
            setattr(imp, c, request.POST.get(c, '').strip())
        if 'logo' in request.FILES:
            imp.logo = request.FILES['logo']
        imp.save()
        messaggio = 'Impostazioni salvate.'
    return render(request, 'sala/impostazioni_ristorante.html', {'imp': imp, 'messaggio': messaggio})


# ─── Scontrino ───────────────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def scontrino_view(request, ordine_id):
    """Genera e mostra lo scontrino di cortesia per un ordine."""
    ordine = get_object_or_404(Ordine, pk=ordine_id)
    imp    = ImpostazioniRistorante.get()

    # Crea (o recupera) il documento scontrino per questo ordine
    doc, creato = Fattura.objects.get_or_create(
        ordine=ordine,
        tipo=Fattura.TIPO_SCONTRINO,
        defaults={'creata_da': request.user},
    )

    if request.method == 'POST':
        # Invia scontrino via email
        dest = request.POST.get('email', '').strip()
        if dest:
            corpo_html = render_to_string('sala/documento_print.html', {
                'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': False,
            })
            try:
                send_mail(
                    subject=f'Scontrino {doc.numero} — {imp.nome}',
                    message=f'Scontrino {doc.numero}\nTotale: €{doc.totale}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[dest],
                    html_message=corpo_html,
                )
                return JsonResponse({'ok': True})
            except Exception as e:
                return JsonResponse({'ok': False, 'errore': str(e)})
        # Stampa via ePrint
        if request.POST.get('eprint') and ordine.tavolo.eprint_email:
            corpo_html = render_to_string('sala/documento_print.html', {
                'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': False,
            })
            try:
                send_mail(
                    subject=f'Scontrino {doc.numero}',
                    message=f'Totale: €{doc.totale}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[ordine.tavolo.eprint_email],
                    html_message=corpo_html,
                )
                return JsonResponse({'ok': True, 'stampante': ordine.tavolo.eprint_email})
            except Exception as e:
                return JsonResponse({'ok': False, 'errore': str(e)})

    return render(request, 'sala/documento_print.html', {
        'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': True,
    })


# ─── Fattura / Ricevuta ───────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def fattura_nuova(request, ordine_id):
    """Form per emettere una fattura o ricevuta intestata a un cliente."""
    ordine = get_object_or_404(Ordine, pk=ordine_id)
    imp    = ImpostazioniRistorante.get()
    errore = None

    if request.method == 'POST':
        tipo = request.POST.get('tipo', Fattura.TIPO_FATTURA)
        doc  = Fattura(ordine=ordine, tipo=tipo, creata_da=request.user)
        doc.cliente_nome      = request.POST.get('cliente_nome', '').strip()
        doc.cliente_indirizzo = request.POST.get('cliente_indirizzo', '').strip()
        doc.cliente_cap       = request.POST.get('cliente_cap', '').strip()
        doc.cliente_citta     = request.POST.get('cliente_citta', '').strip()
        doc.cliente_piva      = request.POST.get('cliente_piva', '').strip()
        doc.cliente_cf        = request.POST.get('cliente_cf', '').strip()
        doc.cliente_email     = request.POST.get('cliente_email', '').strip()
        doc.cliente_pec       = request.POST.get('cliente_pec', '').strip()
        doc.cliente_sdi       = request.POST.get('cliente_sdi', '').strip()
        doc.note              = request.POST.get('note', '').strip()

        if tipo == Fattura.TIPO_FATTURA and not doc.cliente_nome:
            errore = 'Per la fattura è obbligatorio il nome/ragione sociale del cliente.'
        else:
            doc.save()
            return redirect('fattura_print', fattura_id=doc.pk)

    return render(request, 'sala/fattura_form.html', {
        'ordine': ordine, 'imp': imp, 'errore': errore,
    })


@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def fattura_print(request, fattura_id):
    """Stampa o invia via email/ePrint una fattura/ricevuta."""
    doc    = get_object_or_404(Fattura, pk=fattura_id)
    ordine = doc.ordine
    imp    = ImpostazioniRistorante.get()

    if request.method == 'POST':
        dest = request.POST.get('email', '').strip()
        if dest:
            corpo_html = render_to_string('sala/documento_print.html', {
                'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': False,
            })
            try:
                send_mail(
                    subject=f'{doc.get_tipo_display()} {doc.numero} — {imp.nome}',
                    message=f'{doc.get_tipo_display()} {doc.numero}\nTotale: €{doc.totale}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[dest],
                    html_message=corpo_html,
                )
                return JsonResponse({'ok': True})
            except Exception as e:
                return JsonResponse({'ok': False, 'errore': str(e)})
        if request.POST.get('eprint') and ordine.tavolo.eprint_email:
            corpo_html = render_to_string('sala/documento_print.html', {
                'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': False,
            })
            try:
                send_mail(
                    subject=f'{doc.get_tipo_display()} {doc.numero}',
                    message=f'Totale: €{doc.totale}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[ordine.tavolo.eprint_email],
                    html_message=corpo_html,
                )
                return JsonResponse({'ok': True, 'stampante': ordine.tavolo.eprint_email})
            except Exception as e:
                return JsonResponse({'ok': False, 'errore': str(e)})

    return render(request, 'sala/documento_print.html', {
        'doc': doc, 'ordine': ordine, 'imp': imp, 'solo_stampa': True,
    })


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def elenco_documenti(request):
    """Archivio di tutti i documenti fiscali emessi."""
    tipo   = request.GET.get('tipo', '')
    anno   = request.GET.get('anno', str(timezone.now().year))
    qs     = Fattura.objects.select_related('ordine__tavolo', 'creata_da')
    if tipo:
        qs = qs.filter(tipo=tipo)
    if anno:
        qs = qs.filter(data__year=anno)
    return render(request, 'sala/elenco_documenti.html', {
        'documenti': qs[:200],
        'tipo': tipo,
        'anno': anno,
        'anni': range(timezone.now().year, 2024, -1),
    })


# ─── Developer Panel (solo DEBUG) ────────────────────────────────────────────

def dev_panel(request):
    """Pannello sviluppatore: tutte le URL navigabili in un'unica pagina."""
    from django.conf import settings as django_settings
    if not django_settings.DEBUG:
        from django.http import Http404
        raise Http404

    # Recupera dati live dal DB per i link parametrici
    sala1 = Sala.objects.first()
    tavolo1 = Tavolo.objects.filter(attivo=True).first() if sala1 else None
    prenotazione1 = Prenotazione.objects.first()

    ctx = {
        'sala1': sala1,
        'tavolo1': tavolo1,
        'prenotazione1': prenotazione1,
        'n_sale': Sala.objects.count(),
        'n_tavoli': Tavolo.objects.filter(attivo=True).count(),
        'n_piatti': Piatto.objects.count(),
        'n_ordini': Ordine.objects.count(),
        'n_prenotazioni': Prenotazione.objects.count(),
    }
    return render(request, 'dev/panel.html', ctx)
