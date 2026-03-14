from decimal import Decimal
from datetime import date as date_type
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
import qrcode
import io
from django.core.files.base import ContentFile


class Sala(models.Model):
    """Rappresenta una sala del ristorante (es. Sala Principale, Terrazza)."""
    nome = models.CharField(_('Nome sala'), max_length=100)
    larghezza = models.IntegerField(_('Larghezza griglia'), default=20)
    altezza = models.IntegerField(_('Altezza griglia'), default=15)
    attiva = models.BooleanField(_('Attiva'), default=True)
    # SVG planimetria: il cliente carica il proprio file SVG della sala
    svg_sfondo = models.FileField(_('SVG planimetria'), upload_to='sale_svg/', blank=True, null=True)
    svg_larghezza = models.IntegerField(_('Larghezza canvas SVG (px)'), default=1200)
    svg_altezza = models.IntegerField(_('Altezza canvas SVG (px)'), default=800)

    class Meta:
        verbose_name = _('Sala')
        verbose_name_plural = _('Sale')

    def __str__(self):
        return self.nome


class Tavolo(models.Model):
    """Rappresenta un tavolo fisico nel ristorante."""
    FORMA_ROTONDO = 'R'
    FORMA_QUADRATO = 'Q'
    FORMA_RETTANGOLO = 'T'
    FORMA_CHOICES = [
        (FORMA_ROTONDO, _('Rotondo')),
        (FORMA_QUADRATO, _('Quadrato')),
        (FORMA_RETTANGOLO, _('Rettangolare')),
    ]

    STATO_LIBERO = 'L'
    STATO_OCCUPATO = 'O'
    STATO_PRENOTATO = 'P'
    STATO_CONTO = 'C'
    STATO_CHOICES = [
        (STATO_LIBERO, _('Libero')),
        (STATO_PRENOTATO, _('Prenotato')),
        (STATO_OCCUPATO, _('Occupato')),
        (STATO_CONTO, _('Conto richiesto')),
    ]

    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name='tavoli', verbose_name=_('Sala'))
    numero = models.IntegerField(_('Numero tavolo'))
    forma = models.CharField(_('Forma'), max_length=1, choices=FORMA_CHOICES, default=FORMA_QUADRATO)
    capacita = models.IntegerField(_('Capacità (posti)'), default=4)
    stato = models.CharField(_('Stato'), max_length=1, choices=STATO_CHOICES, default=STATO_LIBERO)
    pos_x = models.IntegerField(_('Posizione X'), default=0)
    pos_y = models.IntegerField(_('Posizione Y'), default=0)
    attivo = models.BooleanField(_('Attivo'), default=True)
    qr_code = models.ImageField(_('QR Code'), upload_to='qrcodes/', blank=True, null=True)
    eprint_email = models.EmailField(_('Email ePrint stampante'), blank=True,
                                     help_text=_('Indirizzo email HP ePrint della stampante associata a questo tavolo'))

    class Meta:
        verbose_name = _('Tavolo')
        verbose_name_plural = _('Tavoli')
        unique_together = ('sala', 'numero')
        ordering = ['numero']

    def __str__(self):
        return f"Tavolo {self.numero} ({self.sala.nome})"

    def genera_qr(self):
        url = f"/prenota/{self.sala.id}/{self.numero}/"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        filename = f'tavolo_{self.sala.id}_{self.numero}.png'
        self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)

    def save(self, *args, **kwargs):
        if not self.qr_code:
            self.genera_qr()
        super().save(*args, **kwargs)

    @property
    def colore_stato(self):
        colori = {
            self.STATO_LIBERO: '#27ae60',
            self.STATO_PRENOTATO: '#f39c12',
            self.STATO_OCCUPATO: '#e74c3c',
            self.STATO_CONTO: '#3498db',
        }
        return colori.get(self.stato, '#95a5a6')


class TavoloUnione(models.Model):
    """
    Unione temporanea di più tavoli (es. per gruppi grandi).
    I tavoli uniti vengono trattati come un singolo tavolo nella mappa.
    """
    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name='unioni', verbose_name=_('Sala'))
    tavoli = models.ManyToManyField('Tavolo', related_name='unioni', verbose_name=_('Tavoli uniti'))
    etichetta = models.CharField(_('Etichetta'), max_length=50, blank=True,
                                 help_text=_('Es. "T3+T4" — lascia vuoto per generazione automatica'))
    creata_il = models.DateTimeField(_('Creata il'), auto_now_add=True)
    attiva = models.BooleanField(_('Attiva'), default=True)

    class Meta:
        verbose_name = _('Unione tavoli')
        verbose_name_plural = _('Unioni tavoli')

    def __str__(self):
        return self.etichetta or f"Unione #{self.pk}"

    @property
    def capacita_totale(self):
        return sum(t.capacita for t in self.tavoli.all())

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.etichetta and self.pk:
            nums = '+'.join(str(t.numero) for t in self.tavoli.order_by('numero'))
            TavoloUnione.objects.filter(pk=self.pk).update(etichetta=f"T{nums}")


class Categoria(models.Model):
    """Categoria del menu (Antipasti, Primi, Dolci, ecc.)."""
    nome = models.CharField(_('Nome'), max_length=100)
    ordine = models.IntegerField(_('Ordine'), default=0)
    icona = models.CharField(_('Icona emoji'), max_length=10, blank=True)

    class Meta:
        verbose_name = _('Categoria')
        verbose_name_plural = _('Categorie')
        ordering = ['ordine']

    def __str__(self):
        return self.nome


class Piatto(models.Model):
    """Piatto nel menu del ristorante."""
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='piatti', verbose_name=_('Categoria'))
    nome = models.CharField(_('Nome'), max_length=200)
    descrizione = models.TextField(_('Descrizione'), blank=True)
    prezzo = models.DecimalField(_('Prezzo'), max_digits=8, decimal_places=2)
    immagine = models.ImageField(_('Immagine'), upload_to='menu/', blank=True, null=True)
    disponibile = models.BooleanField(_('Disponibile'), default=True)
    allergeni = models.CharField(_('Allergeni'), max_length=500, blank=True)
    aliquota_iva = models.DecimalField(_('Aliquota IVA %'), max_digits=5, decimal_places=2,
                                       default=Decimal('10.00'),
                                       help_text=_('Es. 10 per 10% — standard ristorazione; 22 per alcol'))
    ingredienti = models.TextField(_('Ingredienti (per lista spesa)'), blank=True,
                                   help_text=_('Elenco ingredienti e quantità per porzione, usato nella lista spesa cuochi'))

    class Meta:
        verbose_name = _('Piatto')
        verbose_name_plural = _('Piatti')

    def __str__(self):
        return f"{self.nome} - €{self.prezzo}"


class Prenotazione(models.Model):
    """Prenotazione di un tavolo con opzione caparra."""
    STATO_ATTESA = 'A'
    STATO_CONFERMATA = 'C'
    STATO_RIFIUTATA = 'R'
    STATO_ANNULLATA = 'X'
    STATO_CHOICES = [
        (STATO_ATTESA, _('In attesa di conferma')),
        (STATO_CONFERMATA, _('Confermata')),
        (STATO_RIFIUTATA, _('Rifiutata')),
        (STATO_ANNULLATA, _('Annullata')),
    ]

    tavolo = models.ForeignKey(Tavolo, on_delete=models.CASCADE, related_name='prenotazioni', verbose_name=_('Tavolo'))
    nome_cliente = models.CharField(_('Nome cliente'), max_length=200)
    telefono = models.CharField(_('Telefono'), max_length=20, blank=True)
    telegram_chat_id = models.CharField(_('Telegram Chat ID'), max_length=50, blank=True)
    num_persone = models.IntegerField(_('Numero di persone'), default=2)
    data_ora = models.DateTimeField(_('Data e ora'))
    note = models.TextField(_('Note'), blank=True)
    stato = models.CharField(_('Stato'), max_length=1, choices=STATO_CHOICES, default=STATO_ATTESA)
    creata_il = models.DateTimeField(_('Creata il'), auto_now_add=True)

    caparra_richiesta = models.BooleanField(_('Caparra richiesta'), default=True)
    caparra_importo = models.DecimalField(_('Importo caparra'), max_digits=6, decimal_places=2, default=10.00)
    caparra_pagata = models.BooleanField(_('Caparra pagata'), default=False)
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = _('Prenotazione')
        verbose_name_plural = _('Prenotazioni')
        ordering = ['data_ora']

    def __str__(self):
        return f"{self.nome_cliente} - {self.tavolo} - {self.data_ora.strftime('%d/%m/%Y %H:%M')}"


class Ordine(models.Model):
    """Ordine associato a un tavolo."""
    STATO_APERTO = 'A'
    STATO_IN_PREPARAZIONE = 'P'
    STATO_SERVITO = 'S'
    STATO_PAGATO = 'X'
    STATO_CHOICES = [
        (STATO_APERTO, _('Aperto')),
        (STATO_IN_PREPARAZIONE, _('In preparazione')),
        (STATO_SERVITO, _('Servito')),
        (STATO_PAGATO, _('Pagato')),
    ]

    tavolo = models.ForeignKey(Tavolo, on_delete=models.CASCADE, related_name='ordini', verbose_name=_('Tavolo'))
    prenotazione = models.ForeignKey(Prenotazione, on_delete=models.SET_NULL, null=True, blank=True, related_name='ordini', verbose_name=_('Prenotazione'))
    cameriere = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_('Cameriere'))
    stato = models.CharField(_('Stato'), max_length=1, choices=STATO_CHOICES, default=STATO_APERTO)
    creato_il = models.DateTimeField(_('Creato il'), auto_now_add=True)
    aggiornato_il = models.DateTimeField(_('Aggiornato il'), auto_now=True)
    note = models.TextField(_('Note'), blank=True)
    totale = models.DecimalField(_('Totale'), max_digits=10, decimal_places=2, default=0)
    sconto_caparra = models.DecimalField(_('Sconto caparra'), max_digits=6, decimal_places=2, default=0)

    class Meta:
        verbose_name = _('Ordine')
        verbose_name_plural = _('Ordini')
        ordering = ['-creato_il']

    def __str__(self):
        return f"Ordine #{self.pk} - {self.tavolo}"

    def calcola_totale(self):
        totale = sum(item.subtotale for item in self.items.all())
        self.totale = totale - self.sconto_caparra
        self.save(update_fields=['totale'])
        return self.totale


class OrdineItem(models.Model):
    """Singola riga dell'ordine (piatto + quantità)."""
    STATO_ATTESA = 'A'
    STATO_IN_CUCINA = 'C'
    STATO_PRONTO = 'P'
    STATO_SERVITO = 'S'
    STATO_CHOICES = [
        (STATO_ATTESA, _('In attesa')),
        (STATO_IN_CUCINA, _('In cucina')),
        (STATO_PRONTO, _('Pronto')),
        (STATO_SERVITO, _('Servito')),
    ]

    ordine = models.ForeignKey(Ordine, on_delete=models.CASCADE, related_name='items', verbose_name=_('Ordine'))
    piatto = models.ForeignKey(Piatto, on_delete=models.CASCADE, verbose_name=_('Piatto'))
    quantita = models.IntegerField(_('Quantità'), default=1)
    prezzo_unitario = models.DecimalField(_('Prezzo unitario'), max_digits=8, decimal_places=2)
    stato = models.CharField(_('Stato'), max_length=1, choices=STATO_CHOICES, default=STATO_ATTESA)
    note = models.TextField(_('Note'), blank=True)

    class Meta:
        verbose_name = _('Voce ordine')
        verbose_name_plural = _('Voci ordine')

    def __str__(self):
        return f"{self.quantita}x {self.piatto.nome}"

    @property
    def subtotale(self):
        return self.quantita * self.prezzo_unitario

    def save(self, *args, **kwargs):
        if not self.prezzo_unitario:
            self.prezzo_unitario = self.piatto.prezzo
        super().save(*args, **kwargs)


# ─── Impostazioni fiscali ristorante ─────────────────────────────────────────

class ImpostazioniRistorante(models.Model):
    """
    Singleton con i dati fiscali del ristorante.
    Usato nell'intestazione di scontrini e fatture.
    """
    nome      = models.CharField(_('Nome ristorante'), max_length=200, default='RistoBAR')
    slogan    = models.CharField(_('Slogan'), max_length=300, blank=True)
    indirizzo = models.CharField(_('Indirizzo'), max_length=200, blank=True)
    cap       = models.CharField(_('CAP'), max_length=10, blank=True)
    citta     = models.CharField(_('Città'), max_length=100, blank=True)
    provincia = models.CharField(_('Provincia (sigla)'), max_length=5, blank=True)
    telefono  = models.CharField(_('Telefono'), max_length=30, blank=True)
    email     = models.EmailField(_('Email'), blank=True)
    sito      = models.URLField(_('Sito web'), blank=True)
    piva      = models.CharField(_('Partita IVA'), max_length=11, blank=True)
    cf        = models.CharField(_('Codice Fiscale'), max_length=16, blank=True)
    regime_fiscale = models.CharField(_('Regime fiscale SDI'), max_length=10, blank=True, default='RF01')
    iban      = models.CharField(_('IBAN'), max_length=34, blank=True)
    logo      = models.ImageField(_('Logo'), upload_to='logo/', blank=True, null=True)
    note_scontrino = models.TextField(_('Note piè scontrino'), blank=True, default='Grazie e arrivederci! 🙏')
    note_fattura   = models.TextField(_('Note piè fattura'), blank=True)

    class Meta:
        verbose_name = _('Impostazioni Ristorante')
        verbose_name_plural = _('Impostazioni Ristorante')

    def __str__(self):
        return f"Impostazioni — {self.nome}"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Sede(models.Model):
    """
    Sede / filiale / indirizzo aggiuntivo del ristorante.
    Utile per catene con più locali o per indicare indirizzi secondari
    (es. sede legale, magazzino, area esterna).
    """
    TIPO_PRINCIPALE = 'P'
    TIPO_FILIALE    = 'F'
    TIPO_LEGALE     = 'L'
    TIPO_ALTRO      = 'A'
    TIPO_CHOICES = [
        (TIPO_PRINCIPALE, _('Sede principale')),
        (TIPO_FILIALE,    _('Filiale')),
        (TIPO_LEGALE,     _('Sede legale')),
        (TIPO_ALTRO,      _('Altro')),
    ]

    ristorante  = models.ForeignKey(ImpostazioniRistorante, on_delete=models.CASCADE,
                                    related_name='sedi', verbose_name=_('Ristorante'))
    tipo        = models.CharField(_('Tipo sede'), max_length=1, choices=TIPO_CHOICES, default=TIPO_FILIALE)
    nome        = models.CharField(_('Nome / etichetta'), max_length=100,
                                   help_text=_('Es. "Centro storico", "Mare", "Sede legale"'))
    indirizzo   = models.CharField(_('Indirizzo'), max_length=200)
    cap         = models.CharField(_('CAP'), max_length=10, blank=True)
    citta       = models.CharField(_('Città'), max_length=100, blank=True)
    provincia   = models.CharField(_('Provincia'), max_length=5, blank=True)
    paese       = models.CharField(_('Paese'), max_length=50, blank=True, default='Italia')
    telefono    = models.CharField(_('Telefono diretto'), max_length=30, blank=True)
    email       = models.EmailField(_('Email diretta'), blank=True)
    note        = models.TextField(_('Note'), blank=True)
    attiva      = models.BooleanField(_('Attiva'), default=True)
    principale  = models.BooleanField(_('Usa come indirizzo principale su documenti'), default=False)

    class Meta:
        verbose_name = _('Sede')
        verbose_name_plural = _('Sedi')
        ordering = ['-principale', 'nome']

    def __str__(self):
        return f"{self.nome} — {self.indirizzo}, {self.citta}"

    def indirizzo_completo(self):
        parti = [self.indirizzo]
        if self.cap or self.citta:
            parti.append(f"{self.cap} {self.citta}".strip())
        if self.provincia:
            parti[-1] += f" ({self.provincia})"
        if self.paese and self.paese != 'Italia':
            parti.append(self.paese)
        return ', '.join(parti)


# ─── Rubrica contatti ────────────────────────────────────────────────────────

class Contatto(models.Model):
    """
    Contatto di un ristorante o di una singola sede.
    Può essere telefono, email, social, sito, servizio delivery, ecc.
    Compilare SOLO uno tra `ristorante` e `sede`.
    """

    # ── Tipi di canale ────────────────────────────────────────
    TEL        = 'tel'
    CELL       = 'cel'
    EMAIL      = 'eml'
    WHATSAPP   = 'wap'
    TELEGRAM   = 'tgm'
    FAX        = 'fax'
    SITO       = 'web'
    FACEBOOK   = 'fb'
    INSTAGRAM  = 'ig'
    TIKTOK     = 'tt'
    LINKEDIN   = 'li'
    YOUTUBE    = 'yt'
    GMAPS      = 'gmp'
    TRIPADV    = 'ta'
    THEFORK    = 'tf'
    DELIVEROO  = 'del'
    GLOVO      = 'glo'
    JUSTEEAT   = 'je'
    ALTRO      = 'alt'

    TIPO_CHOICES = [
        ('── Recapiti ──',   []),   # gruppo visivo
        (TEL,       _('📞 Telefono fisso')),
        (CELL,      _('📱 Cellulare')),
        (EMAIL,     _('✉️ Email')),
        (WHATSAPP,  _('💬 WhatsApp')),
        (TELEGRAM,  _('✈️ Telegram')),
        (FAX,       _('📠 Fax')),
        ('── Web & Social ──', []),
        (SITO,      _('🌐 Sito web')),
        (FACEBOOK,  _('📘 Facebook')),
        (INSTAGRAM, _('📸 Instagram')),
        (TIKTOK,    _('🎵 TikTok')),
        (LINKEDIN,  _('💼 LinkedIn')),
        (YOUTUBE,   _('▶️ YouTube')),
        ('── Mappe & Recensioni ──', []),
        (GMAPS,     _('📍 Google Maps')),
        (TRIPADV,   _('⭐ TripAdvisor')),
        (THEFORK,   _('🍴 TheFork')),
        ('── Delivery ──', []),
        (DELIVEROO, _('🛵 Deliveroo')),
        (GLOVO,     _('🟡 Glovo')),
        (JUSTEEAT,  _('🟠 Just Eat')),
        (ALTRO,     _('📌 Altro')),
    ]

    # Icone per visualizzazione rapida nel template
    ICONE = {
        TEL: '📞', CELL: '📱', EMAIL: '✉️', WHATSAPP: '💬', TELEGRAM: '✈️',
        FAX: '📠', SITO: '🌐', FACEBOOK: '📘', INSTAGRAM: '📸', TIKTOK: '🎵',
        LINKEDIN: '💼', YOUTUBE: '▶️', GMAPS: '📍', TRIPADV: '⭐',
        THEFORK: '🍴', DELIVEROO: '🛵', GLOVO: '🟡', JUSTEEAT: '🟠', ALTRO: '📌',
    }

    # ── Appartenenza (uno solo tra i due) ────────────────────
    ristorante  = models.ForeignKey(
        ImpostazioniRistorante, on_delete=models.CASCADE,
        related_name='contatti', null=True, blank=True,
        verbose_name=_('Ristorante'),
    )
    sede        = models.ForeignKey(
        Sede, on_delete=models.CASCADE,
        related_name='contatti', null=True, blank=True,
        verbose_name=_('Sede'),
    )

    # ── Dati contatto ────────────────────────────────────────
    tipo        = models.CharField(_('Tipo'), max_length=3, choices=TIPO_CHOICES, default=TEL)
    etichetta   = models.CharField(_('Etichetta'), max_length=100, blank=True,
                                   help_text=_('Es. "Prenotazioni", "Chef Marco", "Ufficio amministrativo"'))
    valore      = models.CharField(_('Valore / URL / Numero'), max_length=500,
                                   help_text=_('Numero, indirizzo email o URL completo'))

    # ── Opzioni ─────────────────────────────────────────────
    principale  = models.BooleanField(_('Contatto principale per questo tipo'), default=False)
    pubblico    = models.BooleanField(_('Mostra sulla vetrina pubblica'), default=True)
    ordine      = models.PositiveSmallIntegerField(_('Ordine visualizzazione'), default=10)
    note        = models.TextField(_('Note interne'), blank=True)

    class Meta:
        verbose_name = _('Contatto')
        verbose_name_plural = _('Contatti')
        ordering = ['ordine', 'tipo']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ristorante__isnull=False, sede__isnull=True) |
                    models.Q(ristorante__isnull=True,  sede__isnull=False)
                ),
                name='contatto_ha_un_solo_proprietario',
            )
        ]

    def __str__(self):
        chi = str(self.ristorante or self.sede)
        return f"{self.get_icona()} {self.valore} ({chi})"

    def get_icona(self):
        return self.ICONE.get(self.tipo, '📌')

    @property
    def proprietario_nome(self):
        if self.sede_id:
            return str(self.sede)
        return str(self.ristorante)

    @property
    def is_link(self):
        """True se il valore è un URL cliccabile."""
        return self.valore.startswith(('http://', 'https://', 'mailto:', 'tel:'))

    @property
    def url(self):
        """URL cliccabile anche per numeri di telefono e email."""
        v = self.valore
        if self.tipo in (self.TEL, self.CELL, self.FAX):
            digits = ''.join(c for c in v if c in '+0123456789')
            return f"tel:{digits}"
        if self.tipo == self.WHATSAPP:
            digits = ''.join(c for c in v if c in '+0123456789')
            return f"https://wa.me/{digits.lstrip('+')}"
        if self.tipo == self.TELEGRAM:
            handle = v.lstrip('@')
            return f"https://t.me/{handle}"
        if self.tipo == self.EMAIL:
            return f"mailto:{v}"
        return v


# ─── Documenti fiscali (scontrino / fattura) ─────────────────────────────────

class Fattura(models.Model):
    """
    Documento fiscale emesso per un ordine.
    - Tipo S = Scontrino di cortesia
    - Tipo R = Ricevuta intestata
    - Tipo F = Fattura (richiede dati del cliente)
    La numerazione è progressiva per anno e per tipo.
    """
    TIPO_SCONTRINO = 'S'
    TIPO_RICEVUTA  = 'R'
    TIPO_FATTURA   = 'F'
    TIPO_CHOICES = [
        (TIPO_SCONTRINO, _('Scontrino di cortesia')),
        (TIPO_RICEVUTA,  _('Ricevuta')),
        (TIPO_FATTURA,   _('Fattura')),
    ]
    PREFIX = {'S': 'SCO', 'R': 'RIC', 'F': 'FAT'}

    ordine     = models.ForeignKey(Ordine, on_delete=models.PROTECT,
                                   related_name='documenti', verbose_name=_('Ordine'))
    tipo       = models.CharField(_('Tipo'), max_length=1, choices=TIPO_CHOICES, default=TIPO_SCONTRINO)
    numero     = models.CharField(_('N° documento'), max_length=30, blank=True)
    data       = models.DateField(_('Data emissione'), default=date_type.today)

    # Intestatario (opzionale per scontrino, obbligatorio per fattura)
    cliente_nome      = models.CharField(_('Nome / Ragione sociale'), max_length=200, blank=True)
    cliente_indirizzo = models.CharField(_('Indirizzo'), max_length=300, blank=True)
    cliente_cap       = models.CharField(_('CAP'), max_length=10, blank=True)
    cliente_citta     = models.CharField(_('Città'), max_length=100, blank=True)
    cliente_piva      = models.CharField(_('Partita IVA'), max_length=11, blank=True)
    cliente_cf        = models.CharField(_('Codice Fiscale'), max_length=16, blank=True)
    cliente_email     = models.EmailField(_('Email'), blank=True)
    cliente_pec       = models.EmailField(_('PEC'), blank=True)
    cliente_sdi       = models.CharField(_('Codice SDI'), max_length=10, blank=True)

    # Totali calcolati
    imponibile  = models.DecimalField(_('Imponibile'), max_digits=10, decimal_places=2, default=0)
    iva_importo = models.DecimalField(_('IVA'), max_digits=10, decimal_places=2, default=0)
    totale      = models.DecimalField(_('Totale'), max_digits=10, decimal_places=2, default=0)

    note        = models.TextField(_('Note'), blank=True)
    creata_il   = models.DateTimeField(_('Creata il'), auto_now_add=True)
    creata_da   = models.ForeignKey(User, on_delete=models.SET_NULL,
                                    null=True, blank=True, verbose_name=_('Operatore'))

    class Meta:
        verbose_name = _('Documento fiscale')
        verbose_name_plural = _('Documenti fiscali')
        ordering = ['-data', '-pk']

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero or '—'} — {self.ordine}"

    def _prossimo_numero(self):
        anno   = self.data.year
        prefix = self.PREFIX[self.tipo]
        ultimo = (
            Fattura.objects
            .filter(tipo=self.tipo, data__year=anno)
            .exclude(pk=self.pk or 0)
            .order_by('-pk')
            .first()
        )
        if ultimo and ultimo.numero:
            try:
                n = int(ultimo.numero.rsplit('/', 1)[-1]) + 1
            except ValueError:
                n = 1
        else:
            n = 1
        return f"{prefix}/{anno}/{n:04d}"

    def calcola_totali(self):
        """Calcola imponibile e IVA per aliquota da OrdineItem."""
        imponibile  = Decimal('0')
        iva         = Decimal('0')
        for item in self.ordine.items.select_related('piatto').all():
            aliq     = item.piatto.aliquota_iva / Decimal('100')
            subtot   = item.quantita * item.prezzo_unitario
            imp      = (subtot / (1 + aliq)).quantize(Decimal('0.01'))
            imponibile  += imp
            iva         += subtot - imp
        self.imponibile  = imponibile
        self.iva_importo = iva
        self.totale      = self.ordine.totale

    @property
    def righe_iva(self):
        """Ritorna lista dict con riepilogo IVA per aliquota (usato nel template)."""
        per_aliq = {}
        for item in self.ordine.items.select_related('piatto').all():
            aliq   = item.piatto.aliquota_iva
            subtot = item.quantita * item.prezzo_unitario
            if aliq not in per_aliq:
                per_aliq[aliq] = {'aliquota': aliq, 'imponibile': Decimal('0'), 'iva': Decimal('0')}
            d    = per_aliq[aliq]
            imp  = (subtot / (1 + aliq / 100)).quantize(Decimal('0.01'))
            d['imponibile'] += imp
            d['iva']        += subtot - imp
        return sorted(per_aliq.values(), key=lambda x: x['aliquota'])

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = self._prossimo_numero()
        self.calcola_totali()


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPOSITIVI HARDWARE - Centro di Controllo
# ═══════════════════════════════════════════════════════════════════════════════

class Dispositivo(models.Model):
    """Dispositivo hardware (ESP32, Arduino, STM32) per display e-ink tavoli."""
    
    TIPO_CHOICES = [
        ('ESP32_WIFI', 'ESP32 (WiFi)'),
        ('ESP32_BLE', 'ESP32 (BLE)'),
        ('ESP32_MULTI', 'ESP32 (Multi-mode)'),
        ('ARDUINO_ESP01', 'Arduino + ESP-01'),
        ('STM32_BLE', 'STM32 (BLE)'),
    ]
    
    MODALITA_CHOICES = [
        ('WIFI', 'WiFi only'),
        ('BLE', 'Bluetooth only'),
        ('COMBINED', 'WiFi + BLE'),
    ]
    
    STATO_CHOICES = [
        ('ONLINE', 'Online'),
        ('OFFLINE', 'Offline'),
        ('ERROR', 'Errore'),
        ('MAINTENANCE', 'Manutenzione'),
    ]
    
    nome = models.CharField(_('Nome dispositivo'), max_length=50)
    tipo = models.CharField(_('Tipo'), max_length=20, choices=TIPO_CHOICES)
    modalita = models.CharField(_('Modalità'), max_length=10, choices=MODALITA_CHOICES, default='WIFI')
    stato = models.CharField(_('Stato'), max_length=15, choices=STATO_CHOICES, default='OFFLINE')
    
    sala = models.ForeignKey(Sala, on_delete=models.CASCADE, related_name='dispositivi')
    tavolo = models.ForeignKey(Tavolo, on_delete=models.SET_NULL, null=True, blank=True, related_name='dispositivo')
    
    # Identificazione
    mac_address = models.CharField(_('MAC Address'), max_length=17, blank=True)
    ble_name = models.CharField(_('Nome BLE'), max_length=32, blank=True)
    ip_address = models.GenericIPAddressField(_('IP Address'), null=True, blank=True)
    
    # Configurazione
    server_url = models.CharField(_('URL Server'), max_length=200, blank=True)
    refresh_interval = models.IntegerField(_('Interval refresh (sec)'), default=60)
    
    # Posizione
    piano = models.CharField(_('Piano'), max_length=20, blank=True)
    posizione = models.CharField(_('Posizione'), max_length=100, blank=True, help_text='Es: "Entrata", "Angolo NW"')
    
    # Monitoraggio
    last_seen = models.DateTimeField(_('Ultimo contatto'), null=True, blank=True)
    last_status = models.JSONField(_('Ultimo stato'), default=dict, blank=True)
    errori = models.TextField(_('Errori'), blank=True)
    
    # Info
    firmware_ver = models.CharField(_('Firmware'), max_length=20, blank=True)
    note = models.TextField(_('Note'), blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Dispositivo')
        verbose_name_plural = _('Dispositivi')
        ordering = ['sala', 'tavolo', 'nome']
    
    def __str__(self):
        return f"{self.nome} ({self.tipo}) - Tavolo {self.tavolo}" if self.tavolo else self.nome
    
    @property
    def is_online(self):
        if not self.last_seen:
            return False
        from django.utils import timezone
        return (timezone.now() - self.last_seen).seconds < 300
    
    def aggiorna_stato(self, dati):
        """Aggiorna lo stato del dispositivo con i dati ricevuti."""
        from django.utils import timezone
        self.last_seen = timezone.now()
        self.last_status = dati
        self.stato = 'ONLINE'
        self.errori = ''
        self.save()
        super().save(*args, **kwargs)
