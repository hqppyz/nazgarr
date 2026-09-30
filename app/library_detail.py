"""Scheda di dettaglio di un contenuto della libreria (vista poster, pannello
laterale): un film o un'intera serie, identificati da (content_type,
tmdb_id). Tutto in sola lettura, calcolato su richiesta — mai nel payload
della griglia, che deve restare leggero.

Per ogni file in libreria: stato, hardlink lato torrent e in quale torrent
di quale client/tracker è in seed, copie duplicate. Per il contenuto: link
esterni (TMDB, IMDb, Radarr/Sonarr), qualità dal nome del file, ricerche
sul tracker (ultima e prossima), candidati valutati e perché, review in
attesa ed esecuzioni già fatte.
"""

from collections import defaultdict
from datetime import UTC
from urllib.parse import urlsplit

import guessit
from sqlalchemy.orm import Session

from app.adapters.torrent_client.base import is_stopped_state
from app.duplicates import find_duplicate_media_files
from app.exclusions import load_exclusions
from app.file_types import is_video
from app.hardlinks import media_links
from app.matching import _as_utc, get_rematch_interval
from app.models import (
    Candidate,
    ClientTorrent,
    ClientTorrentFile,
    MatchAttempt,
    MatchReview,
    MediaFile,
    MediaItem,
    RadarrInstance,
    SeedFile,
    SeedJob,
    SonarrInstance,
    TorrentClient,
    Tracker,
    TrackerUploadProfile,
)
from app.review import READY_FOR_DECISION_STATUSES, hashes_in_clients, seed_job_display_status
from app.scan_state import is_current, latest_scan_by_disk

MAX_CANDIDATES = 30


def _host(url: str | None) -> str | None:
    host = urlsplit(url).hostname if url else None
    return host.removeprefix("www.") if host else None


def _quality(filename: str) -> str | None:
    """"1080p · BluRay · H.265" dal nome del file (guessit), nessuna lettura
    del file e nessuna chiamata esterna."""
    guess = guessit.guessit(filename)
    parts = [guess.get("screen_size"), guess.get("source"), guess.get("video_codec")]
    other = guess.get("other")
    if isinstance(other, list):
        other = next((o for o in other if o in ("Remux", "HDR10", "Dolby Vision")), None)
    if other in ("Remux", "HDR10", "Dolby Vision"):
        parts.append(other)
    text = " · ".join(str(p) for p in parts if p)
    return text or None


def _arr_url(session: Session, item: MediaItem) -> str | None:
    if not (item.arr_kind and item.arr_instance_id and item.arr_slug):
        return None
    model = RadarrInstance if item.arr_kind == "radarr" else SonarrInstance
    instance = session.get(model, item.arr_instance_id)
    if instance is None:
        return None
    return f"{instance.base_url.rstrip('/')}/{'movie' if item.arr_kind == 'radarr' else 'series'}/{item.arr_slug}"


def tracker_overview(session: Session, files: list[dict]) -> list[dict]:
    """Per ogni tracker configurato e abilitato (anche a zero) e per ogni
    altro tracker trovato nei torrent (es. uno pubblico): quanti video del
    contenuto sono in seed lì, e dove. Il tracker di un torrent si riconosce
    dall'host del suo announce, confrontato con announce e base_url dei
    tracker configurati."""
    configured = session.query(Tracker).filter(Tracker.enabled.is_(True)).order_by(Tracker.label).all()
    profiled = {tid for (tid,) in session.query(TrackerUploadProfile.tracker_id)}
    by_host: dict[str, Tracker] = {}
    for tracker in configured:
        for url in (tracker.announce_url, tracker.base_url):
            host = _host(url)
            if host:
                by_host.setdefault(host, tracker)

    videos = [f for f in files if f["is_video"] and not f["excluded"]]
    groups: dict[str, dict] = {}
    for tracker in configured:
        groups[f"t{tracker.id}"] = {
            "tracker_id": tracker.id, "label": tracker.label, "configured": True,
            "has_upload_profile": tracker.id in profiled, "seeding": set(), "entries": [],
        }
    for f in videos:
        for link in f["hardlinks"]:
            for torrent in link["torrents"]:
                host = torrent["tracker"]
                tracker = by_host.get(host) if host else None
                key = f"t{tracker.id}" if tracker else f"h{host or ''}"
                group = groups.setdefault(key, {
                    "tracker_id": None, "label": host or "?", "configured": False,
                    "has_upload_profile": False, "seeding": set(), "entries": [],
                })
                group["seeding"].add(f["media_file_id"])
                group["entries"].append({
                    "media_file_id": f["media_file_id"], "season_number": f["season_number"],
                    "episode_number": f["episode_number"], "seed_path": link["relative_path"],
                    "client": torrent["client"], "client_enabled": torrent["client_enabled"],
                    "state": torrent["state"], "torrent": torrent["name"],
                })
    out = []
    for group in groups.values():
        out.append({**group, "seeding": len(group["seeding"]), "total": len(videos)})
    # Prima i tracker configurati, poi gli altri; dentro, chi ne ha di più.
    out.sort(key=lambda g: (not g["configured"], -g["seeding"], g["label"].lower()))
    return out


def item_detail(session: Session, content_type: str, tmdb_id: int) -> dict | None:
    items = session.query(MediaItem).filter_by(content_type=content_type, tmdb_id=tmdb_id).all()
    if not items:
        return None
    item_ids = [i.id for i in items]
    exclusions = load_exclusions(session)

    latest_media = latest_scan_by_disk(session, MediaFile)
    media_files = [
        mf for mf in session.query(MediaFile).filter(MediaFile.media_item_id.in_(item_ids)).all()
        if is_current(mf, latest_media)
    ]
    mf_ids = [mf.id for mf in media_files]

    latest_seed = latest_scan_by_disk(session, SeedFile)
    seeds_by_media: dict[int, list[SeedFile]] = defaultdict(list)
    links = media_links(session, mf_ids) if mf_ids else {}
    linked_ids = {sf_id for sfs in links.values() for sf_id, _ in sfs}
    seed_rows = (
        {sf.id: sf for sf in session.query(SeedFile).filter(SeedFile.id.in_(linked_ids)).all()} if linked_ids else {}
    )
    for mf_id, sfs in links.items():
        for sf_id, _path in sfs:
            sf = seed_rows.get(sf_id)
            if sf is not None and is_current(sf, latest_seed):
                seeds_by_media[mf_id].append(sf)
    seed_ids = [sf.id for seeds in seeds_by_media.values() for sf in seeds]

    torrents_by_seed: dict[int, list[dict]] = defaultdict(list)
    if seed_ids:
        rows = (
            session.query(ClientTorrentFile.seed_file_id, ClientTorrent, TorrentClient.label, TorrentClient.enabled)
            .join(ClientTorrent, ClientTorrent.id == ClientTorrentFile.client_torrent_id)
            .join(TorrentClient, TorrentClient.id == ClientTorrent.torrent_client_id)
            .filter(ClientTorrentFile.seed_file_id.in_(seed_ids))
            .all()
        )
        for seed_file_id, torrent, client_label, client_enabled in rows:
            torrents_by_seed[seed_file_id].append({
                "name": torrent.name, "client": client_label, "tracker": _host(torrent.tracker_url),
                "state": torrent.state, "client_enabled": bool(client_enabled),
            })

    duplicate_peers: dict[int, list[dict]] = {}
    wanted = set(mf_ids)
    for group in find_duplicate_media_files(session):
        for f in group["files"]:
            if f["media_file_id"] in wanted:
                duplicate_peers.setdefault(f["media_file_id"], []).extend(
                    {"relative_path": g["relative_path"], "size_bytes": group["size_bytes"],
                     "same_file": group["kind"] == "hardlink"}
                    for g in group["files"] if g["media_file_id"] != f["media_file_id"]
                )

    reviews = [
        r for r in session.query(MatchReview)
        .filter(MatchReview.media_file_id.in_(mf_ids), MatchReview.status.in_(READY_FOR_DECISION_STATUSES))
        .all()
        if not session.query(SeedJob).filter_by(candidate_id=r.candidate_id).count()
    ] if mf_ids else []
    in_review = {r.media_file_id for r in reviews}

    items_by_id = {i.id: i for i in items}
    files = []
    for mf in sorted(media_files, key=lambda f: (
        items_by_id[f.media_item_id].season_number or 0, items_by_id[f.media_item_id].episode_number or 0,
        f.relative_path,
    )):
        seeds = seeds_by_media.get(mf.id, [])
        tracked = [t for sf in seeds for t in torrents_by_seed.get(sf.id, [])]
        item = items_by_id[mf.media_item_id]
        files.append({
            "media_file_id": mf.id,
            "season_number": item.season_number,
            "episode_number": item.episode_number,
            "disk_id": mf.disk_id,
            "relative_path": mf.relative_path,
            "size_bytes": mf.size_bytes,
            "is_video": is_video(mf.relative_path),
            "state": "seeding" if tracked else "orphan_media",
            "stopped": bool(tracked) and all(is_stopped_state(t["state"]) for t in tracked),
            "excluded": exclusions.is_excluded(mf.relative_path),
            "in_review": mf.id in in_review,
            "hardlinks": [
                {"relative_path": sf.relative_path, "torrents": torrents_by_seed.get(sf.id, [])} for sf in seeds
            ],
            "duplicates": duplicate_peers.get(mf.id, []),
        })

    interval = get_rematch_interval(session)
    tracker_labels = dict(session.query(Tracker.id, Tracker.label).all())
    searches = []
    if mf_ids:
        by_tracker: dict[int, list[MatchAttempt]] = defaultdict(list)
        for attempt in session.query(MatchAttempt).filter(MatchAttempt.media_file_id.in_(mf_ids)).all():
            by_tracker[attempt.tracker_id].append(attempt)
        for tracker_id, attempts in by_tracker.items():
            last = max(_as_utc(a.attempted_at) for a in attempts)
            first = min(_as_utc(a.attempted_at) for a in attempts)
            searches.append({
                "tracker": tracker_labels.get(tracker_id, f"#{tracker_id}"),
                "files_searched": len(attempts),
                "last_searched_at": last.astimezone(UTC),
                "next_search_at": (first + interval).astimezone(UTC) if interval.total_seconds() > 0 else None,
            })

    seen: set[tuple[int, str]] = set()
    candidates = []
    for c in (
        session.query(Candidate).filter(Candidate.media_item_id.in_(item_ids))
        .order_by(Candidate.confidence.desc(), Candidate.id.desc()).all()
    ):
        key = (c.tracker_id, c.torrent_id_remote)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "id": c.id, "name": c.name, "tracker": tracker_labels.get(c.tracker_id, f"#{c.tracker_id}"),
            "torrent_id_remote": c.torrent_id_remote, "confidence": c.confidence,
            "ambiguity_reason": c.ambiguity_reason, "source": c.source, "direction": c.direction,
            "videos": sum(1 for f in c.files if f.is_video) or 1,
        })
        if len(candidates) >= MAX_CANDIDATES:
            break

    seed_jobs = []
    in_client = hashes_in_clients(session)
    if mf_ids:
        for sj in (
            session.query(SeedJob).filter(SeedJob.source_media_file_id.in_(mf_ids)).order_by(SeedJob.id.desc()).all()
        ):
            seed_jobs.append({
                "id": sj.id, "candidate_id": sj.candidate_id, "candidate_name": sj.candidate.name,
                "final_status": sj.final_status, "display_status": seed_job_display_status(sj, in_client),
                "recheck_status": sj.recheck_status, "error_message": sj.error_message,
                "torrent_added_at": sj.torrent_added_at,
            })

    head = next((i for i in items if i.title), items[0])
    first_video = next((f["relative_path"] for f in files if f["is_video"]), None)
    return {
        "content_type": content_type,
        "tmdb_id": tmdb_id,
        "title": head.title,
        "year": head.year,
        "has_poster": any(i.tmdb_poster_path for i in items),
        "imdb_id": next((i.imdb_id for i in items if i.imdb_id), None),
        "arr_kind": head.arr_kind,
        "arr_url": next((u for u in (_arr_url(session, i) for i in items) if u), None),
        "quality": _quality(first_video.rsplit("/", 1)[-1]) if first_video else None,
        "total_size_bytes": sum(f["size_bytes"] for f in files if not f["excluded"]),
        "files": files,
        "trackers": tracker_overview(session, files),
        "searches": searches,
        "candidates": candidates,
        "reviews": reviews,  # MatchReview: l'API li serializza con ReviewResponse (riepilogo pack incluso)
        "seed_jobs": seed_jobs,
    }
