# v1.0 release acceptance

This checklist is the final evidence set for the first stable MakerVault release. Automated CI is necessary but does not replace a recovery rehearsal using a real installation.

## Automated gates

Run from the deployed checkout after building the candidate:

```bash
sudo docker compose exec -T makervault python manage.py v1_release_preflight
```

The command checks PostgreSQL, pending migrations, Redis, the private-file encryption key, media/backup write access, production mode and the configured Django secret.

The release candidate must also have green backend/frontend tests, migration checks, dependency audits, static security checks, production Docker build, container vulnerability scan, managed-backup rehearsal, encrypted-file recovery rehearsal and guide build/link checks.

## Clean-install acceptance — passed 3 October 2026

A fresh MakerVault deployment was completed on a separate Debian/Docker host using a newly created `.env`, the documented three-service Compose stack and Docker-managed named volumes.

The clean install successfully completed first-run migrations/catalogue setup, created a new superuser, loaded the main application areas, created inventory/project test data and used private encrypted storage. The stack was restarted and the created data remained available. Native HTTPS was also exercised on the fresh host using the MakerVault Local CA/server-certificate workflow. A final `v1_release_preflight` after restart passed PostgreSQL, migrations, Redis, AES-256 private storage key, media/backup write access, Django secret and production-mode checks.

The brief initial browser-unavailable window observed during first-run catalogue initialization resolved once startup completed and Gunicorn entered service; the installation then remained reachable normally.

## Upgrade acceptance

Using a protected copy of a representative pre-v1 installation:

- create and verify a backup before updating;
- preserve the existing `.env`, database, media and key storage;
- update with the documented fast-forward/build procedure;
- confirm migrations complete once and restart cleanly;
- verify existing projects, inventory, files and printer/spool records;
- authenticate a private file and an older file revision;
- run `v1_release_preflight`.

Do not treat switching application code backwards as a database rollback.

## Real backup/restore acceptance — passed 3 October 2026

A managed backup from a representative real MakerVault installation was downloaded and restored on a separate clean Debian host using the guarded off-server recovery helper. The restored deployment passed `v1_release_preflight`, `verify_private_storage` and `audit_private_ownership --fail-on-issues`; the restored application was opened successfully after adjusting the recovered allowed-host/origin values for the replacement host.

Recovery preserved the database, media and AES-256 private-storage key together. The private-file audit reported 3 referenced private files checked, 0 legacy files and 0 failures. The ownership audit reported no unowned records and no relationship ownership mismatches. The rehearsal also identified that a replacement host needs its new address in Django's allowed-host/origin configuration; the release-candidate restore helper now adapts a recovered `.env` automatically for the detected replacement-host IPv4 address while retaining the original values.

Rehearsal procedure retained below for future releases:

1. From the real MakerVault installation, create a managed backup from **Settings → Backup & restore** and verify it.
2. Download/copy that bundle to a **separate isolated host** with empty target storage.
3. Build the exact release-candidate revision there.
4. Keep printer/cloud/integration network access isolated until restored schedules are reviewed.
5. Restore the bundle using the documented recovery helper.
6. Run:
   ```bash
   sudo docker compose exec -T makervault python manage.py v1_release_preflight
   sudo docker compose exec -T --user makervault makervault python manage.py verify_private_storage
   sudo docker compose exec -T makervault python manage.py audit_private_ownership --fail-on-issues
   ```
7. Sign in and manually verify a known project, inventory item, current and older private file version, model, printer/spool data, account settings and storage summary.
8. Record the source and target storage layouts, candidate commit and any deviations.

Do not delete the original backup after the rehearsal. A successful synthetic CI restore is not a substitute for this test.

## UI/accessibility acceptance

Check desktop and mobile layouts, keyboard-only navigation, visible focus, modal close/cancel behaviour, form labels, empty/error states, destructive confirmations and reduced-motion behaviour. Authentication pages and the main React application should use consistent MakerVault wording and branding.

## Release decision

All mandatory v1.0 release gates are complete: representative real-install recovery, clean installation, restart/persistence checks, deployment preflight, security/reliability checks, UI/accessibility review and green final CI. MakerVault v1.0.0 is approved for stable release.

A v1.0 release candidate may retain printer adapters explicitly labelled **Experimental** where hardware validation is unavailable. Experimental status must describe validation uncertainty, not hide already implemented functionality. Open issue #37 continues to track representative hardware testing after the release candidate.
