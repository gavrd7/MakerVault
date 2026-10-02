# Back up and restore

**Goal:** recover your installation, including encrypted private files, after a disk or server failure.

!!! warning "The key is essential"
    A database backup alone is not a complete backup. Encrypted uploads require both their stored bytes and the matching key. Do not generate a replacement key to repair missing-key errors.

## What belongs in a recovery set

| Item | Why you need it |
| --- | --- |
| PostgreSQL dump | Accounts, projects, catalogue records, file references and other structured data |
| Media archive | Uploaded files and cached images |
| Key archive | The key that decrypts private uploads |
| `.env` and Compose configuration | Secrets, storage paths and deployment settings |
| Source revision | The matching version of MakerVault for the first restore |
| Redis data (optional for core records) | Queue/cache state; not a substitute for the database |

Keep the set together in a protected backup destination, with another copy on a different device. A folder on the same failing disk is not disaster recovery. Protect the entire set: it contains credentials, personal data and the key needed to read the uploads.

## Create a consistent backup

The following Linux procedure works with the standard Compose mounts, including named volumes or bind mounts. It stops the app briefly so uploads and database records cannot change independently while being copied. Run it from the source folder, in the same terminal. Make sure enough free space is available first.

Create a unique destination and build/reuse the application's image:

```bash
umask 077
backup_dir="$HOME/makervault-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
git rev-parse HEAD > "$backup_dir/source-commit.txt"
cp .env compose.yaml "$backup_dir/"
sudo docker compose build makervault
sudo docker compose stop makervault
```

Also preserve any Compose override files, external secret files and intentional shell-provided configuration. `cp .env compose.yaml` covers only the standard setup. Do not publish this recovery set or attach it to an issue.

The database remains running for its logical dump. Stop if any step below fails; do not treat an incomplete set as a valid backup.

```bash
sudo docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_dir/database.dump"
sudo docker compose run --rm -T --no-deps --entrypoint tar makervault -C /app/media -czf - . > "$backup_dir/media.tar.gz"
sudo docker compose run --rm -T --no-deps --entrypoint tar makervault -C /app/keys -czf - . > "$backup_dir/keys.tar.gz"
```

These one-off commands mount the normal storage but bypass the application's normal startup; they do not start another web server or migrate the database. If you use an external `MAKERVAULT_STORAGE_KEY` or a custom key-file location, back up that actual key source as well: the default `/app/keys` archive may not contain it.

Optionally capture Redis with it stopped:

```bash
sudo docker compose stop redis
sudo docker compose run --rm -T --no-deps --entrypoint tar redis -C /data -czf - . > "$backup_dir/redis.tar.gz"
sudo docker compose start redis
```

Check the main backup files:

```bash
test -s "$backup_dir/database.dump"
tar -tzf "$backup_dir/media.tar.gz" > /dev/null
tar -tzf "$backup_dir/keys.tar.gz" > /dev/null
sudo docker compose exec -T postgres pg_restore --list < "$backup_dir/database.dump" > "$backup_dir/database-contents.txt"
sudo docker compose start makervault
sudo docker compose ps
```

If a dump or archive step fails, restart any services you stopped with `sudo docker compose start redis makervault`, investigate, and create a new recovery set. Never label the failed set complete.

After every backup file is final, record checksums:

```bash
(cd "$backup_dir" && sha256sum database.dump media.tar.gz keys.tar.gz .env compose.yaml source-commit.txt > SHA256SUMS)
```

Include additional configuration/key files and optional Redis archives in your checksum list too. Checksums detect accidental corruption, not malicious replacement of both files and manifest.

Check the application works again. Copy the protected recovery set off the server. These checks detect some broken archives; only a successful test restore proves the whole set is usable.

Do not copy a running PostgreSQL data directory as a substitute for `pg_dump` unless you are deliberately using a PostgreSQL-aware physical backup method.

## Restore to a clean test server

Use a separate host or VM with no existing MakerVault deployment. The Compose project uses fixed container names; changing only the port does not isolate a second installation on the same Docker host. The following procedure is for **empty target storage**, not a repair over a live installation.

1. Install Docker/Compose and clone the repository as in the installation chapter.
2. Read `source-commit.txt` and check out that exact revision with `git checkout COMMIT_FROM_BACKUP`, substituting its value.
3. Copy the saved `.env` into the source directory. Adjust bind paths, hostnames/origins and port for the test server. Keep the database credentials, Django secret and matching storage key. Use empty target storage paths/volumes.
4. Keep the target isolated from printers, Spoolman and cloud integrations during the test. Restored schedules can run as soon as the app starts.
5. In that same terminal set `backup_dir` to the restored backup folder's absolute path.

Before starting services or extracting anything, verify the transferred recovery set:

```bash
(cd "$backup_dir" && sha256sum --check SHA256SUMS)
```

Stop on a missing file or mismatch. Older sets without a manifest need careful review and a test restore; do not create a manifest after transfer and treat it as evidence that transfer was correct. Extract only your own trusted backups.

Build the matching image and start only the backing services:

```bash
sudo docker compose build makervault
sudo docker compose up -d postgres redis
sudo docker compose ps
```

Wait for PostgreSQL to become healthy. Restore its records into the empty database, then media and keys:

```bash
sudo docker compose exec -T postgres sh -c 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$backup_dir/database.dump"
sudo docker compose run --rm -T --no-deps --entrypoint tar makervault -C /app/media -xzf - < "$backup_dir/media.tar.gz"
sudo docker compose run --rm -T --no-deps --entrypoint tar makervault -C /app/keys -xzf - < "$backup_dir/keys.tar.gz"
```

Stop on any error. Do not use these extraction commands to mix a backup with existing live files. The default startup repairs application storage ownership; deployments with `FIX_PERMISSIONS=false` must arrange correct ownership themselves.

For the normal recovery test, a fresh Redis queue avoids replaying old queued work. If preserving Redis is intentional, stop Redis and restore its archive to empty `/data` through a one-off container before restarting it.

Start MakerVault only after database, media and the correct key are restored:

```bash
sudo docker compose up -d makervault
sudo docker compose logs --tail=100 makervault
```

## Verify the recovery

Sign in; open a known project; inspect inventory; download a private file and an older version; open a model; check storage and account settings. Disable unwanted schedules before permitting external network access. Keep the original backup unchanged until these checks pass.

Once restoration works at the backed-up revision, follow the ordinary [update procedure](updates.md). Returning only the application code to an older version does not reverse database migrations.

## Authenticate restored private files

On versions that include the recovery audit, run it after restoring the database, media and key, before starting the normal app/worker:

```bash
sudo docker compose run --rm -T --no-deps --entrypoint python makervault manage.py verify_private_storage
sudo docker compose run --rm -T --no-deps --entrypoint python makervault manage.py audit_private_ownership --fail-on-issues
```

The private-file audit is read-only. It reads every referenced private file, authenticates encrypted content and compares recorded SHA-256 values where available. It fails for missing files, missing/invalid/wrong keys, damaged encrypted blobs or checksum mismatches. It reports legacy plaintext separately. It does not create a key, repair files, check unreferenced media or prove all application relationships are correct. Large libraries require time and temporary disk space for decrypted reads; do not run it as a frequent health probe.

After normal startup has restored storage ownership, repeat the file audit as the application's user to check permissions too:

```bash
sudo docker compose exec -T --user makervault makervault python manage.py verify_private_storage
```

If the backed-up release predates this command, perform its manual recovery checks first; do not substitute newer application code into the initial restore solely to obtain the command.

## Automated recovery rehearsal

The repository's Docker CI runs `scripts/recovery_rehearsal.sh` against the built application image. It creates synthetic users, a project, inventory and two encrypted model/file revisions, then dumps PostgreSQL and archives media/keys. It restores into fresh target storage twice: once with named volumes and once with bind mounts.

Acceptance checks cover password login, project/model/version relationships, old/current authenticated downloads, rejection of another owner's access and private-file authentication as the unprivileged app user. Negative checks require missing and wrong keys to fail and require the real startup script to refuse replacement-key generation over encrypted uploads.

The rehearsal uses uniquely named disposable containers, an internal Docker network, no published ports and no web/worker processes. It removes only its own resources. This is synthetic same-version recovery evidence, not a copy of your installation and not a full OIDC/MFA, reverse-proxy, browser, clean-install or historical-upgrade test.

For a development checkout with Docker available:

```bash
sudo docker build -t makervault-recovery .
sudo bash scripts/recovery_rehearsal.sh makervault-recovery
```

A release still needs a protected restore of a representative real backup on a separate host, including its deployment configuration and manual UI checks above. Keep that test isolated from integrations until schedules have been reviewed.
