# Configuration reference

For a step-by-step explanation, start with [Configure your .env file](../getting-started/environment.md) and [Choose your storage](../getting-started/storage.md).

The repository's `.env.example` is the full deployment reference. This table covers the settings most operators need. Edit existing entries in `.env` and apply with `sudo docker compose up -d`; a simple restart retains the old container environment.

| Setting | Purpose / normal guidance |
| --- | --- |
| `MAKERVAULT_BIND_ADDRESS` | `0.0.0.0` for LAN access; `127.0.0.1` for the documented same-host proxy |
| `MAKERVAULT_PORT` | Browser-facing host port; default `8765` |
| `DJANGO_SECRET_KEY` | Strong stable application secret; keep private |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated accepted hostnames/IPs; no schemes/ports |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Full trusted origins including scheme and non-default port |
| `DJANGO_DEBUG` | Keep `false` for normal deployments |
| `DJANGO_SECURE_COOKIES` | Enable when browser access is HTTPS-only |
| `DJANGO_SECURE_SSL_REDIRECT` | Enable after HTTPS/proxy verification |
| `DJANGO_HSTS_SECONDS` | Start at `0`; enable deliberately once HTTPS is reliable |
| `TRUST_PROXY_HEADERS` | Only trust when requests pass through your controlled proxy |
| `TRUST_X_FORWARDED_HOST` | Normally `false`; only change for a deliberately trusted topology |
| `ALLAUTH_TRUSTED_PROXY_COUNT` | `0` for direct access; actual number for a trusted proxy chain |
| `ALLOW_LOCAL_REGISTRATION` | Default `false`; controls local self-registration |
| `MAKERVAULT_ADMIN_*` | Optional bootstrapped superuser; a configured password is applied at startup |
| `MAKERVAULT_LEGACY_OWNER_USERNAME` | Resolves ambiguous pre-v0.7 private ownership |
| `MEDIA_STORAGE` / `KEY_STORAGE` | Uploads and matching encryption key storage |
| `POSTGRES_STORAGE` / `REDIS_STORAGE` | Database and queue/cache persistence |
| `MAKERVAULT_STORAGE_KEY_FILE` | Default `/app/keys/private_storage.key` |
| `MAKERVAULT_STORAGE_KEY` | Advanced alternative key source; protect and back up the actual value |
| `PUID` / `PGID` | Numeric ownership for writable application storage |
| `UMASK` / `FIX_PERMISSIONS` | File creation permissions/startup ownership handling |
| `TZ` / `DJANGO_TIME_ZONE` | Container and application timezone |
| `DJANGO_LANGUAGE_CODE` | Application locale, e.g. `en-gb` |
| `MAKERVAULT_CURRENCY` | Default currency, e.g. `GBP`; not exchange-rate conversion |
| `MAKERVAULT_MEASUREMENT_SYSTEM` | Measurement preference, normally `metric` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Database identity/credentials; retain original values for existing storage |
| `ENRICH_BOARD_CATALOGUE` | Master switch for technical board enrichment |
| `SEED_CATALOGUE_IMAGES` | Master switch for automatic catalogue images |
| `SYNC_ORCASLICER_PRINTER_CATALOGUE` | Optional printer catalogue expansion |
| `OIDC_*` | Optional identity-provider bootstrap settings |
| `EMAIL_*` / `DEFAULT_FROM_EMAIL` | Optional SMTP delivery |
| `CELERY_CONCURRENCY` / `WEB_CONCURRENCY` | Worker capacity; tune only after measuring resource use |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE` | Django request/upload buffering settings, not a universal end-to-end file-size guarantee |

## Common command reference

| Task | Command |
| --- | --- |
| Validate configuration without exposing values | `sudo docker compose config --quiet` |
| Build/start or update | `sudo docker compose up -d --build` |
| Apply `.env` changes | `sudo docker compose up -d` |
| Inspect service state | `sudo docker compose ps` |
| Follow app logs | `sudo docker compose logs -f makervault` |
| Stop / start existing containers | `sudo docker compose stop` / `sudo docker compose start` |
| Create administrator | `sudo docker compose exec makervault python manage.py createsuperuser` |
| Reset local password | `sudo docker compose exec makervault python manage.py changepassword USERNAME` |
| Inspect legacy encryption migration | `sudo docker compose exec makervault python manage.py migrate_private_storage --dry-run` |

Do not use `down -v` for routine operations. Do not publish fully expanded configuration output: it can include secrets.
