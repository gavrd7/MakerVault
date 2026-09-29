# Upgrading from before v0.7

**Advanced · Existing installations only**

The v0.7 milestone introduces private ownership, quotas and encrypted private uploads. Do not treat this as a fresh install over your existing storage.

## Prepare

1. Preserve the current source revision and `.env`.
2. Back up the database and all current media before migration.
3. Review the existing users and decide who owns legacy private records.
4. If multiple users make ownership ambiguous, configure `MAKERVAULT_LEGACY_OWNER_USERNAME` to the existing username that should receive the legacy records before the first upgrade start.
5. Add persistent `KEY_STORAGE`, either the supplied named volume or a separate absolute bind path. Include it in all subsequent backups.
6. Plan downtime and preferably rehearse on an isolated restoration first.

Do not select an owner casually: this determines whose private workspace receives old records. There is no general collaboration/sharing migration implied by this setting.

## Start and inspect

Follow the normal update steps. Startup runs database migrations and attempts to migrate legacy private media to encrypted storage. Existing private files remain readable during the transition; migration problems are logged and retried on a subsequent startup.

After startup, inspect what remains:

```bash
sudo docker compose exec makervault python manage.py migrate_private_storage --dry-run
```

A running web page alone does not prove every old file was encrypted. Review logs and the dry-run result, open known projects and download representative older files. Investigate missing or unreadable source files before declaring migration complete.

Make a fresh complete backup after verification, including the new key. Keep the pre-upgrade recovery set until you have tested the upgraded restore. Do not overwrite it with a partially migrated backup.
