from django.contrib import admin
from django.urls import path, include
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
    path('amministrazione/', admin.site.urls),
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
    path('prenota/<int:sala_id>/<int:numero_tavolo>/', views.prenota,            name='prenota'),
    path('prenota/conferma/<int:prenotazione_id>/', views.conferma_prenotazione, name='conferma_prenotazione'),
    path('prenota/caparra/<int:prenotazione_id>/',  views.pagamento_caparra,     name='pagamento_caparra'),

    # ══════════════════════════════════════════════════════════
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
    path('sala/capo/sala/<int:sala_id>/', views.mappa_sala,  name='mappa_sala'),

    # Aggiorna stato tavolo (usato da cameriere e capo area)
    path('sala/tavolo/<int:tavolo_id>/stato/', views.aggiorna_stato_tavolo, name='aggiorna_stato_tavolo'),

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

    # ══════════════════════════════════════════════════════════
    #  API — STM32 + ESP32 + REST
    # ══════════════════════════════════════════════════════════
    # STM32 (BLE -> HTTP bridge)
    path('api/tavolo/<int:sala_id>/<int:numero_tavolo>/', views.api_stato_tavolo, name='api_stato_tavolo'),
    path('api/sala/<int:sala_id>/',                        views.api_sala_completa, name='api_sala_completa'),
    # ESP32 (WiFi direct)
    path('api/esp32/tavolo/<int:sala_id>/<int:numero_tavolo>/', views.api_esp32_tavolo, name='api_esp32_tavolo'),
    path('api/esp32/sala/<int:sala_id>/',                     views.api_esp32_sala,     name='api_esp32_sala'),
    path('api/', include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('dev/', views.dev_panel, name='dev_panel'),
    ]
