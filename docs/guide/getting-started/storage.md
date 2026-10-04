# Choose where your data lives

**Goal:** choose between Docker-managed named volumes and host bind mounts before your first start.

Both options use Docker. A bind mount is not an alternative way to run MakerVault without Docker; it is another way to give its containers persistent storage.

A container can be replaced during an update. The database and uploads must therefore live outside that container's temporary writable layer. Named volumes and bind mounts both provide that persistence. Neither is a backup by itself.

## The difference

| Question | Docker-managed named volume | Host bind mount |
| --- | --- | --- |
| Who chooses the host location? | Docker manages the storage location | You choose a specific host folder |
| What does `.env` contain? | A supplied volume name, e.g. `makervault_media` | An absolute host path, e.g. `/srv/makervault/media` |
| Must I create a host folder first? | No; Compose creates the declared volumes | Create the intended directories before starting |
| What is easiest for a new Docker user? | Keep the supplied defaults | Useful when you already organise server data in known folders |
| Does data survive replacing the app container? | Yes, while the volume is retained | Yes, while the host files/folder are retained |
| How do I back it up? | Through a container mounting the volume, or suitable Docker-aware tooling | Through the mounted container or suitable host backup tooling |
| Main thing to watch | Do not delete the volume or use `down -v` | Correct path, disk availability and ownership; host deletion affects live data |

Named volumes still consume space on the Docker host's disk. They are not cloud storage. Bind mounts do not automatically give you an extra copy of the data; the host directory is the actual live storage.

Docker's [volumes guide](https://docs.docker.com/engine/storage/volumes/) and [bind mounts guide](https://docs.docker.com/engine/storage/bind-mounts/) describe the underlying storage options.

## MakerVault's five storage locations

| `.env` setting | What it stores | Path seen inside the container |
| --- | --- | --- |
| `MEDIA_STORAGE` | Uploaded files/private encrypted blobs and cached images | `/app/media` |
| `KEY_STORAGE` | The key needed to decrypt private uploads | `/app/keys` |
| `POSTGRES_STORAGE` | Database records, accounts and settings | `/var/lib/postgresql` |
| `REDIS_STORAGE` | Background queue/cache state | `/data` |
| `BACKUP_STORAGE` | Managed `.mvbackup` recovery bundles and validation metadata | `/app/backups` |

Your source folder, containing `compose.yaml` and `.env`, is separate. Keeping a copy of the source folder alone does not back up these persistent data locations.

## Option A: keep the named-volume defaults

For the simplest setup, retain:

```dotenv
MEDIA_STORAGE=makervault_media
KEY_STORAGE=makervault_keys
POSTGRES_STORAGE=makervault_postgres
REDIS_STORAGE=makervault_redis
BACKUP_STORAGE=makervault_backups
```

You do not need to make directories named `makervault_media` beside your Compose file. Compose creates its declared named volumes when you start the stack. Their actual Docker names may include the project-name prefix.

Keep the supplied names unless also editing the volume declarations in `compose.yaml`. Changing them to arbitrary new names in `.env` alone is not a supported shortcut to creating undeclared volumes.

Use the [backup procedure](../administration/backup.md) without needing to know Docker's internal storage folder. Do not manually edit files under Docker's storage directory.

## Option B: use your own server folders

For a **new Linux installation**, you might choose this layout:

| Host folder | Purpose |
| --- | --- |
| `/srv/makervault/app` | Optional location for the cloned source and `.env` |
| `/srv/makervault/media` | Live uploads/images |
| `/srv/makervault/keys` | Live encryption key |
| `/srv/makervault/postgres` | Live database files |
| `/srv/makervault/redis` | Live queue/cache data |
| `/srv/makervault/backups` | Managed recovery bundles |

The source can also remain in `~/apps/MakerVault` as in the installation guide; you do not have to move it to use these data folders. A path such as `/mnt/Server/MakerVault/media` is equally valid if that is where you organise your server's storage. Choose a reliable local filesystem; external/network mounts need additional care to ensure availability before startup.

Create the data folders:

```bash
sudo mkdir -p /srv/makervault/media /srv/makervault/keys /srv/makervault/postgres /srv/makervault/redis /srv/makervault/backups
```

Replace the **five existing storage entries** in `.env` with:

```dotenv
MEDIA_STORAGE=/srv/makervault/media
KEY_STORAGE=/srv/makervault/keys
POSTGRES_STORAGE=/srv/makervault/postgres
REDIS_STORAGE=/srv/makervault/redis
BACKUP_STORAGE=/srv/makervault/backups
```

Use full absolute paths beginning with `/`. Avoid `~`, relative paths and spaces for this beginner setup. If using the commented examples in `.env.example`, remove their `#` and remove/replace the old active entries so there is only one active entry per setting.

### Host path versus container path

With `MEDIA_STORAGE=/srv/makervault/media`, Docker makes that host folder available **inside the app container as `/app/media`**. These are two views of the same data. Files do not need to be manually copied between them.

Likewise, the host's `/srv/makervault/keys/private_storage.key` is seen by the app as `/app/keys/private_storage.key`. Native HTTPS material is kept alongside it under `/srv/makervault/keys/tls/` (seen as `/app/keys/tls/`), so it automatically follows the same named-volume or bind-mount choice. Leave:

```dotenv
MAKERVAULT_STORAGE_KEY_FILE=/app/keys/private_storage.key
```

Do not replace that container path with the host's `/srv/...` path.

### Set file ownership

On the host, run as the Linux user intended to own the application files:

```bash
id -u
id -g
```

The first number is the user ID (PUID); the second is the group ID (PGID). Put those numbers in `.env`. For example, if both commands returned `1000`:

```dotenv
PUID=1000
PGID=1000
FIX_PERMISSIONS=true
UMASK=0022
```

Do not run `sudo id` to find your normal user's IDs; it reports root's IDs. MakerVault's startup normally fixes ownership of its application media/key/backup storage. PostgreSQL uses the official image's own user: do not change its data directory to MakerVault's PUID/PGID.

Continue with the normal installation after saving. Bind mounts do not need a separate MakerVault image or different web port.

## Can I mix the two?

Yes. Each storage setting is independent. For example, you can use host folders for media and keys and retain Docker-managed volumes for PostgreSQL and Redis. Document the choices and include all required storage in the recovery plan.

## What survives each operation?

| Operation | Expected storage behaviour |
| --- | --- |
| Stop/start containers | Both types retain data |
| Rebuild/update app | Both types retain data if the same mounts are retained |
| `docker compose down` without `-v` | Removes containers/networks; named volumes and bind data are retained |
| `docker compose down -v` | Removes Compose-managed named volumes, including defaults; do not use for routine maintenance |
| Delete the host bind directory/files | Deletes the actual data stored there |
| Change a storage path/name | Selects different storage; it does not move existing data |
| Host disk failure | Both types can be lost; restore from an independent backup |

A bind mount's files are not removed by `down -v`, but any named volumes in a mixed setup still can be. Avoid the command entirely for routine operations.

## Already have data? Stop before switching

An empty new location can make your installation appear to have lost its accounts or files. Do not keep creating new records while searching for the original data. The old data may still exist in its original mount.

Follow [Back up and restore](../administration/backup.md) to migrate deliberately and verify the new copy before removing the old one. Restore the **matching database, media and key** together. Merely copying the media folder does not transfer your projects/accounts, and copying media without its key cannot recover encrypted private files.

**Next:** return to [Configure your .env file](environment.md) or [installation step 4](install.md#4-pull-and-start-makervault-recommended). Advanced operators can read [permissions and key handling](../advanced/storage.md).
