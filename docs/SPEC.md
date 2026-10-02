# Nazgarr — Functional and architectural spec (v1)

A document consolidated from a user's stream of ideas, reorganized and grounded by comparing it against four related local projects. Not an open brainstorm: wherever something is explicitly undecided, it's flagged as such at the bottom (section 15).

**Name** (renamed 2026-09-29, user decision): project name **"Nazgarr"**, repo/technical name **`nazgarr`**. It was "The Media Gauntlet*rr" / `gauntletarr`, and the rename carries the data along (`gauntletarr.db` is renamed at startup, `app/db.py`). It's *arr style (like Bazarr/Cleanuparr/Prowlarr) without actually depending on Sonarr/Radarr, the same stylistic "wink" Auditorr already does. "Nazg" is a fantasy word for "ring" and the icon is a plain golden ring: a light fantasy flavour is fine in the UI, but no direct references to the source works or their marks, and none in the README. The **Media Stones** theme below comes from the old name and stays only as internal naming of domains/phases for now; a re-theme around the new name is to be evaluated (it isn't visible in the UI today).

## Theme: the Media Stones

Six "stones," one per main functional domain — used as a reading key to organize the spec and as the basis for the visual identity (icon/color per module in dashboard and sidebar), not as a rename of the underlying technical concepts (the code/API keeps ordinary descriptive names: `media_item`, `TorrentClientAdapter`, etc. — the Stones are a branding layer on top, not a replacement).

| Stone | Color | Domain | Section |
|---|---|---|---|
| **Stone of Bond** | Blue | Disk/hardlink model, unified per-file state (orphaned/ignored) | §3-4 |
| **Stone of Control** | Purple | Multi-client torrent adapters, presence/seeding state | §5 |
| **Stone of Knowledge** | Yellow | Content identification (TMDB), poster cache | §6 |
| **Stone of Reintegration** | Red | Matching and reseeding engine (repairs broken links) | §6, 8 |
| **Stone of Time** | Green | Scheduling, run history, dashboard trends over time | §8, 10 |
| **Stone of Genesis** | Orange | Upload — gives content "new life" by publishing it to a tracker | §9 |

"Wearing the gauntlet" = having all six Stones configured and active (disks mapped, clients connected, resolver working, matching engine active, scheduler configured, upload ready) — also useful as a metaphor for a future onboarding/setup wizard in the UI: a six-item checklist before the system is "complete."

## 0. Provenance — where this project comes from

This doesn't start from scratch. It synthesizes:

- **`ratio-guardian`** (its own `docs/SPEC.md`, a separate project): the most mature architectural analysis and the closest to this scope — a disk/hardlink model with no Unraid/FUSE dependency, a TMDB matching engine with explicit confidence, a reseeding engine with forced recheck, and — decided in that project's most recent session — a second "Upload" mode inspired by Upload-Assistant. Nazgarr **inherits ratio-guardian's entire data architecture and matching/reseeding engine**, which should be read for the verified implementation details (the real shape of the UNIT3D API, already-fixed known bugs like the season pack size comparison, mediainfo edge cases). This document doesn't repeat those details where they haven't changed, it references them.
- **Auditorr**: reference for the visualization experience — library tree view, per-file state (presence/hardlink/seeding), dashboard with a "library health" gauge, reverse hardlink lookup from the torrent side.
- **Upload-Assistant**: domain reference for the upload flow (mediainfo, screenshots, description, dupe-check, ~90 supported trackers). **In development freeze** as declared by the project itself — to be treated as a domain reference to reimplement against our own contracts, never as a live dependency.
- **smartmediareseed**: reference for verifying file↔torrent identity via **piece hashes** (BEP3) against the hash declared in the `.torrent` — a stronger confidence signal than mediainfo Unique ID alone (which doesn't distinguish different audio tracks on otherwise-identical video). To be integrated as an additional signal in the matching engine (section 6), never as a substitute for a real recheck.

## 1. Vision and problem

The user manages a media library (movies/shows) and one or more torrent seeding folders, often on separate physical disks with no RAID/FUSE. Everyday use accumulates drift:

- files moved/renamed in the library that break the hardlink and therefore seeding, without the user noticing (ratio-guardian's core problem);
- files present in the torrent folder that the torrent client no longer tracks (removed from the client, client reinstalled, a migration never completed);
- files seeding that were never organized/linked into the actual media library;
- downloaded/organized files that were never correctly identified (no TMDB match), and are therefore invisible to any matching logic.

Nazgarr has to give **a single, coherent view of every file's state**, on both sides (media and torrent) and on the torrent client itself, plus the tools to fix every kind of drift: reseeding, manual linking, uploading new content.

## 2. Genericity requirements (binding, inherited from ratio-guardian §2)

- **Must not assume Unraid/FUSE.** N separate physical disks, each potentially holding part of the library, with no unifying filesystem.
- **Must not assume Sonarr/Radarr.** Optional integration as an additional media resolver adapter, never a dependency.
- **Adapter architecture for trackers, torrent clients and media resolvers**, to allow future extension without rewrites (detail in section 5).
- Distribution: Docker container, web UI for configuration.
- **Designed for public/open source release** (an explicit decision, unlike the source tools which are for personal use): implies example config with no personal data, no hardcoded secrets, clean `.env.example`/`config.example.yaml`, a LICENSE, and care not to assume the original user's specific setup (paths, trackers, disk names) in any default.

## 3. The two directions of the problem: orphaned and ignored

The central point of the original request, distinct from (and complementary to) the "media→torrent" model ratio-guardian already covers. **Both scan directions** need to be maintained, on the same hardlink graph:

### Media → torrent direction (already covered by ratio-guardian's engine)

Files in the media library **without** a valid hardlink to the disk's torrent folder → candidates for the matching/reseeding engine (section 6). This is the "I moved/renamed the file and broke seeding" case.

### Torrent → client/media direction (new requirement for Nazgarr)

For every file in a disk's torrent folder:

- **Orphaned file**: present on the filesystem (torrent folder) but **not tracked by any configured torrent client** (no torrent in the client whose resolved path points to that file). Typically: a file left behind after removal from the client, a migration that was never finished, a reconfigured client. The natural action: the same reseeding engine as ratio-guardian, but triggered from the torrent side — search the configured trackers for a match for that file (size + mediainfo + piece hash, section 6), and if the match reaches maximum confidence (100%, not the 0.95 threshold used for the media→torrent case — see note below) **download the `.torrent` from the tracker and add it to the client pointing at the file that's already there**, with no need to recreate the hardlink (the file is already in place).
- **Ignored file**: present on the filesystem (torrent folder) and correctly tracked by the client, but **with no hardlink into any enabled `MediaPath`**. It's a seeding file "orphaned from the library": technically healthy, but invisible to the user's media organization. Action: flag only in the UI (never automatic) — the user decides whether it's worth organizing (manual hardlink into a MediaPath) or leaving it as-is (e.g. cross-seeded content that isn't theirs).

**"Tracked by a client"** means the torrent was present at the latest complete, successful listing of that client. A torrent removed from the client leaves the index at the next scan, and its file becomes an orphan again. A file whose torrents are all stopped (paused) in the client stays `seeding` in the state model, with a separate `stopped` flag in the UI. An execution that reached seeding and whose torrent was then removed from the client is shown as "removed from client", and it no longer blocks a new review for that torrent.

**Library ↔ torrent link by inode:** a library file is hardlinked (and seeding, if a client tracks the torrent side) when **any** torrent-side file shares its inode on the same disk. It does not depend only on the single `seed_file.media_file_id` the scanner writes. The same inode reachable from two library paths (e.g. a double import by Sonarr/Radarr) is therefore seeding on both paths, and is never searched as an orphan (`app/hardlinks.py`). Duplicates come in two kinds: `copy` (same content on different inodes, wasting space) and `hardlink` (same inode under several library paths: no extra space, but the content appears twice and one path can be deleted without touching the seed).

**Note on the threshold for torrent-side orphans**: the risk here differs from what's discussed in ratio-guardian §9 (a false positive that leads to seeding the wrong data). Adding a torrent that's already present locally based on a wrong match is still risky (it associates the file with a torrent that isn't a match; the client rechecks it and, worst case, fails — less severe than a false hardlink, but not harmless). So treat it with the **same severity**: a high, configurable threshold, and below it, the manual review queue, exactly as for the media→torrent case — never a bypass "because the file already exists."

### Unified per-file state

Every file (on either side) must expose a composite state, inspired by ratio-guardian's Library page (§12) but extended:

| State | Meaning |
|---|---|
| `seeding` | Valid hardlink + tracked by the client, actively seeding |
| `orphan_media` | In the media library, no valid hardlink (reseeding candidate — media→torrent direction) |
| `orphan_torrent` | In the torrent folder, not tracked by any client (reseeding candidate — torrent→client direction) |
| `ignored` | In the torrent folder, tracked by the client, no hardlink into the media library |
| `unmatched` | No TMDB match resolved (unparsable filename, or no tracker candidate), regardless of side |
| `pending_review` | A match was found but below the confidence threshold, in the manual review queue |

A media file counts as seeding only through a torrent a client tracks. A hardlink in the torrent folder that no client follows doesn't count: for example, a file downloaded by hand into the torrent folder and imported by Radarr is still searched as `orphan_media`. **Cross-seeds** (user decision, 2026-10-02, on by default, setting `cross_seed_search`): for each tracker, the media→torrent matching searches the files that don't seed on *that* tracker, so a file seeding on tracker A is also searched on tracker B. Reviews are kept per file and tracker, so a file can have one proposal on each tracker. A candidate whose info hash is already in a client is dropped. When the destination of a hardlink already exists with the same inode (the same release, under the same name, seeding for another tracker), execution reuses it instead of failing. A different file at that path is still an error and is never overwritten. The review queue marks these proposals as "Cross-seed · seeding on X" (`app/seeding.py`).

## 4. Data architecture (inherits ratio-guardian §3-4, §13 — extended here)

Disk/library model unchanged from ratio-guardian: a **Disk** entity (physical root, cached `st_dev` to detect remounts), **MediaPath** (one or more per disk, typed `movie`/`tv`), paths always relative to the disk (never absolute), two-level validation (scoped file browser in the UI + `st_dev` comparison at runtime before every hardlink). See ratio-guardian SPEC.md §3 for the full reasoning — not repeated here. Full table-by-table DB schema: `docs/schema.sql`.

### Two supported layouts: per-disk mounts or a single TrashGuide-style mount

`disk_scan_root` (default `/data`, see `config.example.yaml`) supports two deployment styles without any code change:

- **Single mount (TrashGuide convention)**: mount one combined torrents+media folder at `/data` — the same host path shared with the download client and media manager, which is what makes hardlinks between them work. In this layout there's a single Disk, and it's registered with `root_path` equal to `disk_scan_root` itself (`create_disk()` explicitly allows this — the scoping check accepts `root_path == scan_root`, not just a subfolder of it).
- **Per-disk mounts (classic Unraid layout)**: `disk_scan_root` points at a parent folder (e.g. `/mnt`) under which each physical disk is bind-mounted directly (`/mnt/disk1`, `/mnt/disk2`, ...), and each shows up as its own registerable Disk. This is the layout to use whenever a single share might span multiple physical disks in a way that could silently break a hardlink.

Either way, the runtime `st_dev` check before every hardlink (§3, `create_disk`/`verify_disk`) is the actual safety net: even inside a single combined mount, individual files are tracked with their own `st_dev` (not just one value per Disk row) — see "The two FKs" below — so a hardlink attempted across two files that don't really share a device fails with an explicit error rather than silently corrupting anything, whichever layout is in use.

### Why ratio-guardian's model isn't enough as-is

Ratio-guardian merges logical identity and physical file into a single row (`media_item` has both `tmdb_id` and `file_path`/`inode`) and **has no table at all for the torrent client inventory** — it checks "is this already seeding" with a live filesystem check (`find -samefile`) plus a client query only at execution time. That works for a single client with no need to see cross-seeding, but it doesn't hold up against Nazgarr's requirements (multi-client, a grid view grouped by content, explicit visibility of every cross-seed claimant — §3, §5, §7). Auditorr's model was also analyzed, as a negative reference: it keeps everything in JSON blobs recomputed on every run and, for cross-seeding, merges every claimant on the same inode down to just "the healthiest one" (`audit.py::_walk_directory`, lines 106-124) — an efficient choice, but one that **loses information**, exactly the opposite of what's needed here.

### The entities (physical separated from logical, as discussed)

```
media_item            -- resolved logical identity: tmdb_id, season, episode, poster
  media_file           -- physical, media side: disk_id, relative_path, size, st_dev/inode
                        --   "as of last scan", media_item_id (FK)

seed_file              -- physical, torrent side: disk_id, relative_path, size, st_dev/inode
                        --   "as of last scan", media_file_id (FK, nullable — see below)
                        --   one row per hardlink sibling: 3-way cross-seed = 3 rows

torrent_client          -- config (already exists)
  client_torrent          -- ONE torrent for ONE client instance: info_hash, name, save_path,
                          --   category, state, tracker_url — UNIQUE(torrent_client_id, info_hash)
    client_torrent_file     -- ONE file inside a client_torrent: path_in_torrent, size,
                            --   seed_file_id (FK, nullable)
```

`media_item` is separate from `media_file` (unlike ratio-guardian, where they're the same row) because the grid view (§7) needs to group several physical files under one poster — a common case for a season with multiple episodes, or content with several versions/qualities in the library.

### The two FKs, and why they're written differently

- **`seed_file.media_file_id`** (the inode link, cross-seed): **never computed at runtime with a live join** on `(disk_id, st_dev, inode)` — on a large library that would be recomputed every time the tree/grid view loads. Instead it is:
  1. computed **once per scan**, in memory, during the same `os.walk` already needed to read `st_dev`/`inode`/`nlink` (the same technique Auditorr uses — a dict kept for the duration of the scan — but here **without discarding the "losing" claimants**: every sibling stays a row);
  2. written with a **bulk upsert at the end of the scan** (batch insert/update, never a per-file query);
  3. tagged with `last_scan_id` (a FK to `run_log`) — a `seed_file` not seen again in a later scan isn't deleted right away (the review queue still needs to be able to show it as "gone"), but its `media_file_id` stops being trusted for current-state computations until it's reconfirmed. This avoids the concrete risk of inodes being reassigned by the filesystem between one scan and the next (the same problem already flagged as open in ratio-guardian §17 — made explicit and handled here).
- **`client_torrent_file.seed_file_id`** (the path link, not inode-based): resolved by comparing `client_torrent.save_path + path_in_torrent` against `disk.root_path + seed_file.relative_path` — doesn't suffer from reassignment (a path doesn't get "reused" for a different file the way an inode number does), so it's more stable across scans, though still reverified on every scan for consistency.

On read, every state query (§3) and every dashboard count (§10) is an indexed JOIN on these FKs — never a computation on `st_dev`/`inode` at runtime, which stay **write-only** columns for the scan process.

### Other extensions

- **Poster cache**: `media_item.tmdb_poster_path` (relative TMDB path) + a local cache of the downloaded images (filesystem, not a DB blob — a predictable path like `data/posters/{tmdb_id}.jpg`, downloaded once and reused). Needed for the grid view (§7).
- Static YAML (`disk_scan_root`, `data_dir`) / dynamic DB (disks, media paths, trackers, clients, thresholds) config split — unchanged from ratio-guardian §4.

Matching/reseeding entities (`candidate`, `match_review`, `seed_job`) and the new upload entities (§9) stay as in ratio-guardian, adapted to reference `media_item`/`media_file` instead of ratio-guardian's merged row — full detail in `docs/schema.sql`. One real gap found while building Fase 4: `candidate.media_item_id` alone isn't enough to know *which physical file* a match applies to when a `media_item` has more than one `media_file` (different quality versions of the same content) — never an issue in ratio-guardian, where a media_item *was* the physical file. Fixed by adding `match_review.media_file_id`/`match_review.seed_file_id` (whichever applies to the candidate's `direction`), so the decision — not just the search result — carries the physical file it's about.

## 5. Torrent clients: multi-client support from v1

An explicit requirement, unlike ratio-guardian (which starts with a single qBittorrent adapter and is generically extensible but with no immediate commitment to other clients). Priority:

1. **qBittorrent** — via `qbittorrent-api`, first adapter, implemented (`app/adapters/torrent_client/qbittorrent.py`). **Validated against a real instance** (deployed on Unraid, `POST /api/torrent-clients/{id}/test` confirmed a working connection) — tests still use a mocked client, the real-instance check was manual.
2. **qui** (multi-instance manager for qBittorrent, `app/adapters/torrent_client/qui.py`) — the Phase 2 pragmatic assumption above (treat it as plain qBittorrent pointed elsewhere) turned out to be **wrong**, confirmed against qui's own OpenAPI spec (github.com/autobrr/qui) and against Auditorr's own working qui integration (`sources/_qui.py`), not just deduced: qui exposes its own aggregation API (`X-API-Key` header, paths under `/api/instances/{id}/...`), not the qBittorrent WebUI API `qbittorrent-api` expects. A deployment manages several qBittorrent instances behind one host+key; `add_torrent` has to target one specific instance deterministically, so one `TorrentClient` row maps to exactly one qui-managed instance (`torrent_client.qui_instance_id`), never chosen at runtime like Auditorr's read-only aggregation across "eligible" instances does. No endpoint exists to read a single torrent's status by hash (confirmed absent from both the OpenAPI spec and Auditorr's implementation) — `get_torrent_status()` therefore does a full paginated scan per call, documented as a known inefficiency in the adapter's own docstring rather than hidden. Still unverified against a real qui instance (built and tested against the real, published API contract and mocks only) — same category of open item as qBittorrent's own real-instance check once was.
3. **Deluge**, 4. **Transmission**, 5. **rutorrent** — **deferred**, not implemented in Phase 2 (three different protocols — JSON-RPC/RPC/XML-RPC — non-trivial cost for a single pass). `app/adapter_factory.py` raises an explicit error for these `adapter_type` values, never a silent failure.

All behind the same `TorrentClientAdapter` contract — `add_torrent`/`get_torrent_status` inherited unchanged from ratio-guardian §14, **`list_torrents()` replaces the original `list_tracked_paths()` sketch** (implemented in `app/adapters/torrent_client/base.py`, different from this early draft):

```python
class TorrentClientAdapter(ABC):
    def add_torrent(self, torrent_file_or_url, save_path, force_recheck=True) -> str: ...
    def get_torrent_status(self, info_hash) -> TorrentStatus: ...
    def list_torrents(self) -> list[ClientTorrentInfo]:
        """Every torrent known to the client, with its files (path_in_torrent + size).
        Needed to populate client_torrent/client_torrent_file (section 4), not just to
        know whether a path is tracked yes/no — orphan_torrent/ignored/seeding are
        derived from that afterwards, never computed by the adapter itself."""
```

A disk/torrents_rel_path can be associated with several configured clients at once (a common case: qBittorrent for one group of trackers, rutorrent for another, on the same disk) — indexing (`app/torrent_indexer.py`) therefore aggregates across every client enabled for that disk, never assuming a 1:1 relationship.

## 6. Content identification (TMDB) and the matching engine

### Media resolver (inherits ratio-guardian §6)

Default: filename parsing (guessit) → TMDB lookup. Optional Sonarr/Radarr adapter for more reliable mapping, never assumed present.

**Sonarr/Radarr adapter (implemented 2026-09-23, `app/arr.py`)**: read-only index built once per run from every enabled instance.
- **Identity:** it gives the identity of every file Radarr/Sonarr know (`tmdbId`, season/episode), used by `ArrResolver` before guessit + TMDB, which stays the fallback. It also works with no TMDB key for the files the *arr instances know.
- **Torrent of origin:** from the history, the torrent a file was imported from. The imported event links `importedPath`/`droppedPath` to a `downloadId`, and the grabbed event gives `guid` (for UNIT3D via Prowlarr, the download URL `…/torrent/download/<id>.<passkey>`) plus the info hash. The matching engine turns this into a single `source='history'` candidate: one `.torrent` download instead of a catalog search, with the same explicit confidence rules (size, then piece hash). It falls back to the catalog search when that candidate isn't plausible.
- **Path matching:** automatic, with no path-mapping config. The folder and file name plus the exact size must match, because *arr paths live in their own container namespace.
- **Posters:** Sonarr only exposes TVDB artwork, so a series' TMDB poster costs one `/tv/{id}` call per series, never a per-episode title search.
- **Season packs:** the imported events also map every file of a download (`droppedPath`) to the library file it became (`importedPath`), even after Sonarr renamed it. This is the most precise way to match a pack's episodes (see "Multi-file torrents" below). On the user's instance: 396 pack folders, 8838 files.

**Extension for the grid view**: at TMDB resolution time, download and cache the poster (`tmdb_poster_path` → local image, section 4). A `media_item` with no poster available (very niche content, or TMDB doesn't have it) shows a placeholder in the UI, never a blocking error.

### Multi-file torrents: season packs and releases with extras (implemented 2026-09-23, `app/torrent_layout.py`)

Every candidate is evaluated as a whole torrent, file by file. This replaces the Phase 4 scope reduction ("more than one file = confidence 0"), which also excluded every movie released with an `.nfo` or subtitles next to it.
- **The library scan records every file**, not only videos. Exclusions are a filter for views, counts and API lookups; an excluded file that is part of a torrent is still used to recreate it. Only videos get an identity and trigger matching.
- **Matching a pack's videos to local files**, most precise first:
  1. Sonarr history (`droppedPath` → `importedPath`);
  2. on the torrent side, the original names under the same root as the orphan;
  3. guessit season/episode on the pack's file names plus exact size.

  Every file must be on the orphan's disk (hardlinks).
- **Extras** (nfo, subtitles, sample) match by name, or by extension plus exact size when renamed. Extras with no local file are left for the client to download after the recheck. The recheck counts as ok only if what is left fits `seed_job.expected_missing_bytes`: those extras plus two pieces each for shared boundary pieces. Anything else below 100% still fails.
- **Confidence:** the lowest of its videos (size → per-file mediainfo Unique ID → per-file piece hash, using the offsets from the `.torrent`, downloaded once per candidate). A pack with any video missing locally is `season_pack_partial`, confidence 0, never executed. User decision: a pack is only recreated whole; seasons collected episode by episode keep using single-episode torrents.
- **One evaluation per pack per run:** the other orphan episodes of the same pack reuse it, and a torrent already queued or running for another file never gets a second review. Every file of the torrent and its local match is stored in `candidate_file`, which the executor recreates from and the Reseeding page shows.

### Matching engine (inherits ratio-guardian §7-8, integrated with smartmediareseed)

Pipeline unchanged in structure (personal history if available → catalog search by tmdb_id → size match → mediainfo Unique ID match → explicit, explainable confidence, never opaque ML). See ratio-guardian SPEC.md §7-8 for every verified detail (UNIT3D API shape, season pack handling, the limits of personal history via scraping).

**New confidence signal**, a recommendation already written up in smartmediareseed's analysis and adopted here as a requirement: **piece hash verification** (BEP3 bencode parsing of the downloaded `.torrent`, byte-exact comparison against the local content) as an additional signal, stronger than mediainfo Unique ID alone because it's deterministic and not subject to the known limitation (same video, different audio → sometimes the same Unique ID). To be used to:
- raise confidence when size+mediainfo already agree but aren't absolutely certain;
- **the only signal acceptable for auto-executing the torrent→client direction** (section 3), where a higher threshold than the media→torrent case is needed, because there the file already exists and a wrong match adds a non-matching torrent in a way that's less recoverable with just a recheck.

**Full hash check (diagnosis):** matching verifies only a sample of pieces. From a candidate or an execution the user can run a check of 100% of the pieces (`app/full_check.py`), boundary pieces included. It reads the files where the client sees them first, then from the library, and reports per file the pieces that match, differ or can't be read, plus whether the info hash changed. It's read-only and runs in the background, one check at a time. It tells a different release apart from a wrong path when a recheck keeps failing, and never replaces the client's recheck.

**Full check before executing** (`verify_before_execute`, on by default, user decision): approving a review first runs the full check. Hardlinks and the add to the client happen only if every piece matches and every file is present at the right size. The only exception is extras missing locally, which the client downloads after its recheck. While the check runs, the review stays in the queue as "verifying", with progress shown in the notification. If the check fails, nothing is touched and the review stays in the queue with the reason. Automatic execution, when turned on, applies the same check. The setting can be turned off (Configuration > Matching & approval) to execute straight away on the sampled pieces.

**Exceptions to the recheck.** Uploads (user decision, 2026-09-30): the torrent of a new upload is created by Nazgarr from the very files it will seed, so it is added without the client's recheck, after checking that every file is at the seed path with its size and, once added, that the client reports that save path; otherwise a normal recheck. Reseeds (user decision, 2026-09-29): the opt-in setting `skip_client_recheck_when_verified` is off by default and requires the full check before executing. With it on, a torrent is added with `skip_checking` only when Nazgarr's full check just verified 100% of its pieces, no extra is missing locally (otherwise the client has to download it) and the info hash matches. The seed job records `recheck_skipped`. The known risk is the short window between the check and the add. **A forced recheck on the client remains mandatory in every case** when adding to the client (never `skip_checking`) — the piece hash is a stronger matching signal, not a substitute for the client's own verification.

## 7. Library view: tree + poster grid

Two display modes over the same underlying data (the unified per-file state, section 3), user-selectable, inspired respectively by Auditorr (tree) and the explicit request for a poster grid:

- **Tree view** (revised 2026-09-23, superseding the original "one tree + detail panel" sketch): **two separate, symmetric views** built on the same component — "Media files" (the tree under `disk.media_rel_path`, from `GET /api/media-files`) and "Torrent files" (the tree under `disk.torrents_rel_path`, from `GET /api/seed-files`). Same information, different dataset. Each one is summary cards per state (count + total size) on top, a toolbar (state tabs, filename/path search, min/max size in GB, show excluded, and — Media files only — a Duplicates filter backed by `GET /api/library/duplicates`), and a real table (indented name with folder chevrons, size aggregated recursively on folders, state badge, hardlink info on hover). Filtering is client-side over the full file list. Still deferred: per-file tracker + tracker filter, seed count, "Open in Radarr", a flat view, copy paths / CSV export, inline mini-posters.
- **Grid view**: a card per `media_item` with a TMDB poster (placeholder fallback), title, year, status badge. Meant for quick visual scanning ("what do I have, what's missing, what's broken") rather than technical detail — that stays one click away (the same detail panel as the tree view).
- **Filters shared between both views**: by state (every state from section 3), by disk, by MediaPath/content_type, text search by title.
- **Reverse lookup from the torrent side** (inspired by Auditorr): given a torrent in the client, show which library file(s) it corresponds to (via hardlink) — useful to understand "why is this seeding" without having to search manually.

Both views share the same backend/API — it's just `?view=tree|grid` over the same filtered resource, never two separate data pipelines.

### Tracker filter (user decisions, 2026-09-30)

A global selector in the top bar (dashboard, library and torrent views) shows the seeding status for every torrent ("All trackers", as always), only for the configured trackers (a public tracker doesn't count), or for one tracker. A torrent belongs to a tracker when the host of its announce URL matches the tracker's announce or base URL (`app/tracker_scope.py`). With a filter, a library file is seeding only if it's in a torrent of that tracker; torrents on disabled clients don't count at all; the torrent view shows only that tracker's torrents plus the orphans (in no torrent), which can become an upload for any tracker. The choice is a setting (`tracker_filter`), so it stays as the default. The dashboard's current numbers follow the filter; its history is kept per filter from the first scan after the filter existed (`tracker_health_snapshot`), while "All trackers" keeps the global history on `run_log`.

## 8. Reseeding engine and execution

Inherits ratio-guardian §9-11 in full:
- A configurable confidence threshold per direction (defaults 0.95 media→torrent, 0.98 torrent→client, see the note in section 6). A match above its threshold is **recommended** in the review queue, not executed. **Nothing that modifies files or the torrent client runs without the user's explicit approval** (user decision, 2026-09-23, after a run auto-executed 20 reviews unasked). Automatic execution of recommended matches is an opt-in setting (`auto_execute_above_threshold`, Configuration → Mapping), off by default.
- Hardlink with the exact name the tracker expects (media→torrent direction only — in the torrent→client direction the file is already in the right place, only the torrent gets added to the client).
- Forced recheck, never skipped.
- Periodic reconciliation of recheck status (async on the client).
- Bulk import mode (one-off full scan) + scheduled run (cron configurable from the UI), both on the same engine.

## 9. Upload: creating and publishing a new torrent

Inherits ratio-guardian §16 in full, including the reasoning on what to reuse from Upload-Assistant (the `torf` library to create the `.torrent`, extended `pymediainfo`, `ffmpeg-python` for screenshots, dupe-check via the same `TrackerAdapter.search_by_tmdb`) and what not to reuse (no code taken directly from Upload-Assistant, which is in development freeze — only a domain reference for the shape of UNIT3D requests and tracker profiles).

Points that stay unchanged:
- Separate data domain (`upload_job`, `tracker_upload_profile`), never touches the reseeding entities.
- Tracker profiles bundled as seed data versioned in the repo, copied into the DB when a tracker is created, freely editable afterwards and never re-read from the file.
- Mandatory human confirmation before submission, as non-negotiable as the forced recheck in reseeding.
- v1 already includes mediainfo + screenshots (not deferred).

Implemented in Fase 6. Two things found while implementing, not in the original design: `tracker.announce_url` was missing from the schema entirely (`base_url` is the API host, `torf` needs the distinct personal announce URL to create a valid `.torrent`) — added as a nullable column, same additive-migration pattern as every other schema gap found mid-implementation. And `type_id` resolution from a filename is reliable only for `category_id`/`resolution_id` (content type, `screen_size`) — the REMUX/ENCODE/WEBDL/BDMUX distinction is too convention-dependent for a generic guess, so it stays an explicit best-effort default, always editable on the `upload_job` before confirmation, exactly as this section already specified ("resolved, editable before submission").

### Upload flow v2 (user decisions, 2026-09-29 — supersedes the single-file/single-tracker pipeline above)

The Phase 6 pipeline handled one file towards one tracker, synchronously inside the HTTP request, with a hand-typed TMDB id. v2 redesigns the flow around what the user actually does:

- **What can be uploaded**: a single movie, a single episode, a season folder as a *season pack*, a whole-series folder as a *complete pack*. Selection happens in a drawer that reuses the folder view and lets the user pick either a file or a folder.
- **One job, many trackers**: `upload_job` is the source (file or folder), its confirmed identity (TMDB/IMDB/TVDB/MAL ids, season(s)), the user's overrides, and the mediainfo/screenshots, all produced **once**. `upload_target` is one row per selected tracker, with its own action (`upload` / `reseed` / `skip`), proposed and approved release name, flags (anonymous, personal release, internal, stream), dupe-check results, `.torrent`, remote id and outcome. This is what makes "reseed on one tracker, upload on the other" possible. `upload_event` is an append-only log of every step, used both for live monitoring and for the history drawer.
- **Tracker selection**: every tracker with an upload profile is preselected; the generated torrent goes to the client configured on that tracker (`tracker.torrent_client_id`, first enabled client when null), the same rule reseeding follows.
- **One `.torrent` per tracker** (user decision): each tracker gets its own file (its announce URL and `source` field, hence a different info hash). The piece hashes are computed once and reused for every tracker's file.
- **State machine persisted in the DB, driven by an in-process worker** (same single-worker thread pattern as `app/full_check.py`, but with state in the DB so a restart resumes the queue instead of losing it). The frontend polls, like runs and full checks.
- **Two human gates, and only two**: (1) confirming the metadata match (and the season, for series); (2) approving, per tracker, the action and the release name. Gate (2) **is** the mandatory human confirmation of this section: once both gates are passed the worker runs to completion on its own, which is what makes a queue of several uploads possible (user decision, 2026-09-29).
- **Identification**: the resolver returns a list of candidates (not just the first hit) shown as posters with the title overlaid and a Movie/Series badge, with a detail panel on click. Forced ids go through TMDB's external-id lookup (`/find`, which covers IMDB and TVDB). For series the detected season is shown with the episodes found against the ones TMDB expects; an ambiguous season gets a picker. Posters of candidates not in the library are served through a backend proxy (the TMDB key stays server-side).
- **Analysis before the trackers**: size and file list compared with the torrents on every client; Radarr/Sonarr history consulted when configured — a file that the history says was grabbed from a tracker is flagged loudly (it's someone else's release: a reseed is probably what the user wants, not an upload).
- **Dupe check per tracker**: the tracker's results filtered on the dimensions that actually make two releases the same slot (resolution, HDR/DV, source, remux vs not, season/episode, byte-identical size), the same dimensions Upload-Assistant's `dupe_checking.py` uses — reimplemented, not copied. A strong match proposes a full piece-hash check (`app/full_check.py`); a passed check turns that tracker's suggested action into `reseed`, executed through the existing reseed path (forced recheck, as always).
- **Release names**: values read from the MediaInfo (resolution, video codec, HDR/DV, every audio track and its languages, subtitles) and from the release name (type, source, service, edition, repack, group), with the user's overrides on top. The release name used is the one of the torrent already seeding the same files (hardlink), else the original name Radarr/Sonarr recorded, else the source name. The variables are the same for every tracker (`app/upload_naming.py` VARIABLES: title and local title, year, season/episode, edition, repack, resolution, source, type, service, video codec, HDR, bit depth, main audio track split into codec/channels/Atmos, every audio track, audio and subtitle languages, subs label, group); each tracker's **naming rules** (`naming_rules_json`) only order and format them, edited in the tracker's upload profile with one input per release type, the variables as insertable chips and a live preview: a main template, an optional one for series (e.g. without the year) and optional ones per release type, plus a few options (local title in the tracker's language, all audio tracks or only the main one, how to write languages, SDR label, separator). Previewed and editable before gate (2).
- **Freeleech** (user decision, 2026-09-30): each profile lists the freeleech percentages the tracker lets uploaders set (UNIT3D `free`), with a preselected one; chosen per tracker when creating the upload and again at gate (2). None listed = no freeleech choice for that tracker.
- **Naming rules are versioned** (user decision, 2026-09-30, the one exception to "bundled profiles are never re-read"): a bundled profile's `naming` block has a `version`. At startup a higher version in the code replaces the rules of a profile the user hasn't edited; an edited profile is only offered the update (a banner with "use the new rules"), unless the bundled version says `force: true`. Category/type/resolution ids are never touched.
- **Overrides without overwhelming the user**: only the four ids are always visible. A collapsed "Detected details" panel lists category, type, source, resolution, season/episode, year, edition/repack, group, service, each showing the detected value as its placeholder so the user only touches what's wrong. An "Advanced" section keeps a handful more (naming toggles, screenshot count, custom description, don't seed, skip dupe check). The long tail of Upload-Assistant's ~115 CLI arguments is deliberately left out of v1.
- **History**: queue and history tabs; each row shows poster, title, kind and one badge per tracker outcome, with a drawer for the event timeline, names used, links, mediainfo, screenshots, description and, on failure, what went wrong.
- **Where uploads seed** (user decision, 2026-09-30): hardlinks in a per-disk folder for uploads (`disk.upload_rel_path`, set like the folder for new reseeding hardlinks), falling back to the seeding folder (`torrents_rel_path`) when not set. A source already inside the seeding folder seeds in place. A reseed decided in the upload flow places the tracker's torrent the same way, with the tracker's own file names. Same filesystem or an explicit error, like reseeding; always a forced recheck.
- **Existing `upload_job` rows are dropped** when the new tables are created (user decision: no real upload data to keep).


**Releases from a watched folder** (user decisions, 2026-10-02). Each disk can have a watched folder (`disk.watch_rel_path`, `app/upload_watch.py`). It can never be the disk itself, and never inside or above the media, torrent or upload folder.

- **Starting:** every new video file or folder put there starts an upload on its own, once its size and mtime stay the same for 2 minutes and it holds no partial files. The upload goes to every tracker that has an upload profile.
- **Once only:** `watch_entry` remembers each entry, so a release starts one upload even after its job is deleted. What is already inside when the folder is chosen doesn't start.
- **Releaser name:** the setting `upload_releaser_name` becomes the `{group}` override of these jobs, and stays editable.
- **Automatic match:** TMDB candidates now carry a confidence (`app/upload_match_score.py`). Every upload, by hand or from the watched folder, confirms its best candidate on its own when the confidence is at least `upload_auto_match_threshold` (default 0.9; 0 turns it off). Ambiguous candidates (two titles nearly as sure) are never confirmed on their own.
- **Where it stops:** the job goes as far as the decision and waits there. Nothing is uploaded, linked or added to a client without approval.
- **A way in, not a home:** the watched folder is only a way in. Once at least one tracker succeeds and the release seeds from the releases (upload) folder under the torrent names, the original in the watched folder is removed. It is removed only if each of its files has another link, the copy that seeds (`_clear_watch_source`). With "don't seed", or when nothing succeeded, it stays where it was.
- **Rollback:** "Change match" (`back_to_match`) takes a job from the decision back to the match and redoes the analysis.

**The media folder is optional** (user decision, 2026-10-02): Nazgarr can also be used only to scan torrents and to upload releases, with no media folder at all. The storage step only needs the torrent folder. Without a library there is no health: the Dashboard says so instead of showing 100%, and scans store no health point, while the torrent numbers keep their trend.
- **Language check:** each tracker with a language gets a warning when no audio track (commentary excluded) is in that language.

## 10. UI/UX — general structure

```
Library
  Tree view               (§7)
  Grid view                (§7)
  Orphaned and ignored     [n]  (§3 — both directions, with contextual actions)

Reseeding
  Dashboard
  Review              [n]  (pending match_review, both directions)
  Verify from .torrent
  Runs

Upload
  New upload
  Upload queue        [n]
  Description templates

Configuration
  Disks
  Torrent clients          (multi-client, §5)
  Trackers
  Settings
```

Dashboard: inherits ratio-guardian §15 (library health gauge, pending review/failed/unresolved KPIs, novelty feed) — **additional KPIs** to reflect the two directions: an `orphan_torrent` count and an `ignored` count, each linking directly to the matching filter in Library. Health gauge formula settled in Fase 5 (`app/health.py`): a single explicit, size-weighted ratio (seeding media size / total media size), not Auditorr's multi-factor weighted score (hardlink/orphan/not-imported/duplicates, each independently weighted) — the other KPIs already surface those signals individually and clickably, so folding them again into one composite number would lose clarity rather than add it. Layout (revised 2026-09-29, Auditorr-inspired, user decision): a 7d/30d/90d/All window drives the health ring and its history. The health is still the single hardlink ratio above: no weighted score. Four cards (hardlinked media, orphaned torrents, not imported, duplicates) show value, size and trend against the previous scan (`run_log` keeps their sizes), plus a link to the filtered view. The **Not imported** view lists seeding torrents with no hardlink in the library (per-file state `ignored`, shown as "not imported"), one row per torrent with a reason. The reasons are superseded, copy, removed, never imported and extras only (`app/not_imported.py`). The view is read-only; actions are a future step through the review queue (docs/ROADMAP.md). Each tracker can set an optional seeding requirement (minimum seed time and/or minimum ratio; with both, either one is enough unless the tracker is set to require both — user decision, 2026-10-01): the view marks the torrents that already met their tracker's requirement as safe to remove, with what is still missing for the others (`app/seed_requirements.py`). The novelty feed is **"Changes since last scan"** (`GET /api/dashboard/changes`, `app/file_changes.py`), a per-file diff in the style of Auditorr and a user decision that replaces the earlier "latest candidates" feed. At the end of each scan where every disk and every client completed, each file's state (media and torrent side) is compared with the previous snapshot. The diff lists new and removed media/torrent files, plus state changes: now seeding, now orphaned, now ignored, stopped and resumed. The first scan only takes the baseline, and excluded files never produce a change.

Frontend stack: **React SPA + shadcn/ui** (a decision already made in ratio-guardian on 2026-09-21, inherited here from the start instead of as a later refactor — Nazgarr already starts with a FastAPI backend as a pure JSON API under `/api/*`, no Jinja2/HTMX phase to outgrow). Fase 8 (in corso): scaffold Vite + React + TypeScript + Tailwind + shadcn/ui in `frontend/`, tipi TS generati dallo schema OpenAPI di FastAPI (`openapi-typescript`, mai duplicati a mano), servito in produzione dallo stesso container FastAPI (`app/frontend.py`, nessun processo Node separato) — sidebar di navigazione con la struttura sopra già in piedi, le singole pagine arrivano per sotto-fasi successive.

**First-access tour** (user decisions, 2026-10-02): an interactive guided setup starts by itself at the first access, when no tour was ever seen and no disk exists. A welcome dialog asks two questions (uploads? Radarr/Sonarr?) that tailor the path. A "Getting started" checklist on the Dashboard follows the real configuration (`GET /api/system/setup-status`, `app/setup_status.py`): a step completes however it was configured. Optional steps with sensible defaults (exclusions, reseeding thresholds) complete once seen. Each step has a guided tour (`frontend/src/onboarding`, driver.js — MIT; Shepherd was set aside because it is AGPL-3.0). The tour moves between screens, highlights one field at a time and waits for the user's save. It steps aside while another dialog or list is open. Anchors are `data-tour` attributes, checked by a test. After the first scan, a tour of the views follows on its own: Dashboard, Library, Not imported and the review queue. It can also be started from the finished checklist and from Settings › Application. The tone is neutral, with at most one light fantasy wink per step and never a name or a literal quote. The progress is stored in `app_settings` (`onboarding_state`), and the tour can be restarted from Settings › Application.

## 11. Tech stack

Inherits ratio-guardian (CLAUDE.md), with additions for multi-client and posters:

- **Python 3.12**, **FastAPI** (pure JSON API under `/api/*`)
- **SQLite** via SQLAlchemy — enough for this load
- **APScheduler** in-process for scheduling
- **httpx** for tracker/TMDB calls (async-friendly)
- **qbittorrent-api**, plus a client library/libraries for Deluge/Transmission/rutorrent (still to be chosen during implementation, section 5)
- **pymediainfo** for mediainfo/Unique ID
- **guessit** for filename parsing
- **torf** to create `.torrent` files for uploads (pure Python)
- **ffmpeg-python** for upload screenshots (needs `ffmpeg` in the container)
- A minimal BEP3 bencode parser (already in ratio-guardian as `app/torrent_file.py`, reusable) — used both for the folder-name fallback (ratio-guardian §7) and for the piece hash (section 6)
- **Frontend**: **React + shadcn/ui** SPA, Vite build, served by the FastAPI container
- **Single container with supervisord** (web + worker/scheduler), same pattern as ratio-guardian

## 12. What to reuse from each source project (summary)

| Project | Reuse |
|---|---|
| ratio-guardian | Data architecture, matching/reseeding engine, adapter contracts — **a direct starting point**, not just inspiration. Python code reusable almost as-is where scope overlaps (torrent_file.py, mediainfo_util.py, adapters). |
| Auditorr | UX reference (tree view, dashboard, reverse lookup) — no direct code reuse (stack/language compatibility to verify during implementation, otherwise a design reference only). |
| Upload-Assistant | Domain reference for upload (tracker request shape, profiles, mediainfo/screenshots) — **no code reuse** (development freeze, incompatible stack: Flask/SSE web_ui vs FastAPI+SPA). |
| smartmediareseed | Piece-hash (BEP3) verification technique, to integrate as an additional confidence signal (section 6) — logic to reimplement against our own contracts, not to import (different Postgres/Flask stack). |

## 13. Open source requirements

- No personal data (paths, trackers, user credentials) in any versioned file — `config.example.yaml`/`.env.example` with generic placeholders.
- An explicit LICENSE (still to choose — MIT/AGPL are the typical picks for this kind of self-hosted tool, AGPL if the goal is discouraging closed-SaaS forks).
- Bundled tracker profiles (section 9) contain only publicly verifiable mapping/naming, never credentials.
- Setup documentation (README) good enough for a third-party user with no context from the design sessions — never assume the reader knows ratio-guardian or the other source projects.

## 14. Suggested roadmap

1. Bootstrap the project (stack, folder structure, requirements) — reusing ratio-guardian's structure/config as a reference.
2. DB schema (disks/media paths/torrent index/tracker/client/media_item with poster/candidate/match_review/seed_job) + SQLAlchemy models.
3. Scoped-per-disk file browser API (a pattern reusable as-is from ratio-guardian).
4. Torrent client adapters: qBittorrent first (direct reuse), then Deluge/Transmission/rutorrent/qui by the priority in section 5.
5. Media resolver (guessit + TMDB) + poster download/cache.
6. Matching engine (size + mediainfo + piece hash) for both directions (section 3), explicit confidence.
7. Review queue UI.
8. Executor: hardlink + add-to-client + forced recheck, both directions.
9. Library view (tree + grid) built on the unified state.
10. Scheduler + run history.
11. Upload module (torf, mediainfo/screenshots, tracker profiles, dupe-check, human confirmation).
12. Cleanup for open source release (example config, LICENSE, README).

Not binding to the letter, but respects the logical dependencies (e.g. there's no point building the Library view before a unified state exists to show).

**Repo**: `https://github.com/lktorrentz/nazgarr` (public, GPL-3.0). A project **separate from `ratio-guardian`** (confirmed decision: doesn't replace it, doesn't reuse its code as-is — reuses architecture/patterns as described in this document, but has its own repo and history).

## 15. Things explicitly left open (not decided in this session)

- **"qui"'s API surface — resolved**: see section 5 — a dedicated adapter (`app/adapters/torrent_client/qui.py`) built and verified against qui's own published OpenAPI spec and Auditorr's real integration, not the earlier "just point qbittorrent-api at it" assumption (which was wrong). Only a real qui instance to test the adapter end-to-end remains open, same category as qBittorrent's own once-open real-instance check.
- **Deluge/Transmission/rutorrent adapters**: deferred in Phase 2 (section 5), not implemented — which Python library to use for each is still to be decided when that slice is picked back up.
- **Confidence threshold for the torrent→client direction** (sections 3, 6): whether it's the same 0.95 or higher — still to decide, no number fixed yet.
- Every point already open in ratio-guardian SPEC.md §17 (UNIT3D history scraping, a match cache persisted independently of the physical path, the exact tracker profile schema) stays open here too, unchanged. **Resolved since**: history for the dashboard chart (Fase 5, `run_log.health_snapshot` + `GET /api/dashboard/history`) and the image host for upload screenshots (Fase 6, below).
- **TVDB and MAL lookups for uploads** (user decision 2026-09-29: fine for v1, to revisit later): in the upload flow v2 (§9) TVDB and MAL ids are only passed through to the tracker, and a forced TVDB id is looked up via TMDB's `/find`. A direct TVDB search (API v4, needs a key) or MAL search (via Jikan, unofficial) would add dependencies and wasn't worth it for v1.
- **Image host for upload screenshots — resolved in Fase 6**: rather than picking one, wired all three realistic options (PTPImg, ImgBB, Imgbox) as a priority-ordered fallback chain (`ImageHostChain`, `app/adapter_factory.py::build_image_host_chain`) — user's explicit choice over picking a single adapter.
