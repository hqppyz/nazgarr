"""Helper SQL condivisi. Vedi docs/SPEC.md sezione 4: ogni scrittura di
massa (scan filesystem, indicizzazione client torrent, e le fasi
successive che ne avranno bisogno) usa un bulk upsert, mai una query per
riga — qui per evitare di duplicare la stessa costruzione dello statement
in ogni modulo che scrive."""

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

# Righe per istruzione: SQLite limita i parametri di una singola istruzione
# (SQLITE_MAX_VARIABLE_NUMBER: 250000 nel Python dell'immagine, 32766 in
# altre build), e un disco scansionato per intero (anche nfo, immagini,
# sottotitoli) supera facilmente le ~28000 righe da 9 colonne che bastano a
# sforarlo in un'unica istruzione. 500 righe restano sotto il limite ovunque.
UPSERT_CHUNK_ROWS = 500


def bulk_upsert(session: Session, table, rows: list[dict], conflict_cols: list[str], update_cols: list[str]) -> None:
    for start in range(0, len(rows), UPSERT_CHUNK_ROWS):
        stmt = sqlite_insert(table).values(rows[start : start + UPSERT_CHUNK_ROWS])
        update_dict = {col: getattr(stmt.excluded, col) for col in update_cols}
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_dict)
        session.execute(stmt)


def bulk_insert(session: Session, table, rows: list[dict]) -> None:
    for start in range(0, len(rows), UPSERT_CHUNK_ROWS):
        session.execute(sqlite_insert(table).values(rows[start : start + UPSERT_CHUNK_ROWS]))
