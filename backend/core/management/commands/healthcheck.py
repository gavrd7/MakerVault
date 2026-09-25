from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Container healthcheck for PostgreSQL and Redis."

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            cache.set("makervault-health-cli", "ok", timeout=10)
            if cache.get("makervault-health-cli") != "ok":
                raise RuntimeError("Redis cache round-trip failed")
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("ok")
