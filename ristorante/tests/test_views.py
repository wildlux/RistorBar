from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from ristorante.models import Sala, Tavolo, Categoria, Piatto


class APIViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
        self.tavolo = Tavolo.objects.create(
            sala=self.sala, numero=1, posti=4, stato='L'
        )
        self.categoria = Categoria.objects.create(nome='Primi', ordine=1)
        self.piatto = Piatto.objects.create(
            nome='Pasta', categoria=self.categoria, prezzo='10.00', disponibile=True
        )
        
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
        self.staff_user = User.objects.create_user(
            username='staff', password='staffpass', is_staff=True
        )
    
    def test_api_tavolo_stato_get(self):
        response = self.client.get(f'/api/tavolo/{self.sala.id}/1/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('t', response.json())
        self.assertEqual(response.json()['t'], 1)
    
    def test_api_tavolo_not_found(self):
        response = self.client.get('/api/tavolo/999/99/')
        self.assertEqual(response.status_code, 404)
    
    def test_api_menu_requires_auth(self):
        response = self.client.get('/api/piatti/')
        self.assertEqual(response.status_code, 401)
    
    def test_api_menu_with_auth(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.get('/api/piatti/')
        self.assertEqual(response.status_code, 200)
    
    def test_api_sale_list(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.get('/api/sale/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)


class HomepageViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.sala = Sala.objects.create(nome='Test Sala', larghezza=20, altezza=15)
    
    def test_homepage_loads(self):
        response = self.client.get('/homepage')
        self.assertEqual(response.status_code, 200)
    
    def test_menu_view_loads(self):
        response = self.client.get(f'/menu/{self.sala.id}/1/')
        self.assertEqual(response.status_code, 200)


class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass'
        )
    
    def test_login_page_loads(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
    
    def test_login_success(self):
        response = self.client.post('/login/', {
            'username': 'testuser',
            'password': 'testpass'
        })
        self.assertEqual(response.status_code, 302)
    
    def test_login_failure(self):
        response = self.client.post('/login/', {
            'username': 'testuser',
            'password': 'wrongpass'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context or {})