from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User, Group
from django.utils import timezone
from ristorante.models import (
    Sala, Tavolo, Categoria, Piatto,
    Prenotazione, Ordine, OrdineItem
)


class SalaModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)

    def test_sala_str(self):
        self.assertEqual(str(self.sala), 'Test Sala')

    def test_sala_larghezza(self):
        self.assertEqual(self.sala.larghezza, 20)


class TavoloModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala,
            numero=1,
            capacita=4,
            forma=Tavolo.FORMA_ROTONDO,
            stato=Tavolo.STATO_LIBERO,
        )

    def test_tavolo_str(self):
        self.assertIn('1', str(self.tavolo))
        self.assertIn('Test Sala', str(self.tavolo))

    def test_tavolo_stato_libero(self):
        self.assertEqual(self.tavolo.stato, Tavolo.STATO_LIBERO)

    def test_tavolo_forma_rotondo(self):
        self.assertEqual(self.tavolo.forma, Tavolo.FORMA_ROTONDO)


class CategoriaModelTest(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1, icona='🍝')

    def test_categoria_str(self):
        self.assertEqual(str(self.categoria), 'Primi')


class PiattoModelTest(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1)
        self.piatto = Piatto.objects.create(
            nome='Spaghetti Carbonara',
            categoria=self.categoria,
            prezzo=Decimal('12.50'),
            disponibile=True,
        )

    def test_piatto_str(self):
        self.assertIn('Spaghetti Carbonara', str(self.piatto))

    def test_piatto_prezzo(self):
        self.assertEqual(self.piatto.prezzo, Decimal('12.50'))

    def test_piatto_disponibile(self):
        self.assertTrue(self.piatto.disponibile)


class PrenotazioneModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, capacita=4, stato=Tavolo.STATO_LIBERO
        )
        self.prenotazione = Prenotazione.objects.create(
            tavolo=self.tavolo,
            nome_cliente='Mario Rossi',
            num_persone=4,
            data_ora=timezone.now() + timezone.timedelta(days=1),
            telefono='+391234567890',
            stato=Prenotazione.STATO_ATTESA,
        )

    def test_prenotazione_str(self):
        self.assertIn('Mario Rossi', str(self.prenotazione))

    def test_prenotazione_stato_default(self):
        self.assertEqual(self.prenotazione.stato, Prenotazione.STATO_ATTESA)


class OrdineModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, capacita=4, stato=Tavolo.STATO_OCCUPATO
        )
        self.ordine = Ordine.objects.create(
            tavolo=self.tavolo,
            cameriere=None,
            stato=Ordine.STATO_APERTO,
        )

    def test_ordine_str(self):
        self.assertIn('Tavolo 1', str(self.ordine))

    def test_ordine_stato_default(self):
        self.assertEqual(self.ordine.stato, Ordine.STATO_APERTO)


class OrdineItemModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, capacita=4, stato=Tavolo.STATO_OCCUPATO
        )
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1)
        self.piatto = Piatto.objects.create(
            nome='Spaghetti', categoria=self.categoria, prezzo=Decimal('10.00')
        )
        self.ordine = Ordine.objects.create(tavolo=self.tavolo)
        self.item = OrdineItem.objects.create(
            ordine=self.ordine,
            piatto=self.piatto,
            quantita=2,
            prezzo_unitario=self.piatto.prezzo,
            stato=OrdineItem.STATO_ATTESA,
        )

    def test_item_str(self):
        self.assertIn('Spaghetti', str(self.item))

    def test_item_stato_default(self):
        self.assertEqual(self.item.stato, OrdineItem.STATO_ATTESA)
