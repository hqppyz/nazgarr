"""Tipi di file: solo i video hanno un'identità (TMDB) e fanno partire il
matching. Gli altri file (nfo, sottotitoli, sample, immagini) vengono
comunque scansionati, perché fanno parte dei torrent da ricreare."""

from pathlib import PurePosixPath

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".wmv", ".mov"}


def is_video(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).suffix.lower() in VIDEO_EXTENSIONS
