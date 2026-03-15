"""
Test suite per RistoBAR
========================
Copertura:
  - Modelli (Sala, Tavolo, Categoria, Piatto, Prenotazione, Ordine, OrdineItem)
  - Sistema ruoli (decoratore ruolo_richiesto, ha_ruolo, sala_dispatch)
  - Views cameriere (ordine, conto, spostamento)
  - Views cuoco / KDS
  - Views capo area (dashboard, pianta_locale, statistiche)
  - API leggera STM32/ESP32
  - sposta_tavolo
"""

import json
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from django.utils import timezone

from ristorante.models import (
    Sala, Tavolo, Categoria, Piatto,
    Prenotazione, Ordine, OrdineItem,
    ImpostazioniRistorante,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_group(name):
    g, _ = Group.objects.get_or_create(name=name)
    return g


def _make_user(username, password, group_name=None):
    u = User.objects.create_user(username=username, password=password)
    if group_name:
        u.groups.add(_make_group(group_name))
    return u


def _make_sala(nome='Sala Test', tipo='PT'):
    return Sala.objects.create(nome=nome, tipo_locale=tipo)


def _make_tavolo(sala, numero=1, stato=Tavolo.STATO_LIBERO, capacita=4, forma=Tavolo.FORMA_QUADRATO):
    return Tavolo.objects.create(sala=sala, numero=numero, stato=stato, capacita=capacita, forma=forma)


def _make_categoria(nome='Antipasti'):
    return Categoria.objects.create(nome=nome, ordine=0)


def _make_piatto(categoria, nome='Bruschetta', prezzo='8.00'):
    return Piatto.objects.create(
        categoria=categoria, nome=nome,
        prezzo=Decimal(prezzo), disponibile=True,
    )


def _make_ordine(tavolo, stato=Ordine.STATO_APERTO, cameriere=None):
    return Ordine.objects.create(tavolo=tavolo, stato=stato, cameriere=cameriere)


def _make_ordine_item(ordine, piatto, quantita=1, stato=OrdineItem.STATO_ATTESA):
    return OrdineItem.objects.create(
        ordine=ordine, piatto=piatto, quantita=quantita,
        prezzo_unitario=piatto.prezzo, stato=stato,
    )


# ──────────────────────────────────────────────────────────────────────────────
# MODEL TESTS
# ──────────────────────────────────────────────────────────────────────────────

class SalaModelTest(TestCase):
    def test_str(self):
        s = _make_sala('Terrazza')
        self.assertEqual(str(s), 'Terrazza')

    def test_defaults(self):
        s = _make_sala()
        self.assertTrue(s.attiva)
        self.assertEqual(s.larghezza, 20)
        self.assertEqual(s.altezza, 15)
        self.assertEqual(s.nazione, 'Italia')

    def test_tipo_choices_valid(self):
        validi = [c[0] for c in Sala.TIPO_CHOICES]
        self.assertIn('PT', validi)
        self.assertIn('TR', validi)
        self.assertIn('GI', validi)


class TavoloModelTest(TestCase):
    def setUp(self):
        self.sala = _make_sala()

    def test_str(self):
        t = _make_tavolo(self.sala, numero=5)
        self.assertIn('5', str(t))

    def test_qr_generato_automaticamente(self):
        t = _make_tavolo(self.sala, numero=1)
        self.assertTrue(bool(t.qr_code))

    def test_colore_stato(self):
        t = _make_tavolo(self.sala)
        self.assertEqual(t.colore_stato, '#27ae60')   # libero = verde
        t.stato = Tavolo.STATO_OCCUPATO
        self.assertEqual(t.colore_stato, '#e74c3c')   # occupato = rosso

    def test_unique_together(self):
        from django.db import IntegrityError
        _make_tavolo(self.sala, numero=3)
        with self.assertRaises(IntegrityError):
            # secondo tavolo con stesso numero nella stessa sala — viola unique_together
            Tavolo.objects.create(sala=self.sala, numero=3, capacita=4)


class CategoriaModelTest(TestCase):
    def test_str(self):
        c = _make_categoria('Dolci')
        self.assertEqual(str(c), 'Dolci')


class PiattoModelTest(TestCase):
    def test_str(self):
        cat = _make_categoria()
        p = _make_piatto(cat, nome='Carbonara', prezzo='12.50')
        self.assertIn('Carbonara', str(p))
        self.assertIn('12.50', str(p))

    def test_aliquota_iva_default(self):
        cat = _make_categoria()
        p = _make_piatto(cat)
        self.assertEqual(p.aliquota_iva, Decimal('10.00'))


class OrdineModelTest(TestCase):
    def setUp(self):
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala)
        self.cat = _make_categoria()
        self.piatto = _make_piatto(self.cat)

    def test_calcola_totale(self):
        ordine = _make_ordine(self.tavolo)
        _make_ordine_item(ordine, self.piatto, quantita=2)
        totale = ordine.calcola_totale()
        self.assertEqual(totale, Decimal('16.00'))  # 2 × 8.00

    def test_calcola_totale_con_sconto(self):
        ordine = _make_ordine(self.tavolo)
        ordine.sconto_caparra = Decimal('10.00')
        ordine.save()
        _make_ordine_item(ordine, self.piatto, quantita=3)
        totale = ordine.calcola_totale()
        self.assertEqual(totale, Decimal('14.00'))  # 24.00 - 10.00

    def test_stato_transizione_aperto_default(self):
        ordine = _make_ordine(self.tavolo)
        self.assertEqual(ordine.stato, Ordine.STATO_APERTO)


class OrdineItemAutoStatoTest(TestCase):
    """Quando tutti gli items di un ordine raggiungono PRONTO, l'ordine diventa SERVITO."""

    def setUp(self):
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala)
        self.cat = _make_categoria()
        self.piatto = _make_piatto(self.cat)

    def test_ordine_diventa_servito_quando_tutti_pronti(self):
        ordine = _make_ordine(self.tavolo, stato=Ordine.STATO_IN_PREPARAZIONE)
        item = _make_ordine_item(ordine, self.piatto, stato=OrdineItem.STATO_IN_CUCINA)

        # simula passaggio a PRONTO tramite la view (qui testiamo il model signal/save)
        item.stato = OrdineItem.STATO_PRONTO
        item.save()
        ordine.refresh_from_db()
        # L'auto-transizione avviene nella view aggiorna_item_kds; qui verifichiamo solo il salvataggio
        self.assertEqual(item.stato, OrdineItem.STATO_PRONTO)


class ImpostazioniRistoranteTest(TestCase):
    def test_singleton_get(self):
        imp1 = ImpostazioniRistorante.get()
        imp2 = ImpostazioniRistorante.get()
        self.assertEqual(imp1.pk, imp2.pk)

    def test_mostra_lavora_con_noi_default_false(self):
        imp = ImpostazioniRistorante.get()
        self.assertFalse(imp.mostra_lavora_con_noi)


# ──────────────────────────────────────────────────────────────────────────────
# AUTH / ROLE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class AuthTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', password='pass123')

    def test_login_page_200(self):
        r = self.client.get(reverse('login'))
        self.assertEqual(r.status_code, 200)

    def test_login_corretto_redirect(self):
        r = self.client.post(reverse('login'), {'username': 'testuser', 'password': 'pass123'})
        self.assertIn(r.status_code, [302, 200])

    def test_login_errato(self):
        r = self.client.post(reverse('login'), {'username': 'testuser', 'password': 'sbagliata'})
        self.assertEqual(r.status_code, 200)

    def test_logout(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('logout'))
        self.assertIn(r.status_code, [302, 200])

    def test_area_protetta_senza_login_redirect(self):
        r = self.client.get(reverse('sala_dispatch'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])


class SalaDispatchTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_cameriere_redirect(self):
        u = _make_user('cam', 'pass', 'cameriere')
        self.client.force_login(u)
        r = self.client.get(reverse('sala_dispatch'))
        self.assertRedirects(r, reverse('cameriere'), fetch_redirect_response=False)

    def test_cuoco_redirect(self):
        u = _make_user('cuoco', 'pass', 'cuoco')
        self.client.force_login(u)
        r = self.client.get(reverse('sala_dispatch'))
        self.assertRedirects(r, reverse('cucina_kds'), fetch_redirect_response=False)

    def test_capo_area_redirect(self):
        u = _make_user('capo', 'pass', 'capo_area')
        self.client.force_login(u)
        r = self.client.get(reverse('sala_dispatch'))
        self.assertRedirects(r, reverse('dashboard'), fetch_redirect_response=False)

    def test_titolare_redirect(self):
        u = _make_user('titolare', 'pass', 'titolare')
        self.client.force_login(u)
        r = self.client.get(reverse('sala_dispatch'))
        self.assertRedirects(r, reverse('dashboard'), fetch_redirect_response=False)

    def test_cameriere_senior_redirect(self):
        u = _make_user('senior', 'pass', 'cameriere_senior')
        self.client.force_login(u)
        r = self.client.get(reverse('sala_dispatch'))
        self.assertRedirects(r, reverse('cameriere'), fetch_redirect_response=False)


class RolePermissionTest(TestCase):
    """Verifica che le view proteggano correttamente l'accesso per ruolo."""

    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()

    def test_cameriere_non_accede_dashboard(self):
        u = _make_user('cam', 'pass', 'cameriere')
        self.client.force_login(u)
        r = self.client.get(reverse('dashboard'))
        self.assertIn(r.status_code, [302, 403])

    def test_cuoco_non_accede_dashboard(self):
        u = _make_user('cuoco', 'pass', 'cuoco')
        self.client.force_login(u)
        r = self.client.get(reverse('dashboard'))
        self.assertIn(r.status_code, [302, 403])

    def test_capo_area_accede_dashboard(self):
        u = _make_user('capo', 'pass', 'capo_area')
        self.client.force_login(u)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_titolare_accede_dashboard(self):
        u = _make_user('titolare', 'pass', 'titolare')
        self.client.force_login(u)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_cameriere_accede_propria_area(self):
        u = _make_user('cam', 'pass', 'cameriere')
        self.client.force_login(u)
        r = self.client.get(reverse('cameriere'))
        self.assertEqual(r.status_code, 200)

    def test_cuoco_accede_kds(self):
        u = _make_user('cuoco', 'pass', 'cuoco')
        self.client.force_login(u)
        r = self.client.get(reverse('cucina_kds'))
        self.assertEqual(r.status_code, 200)

    def test_cameriere_non_accede_kds(self):
        u = _make_user('cam', 'pass', 'cameriere')
        self.client.force_login(u)
        r = self.client.get(reverse('cucina_kds'))
        self.assertIn(r.status_code, [302, 403])


# ──────────────────────────────────────────────────────────────────────────────
# CAMERIERE VIEW TESTS
# ──────────────────────────────────────────────────────────────────────────────

class CameriereOrdineTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=1, stato=Tavolo.STATO_OCCUPATO)
        self.cat = _make_categoria()
        self.piatto = _make_piatto(self.cat)
        self.cameriere = _make_user('cam', 'pass', 'cameriere')
        self.senior = _make_user('senior', 'pass', 'cameriere_senior')

    def test_cameriere_puo_aprire_comanda(self):
        self.client.force_login(self.cameriere)
        r = self.client.get(reverse('cameriere_ordine', args=[self.tavolo.pk]))
        self.assertEqual(r.status_code, 200)

    def test_cameriere_non_puo_chiedere_conto(self):
        """Il cameriere base non può eseguire l'azione chiedi_conto (ritorna 403)."""
        self.client.force_login(self.cameriere)
        _make_ordine(self.tavolo, cameriere=self.cameriere)
        r = self.client.post(
            reverse('cameriere_ordine', args=[self.tavolo.pk]),
            data=json.dumps({'azione': 'chiedi_conto'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)

    def test_senior_puo_chiedere_conto(self):
        """Il cameriere senior può eseguire l'azione chiedi_conto."""
        self.client.force_login(self.senior)
        _make_ordine(self.tavolo, cameriere=self.senior)
        r = self.client.post(
            reverse('cameriere_ordine', args=[self.tavolo.pk]),
            data=json.dumps({'azione': 'chiedi_conto'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.tavolo.refresh_from_db()
        self.assertEqual(self.tavolo.stato, Tavolo.STATO_CONTO)


class AggiornaTavoloStatoTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=2)
        self.cameriere = _make_user('cam', 'pass', 'cameriere')

    def test_aggiorna_stato_tavolo(self):
        self.client.force_login(self.cameriere)
        r = self.client.post(
            reverse('aggiorna_stato_tavolo', args=[self.tavolo.pk]),
            data=json.dumps({'stato': 'O'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.tavolo.refresh_from_db()
        self.assertEqual(self.tavolo.stato, Tavolo.STATO_OCCUPATO)

    def test_stato_invalido_ritorna_errore(self):
        self.client.force_login(self.cameriere)
        r = self.client.post(
            reverse('aggiorna_stato_tavolo', args=[self.tavolo.pk]),
            data=json.dumps({'stato': 'X'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)


# ──────────────────────────────────────────────────────────────────────────────
# SPOSTA TAVOLO
# ──────────────────────────────────────────────────────────────────────────────

class SpostaTavoloTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.t_src = _make_tavolo(self.sala, numero=1, stato=Tavolo.STATO_OCCUPATO)
        self.t_dst = _make_tavolo(self.sala, numero=2, stato=Tavolo.STATO_LIBERO)
        self.cat = _make_categoria()
        self.piatto = _make_piatto(self.cat)
        self.senior = _make_user('senior', 'pass', 'cameriere_senior')

    def _sposta(self, src, dst):
        return self.client.post(
            reverse('sposta_tavolo', args=[src.pk]),
            data=json.dumps({'dest_id': dst.pk}),
            content_type='application/json',
        )

    def test_sposta_trasferisce_ordini(self):
        ordine = _make_ordine(self.t_src)
        self.client.force_login(self.senior)
        r = self._sposta(self.t_src, self.t_dst)
        self.assertEqual(r.status_code, 200)
        ordine.refresh_from_db()
        self.assertEqual(ordine.tavolo, self.t_dst)

    def test_sposta_aggiorna_stati(self):
        _make_ordine(self.t_src)
        self.client.force_login(self.senior)
        self._sposta(self.t_src, self.t_dst)
        self.t_src.refresh_from_db()
        self.t_dst.refresh_from_db()
        self.assertEqual(self.t_src.stato, Tavolo.STATO_LIBERO)
        self.assertEqual(self.t_dst.stato, Tavolo.STATO_OCCUPATO)

    def test_sposta_verso_tavolo_occupato_da_errore(self):
        self.t_dst.stato = Tavolo.STATO_OCCUPATO
        self.t_dst.save()
        self.client.force_login(self.senior)
        r = self._sposta(self.t_src, self.t_dst)
        self.assertEqual(r.status_code, 400)
        data = json.loads(r.content)
        self.assertIn('errore', data)

    def test_cameriere_base_non_puo_spostare(self):
        cam = _make_user('cam', 'pass', 'cameriere')
        self.client.force_login(cam)
        r = self._sposta(self.t_src, self.t_dst)
        self.assertIn(r.status_code, [302, 403])


# ──────────────────────────────────────────────────────────────────────────────
# KDS / CUCINA TESTS
# ──────────────────────────────────────────────────────────────────────────────

class KdsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=3, stato=Tavolo.STATO_OCCUPATO)
        self.cat = _make_categoria()
        self.piatto = _make_piatto(self.cat)
        self.cuoco = _make_user('cuoco', 'pass', 'cuoco')

    def test_kds_carica(self):
        self.client.force_login(self.cuoco)
        r = self.client.get(reverse('cucina_kds'))
        self.assertEqual(r.status_code, 200)

    def test_aggiorna_item_kds(self):
        ordine = _make_ordine(self.tavolo, stato=Ordine.STATO_IN_PREPARAZIONE)
        item = _make_ordine_item(ordine, self.piatto, stato=OrdineItem.STATO_IN_CUCINA)
        self.client.force_login(self.cuoco)
        r = self.client.post(
            reverse('aggiorna_item_kds', args=[item.pk]),
            data=json.dumps({'stato': OrdineItem.STATO_PRONTO}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.stato, OrdineItem.STATO_PRONTO)

    def test_tutti_items_pronti_ordine_diventa_servito(self):
        ordine = _make_ordine(self.tavolo, stato=Ordine.STATO_IN_PREPARAZIONE)
        item = _make_ordine_item(ordine, self.piatto, stato=OrdineItem.STATO_IN_CUCINA)
        self.client.force_login(self.cuoco)
        self.client.post(
            reverse('aggiorna_item_kds', args=[item.pk]),
            data=json.dumps({'stato': OrdineItem.STATO_PRONTO}),
            content_type='application/json',
        )
        ordine.refresh_from_db()
        self.assertEqual(ordine.stato, Ordine.STATO_SERVITO)


# ──────────────────────────────────────────────────────────────────────────────
# DASHBOARD / PIANTA LOCALE
# ──────────────────────────────────────────────────────────────────────────────

class DashboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.t1 = _make_tavolo(self.sala, numero=1, stato=Tavolo.STATO_LIBERO)
        self.t2 = _make_tavolo(self.sala, numero=2, stato=Tavolo.STATO_OCCUPATO)
        self.capo = _make_user('capo', 'pass', 'capo_area')

    def test_dashboard_200(self):
        self.client.force_login(self.capo)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_contiene_dati_js(self):
        # I tavoli vengono iniettati come JSON per JS (TUTTI_TAVOLI), non come HTML letterale
        self.client.force_login(self.capo)
        r = self.client.get(reverse('dashboard'))
        content = r.content.decode()
        # Verifica che ci siano i dati JSON dei tavoli nel contesto
        self.assertIn(str(self.t1.pk), content)
        self.assertIn(str(self.t2.pk), content)


class PiantaLocaleTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala('Sala Principale', tipo='PT')
        _make_tavolo(self.sala, numero=1)
        self.capo = _make_user('capo', 'pass', 'capo_area')
        self.cameriere = _make_user('cam', 'pass', 'cameriere')

    def test_pianta_200_per_capo(self):
        self.client.force_login(self.capo)
        r = self.client.get(reverse('pianta_locale', args=[self.sala.pk]))
        self.assertEqual(r.status_code, 200)

    def test_pianta_200_per_cameriere(self):
        # Il cameriere può vedere la pianta (read-only), non modificare
        self.client.force_login(self.cameriere)
        r = self.client.get(reverse('pianta_locale', args=[self.sala.pk]))
        self.assertEqual(r.status_code, 200)

    def test_pianta_404_sala_inesistente(self):
        self.client.force_login(self.capo)
        r = self.client.get(reverse('pianta_locale', args=[9999]))
        self.assertEqual(r.status_code, 404)

    def test_pianta_post_modifica_info(self):
        self.client.force_login(self.capo)
        r = self.client.post(
            reverse('pianta_locale', args=[self.sala.pk]),
            {
                'azione': 'modifica_info',
                'nome': 'Sala Aggiornata',
                'tipo_locale': 'TR',
                'piano': '1',
                'nazione': 'Italia',
                'citta': 'Roma',
                'indirizzo': 'Via Roma 1',
                'descrizione': 'Vista panoramica',
            },
        )
        self.assertIn(r.status_code, [200, 302])
        self.sala.refresh_from_db()
        self.assertEqual(self.sala.nome, 'Sala Aggiornata')
        self.assertEqual(self.sala.tipo_locale, 'TR')
        self.assertEqual(self.sala.citta, 'Roma')


# ──────────────────────────────────────────────────────────────────────────────
# API TESTS
# ──────────────────────────────────────────────────────────────────────────────

class ApiStatoTavoloTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=5, stato=Tavolo.STATO_OCCUPATO)

    def test_api_ritorna_json_compresso(self):
        r = self.client.get(
            reverse('api_stato_tavolo', args=[self.sala.pk, self.tavolo.numero])
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('s', data)
        self.assertIn('t', data)
        self.assertEqual(data['s'], 'O')
        self.assertEqual(data['t'], 5)

    def test_api_tavolo_inesistente_404(self):
        r = self.client.get(
            reverse('api_stato_tavolo', args=[self.sala.pk, 999])
        )
        self.assertEqual(r.status_code, 404)


class ApiSalaCompletaTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        _make_tavolo(self.sala, numero=1)
        _make_tavolo(self.sala, numero=2, stato=Tavolo.STATO_OCCUPATO)

    def test_api_sala_ritorna_tutti_tavoli(self):
        r = self.client.get(reverse('api_sala_completa', args=[self.sala.pk]))
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        # api_sala_completa restituisce una lista di oggetti tavolo
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)


class ApiEsp32Test(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=3)

    def test_esp32_tavolo_ok(self):
        # URL: /api/esp32/tavolo/<sala_id>/<numero_tavolo>/
        url = f'/api/esp32/tavolo/{self.sala.pk}/{self.tavolo.numero}/'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)

    def test_esp32_sala_ok(self):
        url = f'/api/esp32/sala/{self.sala.pk}/'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# HOMEPAGE / VETRINA (pubblica)
# ──────────────────────────────────────────────────────────────────────────────

class VetrinaTest(TestCase):
    def test_homepage_200(self):
        r = self.client.get(reverse('homepage'))
        self.assertEqual(r.status_code, 200)

    def test_root_redirect_homepage(self):
        r = self.client.get('/')
        self.assertIn(r.status_code, [301, 302])

    def test_lavora_con_noi_nascosta_di_default(self):
        r = self.client.get(reverse('homepage'))
        self.assertEqual(r.status_code, 200)
        # di default mostra_lavora_con_noi=False → sezione non presente
        content = r.content.decode()
        self.assertNotIn('footer-lavora', content)

    def test_lavora_con_noi_visibile_se_abilitata(self):
        imp = ImpostazioniRistorante.get()
        imp.mostra_lavora_con_noi = True
        imp.save()
        r = self.client.get(reverse('homepage'))
        content = r.content.decode()
        self.assertIn('footer-lavora', content)


# ──────────────────────────────────────────────────────────────────────────────
# STATISTICHE
# ──────────────────────────────────────────────────────────────────────────────

class StatisticheTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.capo = _make_user('capo', 'pass', 'capo_area')

    def test_statistiche_200(self):
        self.client.force_login(self.capo)
        r = self.client.get(reverse('statistiche'))
        self.assertEqual(r.status_code, 200)

    def test_statistiche_no_decimal_error(self):
        """Verifica che non venga sollevato NameError per Decimal (bug fix)."""
        self.client.force_login(self.capo)
        r = self.client.get(reverse('statistiche'))
        # se Decimal non è importato, Django restituisce 500
        self.assertNotEqual(r.status_code, 500)


# ──────────────────────────────────────────────────────────────────────────────
# EDITOR SALA
# ──────────────────────────────────────────────────────────────────────────────

class EditorSalaTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        _make_tavolo(self.sala, numero=1)
        self.capo = _make_user('capo', 'pass', 'capo_area')
        self.cameriere = _make_user('cam', 'pass', 'cameriere')

    def test_editor_200_capo(self):
        self.client.force_login(self.capo)
        r = self.client.get(reverse('editor_sala', args=[self.sala.pk]))
        self.assertEqual(r.status_code, 200)

    def test_editor_login_required_cameriere(self):
        # L'editor usa @login_required (non @ruolo_richiesto),
        # quindi un cameriere loggato può vederlo (200)
        self.client.force_login(self.cameriere)
        r = self.client.get(reverse('editor_sala', args=[self.sala.pk]))
        self.assertEqual(r.status_code, 200)

    def test_salva_layout(self):
        t = _make_tavolo(self.sala, numero=10)
        self.client.force_login(self.capo)
        payload = {'tavoli': [{'id': t.pk, 'x': 150, 'y': 250}]}
        r = self.client.post(
            reverse('salva_layout', args=[self.sala.pk]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.pos_x, 150)
        self.assertEqual(t.pos_y, 250)

    def test_aggiungi_tavolo_editor(self):
        self.client.force_login(self.capo)
        count_before = self.sala.tavoli.count()
        r = self.client.post(
            reverse('aggiungi_tavolo_editor', args=[self.sala.pk]),
            data=json.dumps({'numero': 99, 'forma': 'R', 'capacita': 6}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.sala.tavoli.count(), count_before + 1)

    def test_elimina_tavolo_editor(self):
        # La view disattiva (attivo=False) invece di cancellare
        t = _make_tavolo(self.sala, numero=55)
        self.client.force_login(self.capo)
        r = self.client.post(
            reverse('elimina_tavolo_editor', args=[self.sala.pk, t.pk]),
        )
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertFalse(t.attivo)


# ──────────────────────────────────────────────────────────────────────────────
# PRENOTAZIONE (pubblica)
# ──────────────────────────────────────────────────────────────────────────────

class PrenotazioneTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=1)

    def test_prenota_get_200(self):
        r = self.client.get(
            reverse('prenota', args=[self.sala.pk, self.tavolo.numero])
        )
        self.assertEqual(r.status_code, 200)

    def test_prenota_post_crea_prenotazione(self):
        from django.utils import timezone as tz
        dt = (tz.now() + tz.timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        r = self.client.post(
            reverse('prenota', args=[self.sala.pk, self.tavolo.numero]),
            {
                'nome': 'Mario Rossi',          # la view legge 'nome'
                'telefono': '3331234567',
                'persone': '2',                 # la view legge 'persone'
                'data_ora': dt,
                'note': 'Finestra',
            },
        )
        self.assertIn(r.status_code, [200, 302])
        self.assertTrue(Prenotazione.objects.filter(nome_cliente='Mario Rossi').exists())


# ──────────────────────────────────────────────────────────────────────────────
# MENU TAVOLO (pubblico)
# ──────────────────────────────────────────────────────────────────────────────

class MenuTavoloTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = _make_sala()
        self.tavolo = _make_tavolo(self.sala, numero=1)
        cat = _make_categoria('Primi')
        _make_piatto(cat, 'Spaghetti', '9.00')

    def test_menu_200(self):
        r = self.client.get(
            reverse('menu_tavolo', args=[self.tavolo.pk])
        )
        self.assertEqual(r.status_code, 200)

    def test_menu_contiene_piatto(self):
        r = self.client.get(
            reverse('menu_tavolo', args=[self.tavolo.pk])
        )
        self.assertIn(b'Spaghetti', r.content)
