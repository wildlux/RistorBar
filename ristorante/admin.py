from django.contrib import admin
from .models import Sala, Tavolo, Categoria, Piatto, Prenotazione, Ordine, OrdineItem, Fattura, ImpostazioniRistorante, Sede, Contatto


@admin.register(Sala)
class SalaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'attiva']
    list_editable = ['attiva']


@admin.register(Tavolo)
class TavoloAdmin(admin.ModelAdmin):
    list_display = ['numero', 'sala', 'forma', 'capacita', 'stato', 'attivo', 'eprint_email', 'nota']
    list_editable = ['stato', 'attivo', 'nota']
    list_filter = ['sala', 'stato', 'forma']
    search_fields = ['numero', 'eprint_email', 'nota']


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'icona', 'ordine']
    list_editable = ['ordine']


@admin.register(Piatto)
class PiattoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'categoria', 'prezzo', 'disponibile']
    list_editable = ['prezzo', 'disponibile']
    list_filter = ['categoria', 'disponibile']
    search_fields = ['nome']
    fieldsets = [
        (None,            {'fields': ['categoria', 'nome', 'descrizione', 'prezzo', 'immagine', 'disponibile', 'allergeni']}),
        ('Lista Spesa',   {'fields': ['ingredienti'], 'classes': ['collapse'],
                           'description': 'Ingredienti per porzione usati nella lista spesa cuochi'}),
    ]


class OrdineItemInline(admin.TabularInline):
    model = OrdineItem
    extra = 0


@admin.register(Prenotazione)
class PrenotazioneAdmin(admin.ModelAdmin):
    list_display = ['nome_cliente', 'tavolo', 'data_ora', 'num_persone', 'stato', 'caparra_pagata']
    list_filter = ['stato', 'caparra_pagata', 'data_ora']
    search_fields = ['nome_cliente', 'telefono']
    list_editable = ['stato']


@admin.register(Ordine)
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


@admin.register(ImpostazioniRistorante)
class ImpostazioniAdmin(admin.ModelAdmin):
    inlines = [SedeInline, ContattoRistoranteInline]
    def has_add_permission(self, request):
        return not ImpostazioniRistorante.objects.exists()


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'indirizzo', 'citta', 'principale', 'attiva']
    list_editable = ['principale', 'attiva']
    list_filter = ['tipo', 'attiva']
    inlines = [ContattoSedeInline]


@admin.register(Contatto)
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


@admin.register(Fattura)
class FatturaAdmin(admin.ModelAdmin):
    list_display = ['numero', 'tipo', 'data', 'ordine', 'cliente_nome', 'totale', 'creata_da']
    list_filter  = ['tipo', 'data']
    search_fields = ['numero', 'cliente_nome', 'cliente_piva']
    readonly_fields = ['numero', 'imponibile', 'iva_importo', 'totale', 'creata_il']
