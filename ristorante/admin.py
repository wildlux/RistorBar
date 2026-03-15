from django.contrib import admin
from django.contrib.admin import AdminSite
from .models import Sala, Tavolo, Categoria, Piatto, Prenotazione, Ordine, OrdineItem, Fattura, ImpostazioniRistorante, Sede, Contatto


# ─── Admin site personalizzato con sezioni ────────────────────────────────────

SEZIONI = [
    {'name': '🏠 Sala & Tavoli',  'modelli': ['Sala', 'Tavolo']},
    {'name': '🍽️ Menu',           'modelli': ['Categoria', 'Piatto']},
    {'name': '📅 Prenotazioni',   'modelli': ['Prenotazione']},
    {'name': '🧾 Ordini',         'modelli': ['Ordine']},
    {'name': '💶 Contabilità',    'modelli': ['Fattura']},
    {'name': '⚙️ Configurazione', 'modelli': ['ImpostazioniRistorante', 'Sede', 'Contatto']},
]


class RistobarAdminSite(AdminSite):
    site_header = "RistoBAR — Amministrazione"
    site_title = "RistoBAR"
    index_title = "Pannello di controllo"

    def get_app_list(self, request, app_label=None):
        original = super().get_app_list(request, app_label)

        modelli_index = {}
        auth_apps = []
        for app in original:
            if app['app_label'] == 'ristorante':
                for model in app['models']:
                    modelli_index[model['object_name']] = model
            else:
                auth_apps.append(app)

        sezioni_admin = []
        for sezione in SEZIONI:
            modelli = [modelli_index[n] for n in sezione['modelli'] if n in modelli_index]
            if modelli:
                sezioni_admin.append({
                    'name': sezione['name'],
                    'app_label': f"ristorante_{sezione['name']}",
                    'app_url': '',
                    'has_module_perms': True,
                    'models': modelli,
                })

        return auth_apps + sezioni_admin


admin_site = RistobarAdminSite(name='admin')


# ─── ModelAdmin classes ───────────────────────────────────────────────────────

class SalaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'attiva']
    list_editable = ['attiva']


class TavoloAdmin(admin.ModelAdmin):
    list_display = ['numero', 'sala', 'forma', 'capacita', 'stato', 'attivo', 'eprint_email', 'nota']
    list_editable = ['stato', 'attivo', 'nota']
    list_filter = ['sala', 'stato', 'forma']
    search_fields = ['numero', 'eprint_email', 'nota']


class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'icona', 'ordine']
    list_editable = ['ordine']


class PiattoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'categoria', 'prezzo', 'disponibile']
    list_editable = ['prezzo', 'disponibile']
    list_filter = ['categoria', 'disponibile']
    search_fields = ['nome']
    fieldsets = [
        (None,          {'fields': ['categoria', 'nome', 'descrizione', 'prezzo', 'immagine', 'disponibile', 'allergeni']}),
        ('Lista Spesa', {'fields': ['ingredienti'], 'classes': ['collapse'],
                         'description': 'Ingredienti per porzione usati nella lista spesa cuochi'}),
    ]


class OrdineItemInline(admin.TabularInline):
    model = OrdineItem
    extra = 0


class PrenotazioneAdmin(admin.ModelAdmin):
    list_display = ['nome_cliente', 'tavolo', 'data_ora', 'num_persone', 'stato', 'caparra_pagata']
    list_filter = ['stato', 'caparra_pagata', 'data_ora']
    search_fields = ['nome_cliente', 'telefono']
    list_editable = ['stato']


class OrdineAdmin(admin.ModelAdmin):
    list_display = ['pk', 'tavolo', 'stato', 'totale', 'creato_il']
    list_filter = ['stato', 'creato_il']
    inlines = [OrdineItemInline]


class SedeInline(admin.TabularInline):
    model = Sede
    extra = 1
    fields = ['tipo', 'nome', 'indirizzo', 'cap', 'citta', 'provincia', 'telefono', 'principale', 'attiva']


class ContattoRistoranteInline(admin.TabularInline):
    model = Contatto
    fk_name = 'ristorante'
    extra = 1
    fields = ['tipo', 'etichetta', 'valore', 'principale', 'pubblico', 'ordine']
    verbose_name = 'Contatto ristorante'
    verbose_name_plural = 'Contatti ristorante'


class ContattoSedeInline(admin.TabularInline):
    model = Contatto
    fk_name = 'sede'
    extra = 1
    fields = ['tipo', 'etichetta', 'valore', 'principale', 'pubblico', 'ordine']
    verbose_name = 'Contatto sede'
    verbose_name_plural = 'Contatti sede'


class ImpostazioniAdmin(admin.ModelAdmin):
    inlines = [SedeInline, ContattoRistoranteInline]

    def has_add_permission(self, request):
        return not ImpostazioniRistorante.objects.exists()


class SedeAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'indirizzo', 'citta', 'principale', 'attiva']
    list_editable = ['principale', 'attiva']
    list_filter = ['tipo', 'attiva']
    inlines = [ContattoSedeInline]


class ContattoAdmin(admin.ModelAdmin):
    list_display  = ['get_icona', 'tipo', 'etichetta', 'valore', 'proprietario_nome', 'pubblico', 'principale', 'ordine']
    list_editable = ['pubblico', 'principale', 'ordine']
    list_filter   = ['tipo', 'pubblico', 'principale']
    search_fields = ['valore', 'etichetta']

    @admin.display(description='')
    def get_icona(self, obj):
        return obj.get_icona()

    @admin.display(description='Appartiene a')
    def proprietario_nome(self, obj):
        return obj.proprietario_nome


class FatturaAdmin(admin.ModelAdmin):
    list_display = ['numero', 'tipo', 'data', 'ordine', 'cliente_nome', 'totale', 'creata_da']
    list_filter  = ['tipo', 'data']
    search_fields = ['numero', 'cliente_nome', 'cliente_piva']
    readonly_fields = ['numero', 'imponibile', 'iva_importo', 'totale', 'creata_il']


# ─── Registrazione ────────────────────────────────────────────────────────────

admin_site.register(Sala,                   SalaAdmin)
admin_site.register(Tavolo,                 TavoloAdmin)
admin_site.register(Categoria,              CategoriaAdmin)
admin_site.register(Piatto,                 PiattoAdmin)
admin_site.register(Prenotazione,           PrenotazioneAdmin)
admin_site.register(Ordine,                 OrdineAdmin)
admin_site.register(ImpostazioniRistorante, ImpostazioniAdmin)
admin_site.register(Sede,                   SedeAdmin)
admin_site.register(Contatto,               ContattoAdmin)
admin_site.register(Fattura,                FatturaAdmin)
