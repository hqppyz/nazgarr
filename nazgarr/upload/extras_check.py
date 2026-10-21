"""La tolleranza degli extra mancanti per i reseed del flusso degli upload
(2026-10-21, la stessa regola dei reseed della coda: docs/SPEC.md §5,
nazgarr/reseed/executor.py::_extras_gate).

Un reseed del flusso degli upload a cui il client, dopo il recheck, dice
di dover scaricare solo i byte degli extra che la sorgente non ha (nfo,
sample: allowed, expected_missing_bytes) partiva. Ma il client dice solo
quanti byte mancano, non quali piece: un piece diverso del video che stava
in quel margine passava per un extra, e il client lo riscriveva dentro gli
hardlink, cioè nel file della libreria. Ora parte solo se ogni piece che
non tocca un extra mancante l'ha verificato Nazgarr, sui file dove li
legge il client (anche col nome ".part" di Transmission).

Di solito senza leggere niente: un reseed del flusso degli upload ha già
un full hash check passato su proprio questi file (nazgarr/upload/verify.py,
che si segna l'identità di ogni file letto: dispositivo, inode, dimensione
e data di modifica). Se nessuno è cambiato da allora, ogni loro piece è già
verificato. Se no (un file sostituito o modificato sul posto dopo la
verifica, o una verifica di prima di questa regola, che non se li segnava)
la lettura gira in background nella coda dei controlli completi, uno alla
volta sul disco, e il reconcile dopo ne legge l'esito. In memoria, per
target, come le verifiche dei reseed della coda: dopo un riavvio, una
lettura non finita riparte al reconcile dopo.
"""

import logging
import os
from dataclasses import dataclass
from typing import NamedTuple

from nazgarr.core.file_types import is_video
from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped
from nazgarr.core.logs import safe_error
from nazgarr.reseed import full_check
from nazgarr.torrents.metainfo import TorrentInfo, compute_info_hash, parse_torrent_info

logger = logging.getLogger(__name__)

# Le letture per target, fra errori e file cambiati dopo una lettura
# passata: ognuna legge l'intero contenuto, come MAX_EXTRAS_CHECKS dei
# reseed della coda.
MAX_CHECKS = 3
CHECKING = "checking"


@dataclass
class _Check:
    status: str = "queued"  # queued | running | done | failed
    passed: bool = False
    reason: str | None = None
    error: str | None = None
    recorded: full_check.Record | None = None


@dataclass
class _Gate:
    check: _Check | None = None
    started: int = 0


_gates: dict[int, _Gate] = {}


class Outcome(NamedTuple):
    """"ok", "pending" o "failed" (reason: il perché, in inglese come i
    messaggi dei seed job); started: una lettura è appena partita."""
    outcome: str
    reason: str | None = None
    started: bool = False


def forget(target_id: int) -> None:
    """Un target rimesso in attesa (una nuova aggiunta, "Riprova il seed") o
    con un esito: la prossima volta si ricomincia."""
    _gates.pop(target_id, None)


def is_open(target_id: int) -> bool:
    """Una lettura per questo target è partita e non è (ancora) passata: un
    100% del client intanto non basta, come per i reseed della coda (un
    torrent che girava può aver scaricato proprio i byte diversi)."""
    gate = _gates.get(target_id)
    if gate is None:
        return False
    return gate.check is None or not (gate.check.status == "done" and gate.check.passed)


def verified_record(verification: dict | None, info_hash: str | None) -> full_check.Record | None:
    """Quel che il full hash check dell'upload ha letto (verify.run_check:
    "files"), se è passato e per questo stesso torrent."""
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        return None
    if not info_hash or str(verification.get("info_hash") or "").lower() != info_hash.lower():
        return None
    files = verification.get("files")
    if not isinstance(files, dict):
        return None
    record: full_check.Record = {}
    for path, identity in files.items():
        if not isinstance(path, str) or not isinstance(identity, list) or len(identity) != 4:
            return None
        if not all(isinstance(part, int) for part in identity):
            return None
        record[path] = (identity[0], identity[1], identity[2], identity[3])
    return record


def seed_locator(save_path: str, parsed: TorrentInfo, partial_suffix: str | None) -> full_check.Locator:
    """Dove il client legge ogni file del torrent: save_path più il nome del
    torrent (e il percorso del file, per un torrent a più file), come li ha
    messi run_reseed; anche col suffisso dei file incompleti. Il percorso
    viene dal .torrent del tracker: mai fuori da save_path."""

    def locate(entry):
        relative = os.path.join(parsed.name, *entry.path.split("/")) if parsed.is_multi_file else parsed.name
        try:
            path = resolve_scoped(save_path, relative)
        except ScopeViolation:
            return None, None
        path = full_check.existing_file(path, partial_suffix)
        return (path, "seed") if path else (None, None)

    return locate


def missing_now(parsed: TorrentInfo, locate: full_check.Locator) -> set[str]:
    """I file del torrent senza file dove li legge il client: gli extra
    mancanti di un'aggiunta di prima di questa regola, che non li segnava.
    Mai un video, come all'aggiunta (upload_reseed_missing_video): contato
    come extra, ogni suo piece sarebbe scusato e la lettura passerebbe.
    Resta fra i file da leggere, assente, e la lettura fallisce."""
    return {entry.path for entry in parsed.files
            if entry.length > 0 and not is_video(entry.path) and locate(entry)[0] is None}


def decide(target_id: int, content: bytes, info_hash: str, save_path: str, missing: set[str] | None,
           verified: full_check.Record | None, partial_suffix: str | None = None) -> Outcome:
    """"ok" se ogni piece fuori dagli extra mancanti è verificato: dal full
    hash check dell'upload (verified) o da una lettura di qui passata, sui
    file come sono adesso; "pending" mentre la lettura gira, o dopo un suo
    errore (si riprova al reconcile dopo); "failed" col perché se un piece
    non coincide, se content (i byte del .torrent aggiunto al client) non è
    il torrent nel client, o dopo MAX_CHECKS letture senza un esito che
    valga. Solleva TorrentMetainfoError per un .torrent illeggibile."""
    parsed = parse_torrent_info(content)
    if compute_info_hash(content) != (info_hash or "").lower():
        return Outcome("failed", "the saved .torrent is not the one in the client, so its pieces could not be checked")
    locate = seed_locator(save_path, parsed, partial_suffix)
    if missing is None:
        missing = missing_now(parsed, locate)
    now = {entry.path: full_check.identity_of(locate(entry)[0]) for entry in parsed.files
           if entry.path not in missing and entry.length > 0}
    if full_check.same_files(verified, now):
        return Outcome("ok")
    gate = _gates.setdefault(target_id, _Gate())
    check = gate.check
    if check is not None and check.status == "done" and check.passed:
        if full_check.same_files(check.recorded, now):
            return Outcome("ok")
        if gate.started >= MAX_CHECKS:
            return Outcome("failed", "the client only lacks the extras the source does not have, but the files "
                                     f"changed after Nazgarr checked their pieces, {gate.started} times")
        check = None  # cambiati dopo: una nuova lettura, sui file di adesso
    started = False
    if check is None:
        check = gate.check = _Check()
        gate.started += 1
        started = True
        logger.info("Target %s: recheck entro il margine degli extra, Nazgarr controlla gli altri piece (%d)",
                    target_id, gate.started)
        full_check.submit(_run, check, content, info_hash, save_path, frozenset(missing), partial_suffix)
    if check.status in ("queued", "running"):
        return Outcome("pending", CHECKING, started)
    if check.status == "done":
        if check.passed:
            return Outcome("ok", None, started)
        return Outcome("failed", check.reason, started)
    if gate.started >= MAX_CHECKS:
        return Outcome("failed", f"Nazgarr could not check the other pieces, {gate.started} times ({check.error})",
                       started)
    gate.check = None  # un errore, non un esito: una nuova al reconcile dopo, che fa anche da attesa
    logger.warning("Target %s: piece fuori dagli extra mancanti non controllati (%s), si riprova", target_id,
                   check.error)
    return Outcome("pending", None, started)


def _run(check: _Check, content: bytes, info_hash: str, save_path: str, missing: frozenset[str],
         partial_suffix: str | None) -> None:
    """Nel thread dei controlli completi: solo file e byte, nessuna sessione."""
    check.status = "running"
    try:
        parsed = parse_torrent_info(content)
        result = full_check.check_pieces_outside(content, info_hash, seed_locator(save_path, parsed, partial_suffix),
                                                 set(missing))
        check.passed, check.reason, check.recorded = result.passed, result.reason, result.recorded
        check.status = "done"
    except Exception as exc:
        logger.warning("Controllo dei piece fuori dagli extra di %s fallito", info_hash, exc_info=True)
        check.status, check.error = "failed", safe_error(exc)
