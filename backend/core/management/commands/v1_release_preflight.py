import os
import ssl
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.private_storage import private_storage_key


class Command(BaseCommand):
    help = "Read-only v1 release preflight for the running MakerVault deployment."

    def handle(self, *args, **options):
        failures = []
        checks = []

        def record(name, fn):
            try:
                detail = fn()
                checks.append((name, "PASS", detail or "ok"))
            except Exception as exc:
                checks.append((name, "FAIL", str(exc)))
                failures.append(name)

        def database_check():
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return connection.settings_dict.get("NAME", "database")

        def migration_check():
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                pending = ", ".join(f"{migration.app_label}.{migration.name}" for migration, _ in plan[:8])
                raise RuntimeError(f"unapplied migrations: {pending}")
            return "all migrations applied"

        def redis_check():
            token = "makervault-v1-preflight"
            cache.set(token, "ok", timeout=10)
            if cache.get(token) != "ok":
                raise RuntimeError("Redis cache round-trip failed")
            cache.delete(token)
            return "cache round-trip"

        def key_check():
            key = private_storage_key()
            if len(key) != 32:
                raise RuntimeError("private-storage key is not 32 bytes")
            return "AES-256 key readable"

        def writable_directory(path, label):
            root = Path(path)
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".makervault-preflight-", dir=root, delete=True) as handle:
                handle.write(b"ok")
                handle.flush()
            return f"{label} writable: {root}"

        record("PostgreSQL", database_check)
        record("Database migrations", migration_check)
        record("Redis", redis_check)
        record("Private storage key", key_check)
        record("Media storage", lambda: writable_directory(settings.MEDIA_ROOT, "media"))
        record("Backup storage", lambda: writable_directory(settings.MAKERVAULT_BACKUP_ROOT, "backup"))

        def native_https_check():
            enabled = os.getenv("MAKERVAULT_HTTPS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
            if not enabled:
                return "disabled"
            cert = Path(os.getenv("MAKERVAULT_TLS_CERT_FILE", "/app/tls/cert.pem"))
            key = Path(os.getenv("MAKERVAULT_TLS_KEY_FILE", "/app/tls/key.pem"))
            if not cert.is_file() or not key.is_file():
                raise RuntimeError("enabled but certificate/key are missing")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert, keyfile=key)
            return f"certificate/key load successfully ({cert})"

        record("Native HTTPS", native_https_check)

        if not settings.DEBUG and len(settings.SECRET_KEY) < 32:
            failures.append("Django secret")
            checks.append(("Django secret", "FAIL", "production secret is shorter than 32 characters"))
        else:
            checks.append(("Django secret", "PASS", "configured"))

        if settings.DEBUG:
            checks.append(("Production mode", "FAIL", "DJANGO_DEBUG is enabled"))
            failures.append("Production mode")
        else:
            checks.append(("Production mode", "PASS", "DJANGO_DEBUG is disabled"))

        for name, status, detail in checks:
            self.stdout.write(f"{status:4}  {name}: {detail}")

        if failures:
            raise CommandError("v1 preflight failed: " + ", ".join(failures))
        self.stdout.write(self.style.SUCCESS("MakerVault v1 release preflight passed."))
