"""
Comando: python manage.py demo_data
Popola il database con dati di esempio completi per la demo.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from ristorante.models import Sala, Tavolo, Categoria, Piatto, ImpostazioniRistorante, Sede, Contatto


UTENTI_DEMO = [
    # (username, password, email, first_name, last_name, gruppo, is_staff)
    ('admin',      'admin123',      'admin@demo.it',      'Admin',   'Rossi',    None,                True),
    ('titolare',   'titolare123',   'titolare@demo.it',   'Marco',   'Ferrari',  'titolare',          True),
    ('capo_area',  'capo123',       'capo@demo.it',       'Laura',   'Bianchi',  'capo_area',         False),
    ('cameriere1', 'cam123',        'cam1@demo.it',       'Giulia',  'Verdi',    'cameriere',         False),
    ('cameriere2', 'cam123',        'cam2@demo.it',       'Luca',    'Mori',     'cameriere',         False),
    ('cassa1',     'cassa123',      'cassa1@demo.it',     'Roberto', 'Esposito', 'cameriere_senior',  False),
    ('cuoco1',     'cuoco123',      'cuoco1@demo.it',     'Antonio', 'Ricci',    'cuoco',             False),
    ('cuoco2',     'cuoco123',      'cuoco2@demo.it',     'Sofia',   'Conti',    'cuoco',             False),
]


class Command(BaseCommand):
    help = 'Crea dati demo per il ristorante'

    def handle(self, *args, **options):
        # Gruppi ruoli
        gruppi = {}
        for nome_gruppo in ['titolare', 'capo_area', 'cameriere', 'cameriere_senior', 'cuoco']:
            g, _ = Group.objects.get_or_create(name=nome_gruppo)
            gruppi[nome_gruppo] = g

        # Utenti demo
        for username, password, email, first, last, gruppo, is_staff in UTENTI_DEMO:
            if not User.objects.filter(username=username).exists():
                if username == 'admin':
                    u = User.objects.create_superuser(username, email, password)
                else:
                    u = User.objects.create_user(username, email, password,
                                                  first_name=first, last_name=last,
                                                  is_staff=is_staff)
                if gruppo:
                    u.groups.add(gruppi[gruppo])
                self.stdout.write(self.style.SUCCESS(f'  ✓ {username} [{gruppo or "superuser"}]'))

        # Sale
        sala1, _ = Sala.objects.get_or_create(nome='Sala Principale', defaults={
            'larghezza': 20, 'altezza': 15, 'svg_larghezza': 1200, 'svg_altezza': 700
        })
        sala2, _ = Sala.objects.get_or_create(nome='Terrazza', defaults={
            'larghezza': 15, 'altezza': 12, 'svg_larghezza': 900, 'svg_altezza': 600
        })

        # Tavoli sala principale (coordinate SVG pixel)
        config_tavoli = [
            (1, 'R', 2,  80,  80), (2, 'R', 2, 220,  80), (3, 'Q', 4, 380,  80),
            (4, 'Q', 4, 560,  80), (5, 'R', 6,  80, 250), (6, 'Q', 4, 260, 250),
            (7, 'T', 8, 460, 250), (8, 'Q', 4,  80, 450), (9, 'R', 2, 260, 450),
            (10,'Q', 4, 460, 450),
        ]
        for num, forma, cap, px, py in config_tavoli:
            Tavolo.objects.get_or_create(sala=sala1, numero=num, defaults={
                'forma': forma, 'capacita': cap, 'pos_x': px, 'pos_y': py
            })

        # Tavoli terrazza
        for i, num in enumerate(range(11, 16)):
            Tavolo.objects.get_or_create(sala=sala2, numero=num, defaults={
                'forma': 'R', 'capacita': 4,
                'pos_x': 80 + i * 160, 'pos_y': 100,
            })

        # Categorie menu
        categorie_data = [
            ('🍕', 'Pizze',          1),
            ('🥗', 'Antipasti',      2),
            ('🍝', 'Primi Piatti',   3),
            ('🥩', 'Secondi Piatti', 4),
            ('🥦', 'Contorni',       5),
            ('🍰', 'Dolci',          6),
            ('🍺', 'Birre',          7),
            ('🍷', 'Vini',           8),
            ('🥂', 'Cocktail',       9),
            ('🥤', 'Analcoliche',   10),
        ]
        categorie = {}
        for icona, nome, ordine in categorie_data:
            cat, _ = Categoria.objects.get_or_create(nome=nome, defaults={'icona': icona, 'ordine': ordine})
            categorie[nome] = cat

        # Piatti — 10 pizze + 10 pietanze + contorni + bevande/alcolici
        piatti_data = [
            # ── 10 PIZZE ─────────────────────────────────────────────────
            ('Pizze', 'Margherita',        'Pomodoro, fior di latte, basilico fresco',                   8.50,  ''),
            ('Pizze', 'Marinara',          'Pomodoro, aglio, origano, olio EVO',                         7.00,  ''),
            ('Pizze', 'Diavola',           'Pomodoro, mozzarella, salame piccante',                      10.00, ''),
            ('Pizze', 'Quattro Formaggi',  'Mozzarella, gorgonzola, scamorza, parmigiano',               11.50, 'Lattosio'),
            ('Pizze', 'Capricciosa',       'Mozzarella, prosciutto cotto, funghi, carciofi, olive',      12.00, 'Glutine'),
            ('Pizze', 'Prosciutto e Rucola','Mozzarella, prosciutto crudo DOP, rucola, grana',           13.00, 'Lattosio'),
            ('Pizze', 'Salmone',           'Mozzarella, salmone affumicato, zucchine, rucola',           13.50, 'Pesce'),
            ('Pizze', 'Vegetariana',       'Mozzarella, peperoni, melanzane, zucchine, pomodorini',      11.00, ''),
            ('Pizze', 'Carbonara',         'Mozzarella, guanciale, uova, pecorino, pepe nero',           12.50, 'Lattosio, Uova'),
            ('Pizze', 'Bufalina',          'Pomodoro, mozzarella di bufala DOP, basilico',               13.00, 'Lattosio'),

            # ── ANTIPASTI ─────────────────────────────────────────────────
            ('Antipasti', 'Bruschetta al pomodoro',      'Pane tostato, pomodorini, basilico, aglio',    6.50,  'Glutine'),
            ('Antipasti', 'Tagliere salumi e formaggi',  'Selezione di affettati e formaggi locali',    14.00,  'Lattosio'),
            ('Antipasti', 'Burrata con pomodori',        'Burrata fresca, datterini, olio EVO',          9.00,  'Lattosio'),
            ('Antipasti', 'Frittura di calamari',        'Calamari fritti, maionese al limone',         12.00,  'Pesce, Uova'),

            # ── PRIMI ─────────────────────────────────────────────────────
            ('Primi Piatti', 'Spaghetti alla carbonara', 'Guanciale, uova, pecorino, pepe nero',        13.00,  'Glutine, Uova, Lattosio'),
            ('Primi Piatti', 'Tagliatelle al ragù',      'Ragù di carne alla bolognese classico',       12.00,  'Glutine, Uova'),
            ('Primi Piatti', 'Risotto ai funghi porcini','Risotto cremoso, porcini freschi di stagione', 14.00, 'Lattosio'),
            ('Primi Piatti', 'Penne all\'arrabbiata',    'Pomodoro piccante, aglio, peperoncino',        9.50,  'Glutine'),
            ('Primi Piatti', 'Gnocchi al pesto',         'Gnocchi di patate, pesto genovese, pinoli',   11.00,  'Glutine, Frutta secca'),

            # ── SECONDI ───────────────────────────────────────────────────
            ('Secondi Piatti', 'Filetto di manzo',       '200g, cottura a scelta, contorno di stagione',24.00, ''),
            ('Secondi Piatti', 'Branzino al forno',      'Con patate, olive e pomodorini',              20.00,  'Pesce'),
            ('Secondi Piatti', 'Pollo alla cacciatora',  'Con olive, capperi, pomodoro e rosmarino',    16.00,  ''),
            ('Secondi Piatti', 'Saltimbocca alla romana','Vitello, prosciutto crudo, salvia',            18.00, 'Glutine'),
            ('Secondi Piatti', 'Salmone al vapore',      'Con verdure grigliate e salsa yogurt',        19.00,  'Pesce, Lattosio'),

            # ── CONTORNI ──────────────────────────────────────────────────
            ('Contorni', 'Patate al forno',              'Con rosmarino e aglio',                        5.00,  ''),
            ('Contorni', 'Insalata mista',               'Lattuga, pomodoro, cetriolo, carote',          4.50,  ''),
            ('Contorni', 'Verdure grigliate',            'Melanzane, zucchine, peperoni di stagione',    6.00,  ''),
            ('Contorni', 'Spinaci al burro',             'Con aglio e limone',                           5.00,  'Lattosio'),

            # ── DOLCI ─────────────────────────────────────────────────────
            ('Dolci', 'Tiramisù della casa',             'Ricetta tradizionale della nonna',             6.00,  'Glutine, Uova, Lattosio'),
            ('Dolci', 'Panna cotta',                     'Con coulis di frutti di bosco freschi',        5.50,  'Lattosio'),
            ('Dolci', 'Cannolo siciliano',               'Ricotta di pecora, gocce di cioccolato',       5.50,  'Glutine, Lattosio'),
            ('Dolci', 'Gelato artigianale (3 gusti)',    'Selezione del giorno',                         5.00,  'Lattosio, Uova'),

            # ── BIRRE ─────────────────────────────────────────────────────
            ('Birre', 'Peroni 0.4L',                     'Birra lager italiana classica',                4.00,  'Glutine'),
            ('Birre', 'Moretti 0.4L',                    'Birra chiara italiana',                        4.00,  'Glutine'),
            ('Birre', 'Birra artigianale IPA 0.4L',      'Birra artigianale locale, amara e aromatica',  6.00,  'Glutine'),
            ('Birre', 'Birra artigianale Weizen 0.5L',   'Birra di frumento non filtrata',               6.50,  'Glutine'),
            ('Birre', 'Corona 0.33L',                    'Birra messicana, servita con lime',            5.00,  'Glutine'),

            # ── VINI ──────────────────────────────────────────────────────
            ('Vini', 'Chianti Classico DOCG',            'Bottiglia 75cl — tannini morbidi, fruttato',  28.00,  ''),
            ('Vini', 'Pinot Grigio IGT',                 'Bottiglia 75cl — fresco, floreale',           22.00,  ''),
            ('Vini', 'Vino rosso della casa',            'Caraffa 25cl',                                 5.00,  ''),
            ('Vini', 'Vino bianco della casa',           'Caraffa 25cl',                                 5.00,  ''),
            ('Vini', 'Prosecco DOC',                     'Calice 12cl — secco, bollicine fini',          6.00,  ''),

            # ── COCKTAIL ──────────────────────────────────────────────────
            ('Cocktail', 'Aperol Spritz',                'Aperol, Prosecco, soda, arancia',              8.00,  ''),
            ('Cocktail', 'Negroni',                      'Gin, Campari, Vermouth rosso',                 9.00,  ''),
            ('Cocktail', 'Mojito',                       'Rum, menta, lime, zucchero, soda',             9.00,  ''),
            ('Cocktail', 'Hugo',                         'Prosecco, fiori di sambuco, menta, soda',      8.00,  ''),
            ('Cocktail', 'Gin Tonic',                    'Gin premium, acqua tonica, lime, cetriolo',    9.50,  ''),

            # ── ANALCOLICHE ───────────────────────────────────────────────
            ('Analcoliche', 'Acqua naturale 0.75L',      '',                                             2.50,  ''),
            ('Analcoliche', 'Acqua frizzante 0.75L',     '',                                             2.50,  ''),
            ('Analcoliche', 'Coca-Cola 0.33L',           '',                                             3.00,  ''),
            ('Analcoliche', 'Succo di frutta',           'Pesca, albicocca o arancia',                   3.00,  ''),
            ('Analcoliche', 'Limonata artigianale',      'Limoni freschi, zucchero, menta',              4.00,  ''),
        ]

        # ── Impostazioni ristorante ────────────────────────────
        imp, _ = ImpostazioniRistorante.objects.update_or_create(
            pk=1,
            defaults={
                'nome':      'La Trattoria',
                'slogan':    'Cucina italiana autentica nel cuore della città',
                'indirizzo': 'Via Roma 42',
                'cap':       '00100',
                'citta':     'Roma',
                'provincia': 'RM',
                'telefono':  '06 1234 5678',
                'email':     'info@latrattoria.it',
                'sito':      'https://www.latrattoria.it',
                'piva':      '12345678901',
                'cf':        '12345678901',
                'regime_fiscale': 'RF01',
                'note_scontrino': 'Grazie per aver scelto La Trattoria! 🙏\nVia Roma 42 — Roma · 06 1234 5678',
                'orari': 'Lun–Ven: 12:00–15:00 / 19:00–23:00\nSabato: 12:00–15:30 / 19:00–23:30\nDomenica: 12:00–16:00',
            }
        )

        # ── Sede principale ────────────────────────────────────
        sede_princ, _ = Sede.objects.get_or_create(
            ristorante=imp,
            nome='Sede principale — Roma Centro',
            defaults={
                'tipo':       Sede.TIPO_PRINCIPALE,
                'indirizzo':  'Via Roma 42',
                'cap':        '00100',
                'citta':      'Roma',
                'provincia':  'RM',
                'paese':      'Italia',
                'telefono':   '06 1234 5678',
                'email':      'info@latrattoria.it',
                'principale': True,
                'attiva':     True,
                'note':       'Aperto dal lunedì alla domenica. Parcheggio convenzionato in Via Cavour.',
            }
        )

        # ── Contatti ristorante principale ─────────────────────
        contatti_demo = [
            # (tipo, valore, etichetta, principale, pubblico, ordine)
            (Contatto.TEL,      '06 1234 5678',                  'Prenotazioni',        True,  True,  1),
            (Contatto.CELL,     '+39 347 1234567',               'Chef / Urgenze',      False, False, 2),
            (Contatto.EMAIL,    'info@latrattoria.it',           'Informazioni',        True,  True,  3),
            (Contatto.EMAIL,    'prenotazioni@latrattoria.it',   'Solo prenotazioni',   False, True,  4),
            (Contatto.WHATSAPP, '+39 347 1234567',               'WhatsApp Prenotaz.',  False, True,  5),
            (Contatto.TELEGRAM, 'LaTrattoriaBot',                'Bot Telegram',        False, True,  6),
            (Contatto.SITO,     'https://www.latrattoria.it',    'Sito ufficiale',      True,  True,  7),
            (Contatto.GMAPS,    'https://maps.google.com/?q=Via+Roma+42+Roma', 'Google Maps', True, True, 8),
            (Contatto.FACEBOOK, 'https://facebook.com/latrattoriait', 'Facebook',       False, True,  9),
            (Contatto.INSTAGRAM,'https://instagram.com/latrattoriait','Instagram',      False, True,  10),
            (Contatto.TRIPADV,  'https://www.tripadvisor.it',    'TripAdvisor',         False, True,  11),
            (Contatto.THEFORK,  'https://www.thefork.it',        'TheFork',             False, True,  12),
        ]
        for tipo, valore, etichetta, principale, pubblico, ordine in contatti_demo:
            Contatto.objects.get_or_create(
                ristorante=imp, tipo=tipo, valore=valore,
                defaults={
                    'etichetta': etichetta, 'principale': principale,
                    'pubblico': pubblico,   'ordine': ordine,
                }
            )

        # ── Contatti sede principale ───────────────────────────
        contatti_sede = [
            (Contatto.TEL,   '06 1234 5678',                       'Sala',              True,  True,  1),
            (Contatto.EMAIL, 'info@latrattoria.it',                 'Info sede',         True,  True,  2),
            (Contatto.GMAPS, 'https://maps.google.com/?q=Via+Roma+42+Roma', 'Indicazioni', True, True, 3),
        ]
        for tipo, valore, etichetta, principale, pubblico, ordine in contatti_sede:
            Contatto.objects.get_or_create(
                sede=sede_princ, tipo=tipo, valore=valore,
                defaults={
                    'etichetta': etichetta, 'principale': principale,
                    'pubblico': pubblico,   'ordine': ordine,
                }
            )

        self.stdout.write(self.style.SUCCESS(
            f'   Ristorante: {imp.nome} | Sedi: {Sede.objects.count()} | '
            f'Contatti: {Contatto.objects.count()}'
        ))

        # ── Piatti ────────────────────────────────────────────
        creati = 0
        for cat_nome, nome, desc, prezzo, allergeni in piatti_data:
            _, nuovo = Piatto.objects.get_or_create(
                nome=nome, categoria=categorie[cat_nome],
                defaults={'descrizione': desc, 'prezzo': prezzo, 'allergeni': allergeni}
            )
            if nuovo:
                creati += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Demo creata!\n'
            f'   Sale: {Sala.objects.count()} | Tavoli: {Tavolo.objects.count()} | Piatti: {Piatto.objects.count()}\n'
            f'\n   URL pubblici (clienti):\n'
            f'   → Vetrina:         http://127.0.0.1:8000/homepage\n'
            f'   → Menu via QR:     http://127.0.0.1:8000/menu/1/\n'
            f'   → Prenotazione:    http://127.0.0.1:8000/prenota/1/1/\n'
            f'\n   URL staff (login richiesto):\n'
            f'   → Login:           http://127.0.0.1:8000/login/\n'
            f'   → Dispatch ruolo:  http://127.0.0.1:8000/sala/\n'
            f'   → Cameriere:       http://127.0.0.1:8000/sala/cameriere/\n'
            f'   → Cucina (KDS):    http://127.0.0.1:8000/sala/cucina/\n'
            f'   → Dashboard capo:  http://127.0.0.1:8000/dashboard/\n'
            f'\n   Credenziali demo:\n'
            f'   admin       admin123    → /amministrazione/  (superuser)\n'
            f'   titolare    titolare123 → /dashboard/        (dashboard completa + admin)\n'
            f'   capo_area   capo123     → /dashboard/        (dashboard + editor)\n'
            f'   cameriere1  cam123      → /sala/cameriere/   (tavoli + comande)\n'
            f'   cuoco1      cuoco123    → /sala/cucina/      (KDS schermo cucina)\n'
            f'\n   Admin Django: http://127.0.0.1:8000/amministrazione/\n'
        ))
