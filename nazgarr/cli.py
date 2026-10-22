"""Il comando `nazgarr`, per l'installazione senza Docker (pacchetto Python
con pipx, decisione dell'utente 2026-10-02). Fa quello che nel container
fanno entrypoint e supervisord:

    nazgarr init --scan-root /mnt     config.yaml, chiave segreta, controlli
    nazgarr serve                     il server (un solo processo, sempre)
    nazgarr install-service           il servizio systemd (Linux) o launchd (macOS)
    nazgarr reset-password            una password nuova, se l'hai dimenticata
    nazgarr db backups                i backup fatti prima di aggiornare il database
    nazgarr db restore <file>         rimette un backup al posto del database
    nazgarr version

e tutti i comandi client, che parlano con un'istanza in esecuzione
(nazgarr/cli_client, docs/CLI.md).

Senza Docker non c'è nessuna mappatura dei volumi: Nazgarr vede il
filesystem vero, e disk_scan_root è la cartella sotto cui stanno i dischi
(il confine oltre il quale non registra e non sfoglia niente)."""

import json
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path

import yaml
from cryptography.fernet import Fernet

SECRET_FILE = "secret.key"
SERVICE_NAME = "nazgarr"
LAUNCHD_LABEL = "io.github.lktorrentz.nazgarr"


def default_dirs() -> tuple[Path, Path]:
    """(config, dati) nelle posizioni standard della piattaforma."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support" / "Nazgarr"
        return base, base / "data"
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Nazgarr"
        return base, base / "data"
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "nazgarr"
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "nazgarr"
    return config, data


def default_config_path() -> Path:
    return Path(os.environ.get("NAZGARR_CONFIG") or default_dirs()[0] / "config.yaml")


def _write_private(path: Path, content: str) -> None:
    """Un file leggibile solo dal proprietario (la chiave segreta)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.chmod(path, 0o600)


def secret_key(config_path: Path) -> str | None:
    """APP_SECRET_KEY dall'ambiente o dal file accanto alla config: cifra le
    credenziali nel DB, deve restare la stessa per sempre."""
    if os.environ.get("APP_SECRET_KEY"):
        return os.environ["APP_SECRET_KEY"]
    path = config_path.parent / SECRET_FILE
    return path.read_text().strip() if path.exists() else None


def missing_tools() -> list[str]:
    """Programmi esterni che servono: mediainfo (identità dei file, upload) e
    ffmpeg (screenshot degli upload)."""
    missing = [tool for tool in ("ffmpeg",) if shutil.which(tool) is None]
    try:
        from pymediainfo import MediaInfo

        if not MediaInfo.can_parse():
            missing.append("mediainfo")
    except Exception:
        missing.append("mediainfo")
    return missing


def cmd_init(args) -> int:
    config_path = Path(args.config) if args.config else default_config_path()
    data_dir = Path(args.data_dir) if args.data_dir else default_dirs()[1]
    scan_root = Path(args.scan_root).expanduser().resolve()
    if not scan_root.is_dir():
        print(f"{scan_root} does not exist: point --scan-root at the folder your disks are under.", file=sys.stderr)
        return 2
    if config_path.exists() and not args.force:
        print(f"{config_path} already exists (--force rewrites it). The secret key is never touched.")
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump({"disk_scan_root": str(scan_root), "data_dir": str(data_dir)}))
        print(f"Configuration written to {config_path}")
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = config_path.parent / SECRET_FILE
    if not key_path.exists() and not os.environ.get("APP_SECRET_KEY"):
        # Una chiave Fernet (32 byte in base64 url-safe): cifra le credenziali (nazgarr/core/crypto.py).
        _write_private(key_path, Fernet.generate_key().decode() + "\n")
        print(f"Secret key created in {key_path}. Back it up with the database: without it the stored "
              "credentials can't be read.")
    missing = missing_tools()
    if missing:
        print(f"Missing: {', '.join(missing)}. Install them with your package manager "
              "(e.g. apt install mediainfo ffmpeg, brew install media-info ffmpeg).", file=sys.stderr)
    print("Done. Start it with `nazgarr serve`, or as a service with `nazgarr install-service`.")
    return 0


def cmd_serve(args) -> int:
    config_path = Path(args.config) if args.config else default_config_path()
    if not config_path.exists():
        print(f"No configuration at {config_path}: run `nazgarr init --scan-root <folder of your disks>` first.",
              file=sys.stderr)
        return 2
    key = secret_key(config_path)
    if not key:
        print(f"No secret key: set APP_SECRET_KEY or run `nazgarr init` again ({config_path.parent}).",
              file=sys.stderr)
        return 2
    os.environ["CONFIG_PATH"] = str(config_path)
    os.environ["APP_SECRET_KEY"] = key
    import uvicorn

    # Un solo processo: il worker degli upload, il pianificatore e la cartella
    # osservata vivono dentro, con più worker si duplicherebbero.
    uvicorn.run("nazgarr.main:app", host=args.host, port=args.port, workers=1)
    return 0


def systemd_unit(config_path: Path, host: str, port: int) -> str:
    return f"""[Unit]
Description=Nazgarr
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={sys.executable} -m nazgarr.cli serve --config "{config_path}" --host {host} --port {port}
# Come nell'immagine Docker: meno memoria tenuta da glibc per i thread.
Environment=MALLOC_ARENA_MAX=2
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
"""


def launchd_plist(config_path: Path, host: str, port: int, log_dir: Path) -> str:
    args = [sys.executable, "-m", "nazgarr.cli", "serve", "--config", str(config_path),
            "--host", host, "--port", str(port)]
    items = "\n".join(f"    <string>{a}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{items}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_dir / "nazgarr.log"}</string>
  <key>StandardErrorPath</key>
  <string>{log_dir / "nazgarr.log"}</string>
</dict>
</plist>
"""


def cmd_install_service(args) -> int:
    """Scrive il file del servizio per l'utente corrente (che deve poter
    leggere e creare hardlink nei dischi) e dice come attivarlo: niente
    comandi di sistema lanciati da qui."""
    config_path = Path(args.config) if args.config else default_config_path()
    if not config_path.exists():
        print("Run `nazgarr init` first.", file=sys.stderr)
        return 2
    system = platform.system()
    if system == "Linux":
        content = systemd_unit(config_path, args.host, args.port)
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / "nazgarr.service"
        steps = [
            "systemctl --user daemon-reload",
            "systemctl --user enable --now nazgarr",
            "sudo loginctl enable-linger $USER   # start at boot, even without logging in",
        ]
    elif system == "Darwin":
        log_dir = Path.home() / "Library" / "Logs" / "Nazgarr"
        log_dir.mkdir(parents=True, exist_ok=True)
        content = launchd_plist(config_path, args.host, args.port, log_dir)
        path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        steps = [f"launchctl load -w {path}"]
    else:
        print("Services are written for Linux (systemd) and macOS (launchd). On Windows use WinSW or NSSM "
              f"with: {sys.executable} -m nazgarr.cli serve --config \"{config_path}\"", file=sys.stderr)
        return 2
    if args.print:
        print(content)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"Service written to {path}. To start it:")
    for step in steps:
        print(f"  {step}")
    return 0


def _as_db_owner(db_path: str) -> None:
    """`docker exec` gira da root: il DB e i suoi -wal/-shm devono restare
    dell'utente dell'app (PUID), o il server non potrebbe più scriverci."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        owner = os.stat(db_path)
        if owner.st_uid != 0:
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)


def _local_settings(config: str | None):
    """Il config.yaml di questa macchina (CONFIG_PATH nel container), o None
    con l'errore già stampato."""
    config_path = Path(config or os.environ.get("CONFIG_PATH") or default_config_path())
    if not config_path.is_file():
        print(f"No configuration at {config_path}: pass --config.", file=sys.stderr)
        return None
    from nazgarr.core.config import load_settings

    return load_settings(str(config_path))


def cmd_reset_password(args) -> int:
    """Password dimenticata: una nuova direttamente nel database, sulla
    macchina dove gira Nazgarr (chi può lanciarlo ha già accesso ai suoi
    file, non è una porta in più). Chiude tutte le sessioni aperte, come
    cambiarla dalle impostazioni. args.ask: chiede la password (a schermo o
    da stdin), solo dopo aver trovato l'account."""
    settings = _local_settings(args.config)
    if settings is None:
        return 2
    db_path = settings.db_path
    if not Path(db_path).is_file():
        print(f"No database at {db_path}.", file=sys.stderr)
        return 2
    _as_db_owner(db_path)
    from nazgarr.core import db, settings_repo
    from nazgarr.web import auth

    engine = db.make_engine(db_path)
    try:
        with db.make_session_factory(engine)() as session:
            username = settings_repo.get_setting(session, "auth_username")
            if not auth.is_auth_configured(session):
                print("No account yet: open Nazgarr and create it with the setup code printed in its log.",
                      file=sys.stderr)
                return 2
            username = (args.username or "").strip() or username
            password = args.ask()
            if len(password) < 8:
                print("The password needs at least 8 characters. Nothing changed.", file=sys.stderr)
                return 2
            settings_repo.set_setting(session, "auth_username", username)
            settings_repo.set_setting(session, "auth_password_hash", auth.hash_password(password))
            auth.revoke_all_tokens(session)
    finally:
        engine.dispose()
    print(f"New password set for {username}. Every open session is logged out: log in again. "
          "API keys keep working.")
    return 0


def cmd_db_backups(args) -> int:
    """I backup fatti prima di un aggiornamento del database
    (nazgarr/core/db_backup.py), dal più recente. args.json: per gli script."""
    settings = _local_settings(args.config)
    if settings is None:
        return 2
    from nazgarr.core import db_backup, db_startup

    folder = db_backup.backups_dir(settings.data_dir)
    backups = db_backup.list_backups(folder)
    status = db_startup.read_status(settings.data_dir) or {}
    # Il backup di prima dell'aggiornamento che non è finito (fallito,
    # interrotto, o ricordato da un backup non riuscito dopo).
    failed_with = status.get("backup") if status.get("status") in (
        db_startup.MIGRATION_FAILED, db_startup.IN_PROGRESS) or status.get("interrupted_update") else None
    if args.json:
        print(json.dumps({"folder": str(folder), "backups": [{
            "file": b.name, "path": str(b.path), "kind": b.kind, "size": b.size, "from_version": b.from_version,
            "to_version": b.to_version, "app_version": b.app_version, "created_at": b.created_at.isoformat(),
            "failed_update": str(b.path) == failed_with,
        } for b in backups]}, indent=2))
        return 0
    where = db_startup.status_path(settings.data_dir)
    if status.get("status") == db_startup.IN_PROGRESS:
        print(f"An update of the database did not finish (Nazgarr stopped while updating it): details in {where}.")
    elif status.get("status") == db_startup.BACKUP_FAILED:
        print(f"The last start did not update the database: the backup before it could not be made "
              f"({status.get('reason')}). Details in {where}.")
    elif status:
        step = (f"step {status['step']}, {status.get('step_name')}" if status.get("step") is not None
                else status.get("step_name"))
        print(f"The last start could not update the database ({step}): details in {where}.")
    if not backups:
        print(f"No backups taken before a database update in {folder} yet: Nazgarr takes one when an update "
              "is about to change the database.")
        return 0
    from nazgarr.cli_client.output import size

    # Righe semplici, non una tabella: il nome si copia per `db restore`, e
    # una tabella stretta lo andrebbe a capo.
    print(f"Backups taken before a database update, in {folder} (newest first):")
    width = max(len(b.name) for b in backups)
    for b in backups:
        note = "  <- before the update that did not finish" if str(b.path) == failed_with else ""
        print(f"  {b.name:<{width}}  {size(b.size):>9}  database v{b.from_version} -> v{b.to_version}  "
              f"{b.created_at:%Y-%m-%d %H:%M} UTC{note}")
    if any(b.kind == db_backup.PRE_RETRY for b in backups):
        print("pre-retry copies hold the database as a later start found it, after an update that did not finish: "
              "restore the pre-migration backup unless Nazgarr was used in between.")
    print("Restore one with `nazgarr db restore <file>`, with Nazgarr stopped (or while it shows the page of a "
          "failed update).")
    return 0


_RUNNING = (
    "Nazgarr is running on this database: stop it first. In Docker, stop the container and run the restore in a "
    "one-off one: docker run --rm -v <your config folder>:/app/config <the image> nazgarr db restore <file>. "
    "After a failed database update Nazgarr leaves the database free, so the restore works while it shows that "
    "page."
)


def cmd_db_restore(args) -> int:
    """Un backup al posto del database: solo con Nazgarr fermo (o in
    modalità di ripristino, che lascia il lucchetto, nazgarr/core/
    instance_lock.py), dopo aver controllato il backup e tenuto una copia
    del database di adesso (<nome>.before-restore). args.confirm(domanda)
    esce se l'utente dice di no."""
    settings = _local_settings(args.config)
    if settings is None:
        return 2
    from nazgarr.core import db_backup, db_startup, instance_lock

    folder = db_backup.backups_dir(settings.data_dir)
    wanted = Path(args.file).expanduser()
    backup = wanted if wanted.is_absolute() or len(wanted.parts) > 1 else folder / wanted
    if not backup.is_file():
        print(f"No backup at {backup}: `nazgarr db backups` lists them.", file=sys.stderr)
        return 2
    db_path = settings.db_path
    owned = next((p for p in (db_path, settings.data_dir) if Path(p).exists()), None)
    if owned:
        _as_db_owner(owned)
    lock = instance_lock.acquire(settings.data_dir)
    if lock is None:
        print(_RUNNING, file=sys.stderr)
        return 1
    try:
        try:
            version = db_backup.verify(backup)
        except db_backup.BackupError as exc:
            print(f"{backup.name} did not pass its check ({exc.detail}): not restored, nothing changed.",
                  file=sys.stderr)
            return 1
        parsed = db_backup.parse_name(backup)
        taken = (f", taken by Nazgarr {parsed.app_version} on {parsed.created_at:%Y-%m-%d %H:%M} UTC before updating "
                 f"to version {parsed.to_version}") if parsed else ""
        print(f"Backup: {backup} (database version {version}{taken}).")
        replaced = Path(db_path).exists()
        if replaced:
            print(f"It replaces {db_path}; the current database is kept next to it first.")
        args.confirm("Restore this backup?")
        try:
            if replaced:
                kept = db_backup.keep_current(db_path)
                print(f"Current database kept as {kept}")
            db_backup.restore(backup, db_path)
        except (OSError, sqlite3.Error) as exc:
            # restore() rinomina solo alla fine: fin lì il database resta quello di prima.
            print(f"Restore failed ({type(exc).__name__}: {exc}): the database was not replaced.", file=sys.stderr)
            return 1
        # Il database è un altro: il prossimo avvio è un aggiornamento nuovo,
        # con il suo backup, non il seguito di quello fallito
        # (nazgarr/core/db_startup.py).
        status_file = db_startup.status_path(settings.data_dir)
        if status_file.exists():
            try:
                status_file.unlink()
                print(f"Removed {status_file.name}: the next start backs the database up again before updating it.")
            except OSError as exc:
                print(f"{status_file} not removed ({exc}): delete it before starting Nazgarr again.", file=sys.stderr)
    finally:
        lock.release()
    newer = f" (starting {parsed.app_version} again would run the same update again)" if parsed else ""
    print(f"Restored: the database is back to version {version}. Start the Nazgarr version you were using before "
          f"the update{newer}, or report the issue with the log: https://github.com/lktorrentz/nazgarr/issues")
    return 0


def cmd_version(_args) -> int:
    from nazgarr.core.version import __commit__, __version__

    print(__version__ + (f" ({__commit__})" if __commit__ else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Tutti i comandi, del server e client (nazgarr/cli_client/app.py, docs/CLI.md)."""
    from nazgarr.cli_client.app import run

    return run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
