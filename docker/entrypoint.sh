#!/bin/sh
# Entrypoint: sets up the PUID/PGID user/group. Standard pattern for
# self-hosted tools (Sonarr, Radarr, qBittorrent on Unraid all do this,
# typically 99:100) - keeps folders the app creates from ending up
# owned by root on the array.
#
# NB: supervisord itself stays root (needed to handle signals correctly
# as PID 1 and to open /dev/stdout/stderr for its children - a non-root
# supervisord trying to reopen those paths hits EACCES, a known issue).
# Privilege drop happens per-program inside supervisord.conf
# (user=%(ENV_RUN_AS_USER)s), not here.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" nazgarr
fi
GROUP_NAME=$(getent group "$PGID" | cut -d: -f1)

if ! getent passwd "$PUID" >/dev/null 2>&1; then
    useradd -u "$PUID" -g "$GROUP_NAME" -M -s /usr/sbin/nologin nazgarr
fi
USER_NAME=$(getent passwd "$PUID" | cut -d: -f1)

# /app/config is mounted as a DIRECTORY (never a file): if the host path
# doesn't exist yet, Docker still creates a directory there (correct
# behaviour), never a file in the wrong place. If config.yaml is missing
# inside it, seed it from the default template so the container still
# starts instead of crashing - physical disks are never listed here,
# they're registered once mounted under disk_scan_root (see
# config.example.yaml). Also covers app/data's default location: it
# lives under this same mount (config.example.yaml's data_dir), so a
# single appdata volume is enough for both.
mkdir -p /app/config
if [ ! -f /app/config/config.yaml ]; then
    cp /app/config.example.yaml /app/config/config.yaml
    echo "config/config.yaml not found: created from config.example.yaml with default values."
fi
chown -R "$PUID:$PGID" /app/config

export RUN_AS_USER="$USER_NAME"
exec "$@"
