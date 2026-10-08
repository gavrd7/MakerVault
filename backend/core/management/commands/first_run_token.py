from django.core.management.base import BaseCommand, CommandError
from core.first_run import create_token


class Command(BaseCommand):
    help = "Generate a one-time 30-minute token for browser-based first administrator setup."

    def handle(self, *args, **options):
        try:
            token = create_token()
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("Open /setup/ on your MakerVault installation.")
        self.stdout.write("One-time token (valid 30 minutes; keep private):")
        self.stdout.write(token)
