import os
import stat
import tomllib
from pathlib import Path

import yaml
from cryptography.fernet import Fernet

from nazgarr import cli

ROOT = Path(__file__).resolve().parent.parent


def test_init_writes_the_config_and_a_private_valid_secret_key(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    (tmp_path / "disks").mkdir()
    config = tmp_path / "cfg" / "config.yaml"

    assert cli.main(["init", "--scan-root", str(tmp_path / "disks"), "--config", str(config),
                     "--data-dir", str(tmp_path / "data")]) == 0

    assert yaml.safe_load(config.read_text()) == {
        "disk_scan_root": str((tmp_path / "disks").resolve()), "data_dir": str(tmp_path / "data"),
    }
    key_file = config.parent / cli.SECRET_FILE
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    Fernet(key_file.read_text().strip().encode())  # una chiave che nazgarr/core/crypto.py accetta
    first_key = key_file.read_text()

    # Rilanciato: la chiave non cambia mai (le credenziali nel DB dipendono da lei).
    cli.main(["init", "--scan-root", str(tmp_path / "disks"), "--config", str(config), "--force"])
    assert key_file.read_text() == first_key


def test_init_wants_an_existing_scan_root(tmp_path):
    assert cli.main(["init", "--scan-root", str(tmp_path / "missing"), "--config", str(tmp_path / "c.yaml")]) == 2


def test_serve_needs_a_config_and_a_key_and_runs_one_process(tmp_path, monkeypatch):
    # serve scrive CONFIG_PATH e APP_SECRET_KEY nell'ambiente del processo:
    # una copia, se no la chiave finta arriverebbe ai test dopo questo.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    config = tmp_path / "config.yaml"
    assert cli.main(["serve", "--config", str(config)]) == 2
    config.write_text("disk_scan_root: /mnt\ndata_dir: /tmp/x\n")
    assert cli.main(["serve", "--config", str(config)]) == 2  # nessuna chiave

    (tmp_path / cli.SECRET_FILE).write_text("k\n")
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert cli.main(["serve", "--config", str(config), "--port", "9000"]) == 0
    assert calls == [(("nazgarr.main:app",), {"host": "0.0.0.0", "port": 9000, "workers": 1})]


def test_the_service_files_start_the_installed_command():
    unit = cli.systemd_unit(Path("/home/u/.config/nazgarr/config.yaml"), "0.0.0.0", 8080)
    assert '-m nazgarr.cli serve --config "/home/u/.config/nazgarr/config.yaml" --host 0.0.0.0 --port 8080' in unit
    assert "Restart=on-failure" in unit and "UMask=0077" in unit
    plist = cli.launchd_plist(Path("/Users/u/c.yaml"), "127.0.0.1", 8080, Path("/Users/u/Logs"))
    assert "<string>serve</string>" in plist and "<key>KeepAlive</key>" in plist


def test_the_package_needs_the_same_libraries_as_the_lock():
    # Il pacchetto pipx e il container non devono divergere: stesse
    # dipendenze dirette di requirements.in (supervisor serve solo nel container).
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    wanted = [
        line.strip() for line in (ROOT / "requirements.in").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert project["dependencies"] == [dep for dep in wanted if dep != "supervisor"]


def _account_db(tmp_path):
    """Un config.yaml e un DB con l'account admin, come dopo il setup."""
    from nazgarr.core import db, migrations, settings_repo
    from nazgarr.web import auth

    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {tmp_path / 'data'}\n")
    engine = db.make_engine(str(tmp_path / "data" / "nazgarr.db"))
    migrations.upgrade(engine)
    session = db.make_session_factory(engine)()
    return config, session, settings_repo, auth


def test_reset_password_sets_a_new_one_and_logs_every_session_out(tmp_path, monkeypatch):
    import io

    config, session, settings_repo, auth = _account_db(tmp_path)
    settings_repo.set_setting(session, "auth_username", "admin")
    settings_repo.set_setting(session, "auth_password_hash", auth.hash_password("forgotten-one"))
    version_before = auth.token_version(session)

    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["reset-password", "--config", str(config), "--password-stdin"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO("a-new-password\n"))
    assert cli.main(["reset-password", "--config", str(config), "--password-stdin"]) == 0

    session.expire_all()
    assert settings_repo.get_setting(session, "auth_username") == "admin"
    assert auth.verify_password("a-new-password", settings_repo.get_setting(session, "auth_password_hash"))
    assert auth.token_version(session) != version_before  # i browser già entrati devono rifare il login

    monkeypatch.setattr("sys.stdin", io.StringIO("another-password\n"))
    assert cli.main(["reset-password", "--config", str(config), "--password-stdin", "--username", "luca"]) == 0
    session.expire_all()
    assert settings_repo.get_setting(session, "auth_username") == "luca"


def test_reset_password_without_an_account_points_to_the_setup_code(tmp_path, monkeypatch, capsys):
    config, _session, _repo, _auth = _account_db(tmp_path)
    asked = []
    monkeypatch.setattr("typer.prompt", lambda *a, **k: asked.append(a) or "never-used")

    assert cli.main(["reset-password", "--config", str(config)]) == 2

    assert asked == []  # niente password chiesta per niente
    assert "setup code" in capsys.readouterr().err


# --- nazgarr db backups / restore (richiesta dell'utente, 2026-10-22) ------------


def _db_with_disk(path: Path, label: str):
    """Un DB vero all'ultima versione, con un disco: per riconoscerlo dopo."""
    from nazgarr.core import db, migrations

    engine = db.make_engine(str(path))
    migrations.upgrade(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO disk (label, root_path) VALUES (?, '/data/x')", (label,))
    engine.dispose()


def _labels(path: Path) -> list[str]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT label FROM disk ORDER BY id")]
    finally:
        conn.close()


def _backed_up(tmp_path):
    """config.yaml, un DB con il disco "after" e il backup di quando aveva "before"."""
    from nazgarr.core import db_backup, migrations

    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {data}\n")
    db_path = data / "nazgarr.db"
    _db_with_disk(db_path, "before")
    backup = db_backup.take_backup(str(db_path), data / "backups", migrations.LATEST, migrations.LATEST, "1.2.3")
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE disk SET label = 'after'")
    return config, data, db_path, backup


def test_db_backups_lists_them_and_marks_the_one_before_a_failed_update(tmp_path, capsys):
    import json

    config, data, _db_path, backup = _backed_up(tmp_path)
    (data / "backups" / "notes.txt").write_text("not a backup")
    (data / "migration-status.json").write_text(json.dumps({
        "status": "migration_failed", "step": 13, "step_name": "x", "backup": str(backup)}))

    assert cli.main(["db", "backups", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert backup.name in out and "before the update that did not finish" in out and "notes.txt" not in out
    assert "could not update the database" in out

    assert cli.main(["--json", "db", "backups", "--config", str(config)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["folder"] == str(data / "backups")
    assert [(b["file"], b["failed_update"], b["app_version"], b["kind"]) for b in listed["backups"]] == [
        (backup.name, True, "1.2.3", "pre-migration")]


def test_db_backups_after_an_interrupted_update_with_a_retry_copy(tmp_path, capsys):
    """Il processo morto a metà (migration-status.json in_progress) e la
    copia pre-retry di un avvio dopo: il backup da ripristinare resta il
    pre-migration, e la lista lo dice."""
    import json

    from nazgarr.core import db_backup, migrations

    config, data, db_path, backup = _backed_up(tmp_path)
    retry = db_backup.take_backup(str(db_path), data / "backups", migrations.LATEST, migrations.LATEST, "1.2.3",
                                  kind=db_backup.PRE_RETRY)
    (data / "migration-status.json").write_text(json.dumps({
        "status": "in_progress", "from_version": migrations.LATEST, "backup": str(backup),
        "retry_backup": str(retry)}))

    assert cli.main(["db", "backups", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "did not finish (Nazgarr stopped while updating it)" in out
    marked = [line for line in out.splitlines() if "<- before the update that did not finish" in line]
    assert len(marked) == 1 and backup.name in marked[0]
    assert retry.name in out and "pre-retry copies" in out


def test_db_backups_without_any(tmp_path, capsys):
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {tmp_path / 'data'}\n")
    assert cli.main(["db", "backups", "--config", str(config)]) == 0
    assert "No backups" in capsys.readouterr().out


def test_db_restore_refuses_while_nazgarr_runs(tmp_path, capsys):
    from nazgarr.core import instance_lock

    config, data, db_path, backup = _backed_up(tmp_path)
    lock = instance_lock.acquire(data)  # come il server acceso
    try:
        assert cli.main(["db", "restore", backup.name, "--config", str(config), "--yes"]) == 1
    finally:
        lock.release()
    assert "running" in capsys.readouterr().err
    assert _labels(db_path) == ["after"]
    assert not list(data.glob("nazgarr.db.before-restore*"))


def test_db_restore_puts_the_backup_back_and_keeps_the_current_database(tmp_path, capsys):
    import sqlite3

    config, data, db_path, backup = _backed_up(tmp_path)
    # Un -wal con dentro l'ultima modifica, non ancora nel file .db.
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE disk SET label = 'only-in-the-wal'")
    writer.commit()
    holder = sqlite3.connect(db_path)
    holder.execute("SELECT 1").fetchall()
    try:
        assert Path(f"{db_path}-wal").stat().st_size > 0
        assert cli.main(["db", "restore", backup.name, "--config", str(config), "--yes"]) == 0
    finally:
        writer.close()
        holder.close()

    out = capsys.readouterr().out
    assert "back to version" in out and "starting 1.2.3 again would run the same update again" in out
    assert "migration-status.json" not in out  # non c'era
    assert _labels(db_path) == ["before"]
    assert not Path(f"{db_path}-wal").exists() and not Path(f"{db_path}-shm").exists()
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    kept = data / "nazgarr.db.before-restore"
    assert _labels(kept) == ["only-in-the-wal"]  # anche quello che era solo nel -wal
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert backup.exists()  # il backup resta dov'è

    # Un secondo ripristino non sovrascrive la copia del primo.
    assert cli.main(["db", "restore", str(backup), "--config", str(config), "--yes"]) == 0
    assert kept.exists() and len(list(data.glob("nazgarr.db.before-restore*"))) == 2


def test_db_restore_forgets_the_failed_update(tmp_path, capsys):
    """Dopo un ripristino il database è un altro: il prossimo avvio è un
    aggiornamento nuovo, con il suo backup, non il seguito di quello fallito
    (nazgarr/core/db_startup.py)."""
    import json

    config, data, db_path, backup = _backed_up(tmp_path)
    status = data / "migration-status.json"
    status.write_text(json.dumps({"status": "migration_failed", "from_version": 1, "backup": str(backup)}))

    assert cli.main(["db", "restore", backup.name, "--config", str(config), "--yes"]) == 0

    assert "Removed migration-status.json" in capsys.readouterr().out
    assert not status.exists() and _labels(db_path) == ["before"]


def test_db_restore_checks_the_backup_and_asks_first(tmp_path, capsys):
    config, data, db_path, backup = _backed_up(tmp_path)
    broken = data / "backups" / "broken.db"
    broken.write_bytes(b"this is not a database" * 50)

    assert cli.main(["db", "restore", "broken.db", "--config", str(config), "--yes"]) == 1
    assert "did not pass its check" in capsys.readouterr().err
    assert cli.main(["db", "restore", "missing.db", "--config", str(config), "--yes"]) == 2
    # Senza --yes e senza un terminale: niente conferma, niente ripristino.
    assert cli.main(["db", "restore", backup.name, "--config", str(config)]) == 3

    assert _labels(db_path) == ["after"]
    assert not list(data.glob("nazgarr.db.before-restore*"))


def test_db_restore_keeps_a_damaged_current_database_as_it_is(tmp_path):
    """Un aggiornamento finito male può lasciare un file che SQLite non
    legge: la copia si fa lo stesso, byte per byte, -wal compreso."""
    config, data, db_path, backup = _backed_up(tmp_path)
    damaged = os.urandom(8192)
    db_path.write_bytes(damaged)
    Path(f"{db_path}-wal").write_bytes(b"wal bytes")

    assert cli.main(["db", "restore", backup.name, "--config", str(config), "--yes"]) == 0

    assert (data / "nazgarr.db.before-restore").read_bytes() == damaged
    assert (data / "nazgarr.db.before-restore-wal").read_bytes() == b"wal bytes"
    assert _labels(db_path) == ["before"] and not Path(f"{db_path}-wal").exists()


def test_db_restore_that_fails_midway_leaves_the_database_as_it_was(tmp_path, monkeypatch, capsys):
    import errno

    from nazgarr.core import db_backup

    config, data, db_path, backup = _backed_up(tmp_path)

    def full_disk(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(db_backup.shutil, "copyfile", full_disk)
    (data / "migration-status.json").write_text("{}")
    assert cli.main(["db", "restore", backup.name, "--config", str(config), "--yes"]) == 1

    assert "was not replaced" in capsys.readouterr().err
    assert (data / "migration-status.json").exists()  # il database è ancora quello: lo stato resta
    assert _labels(db_path) == ["after"]
    assert not (data / "nazgarr.db.restoring").exists()
