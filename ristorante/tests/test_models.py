from django.test import TestCase
from django.contrib.auth.models import User, Group
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
            posti=4,
            forma='R',
            stato='L'
        )
    
    def test_tavolo_str(self):
        self.assertEqual(str(self.tavolo), 'Tavolo 1 - Test Sala')
    
    def test_tavolo_stato_libero(self):
        self.assertEqual(self.tavolo.stato, 'L')
    
    def test_tavolo_forma_rotondo(self):
        self.assertEqual(self.tavolo.forma, 'R')


class CategoriaModelTest(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(
            nome='Primi',
            ordine=1,
            icona='🍝'
        )
    
    def test_categoria_str(self):
        self.assertEqual(str(self.categoria), 'Primi')


class PiattoModelTest(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1)
        self.piatto = Piatto.objects.create(
            nome='Spaghetti Carbonara',
            categoria=self.categoria,
            prezzo=12.50,
            disponibile=True
        )
    
    def test_piatto_str(self):
        self.assertEqual(str(self.piatto), 'Spaghetti Carbonara')
    
    def test_piatto_prezzo(self):
        self.assertEqual(self.piatto.prezzo, 12.50)
    
    def test_piatto_disponibile(self):
        self.assertTrue(self.piatto.disponibile)


class PrenotazioneModelTest(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, posti=4, stato='L'
        )
        self.prenotazione = Prenotazione.objects.create(
            tavolo=self.tavolo,
            nome_cliente='Mario Rossi',
            num_persone=4,
            data_ora=timezone.now() + timezone.timedelta(days=1),
            telefono='+391234567890',
            stato=Prenotazione.STATO_IN_ATTESA
        )
    
    def test_prenotazione_str(self):
        self.assertIn('Mario Rossi', str(self.prenotazione))
    
    def test_prenotazione_stato_default(self):
        self.assertEqual(self.prenotazione.stato, Prenotazione.STATO_IN_ATTESA)


class OrdineModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, posti=4, stato='O'
        )
        self.ordine = Ordine.objects.create(
            tavolo=self.tavolo,
            cameriere=None,
            stato=Ordine.STATO_IN_ATTESA
        )
    
    def test_ordine_str(self):
        self.assertIn('Tavolo 1', str(self.ordine))
    
    def test_ordine_stato_default(self):
        self.assertEqual(self.ordine.stato, Ordine.STATO_IN_ATTESA)


class OrdineItemModelTest(TestCase):
    def setUp(self):
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, posti=4, stato='O'
        )
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1)
        self.piatto = Piatto.objects.create(
            nome='Spaghetti', categoria=self.categoria, prezzo=10.00
        )
        self.ordine = Ordine.objects.create(tavolo=self.tavolo)
        self.item = OrdineItem.objects.create(
            ordine=self.ordine,
            piatto=self.piatto,
            quantita=2,
            stato=OrdineItem.STATO_IN_ATTESA
        )
    
    def test_item_str(self):
        self.assertIn('Spaghetti', str(self.item))
    
    def test_item_stato_default(self):
        self.assertEqual(self.item.stato, OrdineItem.STATO_IN_ATTESA)