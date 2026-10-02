#!/usr/bin/env bash
# Integration rehearsal for the three-container managed backup design.
# Uses disposable PostgreSQL containers/volumes and the normal MakerVault image.
set -euo pipefail

image="${1:-makervault-ci}"
token="mv-managed-backup-$(date +%s)-${RANDOM}"
network="$token"
containers=()
volumes=()

cleanup() {
  for item in "${containers[@]}"; do docker rm -fv "$item" >/dev/null 2>&1 || true; done
  for item in "${volumes[@]}"; do docker volume rm "$item" >/dev/null 2>&1 || true; done
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_db() {
  local name="$1"
  for _ in $(seq 1 60); do
    if docker exec "$name" pg_isready -U makervault -d makervault >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Database $name did not become ready" >&2
  return 1
}

docker image inspect "$image" >/dev/null
docker network create --internal "$network" >/dev/null

source_db="$token-source-db"
target_db="$token-target-db"
for db in "$source_db" "$target_db"; do
  containers+=("$db")
  docker run -d --name "$db" --network "$network" \
    -e POSTGRES_DB=makervault \
    -e POSTGRES_USER=makervault \
    -e POSTGRES_PASSWORD=synthetic-backup-password \
    postgres:18.6 >/dev/null
  wait_db "$db"
done

for kind in source-media source-keys target-media target-keys backups import-backups; do
  volume="$token-$kind"
  docker volume create "$volume" >/dev/null
  volumes+=("$volume")
  printf -v "${kind//-/_}" '%s' "$volume"
done

docker exec "$source_db" psql -U makervault -d makervault -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE recovery_marker (id integer primary key, value text not null); INSERT INTO recovery_marker VALUES (1, 'integrated-backup-ok');" >/dev/null

# Match the image's built-in application UID for this direct, entrypoint-free rehearsal.
docker run --rm --network none \
  -v "$source_media:/app/media" -v "$source_keys:/app/keys" -v "$backups:/app/backups" \
  --entrypoint sh "$image" -c \
  "printf 'media-ok\n' > /app/media/example.txt; printf 'key-ok\n' > /app/keys/private_storage.key; chown -R 911:911 /app/media /app/keys /app/backups" >/dev/null

common_env=(
  -e DJANGO_SECRET_KEY=ci-only-secret-key-for-managed-backup-0123456789
  -e DATABASE_PORT=5432
  -e POSTGRES_DB=makervault
  -e POSTGRES_USER=makervault
  -e POSTGRES_PASSWORD=synthetic-backup-password
  -e MAKERVAULT_STORAGE_KEY_FILE=/app/keys/private_storage.key
  -e MAKERVAULT_BACKUP_ROOT=/app/backups
)

docker run --rm --user 911:911 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$source_media:/app/media:ro" \
  -v "$source_keys:/app/keys:ro" \
  -v "$backups:/app/backups" \
  --entrypoint python "$image" \
  manage.py backup_bundle create --id synthetic-integrated --label "CI integrated backup"

docker run --rm --user 911:911 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$source_media:/app/media:ro" \
  -v "$source_keys:/app/keys:ro" \
  -v "$backups:/app/backups:ro" \
  --entrypoint python "$image" \
  manage.py backup_bundle validate --id synthetic-integrated

# Rehearse importing a downloaded bundle onto a clean backup volume. This uses
# the same MakerVault image, not a fourth service or a second long-running image.
docker run --rm --network none \
  -v "$backups:/from:ro" -v "$import_backups:/to" \
  --entrypoint sh "$image" -c \
  'cp /from/synthetic-integrated.mvbackup /to/imported-integrated.mvbackup; chown 911:911 /to /to/imported-integrated.mvbackup; chmod 700 /to; chmod 600 /to/imported-integrated.mvbackup'

docker run --rm --user 911:911 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$source_media:/app/media:ro" \
  -v "$source_keys:/app/keys:ro" \
  -v "$import_backups:/app/backups" \
  --entrypoint python "$image" \
  manage.py backup_bundle register --id imported-integrated

docker run --rm --user 0:0 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$target_db" \
  -v "$target_media:/app/media" \
  -v "$target_keys:/app/keys" \
  -v "$backups:/app/backups:ro" \
  --entrypoint python "$image" \
  manage.py backup_bundle restore --id synthetic-integrated

value="$(docker exec "$target_db" psql -U makervault -d makervault -Atc "SELECT value FROM recovery_marker WHERE id=1")"
test "$value" = "integrated-backup-ok"

docker run --rm --network none \
  -v "$target_media:/app/media:ro" -v "$target_keys:/app/keys:ro" \
  --entrypoint sh "$image" -c \
  'test "$(cat /app/media/example.txt)" = media-ok && test "$(cat /app/keys/private_storage.key)" = key-ok'

echo "PASS: three-container managed backup database/media/key recovery rehearsal"
