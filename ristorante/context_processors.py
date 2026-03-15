from .models import ImpostazioniRistorante


def impostazioni(request):
    """Inietta ImpostazioniRistorante in ogni template context."""
    return {'impostazioni': ImpostazioniRistorante.get()}
