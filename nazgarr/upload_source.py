"""Cosa c'è dentro la sorgente di un upload (docs/SPEC.md §9 "Upload flow
v2"): i video, quale è il principale, e se si tratta di un film, di un
episodio, di un season pack o di un complete pack.

Solo lettura del filesystem e guessit: nessuna rete. Il risultato è una
proposta, che l'utente conferma (o corregge) al primo punto di approvazione.
"""

import os
from dataclasses import dataclass, field

import guessit

from nazgarr.file_types import is_video

# Sotto questa dimensione un video con "sample" nel nome è un campione, non
# un episodio: non conta per il tipo né per gli episodi trovati.
SAMPLE_MAX_BYTES = 300 * 1024 * 1024

# guessit a volte legge l'anno come stagione ("Show 2019" -> season 2019).
_MAX_PLAUSIBLE_SEASON = 100


@dataclass
class SourceVideo:
    relative_path: str  # relativo alla sorgente ("" per un file singolo scelto direttamente)
    size_bytes: int
    season: int | None = None
    episodes: list[int] = field(default_factory=list)


@dataclass
class SourceLayout:
    kind: str  # movie | episode | season_pack | complete_pack
    content_type: str  # movie | tv
    videos: list[SourceVideo]
    other_files: int  # file non video (nfo, sottotitoli, ...), solo il conteggio
    total_size_bytes: int
    main_video: str  # percorso assoluto del video principale (il più grande)
    title: str | None
    year: int | None
    seasons: list[int]
    # stagione -> episodi trovati, per il confronto con quelli attesi da TMDB
    episodes_by_season: dict[int, list[int]]
    release_group: str | None = None


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _seasons(guess: dict) -> list[int]:
    return [s for s in _as_list(guess.get("season")) if isinstance(s, int) and 0 <= s < _MAX_PLAUSIBLE_SEASON]


def _is_sample(name: str, size: int) -> bool:
    return "sample" in name.lower() and size < SAMPLE_MAX_BYTES


def _walk(source_path: str) -> tuple[list[tuple[str, int]], int]:
    videos, others = [], 0
    for dirpath, dirnames, filenames in os.walk(source_path):
        dirnames.sort()
        for name in sorted(filenames):
            absolute = os.path.join(dirpath, name)
            if not os.path.isfile(absolute):
                continue
            size = os.path.getsize(absolute)
            if is_video(name) and not _is_sample(name, size):
                videos.append((os.path.relpath(absolute, source_path), size))
            else:
                others += 1
    return videos, others


def scan_source(source_path: str) -> SourceLayout:
    is_dir = os.path.isdir(source_path)
    if is_dir:
        walked, other_files = _walk(source_path)
        if not walked:
            raise ValueError("no_video_files")
        name_guess = guessit.guessit(os.path.basename(source_path.rstrip(os.sep)))
    else:
        walked, other_files = [("", os.path.getsize(source_path))], 0
        name_guess = guessit.guessit(os.path.basename(source_path))

    videos: list[SourceVideo] = []
    any_episode = name_guess.get("type") == "episode"
    for relative, size in walked:
        guess = guessit.guessit(os.path.basename(relative)) if relative else name_guess
        seasons = _seasons(guess)
        episodes = [e for e in _as_list(guess.get("episode")) if isinstance(e, int)]
        if guess.get("type") == "episode":
            any_episode = True
        videos.append(SourceVideo(relative, size, seasons[0] if seasons else None, episodes))

    # Un episodio senza stagione nel nome del file la prende dalla cartella
    # (".../Season 2/03.mkv"), e in ultima istanza dal nome della sorgente.
    folder_seasons = _seasons(name_guess)
    for video in videos:
        if video.season is None and video.episodes:
            parent = os.path.basename(os.path.dirname(video.relative_path))
            parent_seasons = _seasons(guessit.guessit(parent)) if parent else []
            fallback = parent_seasons or (folder_seasons if len(folder_seasons) == 1 else [])
            video.season = fallback[0] if fallback else None

    episodes_by_season: dict[int, list[int]] = {}
    for video in videos:
        if video.season is not None:
            episodes_by_season.setdefault(video.season, [])
            episodes_by_season[video.season].extend(video.episodes)
    episodes_by_season = {s: sorted(set(eps)) for s, eps in sorted(episodes_by_season.items())}
    seasons = sorted(episodes_by_season) or folder_seasons

    content_type = "tv" if any_episode or seasons else "movie"
    if content_type == "movie":
        kind = "movie"
    elif len(videos) == 1:
        kind = "episode"
    else:
        kind = "complete_pack" if len(seasons) > 1 else "season_pack"

    main = max(videos, key=lambda v: v.size_bytes)
    main_path = os.path.join(source_path, main.relative_path) if main.relative_path else source_path
    # Una cartella con un solo contenuto (un film, un episodio): prima il nome
    # del file, che descrive proprio quel video, e la cartella solo per quello
    # che manca (decisione dell'utente, 2026-10-02). Per i pack resta la
    # cartella: il nome di un file dice solo il suo episodio.
    primary = name_guess
    if is_dir and kind in ("movie", "episode"):
        primary = guessit.guessit(os.path.basename(main.relative_path))

    def pick(key):
        value = primary.get(key)
        return value if value not in (None, "") else name_guess.get(key)

    year = pick("year")
    return SourceLayout(
        kind=kind,
        content_type=content_type,
        videos=videos,
        other_files=other_files,
        total_size_bytes=sum(v.size_bytes for v in videos),
        main_video=main_path,
        title=pick("title"),
        year=year if isinstance(year, int) else None,
        seasons=seasons,
        episodes_by_season=episodes_by_season,
        release_group=pick("release_group"),
    )
