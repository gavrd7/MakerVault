#!/usr/bin/env bash
# Synthetic data only. No production Compose project, ports or storage are used.
set -euo pipefail
image="${1:-makervault-ci}"
root="$(cd "$(dirname "$0")/.." && pwd)"
token="mv-recovery-$(date +%s)-${RANDOM}"
work="$(mktemp -d)"
chmod 700 "$work"
umask 077
containers=()
volumes=()
cleanup() {
  for item in "${containers[@]}"; do docker rm -fv "$item" >/dev/null 2>&1 || true; done
  for item in "${volumes[@]}"; do docker volume rm "$item" >/dev/null 2>&1 || true; done
  docker network rm "$token" >/dev/null 2>&1 || true
  # Container-written bind data can be root-owned. Delete only this run's temp mount.
  docker run --rm --network none -v "$work:/cleanup" --entrypoint sh "$image" -c 'rm -rf /cleanup/*' || true
  rm -rf "$work"
}
trap cleanup EXIT
docker image inspect "$image" >/dev/null
docker pull postgres:18.6 >/dev/null
docker network create --internal "$token" >/dev/null
for mode in volume bind; do
  echo "Recovery rehearsal: $mode storage"
  for side in source target; do
    db="$token-$mode-$side"
    containers+=("$db")
    docker run -d --name "$db" --network "$token" \
      -e POSTGRES_USER=makervault -e POSTGRES_DB=makervault \
      -e POSTGRES_PASSWORD=synthetic-recovery-only postgres:18.6 >/dev/null
    ready=false
    for attempt in $(seq 1 60); do
      if docker exec "$db" pg_isready -h 127.0.0.1 -U makervault -d makervault >/dev/null 2>&1; then ready=true; break; fi
      sleep 1
    done
    "$ready" || { echo "Database did not become ready" >&2; exit 1; }
    for kind in media keys; do
      storage="$token-$mode-$side-$kind"
      if [ "$mode" = volume ]; then
        docker volume create "$storage" >/dev/null
        volumes+=("$storage")
      else
        storage="$work/$mode-$side-$kind"
        mkdir -p "$storage"
      fi
      printf -v "${side}_${kind}" '%s' "$storage"
    done
  done
  app() {
    local side="$1"; shift
    local media_var="${side}_media" keys_var="${side}_keys"
    local run_user=0:0
    if [ "$phase" = verify ]; then run_user=911:911; fi
    docker run --rm -i --user "$run_user" --network "$token" \
      -e DATABASE_HOST="$token-$mode-$side" -e POSTGRES_PASSWORD=synthetic-recovery-only \
      -e DJANGO_SECRET_KEY=synthetic-recovery-only-secret-at-least-32-characters \
      -e MAKERVAULT_STORAGE_KEY_FILE=/app/keys/private_storage.key \
      -e MAKERVAULT_RECOVERY_REHEARSAL=synthetic-only -e RECOVERY_PHASE="$phase" \
      -v "${!media_var}:/app/media" -v "${!keys_var}:/app/keys" \
      -v "$root/scripts/recovery_fixture.py:/fixture.py:ro" \
      --entrypoint python "$image" "$@"
  }
  phase=seed
  app source -c 'import base64,os; open("/app/keys/private_storage.key","wb").write(base64.urlsafe_b64encode(os.urandom(32)))'
  app source manage.py migrate --noinput >/dev/null
  app source manage.py shell -c 'exec(open("/fixture.py").read())'
  # No worker/web service is started: the source is quiescent and the network is internal.
  docker exec "$token-$mode-source" pg_dump -U makervault -d makervault -Fc > "$work/database.dump"
  for kind in media keys; do
    source_var="source_$kind"; target_var="target_$kind"
    docker run --rm --network none -v "${!source_var}:/data:ro" --entrypoint tar "$image" -C /data -czf - . > "$work/$kind.tar.gz"
    docker run --rm -i --network none -v "${!target_var}:/data" --entrypoint tar "$image" -C /data -xzf - < "$work/$kind.tar.gz"
  done
  docker exec -i "$token-$mode-target" pg_restore --exit-on-error --no-owner --no-privileges -U makervault -d makervault < "$work/database.dump"
  docker run --rm --network none -v "$target_media:/app/media" -v "$target_keys:/app/keys" \
    --entrypoint chown "$image" -R 911:911 /app/media /app/keys
  phase=verify
  app target manage.py shell -c 'exec(open("/fixture.py").read())'
  app target -c 'from pathlib import Path; p=Path("/app/keys/private_storage.key"); p.rename(p.with_suffix(".saved"))'
  if app target manage.py verify_private_storage; then echo "ERROR: missing key accepted" >&2; exit 1; fi
  # Exercise the real entrypoint's missing-key protection before migrations or workers.
  if docker run --rm --network none -v "$target_media:/app/media" -v "$target_keys:/app/keys" \
      -e PUID=911 -e PGID=911 -e MAKERVAULT_STORAGE_KEY_FILE=/app/keys/private_storage.key "$image" true > "$work/missing-key.log" 2>&1; then
    echo "ERROR: startup accepted missing key" >&2; exit 1
  fi
  grep -q 'storage key is missing' "$work/missing-key.log"
  app target -c 'from pathlib import Path; p=Path("/app/keys/private_storage.key"); assert not p.exists(); p.write_text("02"*32)'
  if app target manage.py verify_private_storage; then echo "ERROR: wrong key accepted" >&2; exit 1; fi
  app target -c 'from pathlib import Path; p=Path("/app/keys/private_storage.key"); p.with_suffix(".saved").replace(p)'
  app target manage.py verify_private_storage
  echo "PASS: $mode restore and missing/wrong-key failure checks"
done
