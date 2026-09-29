# Bind mounts and permissions

**Advanced · Configure before first start where possible**

New to volumes and host folders? Start with [Choose your storage](../getting-started/storage.md) for the comparison and beginner examples. This chapter covers further operational details.

A named volume is managed by Docker. A bind mount stores data in a specific folder on the host. Both persist beyond the container's lifetime.

## Configure host folders

Create four separate folders on a reliable local disk. These are example paths, not required names:

```bash
sudo mkdir -p /srv/makervault/media /srv/makervault/keys /srv/makervault/postgres /srv/makervault/redis
id -u
id -g
```

Set the corresponding existing `.env` lines:

```dotenv
MEDIA_STORAGE=/srv/makervault/media
KEY_STORAGE=/srv/makervault/keys
POSTGRES_STORAGE=/srv/makervault/postgres
REDIS_STORAGE=/srv/makervault/redis
PUID=1000
PGID=1000
FIX_PERMISSIONS=true
```

Use the actual numeric user/group IDs from `id`, not automatically `1000`. An absolute path is a bind mount; the supplied simple default names refer to declared Docker volumes. Arbitrary new named-volume names also need matching Compose declarations.

The container targets stay `/app/media`, `/app/keys`, `/var/lib/postgresql` and `/data`. In particular, the supplied PostgreSQL 18 deployment mounts `/var/lib/postgresql`, not the older `/var/lib/postgresql/data` convention.

MakerVault's startup fixes ownership of its own media/key directories by default. PostgreSQL uses its image's own database user; do not recursively change its directory to MakerVault's PUID/PGID. Avoid putting live database storage on an unverified SMB/NFS mount.

## Moving an existing installation

Changing a path points at different storage. It does not copy or migrate the existing records. Use the [backup and clean restore procedure](../administration/backup.md), with the new paths configured on the restore target. Keep the old storage untouched until the restored system passes verification.

## Key handling

The default key is generated once at `/app/keys/private_storage.key`. Keep key and media in separate storage sources and back up both. If encrypted blobs exist but the key is missing, startup refuses to silently generate a substitute.

The advanced environment option `MAKERVAULT_STORAGE_KEY` can supply the key directly; `MAKERVAULT_STORAGE_KEY_FILE` can select a file. Do not change key material as if it were a password reset. This guide does not provide a supported key-rotation procedure.

## Permissions failures

Check that the source path exists, the filesystem is writable, disk space is available, and the configured IDs match your intended ownership. Read logs for the exact failing path. Do not use `chmod -R 777` on the entire installation as a fix, especially the keys and database.
