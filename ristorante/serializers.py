from rest_framework import serializers
from .models import Tavolo, Prenotazione, Ordine, OrdineItem, Piatto, Categoria


class PiattoSerializer(serializers.ModelSerializer):
    categoria_nome = serializers.CharField(source='categoria.nome', read_only=True)

    class Meta:
        model = Piatto
        fields = ['id', 'nome', 'descrizione', 'prezzo', 'categoria_nome', 'disponibile', 'allergeni']


class TavoloSerializer(serializers.ModelSerializer):
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)
    forma_display = serializers.CharField(source='get_forma_display', read_only=True)
    colore_stato = serializers.CharField(read_only=True)

    class Meta:
        model = Tavolo
        fields = ['id', 'numero', 'forma', 'forma_display', 'capacita',
                  'stato', 'stato_display', 'colore_stato', 'pos_x', 'pos_y', 'sala']


class PrenotazioneSerializer(serializers.ModelSerializer):
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)

    class Meta:
        model = Prenotazione
        fields = ['id', 'tavolo', 'nome_cliente', 'telefono', 'num_persone',
                  'data_ora', 'note', 'stato', 'stato_display',
                  'caparra_richiesta', 'caparra_importo', 'caparra_pagata']


class OrdineItemSerializer(serializers.ModelSerializer):
    piatto_nome = serializers.CharField(source='piatto.nome', read_only=True)
    subtotale = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)

    class Meta:
        model = OrdineItem
        fields = ['id', 'piatto', 'piatto_nome', 'quantita', 'prezzo_unitario',
                  'subtotale', 'stato', 'stato_display', 'note']


class OrdineSerializer(serializers.ModelSerializer):
    items = OrdineItemSerializer(many=True, read_only=True)
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)
    tavolo_numero = serializers.IntegerField(source='tavolo.numero', read_only=True)

    class Meta:
        model = Ordine
        fields = ['id', 'tavolo', 'tavolo_numero', 'stato', 'stato_display',
                  'creato_il', 'totale', 'sconto_caparra', 'note', 'items']
