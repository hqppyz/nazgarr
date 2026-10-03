#!/usr/bin/env bash
# Gli adapter Transmission, Deluge e rTorrent/ruTorrent contro client veri in
# Docker (tests/integration/test_real_clients.py). Mai in CI.
#
#   scripts/test_real_clients.sh [argomenti di pytest]
#
# Avvia un container per client con una cartella temporanea montata come
# /srv/seed (un percorso che qui non esiste), esegue i test e alla fine toglie
# container e file. Immagini sostituibili con IT_TRANSMISSION_IMAGE,
# IT_DELUGE_IMAGE, IT_RTORRENT_IMAGE; NAZGARR_IT_KEEP=1 lascia tutto acceso.
set -euo pipefail
cd "$(dirname "$0")/.."

TRANSMISSION_IMAGE="${IT_TRANSMISSION_IMAGE:-lscr.io/linuxserver/transmission:latest}"
DELUGE_IMAGE="${IT_DELUGE_IMAGE:-lscr.io/linuxserver/deluge:latest}"
RTORRENT_IMAGE="${IT_RTORRENT_IMAGE:-crazymax/rtorrent-rutorrent:latest}"
PYTEST="${PYTEST:-.venv/bin/pytest}"
PREFIX="nazgarr-it-$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/nazgarr-it.XXXXXX")"
WORK="$(cd "$WORK" && pwd -P)"
mkdir -p "$WORK/transmission/seed" "$WORK/deluge/seed" "$WORK/rtorrent/seed" "$WORK/rtorrent/data"

cleanup() {
  if [ "${NAZGARR_IT_KEEP:-}" = "1" ]; then
    echo "Kept: containers $PREFIX-*, files in $WORK"
    return
  fi
  docker rm -f "$PREFIX-transmission" "$PREFIX-deluge" "$PREFIX-rtorrent" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

ids=(-e PUID="$(id -u)" -e PGID="$(id -g)" -e TZ=Etc/UTC --add-host=host.docker.internal:host-gateway)

docker run -d --name "$PREFIX-transmission" "${ids[@]}" -e USER=nazgarr -e PASS=it-secret \
  -p 127.0.0.1::9091 -v "$WORK/transmission/seed:/srv/seed" "$TRANSMISSION_IMAGE" >/dev/null
docker run -d --name "$PREFIX-deluge" "${ids[@]}" \
  -p 127.0.0.1::8112 -v "$WORK/deluge/seed:/srv/seed" "$DELUGE_IMAGE" >/dev/null
docker run -d --name "$PREFIX-rtorrent" "${ids[@]}" \
  -p 127.0.0.1::8000 -p 127.0.0.1::8080 \
  -v "$WORK/rtorrent/data:/data" -v "$WORK/rtorrent/seed:/srv/seed" "$RTORRENT_IMAGE" >/dev/null

port() { docker port "$1" "$2" | head -n1 | sed 's/.*://'; }
TR="http://127.0.0.1:$(port "$PREFIX-transmission" 9091)"
DE="http://127.0.0.1:$(port "$PREFIX-deluge" 8112)"
RT="http://127.0.0.1:$(port "$PREFIX-rtorrent" 8000)/RPC2"
RU="http://127.0.0.1:$(port "$PREFIX-rtorrent" 8080)"

XML='<?xml version="1.0"?><methodCall><methodName>system.client_version</methodName></methodCall>'
wait_for() {  # nome, comando che riesce quando il client risponde
  local name="$1"; shift
  for _ in $(seq 1 120); do
    if "$@" >/dev/null 2>&1; then echo "$name ready"; return 0; fi
    sleep 1
  done
  echo "$name did not start" >&2
  docker logs "$PREFIX-$name" 2>&1 | tail -n 30 >&2
  return 1
}
wait_for transmission sh -c "curl -s -o /dev/null -w '%{http_code}' '$TR/transmission/rpc' | grep -qE '401|409'"
wait_for deluge curl -sf -H 'Content-Type: application/json' -d '{"method":"auth.login","params":["deluge"],"id":1}' "$DE/json"
wait_for rtorrent sh -c "curl -sf -H 'Content-Type: text/xml' -d '$XML' '$RT' | grep -q string"
wait_for rtorrent sh -c "curl -sf -H 'Content-Type: text/xml' -d '$XML' '$RU/plugins/httprpc/action.php' | grep -q string"

for c in "$PREFIX-transmission" "$PREFIX-deluge" "$PREFIX-rtorrent"; do
  image="$(docker inspect -f '{{.Config.Image}}' "$c")"
  echo "$c: $image $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}} {{index .RepoDigests 0}}' "$image")"
done

NAZGARR_IT_CLIENTS=1 NAZGARR_IT_DIR="$WORK" \
NAZGARR_IT_TRANSMISSION_URL="$TR" NAZGARR_IT_TRANSMISSION_USER=nazgarr NAZGARR_IT_TRANSMISSION_PASSWORD=it-secret \
NAZGARR_IT_DELUGE_URL="$DE" NAZGARR_IT_DELUGE_PASSWORD=deluge \
NAZGARR_IT_RTORRENT_URL="$RT" NAZGARR_IT_RUTORRENT_URL="$RU" \
  "$PYTEST" tests/integration -v -p no:cacheprovider "$@"
