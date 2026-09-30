"""Quali righe media_file/seed_file esistono ancora sul disco.

Lo scanner non cancella mai una riga (docs/SPEC.md §4, app/scanner.py): un
file spostato o cancellato resta con il last_scan_id dell'ultimo scan che
l'ha visto. È "attuale" solo se l'ha visto l'ultimo scan riuscito del SUO
disco — il last_scan_id più alto fra le righe di quel disco su quel lato.
Uno scan fallito non scrive righe, quindi non rende "vecchio" niente: nel
dubbio un file resta attuale, mai il contrario.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Disk, MediaFile, SeedFile


def latest_scan_by_disk(session: Session, model: type[MediaFile] | type[SeedFile]) -> dict[int, int]:
    """L'ultimo scan che ha letto quel lato del disco: quello registrato sul
    disco (media_scan_id / seed_scan_id, scritto anche se la cartella era
    vuota), altrimenti il più alto fra le righe (DB di prima della colonna)."""
    latest = dict(session.query(model.disk_id, func.max(model.last_scan_id)).group_by(model.disk_id).all())
    column = Disk.media_scan_id if model is MediaFile else Disk.seed_scan_id
    for disk_id, scan_id in session.query(Disk.id, column).filter(column.isnot(None)).all():
        if scan_id >= latest.get(disk_id, 0):
            latest[disk_id] = scan_id
    return latest


def is_current(row: MediaFile | SeedFile, latest: dict[int, int]) -> bool:
    return row.last_scan_id == latest.get(row.disk_id, row.last_scan_id)
