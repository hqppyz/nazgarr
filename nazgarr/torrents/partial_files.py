"""I file che un client rinomina mentre sono incompleti (decisione
dell'utente, 2026-10-19).

Transmission con rename-partial-files (acceso di default) rinomina un file
incompleto in "<nome>.part" già durante il recheck, anche di un torrent
fermo (visto sull'istanza reale, audit 2026-10-18). Dopo il recheck fallito
di un reseed l'hardlink nella cartella dei torrent restava "<nome>.part"
(il file in libreria tiene il suo nome, è un altro link dello stesso
inode); per un torrent già su disco era il file dell'utente nella cartella
di seeding, magari usato da un altro torrent. Un torrent fermo il client
non lo rinomina più finché qualcuno non lo avvia o lo ricontrolla: il nome
si rimette qui, e un nuovo recheck (Retry) lo trova dove l'aveva lasciato.

Solo per i file che Nazgarr ha messo o che segue, e solo se tutto torna:
- il file rinominato ha il dispositivo e l'inode registrati (un hardlink
  creato da Nazgarr, un file della libreria o della cartella di seeding
  già indicizzato): mai un file qualunque con quel nome;
- è un file vero (lstat, mai un link simbolico seguito), dentro le
  cartelle date (quelle di seeding del disco), senza link simbolici nelle
  cartelle sopra fino lì;
- al nome originale non c'è niente: mai sopra un altro file.
"""

import logging
import os
import stat
from collections.abc import Iterable

logger = logging.getLogger(__name__)

Identity = tuple[int, int]  # (st_dev, st_ino)


def _inside(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def restore_names(paths: Iterable[str], identities: set[Identity], suffix: str, folders: list[str]) -> list[str]:
    """Rimette a "<percorso>" ogni "<percorso><suffix>" che rispetta le
    regole del modulo. paths: dove il torrent si aspetta i suoi file, come
    percorsi assoluti sotto la cartella reale (realpath) del disco. Ritorna
    i percorsi rimessi; quello che non si può (un errore del filesystem) si
    scrive nel log e si lascia com'è."""
    if not suffix or not identities:
        return []
    roots = [os.path.realpath(folder) for folder in folders if folder]
    restored = []
    for path in dict.fromkeys(os.path.normpath(p) for p in paths):
        parent = os.path.dirname(path)
        if not os.path.isabs(path) or not _inside(parent, roots):
            continue
        if os.path.realpath(parent) != parent:
            continue  # una cartella sopra è un link simbolico: mai seguito
        renamed = path + suffix
        try:
            st = os.lstat(renamed)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) not in identities:
            continue
        if os.path.lexists(path):
            continue
        try:
            os.rename(renamed, path)
        except OSError:
            logger.warning("%s non rinominato in %s", renamed, path, exc_info=True)
            continue
        logger.info("Rimesso il nome a %s: il client l'aveva rinominato %s mentre era incompleto", path,
                    os.path.basename(renamed))
        restored.append(path)
    return restored


def suffix_of(adapter) -> str | None:
    """partial_file_suffix() del client, None se non lo dice (un plugin
    senza la classe base) o se non risponde: allora non si rinomina niente."""
    ask = getattr(adapter, "partial_file_suffix", None)
    if not callable(ask):
        return None
    try:
        suffix = ask()
    except Exception:
        logger.warning("Il client non dice se rinomina i file incompleti", exc_info=True)
        return None
    return suffix if isinstance(suffix, str) and suffix and os.sep not in suffix else None
