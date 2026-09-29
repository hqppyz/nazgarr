"""Dupe check di un upload contro i risultati di un tracker (docs/SPEC.md §9
"Upload flow v2"). Funzioni pure: nessuna rete, nessun DB.

Per ogni torrent già presente sul tracker, uno di tre verdetti:
- "identical": stessi byte (dimensione totale o dimensioni dei video
  identiche). Probabilmente la stessa release: invece di un upload conviene
  un reseed, da confermare con un full hash check.
- "same_slot": una release diversa ma nello stesso "posto" (stessa
  risoluzione, sorgente, remux o no, HDR/DV, stessa stagione/episodio): il
  tracker la tratterebbe quasi sicuramente come un dupe.
- "different": un'altra versione (es. 1080p contro 2160p), non un dupe.

Le dimensioni confrontate sono le stesse del dupe check di Upload-Assistant
(src/dupe_checking.py, riferimento di dominio): risoluzione, HDR/DV,
sorgente, remux, stagione/episodio, dimensione identica al byte. Qui però
nessun risultato viene scartato in silenzio: si mostra tutto con il suo
verdetto e l'utente decide.
"""

from dataclasses import dataclass

import guessit

from app.adapters.tracker.base import TorrentCandidate
from app.file_types import is_video


@dataclass(frozen=True)
class ReleaseTraits:
    resolution: str | None
    source: str | None  # web | bluray | hdtv | dvd | None
    remux: bool
    hdr: frozenset[str]  # sottoinsieme di {"HDR", "DV"}
    seasons: frozenset[int]
    episodes: frozenset[int]
    repack: bool
    group: str | None


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


_SOURCES = {
    "web": "web", "web-dl": "web", "webrip": "web",
    "blu-ray": "bluray", "ultra hd blu-ray": "bluray", "hd-dvd": "bluray",
    "hdtv": "hdtv", "ultra hdtv": "hdtv", "tv": "hdtv",
    "dvd": "dvd",
}


def traits_of(name: str) -> ReleaseTraits:
    guess = guessit.guessit(name)
    others = {str(o) for o in _as_list(guess.get("other"))}
    hdr = set()
    if others & {"HDR10", "HDR10+", "HDR"}:
        hdr.add("HDR")
    if "Dolby Vision" in others or " dv " in f" {name.lower().replace('.', ' ')} ":
        hdr.add("DV")
    source = _SOURCES.get(str(guess.get("source") or "").lower())
    return ReleaseTraits(
        resolution=guess.get("screen_size"),
        source=source,
        remux="Remux" in others,
        hdr=frozenset(hdr),
        seasons=frozenset(s for s in _as_list(guess.get("season")) if isinstance(s, int)),
        episodes=frozenset(e for e in _as_list(guess.get("episode")) if isinstance(e, int)),
        repack=bool(guess.get("proper_count")) or bool(others & {"Proper", "Repack"}),
        group=guess.get("release_group"),
    )


@dataclass(frozen=True)
class SourceSummary:
    """Quello che serve della sorgente locale per confrontarla."""

    name: str  # nome della cartella o del file, da cui si leggono i tratti
    total_size_bytes: int  # tutti i file, video e non (come la dimensione di un torrent)
    video_sizes: tuple[int, ...]
    kind: str  # movie | episode | season_pack | complete_pack
    seasons: frozenset[int]
    episode: int | None


def _covers(source: SourceSummary, other: ReleaseTraits) -> tuple[bool, str | None]:
    """La release sul tracker copre lo stesso contenuto (stagione/episodio)?"""
    if source.kind == "movie":
        return True, None
    if other.seasons and not (other.seasons & source.seasons):
        return False, "season"
    if source.kind == "episode":
        if other.episodes:
            return (source.episode in other.episodes), (None if source.episode in other.episodes else "episode")
        return True, "covered_by_pack"  # un season pack della stessa stagione contiene l'episodio
    # Un pack contro un singolo episodio: non sono lo stesso posto.
    if other.episodes:
        return False, "single_episode"
    if source.kind == "complete_pack" and other.seasons and other.seasons != source.seasons:
        return False, "season"
    return True, None


def classify(candidate: TorrentCandidate, source: SourceSummary) -> dict:
    mine = traits_of(source.name)
    theirs = traits_of(candidate.name)
    reasons: list[str] = []

    same_bytes = candidate.size_bytes == source.total_size_bytes
    if not same_bytes and candidate.file_sizes:
        their_videos = sorted(size for name, size in candidate.file_sizes.items() if is_video(name))
        same_bytes = bool(their_videos) and their_videos == sorted(source.video_sizes)

    covers, cover_reason = _covers(source, theirs)
    if cover_reason and not covers:
        reasons.append(cover_reason)
    if mine.resolution and theirs.resolution and mine.resolution != theirs.resolution:
        reasons.append("resolution")
    if mine.source and theirs.source and mine.source != theirs.source:
        reasons.append("source")
    if mine.remux != theirs.remux:
        reasons.append("remux")
    if mine.hdr != theirs.hdr:
        reasons.append("hdr")

    if same_bytes:
        verdict = "identical"
    elif not reasons:
        verdict = "same_slot"
        if cover_reason == "covered_by_pack":
            reasons.append("covered_by_pack")
        # Un repack dello stesso gruppo sostituisce la release, non la duplica.
        if mine.repack and not theirs.repack and mine.group and mine.group == theirs.group:
            verdict = "different"
            reasons.append("repack_of_same_group")
    else:
        verdict = "different"

    return {
        "torrent_id_remote": candidate.torrent_id_remote,
        "name": candidate.name,
        "size_bytes": candidate.size_bytes,
        "verdict": verdict,
        "reasons": reasons,
        "download_link": candidate.download_link,
        "verification": None,
    }


_VERDICT_ORDER = {"identical": 0, "same_slot": 1, "different": 2}


def check(candidates: list[TorrentCandidate], source: SourceSummary) -> tuple[list[dict], str]:
    """(risultati classificati, azione suggerita per questo tracker)."""
    results = sorted((classify(c, source) for c in candidates), key=lambda r: _VERDICT_ORDER[r["verdict"]])
    verdicts = {r["verdict"] for r in results}
    if "identical" in verdicts:
        suggested = "reseed"
    elif "same_slot" in verdicts:
        suggested = "skip"
    else:
        suggested = "upload"
    return results, suggested
