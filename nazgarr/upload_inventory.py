"""I file di una sorgente di upload, con una sola regola per quello che
entra nel torrent: analisi (layout, dupe check), nomi dei file e hashing
devono vedere gli stessi file.

Restano fuori:
- la spazzatura: file e cartelle nascosti, file di sistema (Thumbs.db,
  desktop.ini), file incompleti dei client (.part, .!qB, .!ut);
- i sample: un file dentro una cartella "sample"/"samples", o sotto
  SAMPLE_MAX_BYTES con "sample" come prima o ultima parola del nome
  (movie-sample.mkv, sample-grp.mkv), come si chiamano i sample delle
  release. Con un glob "*sample*" sul percorso il torrent di un film che si
  chiama "Free Sample" usciva vuoto, e un episodio con la parola nel titolo
  ("S01E03.The.Sample") spariva dal torrent in silenzio.

I link simbolici non si seguono mai (nazgarr/upload_jobs.py rifiuta già una
sorgente che ne contiene).
"""

import os
import re
from dataclasses import dataclass

SAMPLE_MAX_BYTES = 300 * 1024 * 1024

_SYSTEM_FILES = {"thumbs.db", "desktop.ini"}
_INCOMPLETE_SUFFIXES = (".part", ".!qb", ".!ut")
_SAMPLE_DIRS = {"sample", "samples"}
_WORDS = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SourceFile:
    path: str  # assoluto
    relative: str  # relativo alla sorgente (o il nome nel pack), con "/"
    size: int


def _parts(relative: str) -> list[str]:
    return relative.replace("\\", "/").split("/")


def is_junk(relative: str) -> bool:
    parts = _parts(relative)
    name = parts[-1].lower()
    return (
        any(part.startswith(".") for part in parts)
        or name in _SYSTEM_FILES
        or name.endswith(_INCOMPLETE_SUFFIXES)
    )


def is_sample(relative: str, size: int) -> bool:
    parts = _parts(relative)
    if any(part.lower() in _SAMPLE_DIRS for part in parts[:-1]):
        return True
    words = _WORDS.findall(os.path.splitext(parts[-1])[0].lower())
    return bool(words) and "sample" in (words[0], words[-1]) and size < SAMPLE_MAX_BYTES


def in_torrent(relative: str, size: int) -> bool:
    return not is_junk(relative) and not is_sample(relative, size)


def walk(root: str) -> list[SourceFile]:
    """Ogni file regolare sotto root (o root stesso se è un file), in ordine,
    senza seguire link simbolici."""
    if not os.path.isdir(root):
        return [SourceFile(root, os.path.basename(root), os.path.getsize(root))] if os.path.isfile(root) else []
    out: list[SourceFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            out.append(SourceFile(path, relative, os.path.getsize(path)))
    return out


def torrent_files(root: str) -> list[SourceFile]:
    """I file sotto root che entrano in un torrent."""
    if not os.path.isdir(root):
        return walk(root)  # un file solo è il torrent
    return [f for f in walk(root) if in_torrent(f.relative, f.size)]


def job_files(job) -> list[SourceFile]:
    """I file della sorgente di un job che entrano nel torrent: un pack scelto
    a mano (i suoi file col nome nel pack), un file solo, o una cartella."""
    from nazgarr import upload_pack  # qui: le regole sopra restano senza dipendenze (upload_source)

    if upload_pack.is_pack(job):
        out = []
        for path, name in upload_pack.entries(job):
            size = os.path.getsize(path)
            if in_torrent(name, size):
                out.append(SourceFile(path, name, size))
        return out
    return torrent_files(job.source_path)
