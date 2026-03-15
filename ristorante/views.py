import json
import stripe
import requests
from decimal import Decimal
from datetime import date, timedelta
from functools import wraps
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.utils import timezone
from django.db.models import Sum, Q, Prefetch
from django.db import models
from django.core.mail import send_mail
from django.template.loader import render_to_string
from rest_framework import viewsets, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import (
    Sala, Tavolo, TavoloUnione, Categoria, Piatto, Prenotazione, Ordine, OrdineItem,
    Fattura, ImpostazioniRistorante, Sede, Contatto, Dispositivo,
    ListaSpesaGenerata, CiboRimasto, CouponSconto, ProdottoMagazzino,
    Promemoria, ReportPeriodico,
)
from .serializers import (
    TavoloSerializer, PrenotazioneSerializer,
    OrdineSerializer, PiattoSerializer
)

stripe.api_key = settings.STRIPE_SECRET_KEY


# ─── Helpers ruoli ────────────────────────────────────────────────────────────

RUOLO_CAMERIERE         = 'cameriere'
RUOLO_CAMERIERE_SENIOR  = 'cameriere_senior'   # cameriere + accesso cassa
RUOLO_CUOCO             = 'cuoco'
RUOLO_CAPO_AREA         = 'capo_area'
RUOLO_TITOLARE          = 'titolare'

# Shortcut: tutti i ruoli di sala (usato nei decoratori interni)
_RUOLI_CAPO = (RUOLO_CAPO_AREA, RUOLO_TITOLARE)

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
    if ha_ruolo(u, RUOLO_CAMERIERE, RUOLO_CAMERIERE_SENIOR):
        return redirect('cameriere')
    if ha_ruolo(u, RUOLO_CUOCO):
        return redirect('cucina_kds')
    # Fallback: dashboard base
    return redirect('dashboard')


# ─── Dashboard capo area / titolare ──────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def dashboard(request):
    from django.db.models import Count
    sale_qs = Sala.objects.filter(attiva=True).prefetch_related(
        Prefetch('tavoli', queryset=Tavolo.objects.filter(attivo=True).order_by('numero'))
    )
    prenotazioni_oggi = Prenotazione.objects.filter(
        data_ora__date=timezone.now().date(),
        stato__in=[Prenotazione.STATO_ATTESA, Prenotazione.STATO_CONFERMATA]
    ).order_by('data_ora')
    ordini_aperti = Ordine.objects.filter(
        stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
    ).select_related('tavolo')

    # Stats globali
    tutti_tavoli = Tavolo.objects.filter(attivo=True)
    stats = {
        'liberi':    tutti_tavoli.filter(stato=Tavolo.STATO_LIBERO).count(),
        'occupati':  tutti_tavoli.filter(stato=Tavolo.STATO_OCCUPATO).count(),
        'prenotati': tutti_tavoli.filter(stato=Tavolo.STATO_PRENOTATO).count(),
        'conto':     tutti_tavoli.filter(stato=Tavolo.STATO_CONTO).count(),
        'totale':    tutti_tavoli.count(),
    }

    # Tutti i tavoli attivi serializzati per il JS (usato dal modal "sposta")
    tutti_tavoli_js = list(
        Tavolo.objects.filter(attivo=True)
        .select_related('sala')
        .order_by('sala__nome', 'numero')
        .values('id', 'numero', 'stato', 'capacita', 'sala__nome', 'sala_id')
    )

    return render(request, 'ristorante/dashboard.html', {
        'sale': sale_qs,
        'prenotazioni_oggi': prenotazioni_oggi,
        'ordini_aperti': ordini_aperti,
        'stats': stats,
        'tutti_tavoli_js': tutti_tavoli_js,
        'FORMA_ROTONDO':    Tavolo.FORMA_ROTONDO,
        'FORMA_QUADRATO':   Tavolo.FORMA_QUADRATO,
        'FORMA_RETTANGOLO': Tavolo.FORMA_RETTANGOLO,
    })


# ─── Mappa tavoli (vista sala) ───────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def pianta_locale(request, sala_id):
    """Pianta interattiva del locale: vista tavoli per area/piano."""
    sala = get_object_or_404(Sala, pk=sala_id, attiva=True)

    # Modifica info sala (solo capo/titolare)
    if request.method == 'POST' and request.POST.get('azione') == 'modifica_info':
        if not ha_ruolo(request.user, RUOLO_CAPO_AREA, RUOLO_TITOLARE):
            return JsonResponse({'errore': 'Non autorizzato'}, status=403)
        sala.nome = request.POST.get('nome', sala.nome).strip() or sala.nome
        sala.tipo_locale = request.POST.get('tipo_locale', sala.tipo_locale)
        piano_str = request.POST.get('piano', '').strip()
        sala.piano = int(piano_str) if piano_str.lstrip('-').isdigit() else sala.piano
        sala.nazione = request.POST.get('nazione', sala.nazione).strip()
        sala.citta = request.POST.get('citta', sala.citta).strip()
        sala.indirizzo = request.POST.get('indirizzo', sala.indirizzo).strip()
        sala.descrizione = request.POST.get('descrizione', sala.descrizione).strip()
        sala.save()
        return redirect('pianta_locale', sala_id=sala.pk)

    tavoli = sala.tavoli.filter(attivo=True).order_by('numero')
    tutte_sale = Sala.objects.filter(attiva=True).order_by('nome')
    tavoli_js = list(tavoli.values(
        'id', 'numero', 'forma', 'capacita', 'stato', 'pos_x', 'pos_y'
    ))
    stats = {
        'liberi':    tavoli.filter(stato=Tavolo.STATO_LIBERO).count(),
        'occupati':  tavoli.filter(stato=Tavolo.STATO_OCCUPATO).count(),
        'prenotati': tavoli.filter(stato=Tavolo.STATO_PRENOTATO).count(),
        'conto':     tavoli.filter(stato=Tavolo.STATO_CONTO).count(),
        'totale':    tavoli.count(),
        'posti':     sum(t.capacita for t in tavoli),
    }
    return render(request, 'ristorante/pianta_locale.html', {
        'sala': sala,
        'tavoli': tavoli,
        'tavoli_js': tavoli_js,
        'tutte_sale': tutte_sale,
        'stats': stats,
        'ha_cassa': ha_ruolo(request.user, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE),
        'is_capo': ha_ruolo(request.user, RUOLO_CAPO_AREA, RUOLO_TITOLARE),
    })


# ─── Interfaccia Cameriere ────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
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


@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
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
            if not ha_ruolo(request.user, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE):
                return JsonResponse({'errore': 'Accesso non autorizzato'}, status=403)
            tavolo.stato = Tavolo.STATO_CONTO
            tavolo.save(update_fields=['stato'])
            return JsonResponse({'ok': True})

    ha_cassa = ha_ruolo(request.user, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
    return render(request, 'sala/ordine.html', {
        'tavolo': tavolo,
        'ordine': ordine_aperto,
        'categorie': categorie,
        'ha_cassa': ha_cassa,
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


@ruolo_richiesto(RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
@require_POST
def sposta_tavolo(request, tavolo_id):
    """
    Trasferisce tutti gli ordini e prenotazioni attive dal tavolo sorgente
    a un tavolo di destinazione. Il tavolo sorgente torna Libero.
    """
    tavolo_src = get_object_or_404(Tavolo, pk=tavolo_id)
    data = json.loads(request.body)
    dest_id = data.get('dest_id')
    if not dest_id:
        return JsonResponse({'errore': 'Tavolo di destinazione mancante'}, status=400)

    tavolo_dst = get_object_or_404(Tavolo, pk=dest_id)
    if tavolo_dst.pk == tavolo_src.pk:
        return JsonResponse({'errore': 'Sorgente e destinazione coincidono'}, status=400)
    if tavolo_dst.stato != Tavolo.STATO_LIBERO:
        return JsonResponse({'errore': f'Il tavolo {tavolo_dst.numero} non è libero'}, status=400)

    # Sposta ordini aperti
    ordini = tavolo_src.ordini.filter(
        stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
    )
    ordini.update(tavolo=tavolo_dst)

    # Sposta prenotazioni attive di oggi
    from django.utils import timezone as tz
    Prenotazione.objects.filter(
        tavolo=tavolo_src,
        data_ora__date=tz.now().date(),
        stato__in=[Prenotazione.STATO_ATTESA, Prenotazione.STATO_CONFERMATA],
    ).update(tavolo=tavolo_dst)

    # Aggiorna stati: destinazione eredita lo stato della sorgente, sorgente → Libero
    tavolo_dst.stato = tavolo_src.stato
    tavolo_src.stato = Tavolo.STATO_LIBERO
    tavolo_dst.save(update_fields=['stato'])
    tavolo_src.save(update_fields=['stato'])

    return JsonResponse({
        'ok': True,
        'src_numero':  tavolo_src.numero,
        'dst_numero':  tavolo_dst.numero,
        'dst_stato':   tavolo_dst.stato,
    })


# ─── Menu cliente (via QR) ───────────────────────────────────────────────────

def menu_tavolo(request, tavolo_id):
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id, attivo=True)
    categorie = Categoria.objects.prefetch_related('piatti').all()
    return render(request, 'ristorante/menu_tavolo.html', {
        'sala': tavolo.sala,
        'tavolo': tavolo,
        'categorie': categorie,
    })


def menu_eink(request, tavolo_id):
    """
    Pagina menu ultra-minimale per display e-ink (ESP32, STM32).
    Niente CSS pesante, niente immagini, solo testo e struttura.
    Ottimizzata per schermi piccoli in bianco/nero con poca memoria.
    """
    tavolo = get_object_or_404(Tavolo, pk=tavolo_id, attivo=True)
    sala = tavolo.sala
    categorie = Categoria.objects.prefetch_related(
        models.Prefetch('piatti', queryset=Piatto.objects.filter(disponibile=True))
    ).all()
    imp = ImpostazioniRistorante.get()
    return render(request, 'ristorante/menu_eink.html', {
        'sala': sala,
        'tavolo': tavolo,
        'categorie': categorie,
        'imp': imp,
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

def _telegram_comandi():
    imp = ImpostazioniRistorante.get()
    nome = imp.nome if imp else 'RistoBAR'
    sito = imp.sito if imp else ''
    prenota_url = f"{sito}/prenota/" if sito else "/prenota/"
    return {
        '/start': f'Benvenuto! Sono il bot di *{nome}*. Usa /aiuto per vedere tutti i comandi.',
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
            f"Per prenotare un tavolo da *{nome}* clicca sul link oppure vai su:\n"
            f"[Prenota tavolo]({prenota_url})\n\n"
            "Oppure invia i dettagli:\n"
            "• Nome\n"
            "• Numero persone\n"
            "• Data e ora\n"
            "• Numero tavolo (opzionale)"
        ),
        '/ordini': lambda: genera_ordini_telegram(),
        '/cucina': lambda: genera_ordini_cucina_telegram(),
    }

TELEGRAM_COMANDI = _telegram_comandi  # callable — valutato ad ogni richiesta


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
    if '@' in testo:
        testo = testo.split('@')[0]
    testo_lower = testo.lower().strip()
    
    comandi = TELEGRAM_COMANDI()
    if testo_lower in comandi:
        cmd = comandi[testo_lower]
        if callable(cmd):
            return cmd()
        return cmd

    for cmd in comandi:
        if cmd in testo_lower:
            return comandi[cmd]

    if 'prenota' in testo_lower:
        return comandi['/prenota']
    
    return "Usa /aiuto per vedere i comandi disponibili."


def genera_menu_telegram():
    try:
        categorie = Categoria.objects.prefetch_related('piatti').all()
        if not categorie:
            return "Menu non disponibile al momento."
        
        menu = "*🍽️ Menu del Giorno*\n\n"
        for cat in categorie:
            piatti = cat.piatto.all()  # Usa related_name 'piatti' dal modello
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
            stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
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
            stato__in=[OrdineItem.STATO_IN_CUCINA, OrdineItem.STATO_ATTESA]
        ).select_related('ordine__tavolo', 'piatto').order_by('ordine__creato_il')[:15]
        
        if not items:
            return "Nessun ordine in cucina."
        
        msg = "*👨‍🍳 Cucina - Ordini*\n\n"
        current_ordine = None
        for item in items:
            if current_ordine != item.ordine_id:
                current_ordine = item.ordine_id
                msg += f"--- Tavolo {item.ordine.tavolo.numero} ---\n"
            stato_emoji = "⏳" if item.stato == OrdineItem.STATO_ATTESA else "🔥"
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


# ─── WhatsApp Business ───────────────────────────────────────────────────────

def invia_whatsapp(messaggio, destinatario, template=None):
    """
    Invia messaggio WhatsApp usando WhatsApp Cloud API.
    """
    imp = ImpostazioniRistorante.get()
    
    if not imp.whatsapp_enabled or not imp.whatsapp_token:
        return False, "WhatsApp non configurato"
    
    url = f"https://graph.facebook.com/v18.0/{imp.whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {imp.whatsapp_token}",
        "Content-Type": "application/json"
    }
    
    try:
        if template:
            payload = {
                "messaging_product": "whatsapp",
                "to": destinatario,
                "type": "template",
                "template": template
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": destinatario,
                "type": "text",
                "text": {"body": messaggio}
            }
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code in [200, 201]:
            return True, response.json()
        return False, response.text
    except Exception as e:
        return False, str(e)


def whatsapp_webhook(request):
    """
    Webhook per WhatsApp Cloud API.
    Riceve messaggi dai clienti e gestisce prenotazioni/richieste.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        data = json.loads(request.body)
        entry = data.get('entry', [])
        if not entry:
            return HttpResponse(status=200)
        
        changes = entry[0].get('changes', [])
        if not changes:
            return HttpResponse(status=200)
        
        value = changes[0].get('value', {})
        messages = value.get('messages', [])
        
        if messages:
            msg = messages[0]
            from_id = msg.get('from')
            msg_type = msg.get('type')
            
            if msg_type == 'text':
                testo = msg['text'].get('body', '').strip()
                gestisci_whatsapp_richiesta(from_id, testo)
            elif msg_type == 'interactive':
                button_id = msg.get('interactive', {}).get('button_reply', {}).get('id', '')
                gestisci_whatsapp_callback(from_id, button_id)
                
    except Exception as e:
        logger.error(f"Errore webhook WhatsApp: {e}")
    
    return HttpResponse(status=200)


def gestisci_whatsapp_richiesta(numero, testo):
    """Gestisce messaggio in ingresso da WhatsApp."""
    imp = ImpostazioniRistorante.get()
    
    testo_lower = testo.lower()
    
    if any(x in testo_lower for x in ['ciao', 'buongiorno', 'buonasera', 'menu', 'ciao']):
        menu = genera_menu_telegram()
        invia_whatsapp(f"👋 Ciao da {imp.nome}!\n\n{menu}", numero)
    
    elif any(x in testo_lower for x in ['prenota', 'prenotazione', 'tavolo']):
        invia_whatsapp(
            f"📅 Per prenotare un tavolo, clicca qui:\n{imp.sito}prenota/1/1\n\n"
            f"Oppure chiamaci al {imp.telefono}",
            numero
        )
    
    elif any(x in testo_lower for x in ['ordine', 'conto', 'pagare']):
        invia_whatsapp(
            "Per il conto, puoi chiedere al cameriere oppure scansiona il QR code al tuo tavolo.",
            numero
        )
    
    else:
        invia_whatsapp(
            f"Grazie per il messaggio! 👨‍🍳\n\n"
            f"Per prenotare: {imp.sito}prenota/1/1\n"
            f"Per vedere il menu: {imp.sito}menu/1/1\n\n"
            f"Oppure chiamaci: {imp.telefono}",
            numero
        )


def gestisci_whatsapp_callback(numero, button_id):
    """Gestisce callback da bottoni interattivi WhatsApp."""
    if button_id.startswith('conferma_'):
        prenotazione_id = int(button_id.split('_')[1])
        Prenotazione.objects.filter(pk=prenotazione_id).update(
            stato=Prenotazione.STATO_CONFERMATA
        )
        invia_whatsapp("✅ Prenotazione confermata!", numero)
    
    elif button_id.startswith('rifiuta_'):
        prenotazione_id = int(button_id.split('_')[1])
        Prenotazione.objects.filter(pk=prenotazione_id).update(
            stato=Prenotazione.STATO_ANNULLATA
        )
        invia_whatsapp("❌ Prenotazione annullata.", numero)


# ─── Notifiche unificate (Telegram + WhatsApp) ─────────────────────────────────

def notifica_cliente(canale, destinazione, messaggio, inline_keyboard=None):
    """
    Invia notifica al cliente tramite canale preferito.
    canale: 'telegram' o 'whatsapp'
    """
    if canale == 'telegram':
        try:
            invia_messaggio_telegram(destinazione, messaggio, inline_keyboard)
            return True
        except:
            return False
    elif canale == 'whatsapp':
        return invia_whatsapp(messaggio, destinazione)[0]
    return False


def notifica_prenotazione(prenotazione, evento):
    """
    Invia notifica di prenotazione al cliente.
    evento: 'nuova', 'confermata', 'annullata'
    """
    imp = ImpostazioniRistorante.get()
    
    if evento == 'nuova':
        messaggio = f"📅 Nuova prenotazione!\n\n"
        messaggio += f"👤 Cliente: {prenotazione.nome_cliente}\n"
        messaggio += f"👥 Persone: {prenotazione.num_persone}\n"
        messaggio += f"🕐 Data: {prenotazione.data_ora.strftime('%d/%m/%Y alle %H:%M')}\n"
        if prenotazione.tavolo:
            messaggio += f"🪑 Tavolo: {prenotazione.tavolo.numero}"
        
        keyboard = [
            [{"text": "✅ Conferma", "callback_data": f"conferma_{prenotazione.pk}"},
             {"text": "❌ Rifiuta", "callback_data": f"rifiuta_{prenotazione.pk}"}]
        ]
        
        if imp.telegram_enabled and imp.telegram_bot_token:
            invia_messaggio_telegram(prenotazione.telegram_chat_id, messaggio, keyboard)
        
        if imp.whatsapp_enabled and prenotazione.telefono:
            template = {
                "name": "reservation_confirmation",
                "language": {"code": "it_IT"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "parameter_name": "customer_name", "text": prenotazione.nome_cliente},
                            {"type": "text", "parameter_name": "date", "text": prenotazione.data_ora.strftime('%d/%m/%Y')},
                            {"type": "text", "parameter_name": "time", "text": prenotazione.data_ora.strftime('%H:%M')}
                        ]
                    }
                ]
            }
            invia_whatsapp("", prenotazione.telefono, template)


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
            stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
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
        
        base_url = request.build_absolute_uri('/')[:-1]
        
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
            'nota': tavolo.nota[:100] if tavolo.nota else '',
            'qr_url': f"{base_url}{tavolo.qr_code.url}" if tavolo.qr_code else '',
            'site_url': base_url,
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
        oggi = timezone.now().date()
        sala = Sala.objects.get(pk=sala_id)
        
        # Prefetch con query ottimizzate
        tavoli = Tavolo.objects.filter(sala=sala, attivo=True).prefetch_related(
            Prefetch(
                'prenotazioni',
                queryset=Prenotazione.objects.filter(
                    stato=Prenotazione.STATO_CONFERMATA,
                    data_ora__date=oggi
                )
            ),
            Prefetch(
                'ordini',
                queryset=Ordine.objects.filter(
                    stato__in=[Ordine.STATO_APERTO, Ordine.STATO_IN_PREPARAZIONE]
                )
            )
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
                    'prenotato': t.prenotazioni.exists(),
                    'ordine_attivo': t.ordini.exists(),
                }
                for t in tavoli
            ],
            'timestamp': timezone.now().isoformat(),
        })
    except Sala.DoesNotExist:
        return Response({'errore': 'Sala non trovata'}, status=404)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@require_http_methods(["POST"])
def api_tavolo_nota(request, tavolo_id):
    """
    Imposta la nota di un tavolo per il display e-ink.
    Accesso: cuoco, capo_area, titolare.
    """
    if not ha_ruolo(request.user, RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE):
        return Response({'errore': 'Non autorizzato'}, status=403)
    
    try:
        tavolo = Tavolo.objects.get(pk=tavolo_id)
    except Tavolo.DoesNotExist:
        return Response({'errore': 'Tavolo non trovato'}, status=404)
    
    nota = request.data.get('nota', '')[:200]
    tavolo.nota = nota
    tavolo.save(update_fields=['nota'])
    
    return Response({
        'ok': True,
        'tavolo': tavolo.numero,
        'nota': tavolo.nota,
    })


# ─── Editor sala (drag & drop / unione tavoli) ────────────────────────────────

@login_required
def editor_sala(request, sala_id):
    """Editor visivo della planimetria: drag, unione, aggiunta/modifica tavoli."""
    sala = get_object_or_404(Sala, pk=sala_id)
    tavoli = list(sala.tavoli.filter(attivo=True).values(
        'id', 'numero', 'forma', 'capacita', 'stato', 'pos_x', 'pos_y', 'etichetta'
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
    if 'etichetta' in data:
        tavolo.etichetta = data['etichetta']
    tavolo.save()
    return JsonResponse({'ok': True, 'numero': tavolo.numero, 'forma': tavolo.forma,
                         'capacita': tavolo.capacita, 'etichetta': tavolo.etichetta})


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
    candidatura_inviata = False

    if request.method == 'POST' and request.POST.get('form_tipo') == 'candidatura':
        nome     = request.POST.get('nome', '').strip()
        email    = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        ruolo    = request.POST.get('ruolo', '').strip()
        msg      = request.POST.get('messaggio', '').strip()

        if nome and email and ruolo and msg:
            imp = ImpostazioniRistorante.get()
            dest = imp.email if imp and imp.email else None
            corpo = (
                f"Nuova candidatura ricevuta dal sito\n\n"
                f"Nome: {nome}\n"
                f"Email: {email}\n"
                f"Telefono: {telefono or '—'}\n"
                f"Ruolo: {ruolo}\n\n"
                f"Messaggio:\n{msg}"
            )
            try:
                if dest:
                    send_mail(
                        subject=f"Candidatura: {ruolo} — {nome}",
                        message=corpo,
                        from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@ristobar.it',
                        recipient_list=[dest],
                        fail_silently=True,
                    )
                # Notifica Telegram se configurato
                token = settings.TELEGRAM_BOT_TOKEN
                chat_id = imp.telegram_chat_id if imp else ''
                if token and chat_id:
                    invia_messaggio_telegram(chat_id, f"📋 *Nuova candidatura*\n👤 {nome}\n🎯 {ruolo}\n📧 {email}")
            except Exception:
                pass
            candidatura_inviata = True

    return render(request, 'ristorante/vetrina.html', {
        'categorie': categorie,
        'candidatura_inviata': candidatura_inviata,
        'impostazioni': ImpostazioniRistorante.get(),
    })


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

def aggrega_lista_spesa(data_da, data_a):
    """Helper: aggrega OrdineItem per categoria nella lista spesa."""
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
    categorie_spesa = {}
    for v in voci:
        cat_nome = v['piatto__categoria__nome']
        if cat_nome not in categorie_spesa:
            categorie_spesa[cat_nome] = {'icona': v['piatto__categoria__icona'], 'voci': []}
        categorie_spesa[cat_nome]['voci'].append(v)
    return categorie_spesa, voci


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

    categorie_spesa, voci = aggrega_lista_spesa(data_da, data_a)

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

    categorie_spesa, voci = aggrega_lista_spesa(data_da, data_a)

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
            subject=f'📋 Lista Spesa {ImpostazioniRistorante.get().nome} — {data_da.strftime("%d/%m")} / {data_a.strftime("%d/%m")}',
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


@ruolo_richiesto(RUOLO_CAMERIERE, RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
@require_POST
def eprint_ordine(request, ordine_id):
    """Invia l'ordine/comanda via email alla stampante ePrint del tavolo."""
    ordine = get_object_or_404(
        Ordine.objects.prefetch_related(
            'items__piatto'
        ),
        pk=ordine_id
    )
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
    """Form per i dati fiscali del ristorante e impostazioni display e-ink."""
    from datetime import date as date_type
    
    imp = ImpostazioniRistorante.get()
    messaggio = None
    if request.method == 'POST':
        campi = [
            'nome', 'slogan', 'indirizzo', 'cap', 'citta', 'provincia',
            'telefono', 'email', 'sito', 'orari', 'piva', 'cf', 'regime_fiscale',
            'iban', 'note_scontrino', 'note_fattura', 'piatto_del_giorno',
            # WhatsApp
            'whatsapp_numero', 'whatsapp_nome',
            # Telegram
            'telegram_nome_bot',
            # Social
            'social_facebook', 'social_x', 'social_pinterest',
            'social_youtube', 'social_tiktok', 'social_instagram',
            # Abbonamento
            'dominio', 'note_abbonamento',
            # Pagamenti dipendenti
            'pag_dip_iban', 'pag_dip_provider', 'pag_dip_note',
            # DDT
            'ddt_causale', 'ddt_vettore', 'ddt_aspetto', 'ddt_note',
        ]
        for c in campi:
            setattr(imp, c, request.POST.get(c, '').strip())
        
        # Boolean fields
        imp.whatsapp_enabled = request.POST.get('whatsapp_enabled') == 'on'
        imp.whatsapp_token = request.POST.get('whatsapp_token', '').strip()
        imp.whatsapp_phone_id = request.POST.get('whatsapp_phone_id', '').strip()
        imp.whatsapp_business_id = request.POST.get('whatsapp_business_id', '').strip()
        
        imp.telegram_enabled = request.POST.get('telegram_enabled') == 'on'
        imp.telegram_bot_token = request.POST.get('telegram_bot_token', '').strip()
        chat_id = request.POST.get('telegram_chat_id', '').strip()
        if chat_id:
            if chat_id.startswith('@'):
                # Username pubblico — lascia invariato
                imp.telegram_chat_id = chat_id
            else:
                digits = chat_id.lstrip('-')
                if digits.isdigit():
                    imp.telegram_chat_id = ('-' + digits) if len(digits) > 9 else digits
                else:
                    imp.telegram_chat_id = chat_id
        
        imp.abbonamento_attivo = request.POST.get('abbonamento_attivo') == 'on'
        imp.mostra_lavora_con_noi = request.POST.get('mostra_lavora_con_noi') == 'on'
        imp.ddt_abilitato = request.POST.get('ddt_abilitato') == 'on'

        # Dropdown / select fields
        imp.pag_dip_metodo = request.POST.get('pag_dip_metodo', 'B')
        imp.ddt_porto = request.POST.get('ddt_porto', 'F')

        # Integer fields
        giorno = request.POST.get('pag_dip_giorno', '').strip()
        if giorno.isdigit():
            imp.pag_dip_giorno = int(giorno)
        
        # Date fields
        for field in ['abbonamento_inizio', 'abbonamento_fine', 'dominio_scadenza']:
            val = request.POST.get(field, '').strip()
            if val:
                try:
                    setattr(imp, field, date_type.fromisoformat(val))
                except ValueError:
                    setattr(imp, field, None)
            else:
                setattr(imp, field, None)
        
        # Decimal fields
        for field in ['abbonamento_mensile_euro', 'dominio_costo_annuale']:
            val = request.POST.get(field, '').strip().replace(',', '.')
            if val:
                try:
                    setattr(imp, field, Decimal(val))
                except ValueError:
                    pass
        
        if 'logo' in request.FILES:
            imp.logo = request.FILES['logo']
        imp.save()
        messaggio = 'Impostazioni salvate.'
    return render(request, 'sala/impostazioni_ristorante.html', {'imp': imp, 'messaggio': messaggio})


# ─── Scontrino ───────────────────────────────────────────────────────────────

@ruolo_richiesto(RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
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

@ruolo_richiesto(RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
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


@ruolo_richiesto(RUOLO_CAMERIERE_SENIOR, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
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

    sala1 = Sala.objects.first()
    tavolo1 = Tavolo.objects.filter(attivo=True).first() if sala1 else None
    prenotazione1 = Prenotazione.objects.first()

    tg_token = settings.TELEGRAM_BOT_TOKEN
    tg_ok = False
    tg_bot_name = ''
    if tg_token:
        try:
            r = requests.get(f'https://api.telegram.org/bot{tg_token}/getMe', timeout=5)
            data = r.json()
            if data.get('ok'):
                tg_ok = True
                tg_bot_name = data['result'].get('username', '')
        except Exception:
            pass

    imp = ImpostazioniRistorante.get()
    wa_ok = bool(getattr(imp, 'whatsapp_enabled', False) and getattr(imp, 'whatsapp_token', ''))

    stripe_ok = bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))
    stripe_pub_ok = bool(getattr(settings, 'STRIPE_PUBLIC_KEY', ''))
    stripe_webhook_ok = bool(getattr(settings, 'STRIPE_WEBHOOK_SECRET', ''))

    ctx = {
        'sala1': sala1,
        'tavolo1': tavolo1,
        'prenotazione1': prenotazione1,
        'n_sale': Sala.objects.count(),
        'n_tavoli': Tavolo.objects.filter(attivo=True).count(),
        'n_piatti': Piatto.objects.count(),
        'n_ordini': Ordine.objects.count(),
        'n_prenotazioni': Prenotazione.objects.count(),
        'tg_ok': tg_ok,
        'tg_bot_name': tg_bot_name,
        'wa_ok': wa_ok,
        'stripe_ok': stripe_ok,
        'stripe_pub_ok': stripe_pub_ok,
        'stripe_webhook_ok': stripe_webhook_ok,
        'tg_chat_id_saved': imp.telegram_chat_id,
    }
    return render(request, 'dev/panel.html', ctx)


@csrf_exempt
def dev_telegram_verifica(request):
    """Verifica che il chat_id sia raggiungibile dal bot."""
    if not settings.DEBUG:
        return JsonResponse({'errore': 'Solo in DEBUG'}, status=403)
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return JsonResponse({'errore': 'Token non configurato'}, status=400)
    data = json.loads(request.body)
    chat_id = data.get('chat_id', '').strip()
    if not chat_id:
        return JsonResponse({'errore': 'chat_id mancante'}, status=400)
    try:
        r = requests.get(
            f'https://api.telegram.org/bot{token}/getChat',
            params={'chat_id': chat_id},
            timeout=10,
        )
        d = r.json()
        if d.get('ok'):
            chat = d['result']
            nome = chat.get('title') or f"{chat.get('first_name','')} {chat.get('last_name','')}".strip()
            tipo = chat.get('type', '')
            return JsonResponse({'ok': True, 'nome': nome, 'tipo': tipo})
        return JsonResponse({'errore': d.get('description', 'Chat non trovata')}, status=400)
    except Exception as e:
        return JsonResponse({'errore': str(e)}, status=500)


@csrf_exempt
def dev_telegram_leggi(request):
    """Legge gli ultimi messaggi ricevuti dal bot (dal buffer in memoria)."""
    if not settings.DEBUG:
        return JsonResponse({'errore': 'Solo in DEBUG'}, status=403)
    from ristorante.telegram_service import _messaggi_recenti
    return JsonResponse({'messaggi': list(reversed(_messaggi_recenti))})


@csrf_exempt
@require_POST
def dev_telegram_invia(request):
    """Invia un messaggio Telegram a un chat_id specificato."""
    if not settings.DEBUG:
        return JsonResponse({'errore': 'Solo in DEBUG'}, status=403)
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return JsonResponse({'errore': 'Token non configurato'}, status=400)
    data = json.loads(request.body)
    chat_id = data.get('chat_id', '').strip()
    testo = data.get('testo', '').strip()
    if not chat_id or not testo:
        return JsonResponse({'errore': 'chat_id e testo obbligatori'}, status=400)
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': testo, 'parse_mode': 'Markdown'},
            timeout=10,
        )
        if r.json().get('ok'):
            return JsonResponse({'ok': True})
        return JsonResponse({'errore': r.json().get('description', 'Errore sconosciuto')}, status=400)
    except Exception as e:
        return JsonResponse({'errore': str(e)}, status=500)


@csrf_exempt
@require_POST
def dev_whatsapp_invia(request):
    """Invia un messaggio WhatsApp di test."""
    if not settings.DEBUG:
        return JsonResponse({'errore': 'Solo in DEBUG'}, status=403)
    data = json.loads(request.body)
    numero = data.get('numero', '').strip()
    testo = data.get('testo', '').strip()
    if not numero or not testo:
        return JsonResponse({'errore': 'numero e testo obbligatori'}, status=400)
    ok, risposta = invia_whatsapp(testo, numero)
    if ok:
        return JsonResponse({'ok': True})
    return JsonResponse({'errore': str(risposta)}, status=400)


# ═══════════════════════════════════════════════════════════════════════════════
#  CENTRO DI CONTROLLO DISPOSITIVI
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def centro_controllo(request):
    """Dashboard centralizzata per la gestione di tutti i dispositivi."""
    sale = Sala.objects.filter(attiva=True).prefetch_related('dispositivi')
    dispositivi = Dispositivo.objects.select_related('sala', 'tavolo').all()
    
    # Statistiche
    stats = {
        'totali': dispositivi.count(),
        'online': dispositivi.filter(stato='ONLINE').count(),
        'offline': dispositivi.filter(stato='OFFLINE').count(),
        'errori': dispositivi.filter(stato='ERROR').count(),
        'wifi': dispositivi.filter(modalita='WIFI').count(),
        'ble': dispositivi.filter(modalita='BLE').count(),
        'combined': dispositivi.filter(modalita='COMBINED').count(),
    }
    
    # Raggruppa per piano
    piani = {}
    for disp in dispositivi:
        piano = disp.piano or 'Non assegnato'
        if piano not in piani:
            piani[piano] = {'online': 0, 'offline': 0, 'dispositivi': []}
        piani[piano]['dispositivi'].append(disp)
        if disp.stato == 'ONLINE':
            piani[piano]['online'] += 1
        else:
            piani[piano]['offline'] += 1
    
    return render(request, 'sala/centro_controllo.html', {
        'dispositivi': dispositivi,
        'sale': sale,
        'stats': stats,
        'piani': piani,
    })


@login_required
def dispositivo_dettaglio(request, dispositivo_id):
    """Dettaglio singolo dispositivo."""
    disp = get_object_or_404(Dispositivo, pk=dispositivo_id)
    return render(request, 'sala/dispositivo_dettaglio.html', {'dispositivo': disp})


@login_required
@require_POST
def dispositivo_aggiungi(request):
    """Aggiungi nuovo dispositivo."""
    nome = request.POST.get('nome')
    tipo = request.POST.get('tipo')
    modalita = request.POST.get('modalita', 'WIFI')
    sala_id = request.POST.get('sala')
    tavolo_id = request.POST.get('tavolo')
    piano = request.POST.get('piano', '')
    posizione = request.POST.get('posizione', '')
    
    sala = get_object_or_404(Sala, pk=sala_id)
    tavolo = Tavolo.objects.get(pk=tavolo_id) if tavolo_id else None
    
    disp = Dispositivo.objects.create(
        nome=nome,
        tipo=tipo,
        modalita=modalita,
        sala=sala,
        tavolo=tavolo,
        piano=piano,
        posizione=posizione,
        stato='OFFLINE',
    )
    return redirect('centro_controllo')


@login_required
@require_POST
def dispositivo_aggiorna(request, dispositivo_id):
    """Aggiorna configurazione dispositivo."""
    disp = get_object_or_404(Dispositivo, pk=dispositivo_id)
    disp.modalita = request.POST.get('modalita', disp.modalita)
    disp.refresh_interval = int(request.POST.get('refresh_interval', 60))
    disp.piano = request.POST.get('piano', '')
    disp.posizione = request.POST.get('posizione', '')
    disp.note = request.POST.get('note', '')
    disp.save()
    return redirect('dispositivo_dettaglio', dispositivo_id)


@login_required
@require_POST
def dispositivo_rimuovi(request, dispositivo_id):
    """Rimuovi dispositivo."""
    disp = get_object_or_404(Dispositivo, pk=dispositivo_id)
    disp.delete()
    return redirect('centro_controllo')


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def api_dispositivo_status(request):
    """API per ricevere stato da dispositivo."""
    mac = request.data.get('mac')
    stato = request.data.get('stato', {})
    errores = request.data.get('error', '')
    
    disp = Dispositivo.objects.filter(mac_address=mac).first()
    if disp:
        disp.aggiorna_stato(stato)
        if errores:
            disp.errori = errores
            disp.stato = 'ERROR'
            disp.save()
        return Response({'ok': True, 'dispositivo_id': disp.id})
    
    return Response({'ok': False, 'errore': 'Dispositivo non registrato'}, status=404)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def api_dispositivo_config(request, dispositivo_id):
    """API per richiedere configurazione."""
    mac = request.GET.get('mac')
    disp = Dispositivo.objects.filter(mac_address=mac).first()
    
    if disp:
        return Response({
            'id': disp.id,
            'nome': disp.nome,
            'modalita': disp.modalita,
            'sala_id': disp.sala_id,
            'tavolo_id': disp.tavolo_id,
            'server_url': disp.server_url,
            'refresh_interval': disp.refresh_interval,
            'stato': disp.last_status,
        })
    
    return Response({'errore': 'Non trovato'}, status=404)


# ─── Chat AI Chef ────────────────────────────────────────────────────────────

def chef_chat_view(request):
    """
    Pagina di chat con lo Chef AI per consigli sul piatto del giorno.
    Accessibile a tutti i clienti senza login.
    """
    impostazioni = ImpostazioniRistorante.get()
    piatto_giorno = impostazioni.piatto_del_giorno
    
    categorie = Categoria.objects.filter(
        piatti__disponibile=True
    ).distinct().prefetch_related('piatti')
    
    piatti = []
    for cat in categorie:
        for p in cat.piatti.filter(disponibile=True):
            piatti.append({
                'nome': p.nome,
                'descrizione': p.descrizione or '',
                'prezzo': p.prezzo,
                'categoria': cat.nome,
            })
    
    return render(request, 'ristorante/chef_chat.html', {
        'impostazioni': impostazioni,
        'piatto_giorno': piatto_giorno,
        'piatti': piatti,
    })


@require_POST
def chef_chat_message(request):
    """
    API per inviare un messaggio allo Chef AI e ricevere una risposta.
    Usa Ollama con modello multilingua.
    """
    messaggio = request.POST.get('messaggio', '').strip()
    impostazioni = ImpostazioniRistorante.get()
    piatto_giorno = impostazioni.piatto_del_giorno
    nome_ristorante = impostazioni.nome
    
    categorie = Categoria.objects.filter(
        piatti__disponibile=True
    ).distinct().prefetch_related('piatti')
    
    menu_testo = ""
    for cat in categorie:
        menu_testo += f"\n{cat.nome}:\n"
        for p in cat.piatti.filter(disponibile=True):
            menu_testo += f"  - {p.nome}: €{p.prezzo}"
            if p.descrizione:
                menu_testo += f" ({p.descrizione[:50]}...)"
            menu_testo += "\n"
    
    risposta = genera_risposta_ollama(messaggio, piatto_giorno, menu_testo, nome_ristorante)
    
    return JsonResponse({'risposta': risposta})


def genera_risposta_ollama(messaggio, piatto_giorno, menu, nome_ristorante):
    """
    Genera risposta usando Ollama API con modello multilingua.
    """
    if not messaggio:
        return "Scrivi un messaggio per parlare con lo chef!"
    
    system_prompt = f"""Sei lo chef di {nome_ristorante}, un ristorante italiano. 
Rispondi SEMPRE nella stessa lingua in cui ti scrivono.
Se ti scrivono in italiano, rispondi in italiano.
Se ti scrivono in inglese, rispondi in inglese.
Se ti scrivono in francese, rispondi in francese.
E così via per tutte le lingue.

Il piatto del giorno è: {piatto_giorno if piatto_giorno else "Nessuno specifico oggi"}

Ecco il menu completo:
{menu}

Regole:
1. Rispondi in modo cordiale e professionale
2. Consiglia i piatti del giorno quando appropriato
3. Se non capisci, chiedi di ripetere
4. Non inventare piatti che non sono nel menu
5. Per prenotazioni, indirizza a /prenota/
6. Usa emoji appropriate per rendere la conversazione più vivace
7. Tieni le risposte brevi e concise (max 2-3 frasi)
8. Se il cliente chiede di ordinare, spiegagli che può farlo tramite il cameriere o scannerizzando il QR code al tavolo"""

    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3.2:3b-instruct-q4_K_M',
                'prompt': f"{system_prompt}\n\nCliente: {messaggio}\nChef:",
                'stream': False,
                'options': {
                    'temperature': 0.7,
                    'num_predict': 200,
                }
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json().get('response', '').strip()
    except Exception as e:
        pass
    
    return generazione_risposta_chef_fallback(messaggio, piatto_giorno, menu, nome_ristorante)


def generazione_risposta_chef_fallback(messaggio, piatto_giorno, menu, nome_ristorante):
    """
    Logica di risposta dello Chef AI di fallback (se Ollama non è disponibile).
    """
    if not messaggio:
        return "Scrivi un messaggio per parlare con lo chef!"
    
    if any(word in messaggio for word in ['ciao', 'buongiorno', 'buonasera', 'salve', 'hello', 'hi']):
        if piatto_giorno:
            return f"Benvenuto da {nome_ristorante}! 🍳 Oggi il nostro piatto del giorno è: **{piatto_giorno}**! Posso suggerirti qualcosa di specifico dal nostro menu?"
        return f"Benvenuto da {nome_ristorante}! 🍳 Sono lo chef. Cosa vorresti mangiare oggi?"
    
    if any(word in messaggio for word in ['piatto del giorno', 'speciale', 'oggi', 'del giorno']):
        if piatto_giorno:
            return f"⭐ Il piatto del giorno è: **{piatto_giorno}**! Un nostro classico, preparato con ingredienti freschi. Te lo consiglio!"
        return "Oggi non abbiamo un piatto del giorno specifico, ma puoi scegliere dal nostro menu completo!"
    
    if any(word in messaggio for word in ['pesce', 'pescado', 'fish']):
        for riga in menu.split('\n'):
            if 'pesce' in riga.lower() or 'pescada' in riga.lower() or 'salmone' in riga.lower() or 'branzino' in riga.lower():
                return f"🐟 Ti consiglio: {riga.strip()}"
        return "Mi dispiace, oggi non abbiamo piatti di pesce disponibili. Vuoi vedere le altre proposte?"
    
    if any(word in messaggio for word in ['carne', 'bistecca', 'manzo', 'pollo']):
        for riga in menu.split('\n'):
            if 'carne' in riga.lower() or 'bistecca' in riga.lower() or 'manzo' in riga.lower() or 'pollo' in riga.lower():
                return f"🥩 Ti consiglio: {riga.strip()}"
        return "Guarda il nostro menu, ci sono ottime proposte di carne!"
    
    if any(word in messaggio for word in ['vegetariano', 'veg', 'verdura']):
        for riga in menu.split('\n'):
            if 'insalata' in riga.lower() or 'verdura' in riga.lower() or 'vegetariano' in riga.lower():
                return f"🥗 Ti consiglio: {riga.strip()}"
        return "Abbiamo diverse opzioni fresche e leggere. Chiedimi del menu completo!"
    
    if any(word in messaggio for word in ['menu', 'cosa avete', 'elenco', 'lista']):
        risposta = f"Ecco il nostro menu di {nome_ristorante}:\n{menu}"
        if piatto_giorno:
            risposta += f"\n⭐ *Piatto del giorno: {piatto_giorno}*"
        return risposta
    
    if any(word in messaggio for word in ['prezzo', 'quanto', 'costa']):
        return "I prezzi sono indicati nel menu. Hai un piatto specifico di cui vuoi sapere il prezzo?"
    
    if any(word in messaggio for word in ['allergen', 'intolleranz', 'gluten', 'lattosio']):
        return "Per informazioni sugli allergeni, ti consiglio di chiedere direttamente al cameriere. Possiamo preparare piatti adatti alle tue esigenze!"
    
    if any(word in messaggio for word in ['prenot', 'tavolo', 'prenota']):
        return "Per prenotare un tavolo, vai su /prenota/ oppure chiedi al cameriere di assisterti!"
    
    if any(word in messaggio for word in ['grazie', 'grazie mille', 'thanks']):
        return "Prego! 🍽️ Se hai altre domande, sono qui!"
    
    if piatto_giorno:
        return f"Non sono sicuro di aver capito. Vuoi provare il nostro piatto del giorno? ⭐ **{piatto_giorno}**"
    
    return "Non sono sicuro di aver capito. Vuoi vedere il nostro menu completo? Chiedimi di mostrartelo!"


# ═══════════════════════════════════════════════════════════════════════════════
#  STATISTICHE E REPORT
# ═══════════════════════════════════════════════════════════════════════════════

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def statistiche_view(request):
    """Dashboard statistiche per il titolare."""
    oggi = date.today()
    
    # Statistiche oggi
    ordini_oggi = Ordine.objects.filter(creato_il__date=oggi)
    incassi_oggi = ordini_oggi.aggregate(totale=Sum('totale'))['totale'] or Decimal('0')
    
    prenotazioni_oggi = Prenotazione.objects.filter(data_ora__date=oggi)
    prenotazioni_confermate = prenotazioni_oggi.filter(stato=Prenotazione.STATO_CONFERMATA).count()
    
    # Ultimi 7 giorni
    ultima_settimana = [oggi - timedelta(days=i) for i in range(7)]
    dati_settimana = []
    for g in reversed(ultima_settimana):
        ordini_giorno = Ordine.objects.filter(creato_il__date=g)
        dati_settimana.append({
            'giorno': g.strftime('%a'),
            'ordini': ordini_giorno.count(),
            'incassi': float(ordini_giorno.aggregate(t=Sum('totale'))['t'] or 0),
        })
    
    # Piatti più venduti (ultimi 30 giorni)
    trenta_giorni_fa = oggi - timedelta(days=30)
    piatti_venduti = list(
        OrdineItem.objects
        .filter(ordine__creato_il__date__gte=trenta_giorni_fa)
        .values('piatto__nome')
        .annotate(totale=Sum('quantita'))
        .order_by('-totale')[:10]
    )
    
    # Promemoria in scadenza
    promemoria_attivi = Promemoria.objects.filter(
        completato=False,
        data_scadenza__lte=oggi + timedelta(days=30)
    ).order_by('data_scadenza')[:10]
    
    # Report recenti
    report_recenti = ReportPeriodico.objects.all()[:5]
    
    return render(request, 'sala/statistiche.html', {
        'incassi_oggi': incassi_oggi,
        'ordini_oggi': ordini_oggi.count(),
        'prenotazioni_confermate': prenotazioni_confermate,
        'dati_settimana': dati_settimana,
        'piatti_venduti': piatti_venduti,
        'promemoria_attivi': promemoria_attivi,
        'report_recenti': report_recenti,
    })


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def genera_report(request):
    """Genera un report periodico con analisi AI."""
    if request.method == 'POST':
        tipo = request.POST.get('tipo', 'MENSILE')
        data_da = date.fromisoformat(request.POST.get('data_da'))
        data_a = date.fromisoformat(request.POST.get('data_a'))
        
        # Calcola statistiche
        ordini_periodo = Ordine.objects.filter(creato_il__date__range=[data_da, data_a])
        totale_incassi = ordini_periodo.aggregate(t=Sum('totale'))['t'] or Decimal('0')
        
        prenotazioni_periodo = Prenotazione.objects.filter(data_ora__date__range=[data_da, data_a])
        tot_pren = prenotazioni_periodo.count()
        pren_confermate = prenotazioni_periodo.filter(stato=Prenotazione.STATO_CONFERMATA).count()
        tasso_conferma = (pren_confermate / tot_pren * 100) if tot_pren > 0 else 0
        
        # Piatti più venduti
        piatti = list(
            OrdineItem.objects
            .filter(ordine__creato_il__date__range=[data_da, data_a])
            .values('piatto__nome')
            .annotate(totale=Sum('quantita'))
            .order_by('-totale')[:10]
        )
        
        # Costi
        imp = ImpostazioniRistorante.get()
        if tipo == 'SETTIMANALE':
            costo_abb = imp.abbonamento_mensile_euro / 4
        elif tipo == 'MENSILE':
            costo_abb = imp.abbonamento_mensile_euro
        elif tipo == 'BIMESTRALE':
            costo_abb = imp.abbonamento_mensile_euro * 2
        elif tipo == 'SEMESTRALE':
            costo_abb = imp.abbonamento_mensile_euro * 6
        else:
            costo_abb = imp.abbonamento_mensile_euro * 12
        
        costo_dom = imp.dominio_costo_annuale / 12 if tipo == 'MENSILE' else imp.dominio_costo_annuale
        if tipo == 'BIMESTRALE':
            costo_dom *= 2
        elif tipo == 'SEMESTRALE':
            costo_dom *= 6
        elif tipo == 'ANNUALE':
            costo_dom = imp.dominio_costo_annuale
        
        margine = totale_incassi - costo_abb - costo_dom
        
        # Crea report
        report = ReportPeriodico.objects.create(
            tipo=tipo,
            data_inizio=data_da,
            data_fine=data_a,
            totale_incassi=totale_incassi,
            totale_ordini=ordini_periodo.count(),
            totale_prenotazioni=tot_pren,
            tasso_prenotazioni_confermate=tasso_conferma,
            piatti_piu_venduti=piatti,
            costo_abbonamento=costo_abb,
            costo_dominio=costo_dom,
            margine_netto=margine,
            creato_da=request.user,
        )
        
        # Analisi AI
        analisi = genera_analisi_ai(report, imp)
        report.analisi_ai = analisi['analisi']
        report.suggerimenti_miglioramento = analisi['suggerimenti']
        report.save()
        
        return redirect('statistiche')
    
    return redirect('statistiche')


def genera_analisi_ai(report, imp):
    """Genera analisi AI del report usando Ollama."""
    
    prompt = f"""Sei un esperto consulente di ristorazione. Analizza questi dati e fornisci:
1. Una breve analisi della situazione
2. Suggerimenti concreti per migliorare

DATI DEL PERIODO {report.data_inizio} / {report.data_fine}:
- Totale ordini: {report.totale_ordini}
- Totale incassi: €{report.totale_incassi}
- Prenotazioni totali: {report.totale_prenotazioni}
- Tasso conferma prenotazioni: {report.tasso_prenotazioni_confermate}%
- Costo abbonamento software: €{report.costo_abbonamento}
- Costo dominio: €{report.costo_dominio}
- Margine netto: €{report.margine_netto}

PIATTI PIÙ VENDUTI:
{chr(10).join([f"- {p['piatto__nome']}: {p['totale']} porzioni" for p in report.piatti_piu_venduti[:5]])}

Rispondi in italiano in modo human e concreto. Non inventare dati."""

    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3.2:3b-instruct-q4_K_M',
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.7, 'num_predict': 500}
            },
            timeout=60
        )
        if response.status_code == 200:
            result = response.json().get('response', '')
            # Separa analisi e suggerimenti
            if 'Suggerimenti' in result or 'suggerimenti' in result.lower():
                parts = result.split('Suggerimenti')
                analisi = parts[0].strip()
                suggerimenti = 'Suggerimenti' + parts[1] if len(parts) > 1 else ''
            else:
                analisi = result
                suggerimenti = ''
            
            return {'analisi': analisi[:2000], 'suggerimenti': suggerimenti[:2000]}
    except:
        pass
    
    return {
        'analisi': f"Periodo {report.data_inizio} - {report.data_fine}: {report.totale_ordini} ordini, €{report.totale_incassi} incassi.",
        'suggerimenti': 'Analisi non disponibile. Verifica che Ollama sia attivo.'
    }


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def promemoria_view(request):
    """Gestione promemoria."""
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'aggiungi':
            Promemoria.objects.create(
                titolo=request.POST.get('titolo'),
                descrizione=request.POST.get('descrizione', ''),
                tipo=request.POST.get('tipo', 'ALTRO'),
                data_scadenza=date.fromisoformat(request.POST.get('data_scadenza')),
                ricorrente=request.POST.get('ricorrente') == 'on',
                frequenza_ricorrenza=request.POST.get('frequenza_ricorrenza', 'NESSUNA'),
                creato_da=request.user,
            )
        elif action == 'completato':
            prom = Promemoria.objects.get(pk=request.POST.get('id'))
            prom.completato = True
            prom.save()
        elif action == 'elimina':
            Promemoria.objects.get(pk=request.POST.get('id')).delete()
    
    promemoria = Promemoria.objects.all()[:50]
    return render(request, 'sala/promemoria.html', {'promemoria': promemoria})


# ═══════════════════════════════════════════════════════════════════════════════
#  QUESTIONARIO FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════════

def questionario_view(request, tavolo_id=None):
    """
    Pagina questionario feedback accessibile via QR code sul tavolo.
    """
    tavolo = None
    if tavolo_id:
        tavolo = get_object_or_404(Tavolo, pk=tavolo_id)
    
    imp = ImpostazioniRistorante.get()
    
    if request.method == 'POST':
        q = Questionario()
        if tavolo:
            q.tavolo = tavolo
        
        q.nome = request.POST.get('nome', '').strip()
        q.email = request.POST.get('email', '').strip()
        q.telefono = request.POST.get('telefono', '').strip()
        q.sesso = request.POST.get('sesso', '')
        
        eta = request.POST.get('eta', '').strip()
        if eta:
            try:
                q.eta = int(eta)
            except:
                pass
        
        q.valutazione_cibo = int(request.POST.get('valutazione_cibo', 0))
        q.valutazione_servizio = int(request.POST.get('valutazione_servizio', 0))
        q.valutazione_ambiente = int(request.POST.get('valutazione_ambiente', 0))
        q.valutazione_prezzo = int(request.POST.get('valutazione_prezzo', 0))
        q.commenti = request.POST.get('commenti', '').strip()
        
        q.save()
        
        # Genera coupon
        coupon = CouponSconto.objects.create(
            codice=CouponSconto.genera_codice(),
            sconto_percentuale=10,
            valido_fino=date.today() + timedelta(days=90),
            creato_da=request.user if request.user.is_authenticated else None,
        )
        q.coupon = coupon
        q.save()
        
        # Invia email con coupon
        if q.email:
            try:
                send_mail(
                    subject=f"🎁 Coupon sconto da {imp.nome}!",
                    message=f"Grazie per il tuo feedback!\n\n"
                            f"Ecco il tuo coupon sconto:\n"
                            f"Codice: {coupon.codice}\n"
                            f"Sconto: {coupon.sconto_percentuale}%\n"
                            f"Valido fino al: {coupon.valido_fino.strftime('%d/%m/%Y')}\n\n"
                            f"Ci rivideremo presto!",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[q.email],
                )
            except:
                pass
        
        return render(request, 'ristorante/questionario_grazie.html', {
            'coupon': coupon,
            'imp': imp,
        })
    
    return render(request, 'ristorante/questionario.html', {
        'tavolo': tavolo,
        'imp': imp,
    })


def genera_domande_ai():
    """
    Genera domande personalizzate per il questionario usando Ollama.
    """
    prompt = """Genera 3 domande brevi di feedback per un ristorante italiano.
Formato JSON array:
[
  {"domanda": "...", "tipo": "stelle" o "testo"},
  ...
]
Rispondi solo in JSON, niente altro."""
    
    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3.2:3b-instruct-q4_K_M',
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.7, 'num_predict': 200}
            },
            timeout=30
        )
        if response.status_code == 200:
            result = response.json().get('response', '')
            import json
            try:
                return json.loads(result)
            except:
                pass
    except:
        pass
    
    return [
        {"domanda": "Cosa ti è piaciuto di più?", "tipo": "testo"},
        {"domanda": "Cosa potremmo migliorare?", "tipo": "testo"},
        {"domanda": "Torneresti a trovarci?", "tipo": "stelle"},
    ]


def attiva_questionario_telegram(chat_id, prenotazione=None):
    """
    Invia messaggio per attivare questionario via Telegram.
    """
    imp = ImpostazioniRistorante.get()
    messaggio = (
        "🍽️ Grazie per aver prenotato da " + imp.nome + "!\n\n"
        "Vuoi avere uno sconto per il tuo prossimo pasto?\n"
        "Rispondi al nostro questionario e ricevi un coupon!\n\n"
        "➡️ Compila qui: " + imp.sito + "questionario/"
    )
    keyboard = [[{"text": "📝 Compila questionario", "url": imp.sito + "questionario/"}]]
    invia_messaggio_telegram(chat_id, messaggio, keyboard)


def attiva_questionario_whatsapp(telefono, prenotazione=None):
    """
    Invia messaggio per attivare questionario via WhatsApp.
    """
    imp = ImpostazioniRistorante.get()
    messaggio = (
        "🍽️ Grazie per aver prenotato da " + imp.nome + "!\n\n"
        "Vuoi avere uno sconto per il tuo prossimo pasto?\n"
        "Rispondi al nostro questionario e ricevi un coupon!\n\n"
        "Compila qui: " + imp.sito + "questionario/"
    )
    invia_whatsapp(messaggio, telefono)


# ═══════════════════════════════════════════════════════════════════════════════
#  GESTIONE MAGAZZINO E SCADENZE
# ═══════════════════════════════════════════════════════════════════════════════

@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def magazzino_view(request):
    """
    Dashboard magazzino con lista scadenze.
    """
    oggi = date.today()
    
    # Prodotti scaduti
    scaduti = ProdottoMagazzino.objects.filter(
        data_scadenza__lt=oggi,
        quantita__gt=0
    ).order_by('data_scadenza')
    
    # In scadenza prossima settimana
    prossima_settimana = oggi + timedelta(days=7)
    in_scadenza = ProdottoMagazzino.objects.filter(
        data_scadenza__gte=oggi,
        data_scadenza__lte=prossima_settimana,
        quantita__gt=0
    ).order_by('data_scadenza')
    
    # Aperti (da consumare)
    aperti = ProdottoMagazzino.objects.filter(
        data_apertura__isnull=False,
        quantita__gt=0
    ).order_by('data_apertura')
    
    # Tutti i prodotti
    tutti = ProdottoMagazzino.objects.all()[:50]
    
    # Statistiche
    stats = {
        'scaduti': scaduti.count(),
        'in_scadenza': in_scadenza.count(),
        'aperti': aperti.count(),
        'totali': ProdottoMagazzino.objects.count(),
    }
    
    return render(request, 'sala/magazzino.html', {
        'scaduti': scaduti,
        'in_scadenza': in_scadenza,
        'aperti': aperti,
        'tutti': tutti,
        'stats': stats,
        'oggi': oggi,
    })


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def magazzino_aggiungi(request):
    """
    Aggiungi nuovo prodotto al magazzino.
    Supporta scansione barcode via camera.
    """
    if request.method == 'POST':
        barcode = request.POST.get('barcode', '').strip()
        
        # Cerca prodotto esistente con stesso barcode
        prodotto_esistente = None
        if barcode:
            prodotto_esistente = ProdottoMagazzino.objects.filter(barcode=barcode).first()
        
        if prodotto_esistente:
            # Aggiorna quantità
            qta = request.POST.get('quantita', '').replace(',', '.')
            try:
                prodotto_esistente.quantita += Decimal(qta)
            except:
                prodotto_esistente.quantita += 1
            prodotto_esistente.data_arrivo = date.today()
            prodotto_esistente.save()
            messaggio = f"Aggiornato: {prodotto_esistente.nome}"
        else:
            # Crea nuovo
            nome = request.POST.get('nome', '').strip()
            if not nome:
                nome = f"Prodotto {barcode}" if barcode else "Nuovo prodotto"
            
            qta = request.POST.get('quantita', '').replace(',', '.')
            try:
                quantita = Decimal(qta) if qta else Decimal('1')
            except:
                quantita = Decimal('1')
            
            data_scad = request.POST.get('data_scadenza', '').strip()
            data_scadenza = None
            if data_scad:
                try:
                    data_scadenza = date.fromisoformat(data_scad)
                except:
                    pass
            
            giorni_dopo = request.POST.get('giorni_dopo_apertura', '7').strip()
            
            prodotto = ProdottoMagazzino.objects.create(
                nome=nome,
                barcode=barcode,
                quantita=quantita,
                unita_misura=request.POST.get('unita_misura', 'PZ'),
                data_scadenza=data_scadenza,
                giorni_dopo_apertura=int(giorni_dopo) if giorni_dopo.isdigit() else 7,
                fornitore=request.POST.get('fornitore', '').strip(),
                categoria=request.POST.get('categoria', '').strip(),
                note=request.POST.get('note', '').strip(),
            )
            messaggio = f"Aggiunto: {prodotto.nome}"
        
        return JsonResponse({'ok': True, 'messaggio': messaggio})
    
    return JsonResponse({'ok': False})


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def magazzino_apri(request, prodotto_id):
    """
    Segna un prodotto come aperto (inizia il conto alla rovescia per il consumo).
    """
    prodotto = get_object_or_404(ProdottoMagazzino, pk=prodotto_id)
    prodotto.data_apertura = date.today()
    prodotto.save()
    return JsonResponse({'ok': True})


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def magazzino_elimina(request, prodotto_id):
    """
    Elimina un prodotto dal magazzino.
    """
    prodotto = get_object_or_404(ProdottoMagazzino, pk=prodotto_id)
    prodotto.delete()
    return JsonResponse({'ok': True})


@ruolo_richiesto(RUOLO_CUOCO, RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def magazzino_cerca_barcode(request):
    """
    Cerca prodotto per barcode.
    """
    barcode = request.GET.get('barcode', '').strip()
    prodotto = ProdottoMagazzino.objects.filter(barcode=barcode).first()
    
    if prodotto:
        return JsonResponse({
            'ok': True,
            'prodotto': {
                'id': prodotto.id,
                'nome': prodotto.nome,
                'quantita': float(prodotto.quantita),
                'unita_misura': prodotto.unita_misura,
                'data_scadenza': prodotto.data_scadenza.isoformat() if prodotto.data_scadenza else None,
                'giorni_dopo_apertura': prodotto.giorni_dopo_apertura,
            }
        })
    
    return JsonResponse({'ok': False})


# ═══════════════════════════════════════════════════════════════════════════════
#  CHIUSURA GIORNALIERA E LISTA SPESA
# ═══════════════════════════════════════════════════════════════════════════════

@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def chiusura_giornaliera(request):
    """
    Pagina per la chiusura giornaliera - inserisci cibo rimasto.
    """
    oggi = date.today()
    
    if request.method == 'POST':
        piatti = Piatto.objects.filter(disponibile=True)
        for piatto in piatti:
            qta_rimasta = request.POST.get(f'rimasto_{piatto.id}', '').strip()
            if qta_rimasta:
                try:
                    qta = float(qta_rimasta)
                    if qta > 0:
                        CiboRimasto.objects.create(
                            data=oggi,
                            piatto=piatto,
                            quantita=qta,
                            note=request.POST.get(f'note_{piatto.id}', '').strip(),
                            creato_da=request.user,
                        )
                except:
                    pass
        
        return redirect('genera_lista_spesa')
    
    piatti = Piatto.objects.filter(disponibile=True).select_related('categoria')
    gia_registrati = CiboRimasto.objects.filter(data=oggi).values_list('piatto_id', flat=True)
    
    return render(request, 'sala/chiusura_giornaliera.html', {
        'piatti': piatti,
        'gia_registrati': list(gia_registrati),
        'oggi': oggi,
    })


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def genera_lista_spesa(request):
    """
    Genera la lista della spesa basata su cibi rimasti e consumati.
    """
    oggi = date.today()
    ieri = oggi - timedelta(days=1)
    
    cibi_rimasti = CiboRimasto.objects.filter(data=ieri).select_related('piatto')
    
    consumati = {}
    ordini_ieri = Ordine.objects.filter(creato_il__date=ieri)
    for ordine in ordini_ieri:
        for item in ordine.items.select_related('piatto').all():
            piatto_nome = item.piatto.nome
            if piatto_nome not in consumati:
                consumati[piatto_nome] = {'nome': piatto_nome, 'quantita': 0, 'piatto': item.piatto}
            consumati[piatto_nome]['quantita'] += item.quantita
    
    prodotti_servono = []
    for nome, data in consumati.items():
        qta_consumata = data['quantita']
        qta_rimasta = 0
        for rimasto in cibi_rimasti:
            if rimasto.piatto.nome == nome:
                qta_rimasta = float(rimasto.quantita)
                break
        
        qta_da_comprare = qta_consumata - qta_rimasta
        if qta_da_comprare > 0:
            prodotti_servono.append({'nome': nome, 'quantita': qta_da_comprare, 'note': ''})
    
    domani = oggi + timedelta(days=1)
    lista = ListaSpesaGenerata.objects.create(
        data_generazione=oggi,
        data_riferimento=domani,
        prodotti_json=prodotti_servono,
        cibi_rimasti_json=[{'nome': r.piatto.nome, 'quantita': float(r.quantita)} for r in cibi_rimasti],
        prodotti_consumati_json=[{'nome': v['nome'], 'quantita': v['quantita']} for v in consumati.values()],
        generata_da=request.user,
    )
    
    return render(request, 'sala/lista_spesa_generata.html', {
        'lista': lista,
        'prodotti_servono': prodotti_servono,
        'cibi_rimasti': cibi_rimasti,
        'consumati': consumati,
        'domani': domani,
    })


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def lista_spesa_view(request):
    """Mostra le liste spesa generate."""
    liste = ListaSpesaGenerata.objects.all()[:10]
    return render(request, 'sala/liste_spesa.html', {'liste': liste})


@ruolo_richiesto(RUOLO_CAPO_AREA, RUOLO_TITOLARE)
def lista_spesa_dettaglio(request, lista_id):
    """Mostra dettaglio lista spesa."""
    lista = get_object_or_404(ListaSpesaGenerata, pk=lista_id)
    return render(request, 'sala/lista_spesa_dettaglio.html', {'lista': lista})
