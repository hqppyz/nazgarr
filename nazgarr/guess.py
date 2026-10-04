"""guessit sui nomi dei file locali, dopo aver tolto quello che non è parte
del nome: il suffisso dei titoli di MakeMKV ("Movie_t00.mkv", "title_t01",
uno per titolo del disco), che guessit legge come parte del titolo ("Movie
t00") o come titolo dell'episodio, e che fa sbagliare il match su TMDB
(segnalato dall'utente, 2026-10-03).
"""

import os
import re

import guessit

# "_t00" … "_t99" (e "_t100"+, dischi con molti titoli) in fondo al nome, prima
# dell'estensione. Con "_" o uno spazio davanti, come li scrive MakeMKV.
_MAKEMKV_TITLE = re.compile(r"[_ ]t\d{2,3}$")


def clean_name(name: str) -> str:
    """Il nome (o percorso) senza il suffisso di MakeMKV, estensione e
    cartelle intatte."""
    folder, filename = os.path.split(name)
    stem, ext = os.path.splitext(filename)
    if ext and not re.fullmatch(r"\.[A-Za-z0-9]{2,4}", ext):
        stem, ext = filename, ""  # "Movie.2024_t00" senza estensione: il punto è parte del nome
    cleaned = _MAKEMKV_TITLE.sub("", stem)
    if not cleaned:
        return name
    return os.path.join(folder, cleaned + ext) if folder else cleaned + ext


def as_list(value) -> list:
    """guessit dà un valore o una lista (es. più episodi): sempre una lista."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def guess(name: str, options: dict | None = None) -> dict:
    return guessit.guessit(clean_name(name), options) if options else guessit.guessit(clean_name(name))
