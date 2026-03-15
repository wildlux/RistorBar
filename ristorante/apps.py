import os
import signal
from django.apps import AppConfig


class RistoranteConfig(AppConfig):
    name = 'ristorante'

    def ready(self):
        # Evita doppio avvio con il reloader di sviluppo Django
        if os.environ.get('RUN_MAIN') != 'true':
            return
        from ristorante.telegram_service import start_bot
        start_bot()

        # Ctrl+C termina il processo in modo pulito
        original = signal.getsignal(signal.SIGINT)
        def handler(sig, frame):
            raise SystemExit(0)
        signal.signal(signal.SIGINT, handler)
