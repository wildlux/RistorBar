from django.contrib import admin
from django.urls import path, include
from ristorante.admin import admin_site
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.shortcuts import redirect
from rest_framework.routers import DefaultRouter
from ristorante import views


def manifest_json(request):
    return JsonResponse({
        "name": "RistoBAR",
        "short_name": "RistoBAR",
        "description": "Gestione intelligente del tuo ristorante",
        "start_url": "/homepage",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#2c3e50",
        "orientation": "any",
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


router = DefaultRouter()
router.register(r'tavoli', views.TavoloViewSet)
router.register(r'prenotazioni', views.PrenotazioneViewSet)
router.register(r'ordini', views.OrdineViewSet)
router.register(r'piatti', views.PiattoViewSet)

urlpatterns = [
    # ── Admin Django (rinominato) ──────────────────────────────
    path('amministrazione/', admin_site.urls),
    path('admin/', lambda r: redirect('/amministrazione/')),  # redirect di cortesia

    # ── Auth (login/logout/password) ───────────────────────────
    path('login/',  views.login_view,  name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Root → homepage pubblica ───────────────────────────────
    path('', lambda r: redirect('homepage'), name='root'),

    # ── PWA ────────────────────────────────────────────────────
    path('manifest.json', manifest_json, name='manifest_json'),
    path('serviceworker.js', lambda r: __import__('django.http', fromlist=['FileResponse']).FileResponse(
        open(settings.BASE_DIR / 'static' / 'js' / 'serviceworker.js', 'rb'),
        content_type='application/javascript'
    )),

    # ── i18n ───────────────────────────────────────────────────
    path('i18n/', include('django.conf.urls.i18n')),

    # ══════════════════════════════════════════════════════════
    #  AREA PUBBLICA — clienti
    # ══════════════════════════════════════════════════════════
    path('homepage',                               views.vetrina,                name='homepage'),
    path('menu/<int:sala_id>/<int:numero_tavolo>/', views.menu_tavolo,           name='menu_tavolo'),
    path('eink/<int:sala_id>/<int:numero_tavolo>/', views.menu_eink,            name='menu_eink'),
    path('prenota/<int:sala_id>/<int:numero_tavolo>/', views.prenota,            name='prenota'),
    path('prenota/conferma/<int:prenotazione_id>/', views.conferma_prenotazione, name='conferma_prenotazione'),
    path('prenota/caparra/<int:prenotazione_id>/',  views.pagamento_caparra,     name='pagamento_caparra'),

    # Chat AI Chef
    path('chef/',                                    views.chef_chat_view,        name='chef_chat'),
    path('chef/message/',                            views.chef_chat_message,    name='chef_chat_message'),

    # Questionario feedback
    path('questionario/', views.questionario_view, name='questionario'),
    path('questionario/<int:tavolo_id>/', views.questionario_view, name='questionario_tavolo'),

    # ═══════════════════════════════════════════════════════════════════════════════
    #  AREA STAFF — /sala/
    # ══════════════════════════════════════════════════════════

    # Dispatch: reindirizza per ruolo dopo il login
    path('sala/',                    views.sala_dispatch,    name='sala_dispatch'),

    # Cameriere
    path('sala/cameriere/',          views.cameriere_view,   name='cameriere'),
    path('sala/cameriere/ordine/<int:tavolo_id>/', views.cameriere_ordine, name='cameriere_ordine'),

    # Cuoco — KDS (Kitchen Display System)
    path('sala/cucina/',             views.cucina_kds,       name='cucina_kds'),
    path('sala/cucina/item/<int:item_id>/stato/', views.aggiorna_item_kds, name='aggiorna_item_kds'),

    # Capo area / Titolare — dashboard completa
    path('sala/capo/',               views.dashboard,        name='dashboard'),
    path('pianta/<int:sala_id>/', views.pianta_locale, name='pianta_locale'),
    
    # Centro di controllo dispositivi hardware
    path('sala/dispositivi/',              views.centro_controllo,     name='centro_controllo'),
    path('sala/dispositivi/aggiungi/',      views.dispositivo_aggiungi, name='dispositivo_aggiungi'),
    path('sala/dispositivi/<int:dispositivo_id>/', views.dispositivo_dettaglio, name='dispositivo_dettaglio'),
    path('sala/dispositivi/<int:dispositivo_id>/aggiorna/', views.dispositivo_aggiorna, name='dispositivo_aggiorna'),
    path('sala/dispositivi/<int:dispositivo_id>/rimuovi/', views.dispositivo_rimuovi, name='dispositivo_rimuovi'),

    # Aggiorna stato tavolo (usato da cameriere e capo area)
    path('sala/tavolo/<int:tavolo_id>/stato/', views.aggiorna_stato_tavolo, name='aggiorna_stato_tavolo'),
    # Sposta ospiti da un tavolo a un altro
    path('sala/tavolo/<int:tavolo_id>/sposta/', views.sposta_tavolo, name='sposta_tavolo'),

    # Editor planimetria (capo area / titolare)
    path('sala/editor/<int:sala_id>/',               views.editor_sala,            name='editor_sala'),
    path('sala/editor/<int:sala_id>/salva/',          views.salva_layout,           name='salva_layout'),
    path('sala/editor/<int:sala_id>/unisci/',         views.unisci_tavoli,          name='unisci_tavoli'),
    path('sala/editor/<int:sala_id>/separa/',         views.separa_tavoli,          name='separa_tavoli'),
    path('sala/editor/<int:sala_id>/aggiungi/',       views.aggiungi_tavolo_editor, name='aggiungi_tavolo_editor'),
    path('sala/editor/<int:sala_id>/tavolo/<int:tavolo_id>/modifica/', views.modifica_tavolo_editor, name='modifica_tavolo_editor'),
    path('sala/editor/<int:sala_id>/tavolo/<int:tavolo_id>/elimina/', views.elimina_tavolo_editor,   name='elimina_tavolo_editor'),

    # Cuoco — Lista Spesa
    path('sala/cucina/lista-spesa/',        views.lista_spesa,              name='lista_spesa'),
    path('sala/cucina/lista-spesa/email/',  views.invia_lista_spesa_email,  name='invia_lista_spesa_email'),

    # ePrint — gestione (capo area) + stampa ordine
    path('sala/capo/eprint/',                      views.gestione_eprint,        name='gestione_eprint'),
    path('sala/ordine/<int:ordine_id>/eprint/',    views.eprint_ordine,          name='eprint_ordine'),

    # Contatti ristorante + sedi
    path('sala/capo/contatti/', views.gestione_contatti, name='gestione_contatti'),

    # Statistiche e Report
    path('sala/capo/statistiche/', views.statistiche_view, name='statistiche'),
    path('sala/capo/statistiche/genera/', views.genera_report, name='genera_report'),
    path('sala/capo/promemoria/', views.promemoria_view, name='promemoria'),

    # Magazzino e scadenze
    path('sala/capo/magazzino/', views.magazzino_view, name='magazzino'),
    path('sala/capo/magazzino/aggiungi/', views.magazzino_aggiungi, name='magazzino_aggiungi'),
    path('sala/capo/magazzino/cerca/', views.magazzino_cerca_barcode, name='magazzino_cerca_barcode'),
    path('sala/capo/magazzino/<int:prodotto_id>/apri/', views.magazzino_apri, name='magazzino_apri'),
    path('sala/capo/magazzino/<int:prodotto_id>/elimina/', views.magazzino_elimina, name='magazzino_elimina'),

    # Chiusura giornaliera e Lista spesa
    path('sala/capo/chiusura/', views.chiusura_giornaliera, name='chiusura_giornaliera'),
    path('sala/capo/lista-spesa/genera/', views.genera_lista_spesa, name='genera_lista_spesa'),
    path('sala/capo/lista-spesa/', views.lista_spesa_view, name='lista_spesa'),
    path('sala/capo/lista-spesa/<int:lista_id>/', views.lista_spesa_dettaglio, name='lista_spesa_dettaglio'),

    # Documenti fiscali — scontrino / fattura / ricevuta
    path('sala/capo/impostazioni/',                views.impostazioni_ristorante, name='impostazioni_ristorante'),
    path('sala/ordine/<int:ordine_id>/scontrino/', views.scontrino_view,          name='scontrino'),
    path('sala/ordine/<int:ordine_id>/fattura/',   views.fattura_nuova,           name='fattura_nuova'),
    path('sala/fattura/<int:fattura_id>/',         views.fattura_print,           name='fattura_print'),
    path('sala/fatture/',                          views.elenco_documenti,        name='elenco_documenti'),

    # ══════════════════════════════════════════════════════════
    #  WEBHOOKS
    # ══════════════════════════════════════════════════════════
    path('webhooks/stripe/',   views.stripe_webhook,   name='stripe_webhook'),
    path('webhooks/telegram/', views.telegram_webhook, name='telegram_webhook'),
    path('webhooks/whatsapp/', views.whatsapp_webhook, name='whatsapp_webhook'),

    # ══════════════════════════════════════════════════════════
    #  API — STM32 + ESP32 + REST
    # ══════════════════════════════════════════════════════════
    # STM32 (BLE -> HTTP bridge)
    path('api/tavolo/<int:sala_id>/<int:numero_tavolo>/', views.api_stato_tavolo, name='api_stato_tavolo'),
    path('api/sala/<int:sala_id>/',                        views.api_sala_completa, name='api_sala_completa'),
    # ESP32 (WiFi direct)
    path('api/esp32/tavolo/<int:sala_id>/<int:numero_tavolo>/', views.api_esp32_tavolo, name='api_esp32_tavolo'),
    path('api/esp32/sala/<int:sala_id>/',                     views.api_esp32_sala,     name='api_esp32_sala'),
    # Centro di controllo dispositivi
    path('api/dispositivo/status/', views.api_dispositivo_status, name='api_dispositivo_status'),
    path('api/dispositivo/config/<int:dispositivo_id>/', views.api_dispositivo_config, name='api_dispositivo_config'),
    # Note display e-ink
    path('api/tavolo/nota/<int:tavolo_id>/', views.api_tavolo_nota, name='api_tavolo_nota'),
    path('api/', include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('dev/', views.dev_panel, name='dev_panel'),
        path('dev/telegram/verifica/', views.dev_telegram_verifica, name='dev_telegram_verifica'),
        path('dev/telegram/leggi/', views.dev_telegram_leggi, name='dev_telegram_leggi'),
        path('dev/telegram/invia/', views.dev_telegram_invia, name='dev_telegram_invia'),
        path('dev/whatsapp/invia/', views.dev_whatsapp_invia, name='dev_whatsapp_invia'),
    ]
