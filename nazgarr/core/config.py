"""Caricamento della configurazione statica (config.yaml).

Vedi docs/SPEC.md sezione 4: config.yaml contiene SOLO il data_dir e,
facoltativo, disk_scan_root (la radice sotto cui stanno i dischi). Senza,
in un container il confine dei dischi sono le cartelle di dati montate
(nazgarr/core/mounts.py, decisione dell'utente 2026-10-05). I singoli
dischi non sono elencati qui: si aggiungono dalla Web UI. Tutto il resto vive nel DB (tabella
app_settings e le altre tabelle di configurazione) ed è editabile da UI
senza restart.
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

DB_FILENAME = "nazgarr.db"
# Nome del file prima del rename del progetto (Gauntletarr -> Nazgarr):
# rinominato all'avvio da nazgarr/core/db.py::migrate_legacy_db_filename.
LEGACY_DB_FILENAME = "gauntletarr.db"


class Settings(BaseModel):
    disk_scan_root: str | None = None
    data_dir: str

    @field_validator("disk_scan_root")
    @classmethod
    def _disk_scan_root_must_be_absolute(cls, value: str | None) -> str | None:
        if value is not None and not os.path.isabs(value):
            raise ValueError(f"disk_scan_root: il path '{value}' deve essere assoluto")
        return value

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, DB_FILENAME)


def load_settings(config_path: str | None = None) -> Settings:
    path = config_path or os.environ.get("CONFIG_PATH", "config.yaml")
    resolved = Path(path)

    if resolved.is_dir():
        # Bind mount di un file su un host dove quel file non esiste ancora:
        # Docker crea silenziosamente una directory vuota al suo posto
        # invece di dare errore. Capita spesso al primo avvio se
        # config.yaml non è stato creato prima sull'host.
        raise NotADirectoryError(
            f"{path} è una directory, non un file: probabile bind mount di un "
            "config.yaml che non esisteva ancora sull'host. Crea il file "
            "config.yaml (copiando config.example.yaml) sull'host PRIMA di "
            "avviare il container, poi ricrea il container."
        )
    if not resolved.exists():
        raise FileNotFoundError(
            f"File di configurazione non trovato: {path}. "
            "Copia config.example.yaml in config.yaml e adattalo ai mount reali."
        )
    with open(path) as f:
        raw = yaml.safe_load(f)
    return Settings(**raw)
