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

import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.core.file_types import is_video
from nazgarr.library.guess import as_list
from nazgarr.library.guess import guess as guess_name


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


_SOURCES = {
    "web": "web", "web-dl": "web", "webrip": "web",
    "blu-ray": "bluray", "ultra hd blu-ray": "bluray", "hd-dvd": "bluray",
    "hdtv": "hdtv", "ultra hdtv": "hdtv", "tv": "hdtv",
    "dvd": "dvd",
}


def traits_of(name: str) -> ReleaseTraits:
    # Lo stesso guessit del resto dell'app (nazgarr/library/guess.py), col nome ripulito.
    guess = guess_name(name)
    others = {str(o) for o in as_list(guess.get("other"))}
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
        seasons=frozenset(s for s in as_list(guess.get("season")) if isinstance(s, int)),
        episodes=frozenset(e for e in as_list(guess.get("episode")) if isinstance(e, int)),
        repack=bool(guess.get("proper_count")) or bool(others & {"Proper", "Repack"}),
        group=guess.get("release_group"),
    )


@dataclass(frozen=True)
class SourceSummary:
    """Quello che serve della sorgente locale per confrontarla."""

    name: str  # il nome da cui si leggono i tratti (name_source dell'analisi)
    total_size_bytes: int  # tutti i file, video e non (come la dimensione di un torrent)
    video_sizes: tuple[int, ...]
    kind: str  # movie | episode | season_pack | complete_pack
    seasons: frozenset[int]
    episode: int | None
    # La risoluzione letta da MediaInfo: vale più di quella del nome, che
    # spesso non c'è (un nome rinominato da Plex/Radarr).
    resolution: str | None = None


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


def source_traits(source: SourceSummary) -> ReleaseTraits:
    traits = traits_of(source.name)
    if source.resolution:
        traits = replace(traits, resolution=source.resolution)
    return traits


def classify(candidate: TorrentCandidate, source: SourceSummary, mine: ReleaseTraits | None = None) -> dict:
    """mine: i tratti della sorgente, se già calcolati (check() li calcola
    una volta per tutti i candidati)."""
    mine = mine or source_traits(source)
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
        "download_link": stored_link(candidate.download_link),
        "verification": None,
    }


# Il link di download di UNIT3D ha la chiave personale (rsskey) nel percorso:
# /torrent/download/<id>.<chiave>. Con quella si scaricano .torrent col
# passkey dell'utente: è un segreto (nel DB solo cifrato, sul tracker), e nel
# dupe check si salva senza (audit 2026-10-18). Al posto della chiave un
# segnaposto con la stessa forma, che rewrite_download_link sostituisce.
_KEYED_LINK = re.compile(r"(/torrent/download/\d+\.)([A-Za-z0-9]+)$")
KEY_PLACEHOLDER = "rsskey"


def stored_link(link: str | None) -> str | None:
    """Il link di un dupe come si salva: senza la chiave personale."""
    if not link:
        return link
    parts = urlsplit(link)
    if not _KEYED_LINK.search(parts.path):
        return link
    return parts._replace(path=_KEYED_LINK.sub(rf"\g<1>{KEY_PLACEHOLDER}", parts.path)).geturl()


def download_link(adapter, dupe: dict) -> str | None:
    """Il link per scaricare il .torrent di un dupe, con la chiave attuale
    del tracker (quella salvata, o imparata dalle sue risposte): per il full
    hash check e il reseed. Senza una chiave nota, quello del dettaglio del
    torrent sul tracker. Un link salvato prima, con la chiave dentro, o di
    un tracker che non la usa, resta com'è."""
    link = dupe.get("download_link")
    keyless = bool(link) and urlsplit(link).path.endswith(f".{KEY_PLACEHOLDER}") \
        and bool(_KEYED_LINK.search(urlsplit(link).path))
    if not keyless:
        return link
    rewrite = getattr(adapter, "rewrite_download_link", None)
    if getattr(adapter, "rss_key", None) and callable(rewrite):
        rebuilt = rewrite(link)
        if rebuilt != link:
            return rebuilt
    detail = getattr(adapter, "get_torrent_detail", None)
    if callable(detail) and dupe.get("torrent_id_remote"):
        return detail(dupe["torrent_id_remote"]).download_link
    return None


_VERDICT_ORDER = {"identical": 0, "same_slot": 1, "different": 2}


def check(candidates: list[TorrentCandidate], source: SourceSummary) -> tuple[list[dict], str]:
    """(risultati classificati, azione suggerita per questo tracker)."""
    mine = source_traits(source)
    results = sorted((classify(c, source, mine) for c in candidates), key=lambda r: _VERDICT_ORDER[r["verdict"]])
    verdicts = {r["verdict"] for r in results}
    if "identical" in verdicts:
        suggested = "reseed"
    elif "same_slot" in verdicts:
        suggested = "skip"
    else:
        suggested = "upload"
    return results, suggested
