from django.core.management.base import BaseCommand
from ristorante.telegram_service import _polling_loop
from django.conf import settings


class Command(BaseCommand):
    help = 'Avvia il bot Telegram in modalità polling (foreground)'

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stderr.write(self.style.ERROR('TELEGRAM_BOT_TOKEN non impostato nel file .env'))
            return
        self.stdout.write(self.style.SUCCESS('Bot Telegram avviato. Ctrl+C per fermare.'))
        try:
            _polling_loop(token)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Bot fermato.'))
