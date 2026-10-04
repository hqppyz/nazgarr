"""Abbinamento di un torrent intero (ogni suo file) ai file locali —
generalizza il vecchio confronto "un file locale contro un torrent a file
singolo", che dava confidence 0 a qualunque torrent con più di un file:
season pack, ma anche un film con il suo .nfo o i sottotitoli accanto.

Due lati, stessa valutazione:
- libreria (media_to_torrent): il torrent va ricreato con hardlink dai file
  in libreria. Ogni video del torrent deve corrispondere a un media_file;
  per un pack l'abbinamento viene, in ordine, dalla history di Sonarr
  (droppedPath -> importedPath, esatto anche con file rinominati) o da
  guessit sul nome del file nel pack (stagione/episodio) + stessa size.
- torrent (torrent_to_client): la cartella del torrent è ancora su disco,
  i nomi sono quelli originali — basta ritrovare ogni file sotto la stessa
  radice dell'anchor.

Regole esplicite (docs/SPEC.md §6), mai un punteggio opaco: ogni video
abbinato ha la sua confidence (size, poi Unique ID mediainfo, poi piece
hash per file con gli offset del .torrent), quella del candidato è la più
bassa fra i video. Un video senza file locale = "season_pack_partial",
confidence 0 (decisione dell'utente: un pack si ricrea solo per intero).
I file extra (non video) non contano per la confidence: se presenti in
locale vengono usati, se mancano li scarica il client dopo il recheck
(nazgarr/executor.py, tolleranza expected_missing_bytes).
"""

import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy.orm import Session, selectinload

from nazgarr.arr import ArrIndex, path_key
from nazgarr.file_types import is_video
from nazgarr.guess import guess as guess_name
from nazgarr.models import MediaFile, SeedFile
from nazgarr.torrent_file import TorrentInfo
from nazgarr.torrent_pieces import verify_file_pieces

CONFIDENCE_PIECE_VERIFIED = 0.99
CONFIDENCE_SIZE_AND_MEDIAINFO_MATCH = 0.9
CONFIDENCE_SIZE_ONLY = 0.5
CONFIDENCE_NO_MATCH = 0.0

# Piece verificati per file video (nazgarr/torrent_pieces.py max_pieces): un
# campione distribuito lungo il file, mai la rilettura dell'intero file.
PIECE_SAMPLE_SIZE = 8

# Piece che un file extra mancante condivide con i vicini: il client li
# riscarica interi. Stima prudente quando la piece length non è nota.
DEFAULT_PIECE_LENGTH = 16 * 1024 * 1024


@dataclass
class LayoutFile:
    path: str  # dentro il torrent, relativo alla sua cartella (senza `folder`)
    size: int | None
    is_video: bool

    def full_path(self, folder: str | None) -> str:
        return f"{folder}/{self.path}" if folder else self.path


@dataclass
class Layout:
    folder: str | None
    files: list[LayoutFile]
    torrent: TorrentInfo | None = None  # presente se ricavato dal .torrent vero

    @property
    def videos(self) -> list[LayoutFile]:
        return [f for f in self.files if f.is_video]

    @property
    def piece_length(self) -> int | None:
        return self.torrent.piece_length if self.torrent else None


def layout_from_torrent(parsed: TorrentInfo) -> Layout:
    folder = parsed.name if parsed.is_multi_file else None
    files = [LayoutFile(path=f.path, size=f.length, is_video=is_video(f.path)) for f in parsed.files]
    return Layout(folder=folder, files=files, torrent=parsed)


def layout_from_catalog(file_list: list[str] | None, file_sizes: dict[str, int] | None,
                        folder: str | None, total_size: int, name: str) -> Layout:
    """Da ciò che espone la ricerca sul catalogo (UNIT3D files[] già
    normalizzati da _normalize_pack_structure): nessun download."""
    names = file_list or [name]
    sizes = file_sizes or {}
    if len(names) == 1 and names[0] not in sizes:
        sizes = {names[0]: total_size}
    return Layout(
        folder=folder,
        files=[LayoutFile(path=n, size=sizes.get(n), is_video=is_video(n)) for n in names],
    )


@dataclass
class LocalFile:
    kind: str  # "media" | "seed"
    id: int
    disk_id: int
    relative_path: str
    abs_path: str
    size: int


@dataclass
class FileMatch:
    layout_file: LayoutFile
    local: LocalFile | None
    size_match: bool | None = None
    mediainfo_match: bool | None = None
    piece_verified: bool | None = None
    piece_boundary_count: int | None = None
    confidence: float = CONFIDENCE_NO_MATCH


@dataclass
class LayoutEvaluation:
    files: list[FileMatch]
    confidence: float
    ambiguity_reason: str | None
    size_match: bool | None
    mediainfo_match: bool | None
    piece_verified: bool | None
    piece_boundary_count: int | None
    missing_extra_bytes: int
    missing_extra_count: int

    @property
    def is_multi_video(self) -> bool:
        return sum(1 for f in self.files if f.layout_file.is_video) > 1


def _media_local(mf: MediaFile) -> LocalFile:
    return LocalFile("media", mf.id, mf.disk_id, mf.relative_path,
                     os.path.join(mf.disk.root_path, mf.relative_path), mf.size_bytes)


def _seed_local(sf: SeedFile) -> LocalFile:
    return LocalFile("seed", sf.id, sf.disk_id, sf.relative_path,
                     os.path.join(sf.disk.root_path, sf.relative_path), sf.size_bytes)


@dataclass
class LocalFiles:
    """Indici in memoria su media_file/seed_file, costruiti una volta per
    run di matching — mai una query per file del torrent."""

    media_by_key: dict[tuple[str, int], list[MediaFile]] = field(default_factory=lambda: defaultdict(list))
    media_by_episode: dict[tuple[int, int, int], list[MediaFile]] = field(default_factory=lambda: defaultdict(list))
    media_by_dir: dict[tuple[int, str], list[MediaFile]] = field(default_factory=lambda: defaultdict(list))
    episodes_by_series: dict[int, set[tuple[int, int]]] = field(default_factory=lambda: defaultdict(set))
    seed_by_path: dict[tuple[int, str], SeedFile] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session) -> "LocalFiles":
        index = cls()
        for mf in session.query(MediaFile).options(selectinload(MediaFile.media_item)).all():
            index.media_by_key[(path_key(mf.relative_path), mf.size_bytes)].append(mf)
            index.media_by_dir[(mf.disk_id, os.path.dirname(mf.relative_path))].append(mf)
            item = mf.media_item
            if item is not None and item.season_number is not None and item.episode_number is not None:
                index.media_by_episode[(item.tmdb_id, item.season_number, item.episode_number)].append(mf)
                index.episodes_by_series[item.tmdb_id].add((item.season_number, item.episode_number))
        for sf in session.query(SeedFile).all():
            index.seed_by_path[(sf.disk_id, sf.relative_path)] = sf
        return index


@lru_cache(maxsize=65536)
def _episode_numbers(filename: str) -> tuple[int, int] | None:
    """Memoizzata: lo stesso pack (es. un'altra stagione della serie) viene
    riesaminato per ogni episodio orfano cercato per tmdb_id, e guessit
    costa millisecondi a nome file."""
    guess = guess_name(filename)
    season, episode = guess.get("season"), guess.get("episode")
    if isinstance(season, list):
        season = season[0] if season else None
    if isinstance(episode, list):
        episode = episode[0] if episode else None
    if season is None or episode is None:
        return None
    return int(season), int(episode)


def _pick_same_disk(files: list[MediaFile], disk_id: int, size: int | None) -> MediaFile | None:
    same_size = [f for f in files if size is None or f.size_bytes == size]
    for f in same_size:
        if f.disk_id == disk_id:
            return f
    return None  # un hardlink non attraversa i dischi: un file su un altro disco non serve


def map_media_side(
    layout: Layout, anchor: MediaFile, local: LocalFiles, arr_index: ArrIndex | None = None, translator=None,
) -> list[FileMatch]:
    """Abbina ogni file del torrent a un media_file sul disco dell'anchor.
    Con un solo video, quel video è l'anchor stesso (il caso di sempre).
    translator (nazgarr/episode_orders.py Translator): se il torrent numera gli
    episodi con un altro ordinamento della libreria, quelli non trovati coi
    loro numeri si cercano tradotti."""
    videos = layout.videos
    matches: dict[int, FileMatch] = {}
    item = anchor.media_item
    unmatched: dict[int, tuple[int, int]] = {}  # indice del file -> (stagione, episodio) del torrent

    for i, lf in enumerate(layout.files):
        if not lf.is_video:
            continue
        mf: MediaFile | None = None
        if len(videos) == 1:
            mf = anchor
        else:
            if arr_index is not None and lf.size is not None:
                imported = arr_index.imported_for(lf.full_path(layout.folder), lf.size)
                if imported is not None:
                    mf = _pick_same_disk(local.media_by_key.get(imported, []), anchor.disk_id, lf.size)
            if mf is None and item is not None and item.content_type == "tv":
                numbers = _episode_numbers(os.path.basename(lf.path))
                if numbers is not None:
                    mf = _pick_same_disk(
                        local.media_by_episode.get((item.tmdb_id, *numbers), []), anchor.disk_id, lf.size
                    )
                    if mf is None:
                        unmatched[i] = numbers
        matches[i] = FileMatch(lf, _media_local(mf) if mf is not None else None)

    if unmatched and translator is not None and item is not None:
        torrent_episodes = {n for lf in videos if (n := _episode_numbers(os.path.basename(lf.path))) is not None}
        mapping = translator.mapping(item.tmdb_id, torrent_episodes, local.episodes_by_series.get(item.tmdb_id, set()))
        for i, numbers in unmatched.items():
            target = mapping.get(numbers)
            if target is None:
                continue
            mf = _pick_same_disk(local.media_by_episode.get((item.tmdb_id, *target), []), anchor.disk_id,
                                 layout.files[i].size)
            if mf is not None:
                matches[i] = FileMatch(layout.files[i], _media_local(mf))

    # Extra: stesse cartelle dei video abbinati, per nome o (sottotitoli
    # rinominati da Sonarr/Radarr) per estensione + size esatta, se univoca.
    dirs = {os.path.dirname(m.local.relative_path) for m in matches.values() if m.local}
    neighbours = [mf for d in dirs for mf in local.media_by_dir.get((anchor.disk_id, d), [])]
    used = {m.local.id for m in matches.values() if m.local}
    for i, lf in enumerate(layout.files):
        if lf.is_video:
            continue
        found = _match_extra(lf, [n for n in neighbours if n.id not in used])
        if found is not None:
            used.add(found.id)
        matches[i] = FileMatch(lf, _media_local(found) if found is not None else None)

    return [matches[i] for i in range(len(layout.files))]


def _match_extra(lf: LayoutFile, neighbours: list[MediaFile]) -> MediaFile | None:
    base = os.path.basename(lf.path).lower()
    for n in neighbours:
        if os.path.basename(n.relative_path).lower() == base and (lf.size is None or n.size_bytes == lf.size):
            return n
    if lf.size is None:
        return None
    ext = os.path.splitext(base)[1]
    same = [n for n in neighbours if n.size_bytes == lf.size and n.relative_path.lower().endswith(ext)]
    return same[0] if len(same) == 1 else None


def map_seed_side(layout: Layout, anchor: SeedFile, local: LocalFiles) -> list[FileMatch]:
    """La cartella del torrent è ancora su disco con i nomi originali:
    ritrovata la radice dall'anchor, ogni altro file è un lookup esatto."""
    root = None
    for lf in layout.files:
        suffix = lf.full_path(layout.folder)
        if anchor.relative_path.endswith(suffix) and (lf.size is None or lf.size == anchor.size_bytes):
            head = anchor.relative_path[: -len(suffix)]
            if head == "" or head.endswith("/"):
                root = head
                break
    if root is None:
        return [FileMatch(lf, None) for lf in layout.files]
    result = []
    for lf in layout.files:
        sf = local.seed_by_path.get((anchor.disk_id, root + lf.full_path(layout.folder)))
        result.append(FileMatch(lf, _seed_local(sf) if sf is not None else None))
    return result


def evaluate(
    matches: list[FileMatch],
    layout: Layout,
    *,
    anchor_id: int,
    unique_ids: dict[str, str] | None,
    single_unique_id: str | None,
    compute_unique_id: Callable[[str], str | None],
    fetch_torrent: Callable[[], TorrentInfo | None],
) -> LayoutEvaluation:
    """Confidence del torrent intero. `fetch_torrent` scarica e analizza il
    .torrent solo se serve davvero (qualche video a sola size), al massimo
    una volta per candidato."""
    videos = [m for m in matches if m.layout_file.is_video]
    reason = None
    if not videos:
        reason = "no_video_in_torrent"
    elif any(m.local is None for m in videos):
        reason = "season_pack_partial" if len(videos) > 1 else "no_local_file"
    elif not any(m.local.id == anchor_id for m in matches if m.local):
        reason = "anchor_not_in_torrent"

    if reason is None:
        for m in videos:
            _score_video(m, len(videos), unique_ids, single_unique_id, compute_unique_id)
        if any(m.size_match is False for m in videos):
            reason = "size_mismatch"
        elif any(m.mediainfo_match is False for m in videos):
            reason = "mediainfo_mismatch"

    if reason is None and any(m.confidence == CONFIDENCE_SIZE_ONLY for m in videos):
        parsed = layout.torrent or fetch_torrent()
        if parsed is not None:
            if layout.torrent is None:
                layout.torrent = parsed
            for m in videos:
                if m.confidence == CONFIDENCE_SIZE_ONLY:
                    _verify_pieces(m, layout.folder, parsed)
            if any(m.piece_verified is False for m in videos):
                reason = "piece_mismatch"

    extras_missing = [m for m in matches if not m.layout_file.is_video and m.local is None]
    missing_bytes = sum(m.layout_file.size or 0 for m in extras_missing)

    if reason is not None:
        confidence = CONFIDENCE_NO_MATCH
    else:
        confidence = min(m.confidence for m in videos)

    def _all(values):
        values = list(values)
        if any(v is False for v in values):
            return False
        if values and all(v is True for v in values):
            return True
        return None

    boundaries = [m.piece_boundary_count for m in videos if m.piece_boundary_count is not None]
    return LayoutEvaluation(
        files=matches,
        confidence=confidence,
        ambiguity_reason=reason,
        size_match=_all(m.size_match for m in videos) if videos else None,
        mediainfo_match=_all(m.mediainfo_match for m in videos) if videos else None,
        piece_verified=_all(m.piece_verified for m in videos) if videos else None,
        piece_boundary_count=sum(boundaries) if boundaries else None,
        missing_extra_bytes=missing_bytes,
        missing_extra_count=len(extras_missing),
    )


def _score_video(m: FileMatch, video_count: int, unique_ids: dict[str, str] | None,
                 single_unique_id: str | None, compute_unique_id: Callable[[str], str | None]) -> None:
    if m.layout_file.size is None:
        m.size_match = None
        m.confidence = CONFIDENCE_NO_MATCH
        return
    m.size_match = m.local.size == m.layout_file.size
    if not m.size_match:
        m.confidence = CONFIDENCE_NO_MATCH
        return
    expected = (
        (unique_ids or {}).get(os.path.basename(m.layout_file.path))
        if video_count > 1
        else single_unique_id or (unique_ids or {}).get(os.path.basename(m.layout_file.path))
    )
    if expected is not None:
        local_id = compute_unique_id(m.local.abs_path)
        if local_id is not None:
            m.mediainfo_match = local_id == expected
    if m.mediainfo_match is True:
        m.confidence = CONFIDENCE_SIZE_AND_MEDIAINFO_MATCH
    elif m.mediainfo_match is False:
        m.confidence = CONFIDENCE_NO_MATCH
    else:
        m.confidence = CONFIDENCE_SIZE_ONLY


def _verify_pieces(m: FileMatch, folder: str | None, parsed: TorrentInfo) -> None:
    entry = next((e for e in parsed.files if e.path == m.layout_file.path), None)
    if entry is None:
        base = os.path.basename(m.layout_file.path).lower()
        entry = next((e for e in parsed.files if os.path.basename(e.path).lower() == base), None)
    if entry is None:
        return
    result = verify_file_pieces(
        m.local.abs_path, parsed.piece_length, parsed.pieces, parsed.total_length, entry.offset, entry.length,
        max_pieces=PIECE_SAMPLE_SIZE,
    )
    m.piece_boundary_count = result.boundary
    if result.mismatches > 0:
        m.piece_verified = False
        m.confidence = CONFIDENCE_NO_MATCH
    elif result.clean:
        m.piece_verified = True
        m.confidence = CONFIDENCE_PIECE_VERIFIED


def expected_missing_bytes(missing_extra_bytes: int, missing_extra_count: int, piece_length: int | None) -> int:
    """Quanto il client può legittimamente dover scaricare dopo il recheck:
    gli extra mancanti più, per ciascuno, fino a due piece condivise con i
    file vicini (un piece a cavallo va riscaricato intero)."""
    if missing_extra_count == 0:
        return 0
    return missing_extra_bytes + 2 * (piece_length or DEFAULT_PIECE_LENGTH) * missing_extra_count
