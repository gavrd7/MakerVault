#!/usr/bin/env bash
# Integration rehearsal for the isolated backup-agent image. Disposable resources only.
set -euo pipefail

image="${1:-makervault-backup-ci}"
token="mv-backup-agent-$(date +%s)-${RANDOM}"
work="$(mktemp -d)"
network="$token"
containers=()
volumes=()

cleanup() {
  for item in "${containers[@]}"; do docker rm -fv "$item" >/dev/null 2>&1 || true; done
  for item in "${volumes[@]}"; do docker volume rm "$item" >/dev/null 2>&1 || true; done
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$work"
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
    -e POSTGRES_PASSWORD=synthetic-agent-password \
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
  "CREATE TABLE recovery_marker (id integer primary key, value text not null); INSERT INTO recovery_marker VALUES (1, 'backup-agent-ok');" >/dev/null

docker run --rm --network none \
  -v "$source_media:/source/media" -v "$source_keys:/source/keys" -v "$backups:/backups" \
  --entrypoint sh "$image" -c \
  "printf 'media-ok\n' > /source/media/example.txt; printf 'key-ok\n' > /source/keys/private_storage.key; chown -R 1000:1000 /source/media /source/keys /backups" >/dev/null

mkdir -p "$work/config"
printf 'SYNTHETIC_BACKUP_AGENT=true\n' > "$work/config/.env"
printf 'services: {}\n' > "$work/config/compose.yaml"

common_env=(
  -e DATABASE_PORT=5432
  -e POSTGRES_DB=makervault
  -e POSTGRES_USER=makervault
  -e POSTGRES_PASSWORD=synthetic-agent-password
)

docker run --rm --user 1000:1000 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$source_media:/source/media:ro" \
  -v "$source_keys:/source/keys:ro" \
  -v "$backups:/backups" \
  -v "$work/config:/source/config:ro" \
  "$image" backup --id synthetic-sidecar --label "CI sidecar rehearsal"

docker run --rm --user 1000:1000 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$backups:/backups:ro" \
  "$image" validate --id synthetic-sidecar

# Rehearse the clean-host ownership handoff used when importing an off-server
# bundle before MakerVault has ever started and chowned the backup volume.
docker run --rm --network none \
  -v "$backups:/from:ro" -v "$import_backups:/to" \
  --entrypoint sh "$image" -c \
  'cp /from/synthetic-sidecar.mvbackup /to/imported-sidecar.mvbackup; chown 1000:1000 /to /to/imported-sidecar.mvbackup; chmod 700 /to; chmod 600 /to/imported-sidecar.mvbackup'

docker run --rm --user 1000:1000 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$import_backups:/backups" \
  "$image" register --id imported-sidecar

docker run --rm --user 1000:1000 --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$source_db" \
  -v "$import_backups:/backups:ro" \
  "$image" validate --id imported-sidecar

docker run --rm --network "$network" \
  "${common_env[@]}" -e DATABASE_HOST="$target_db" \
  -v "$target_media:/source/media" \
  -v "$target_keys:/source/keys" \
  -v "$backups:/backups:ro" \
  "$image" restore --id synthetic-sidecar

value="$(docker exec "$target_db" psql -U makervault -d makervault -Atc "SELECT value FROM recovery_marker WHERE id=1")"
test "$value" = "backup-agent-ok"

docker run --rm --network none \
  -v "$target_media:/source/media:ro" -v "$target_keys:/source/keys:ro" \
  --entrypoint sh "$image" -c \
  'test "$(cat /source/media/example.txt)" = media-ok && test "$(cat /source/keys/private_storage.key)" = key-ok'

echo "PASS: isolated backup-agent database/media/key recovery rehearsal"
