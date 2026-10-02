"""Il comando `nazgarr`, per l'installazione senza Docker (pacchetto Python
con pipx, decisione dell'utente 2026-10-02). Fa quello che nel container
fanno entrypoint e supervisord:

    nazgarr init --scan-root /mnt     config.yaml, chiave segreta, controlli
    nazgarr serve                     il server (un solo processo, sempre)
    nazgarr install-service           il servizio systemd (Linux) o launchd (macOS)
    nazgarr version

Senza Docker non c'è nessuna mappatura dei volumi: Nazgarr vede il
filesystem vero, e disk_scan_root è la cartella sotto cui stanno i dischi
(il confine oltre il quale non registra e non sfoglia niente)."""

import argparse
import os
import platform
import shutil
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
        # Una chiave Fernet (32 byte in base64 url-safe): cifra le credenziali (nazgarr/crypto.py).
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


def cmd_version(_args) -> int:
    from nazgarr.version import __commit__, __version__

    print(__version__ + (f" ({__commit__})" if __commit__ else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nazgarr", description="Nazgarr without Docker.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write the configuration and the secret key, check the tools")
    init.add_argument("--scan-root", required=True, help="the folder your disks are under (e.g. /mnt)")
    init.add_argument("--data-dir", help="where to keep the database and caches")
    init.add_argument("--config", help="path of config.yaml")
    init.add_argument("--force", action="store_true", help="rewrite config.yaml if it exists")
    init.set_defaults(func=cmd_init)

    for name, func, help_text in (("serve", cmd_serve, "start the server"),
                                  ("install-service", cmd_install_service, "write the service file")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--config", help="path of config.yaml")
        command.add_argument("--host", default="0.0.0.0")
        command.add_argument("--port", type=int, default=8080)
        if name == "install-service":
            command.add_argument("--print", action="store_true", help="print the file instead of writing it")
        command.set_defaults(func=func)

    sub.add_parser("version", help="the installed version").set_defaults(func=cmd_version)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
