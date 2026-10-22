"""Il lucchetto di chi usa il database: <data_dir>/nazgarr.lock, tenuto dal
server finché lavora sul database (nazgarr/main.py). `nazgarr db restore`
(nazgarr/cli.py) non sostituisce il database se qualcuno lo tiene: il
server lo riscriverebbe con le sue connessioni aperte.

Un lock del sistema operativo (flock, su Windows msvcrt.locking), non un
file con un pid: lo rilascia il kernel quando il processo finisce, anche
male, e non resta mai un lucchetto orfano dopo un crash o un kill. In
modalità di ripristino il server lo lascia (non tocca più il database), così
il ripristino si fa anche con il container acceso."""

import os
from pathlib import Path

LOCK_FILENAME = "nazgarr.lock"

if os.name == "nt":  # pragma: no cover - Windows non è nei test
    import msvcrt

    def _lock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class InstanceLock:
    def __init__(self, fd: int, path: Path):
        self._fd: int | None = fd
        self.path = path

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            _unlock(self._fd)
        except OSError:
            pass  # chiudere il file lo rilascia comunque
        os.close(self._fd)
        self._fd = None


def acquire(data_dir: str | os.PathLike) -> InstanceLock | None:
    """Il lucchetto, o None se un altro lo tiene già (anche lo stesso
    processo con un altro acquire: flock vale per file aperto)."""
    path = Path(data_dir) / LOCK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _lock(fd)
    except OSError:
        os.close(fd)
        return None
    return InstanceLock(fd, path)
