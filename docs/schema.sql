-- Nazgarr — DB schema
-- See docs/SPEC.md for the rationale behind every table/field.
-- Inherits ratio-guardian/docs/schema.sql's setup, with one main structural
-- difference: here the physical file (media_file/seed_file) is an entity
-- separate from the logical identity (media_item) and from the torrent
-- client record (client_torrent/client_torrent_file) — see SPEC.md §4 for
-- the why and for how the FKs are written (never a live join on inode).

-- ============ CONFIGURATION ============

CREATE TABLE IF NOT EXISTS disk (
    id                          INTEGER PRIMARY KEY,
    label                       TEXT NOT NULL,
    root_path                   TEXT NOT NULL UNIQUE,   -- must match/be inside a config.yaml mount
    st_dev                      INTEGER,                -- cached from the last verification
    media_rel_path              TEXT,                   -- relative to root_path, nullable — where the scan
                                                         -- looks for video files. One media library per disk;
                                                         -- movie vs tv is detected by the resolver (filename/
                                                         -- path heuristics), never chosen here.
    torrents_rel_path           TEXT,                   -- relative to root_path, nullable
    new_torrent_rel_path        TEXT,                   -- optional, relative to root_path (same convention as
                                                         -- torrents_rel_path): ONLY where to create a NEW
                                                         -- hardlink and which save_path to hand the client.
                                                         -- Does NOT narrow the "already seeding" search, which
                                                         -- always stays on the whole torrents_rel_path. If
                                                         -- null, torrents_rel_path is used unchanged.
    media_scan_id               INTEGER,                -- last run that read media_rel_path successfully, even
    seed_scan_id                INTEGER,                -- when empty (same for torrents_rel_path): what makes a
                                                         -- file "current" (app/scan_state.py), so an emptied
                                                         -- folder doesn't keep its old files alive
    upload_rel_path             TEXT,                   -- optional, relative to root_path: where a NEW UPLOAD
                                                         -- (and a reseed decided in the upload flow) gets its
                                                         -- hardlinks and save_path. If null, torrents_rel_path
                                                         -- (SPEC.md §9 "Upload flow v2").
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracker (
    id                      INTEGER PRIMARY KEY,
    label                   TEXT NOT NULL,
    adapter_type            TEXT NOT NULL,          -- "unit3d", future: "gazelle", etc.
    base_url                TEXT NOT NULL,
    api_token               TEXT NOT NULL,          -- encrypted at rest
    rss_key                 TEXT,                   -- encrypted at rest; the key in UNIT3D download links
                                                    -- (/torrent/download/<id>.<rss_key>). Learned automatically
                                                    -- from the API's download_link, optional manual override:
                                                    -- rewrites links saved by Sonarr/Radarr before a key change
    announce_url            TEXT,                   -- personal announce URL, needed only for creating a NEW
                                                      -- .torrent to upload (SPEC.md §9) — distinct from base_url
                                                      -- (the API host). Null for a tracker only used for
                                                      -- matching/reseeding, never upload. Missing from the
                                                      -- original Phase 0 draft (found while implementing
                                                      -- Fase 6's torrent_create.create_torrent()).
    history_mode            TEXT NOT NULL DEFAULT 'unsupported'
                            CHECK (history_mode IN ('api','scrape','unsupported')),
    history_session_cookie  TEXT,                   -- if history_mode='scrape'
    rate_limit_per_min      INTEGER DEFAULT 30,
    enabled                 BOOLEAN NOT NULL DEFAULT 1,
    torrent_client_id       INTEGER,
        -- client where torrents of this tracker are added when reseeding (e.g. a private-trackers
        -- instance); null or a disabled/deleted client = the first enabled client. No FK: a deleted
        -- client must just fall back, never block deleting it.
    language                TEXT,
        -- ISO 639-1 (e.g. 'it'): the tracker's language, for upload names (localized title, that
        -- language first among the audio tracks, how subtitles are written). Null = none.
    adapter_config_json     TEXT
        -- encrypted at rest: the values of the fields a plugin adapter declares
        -- (app/plugins/config.py). Built-in adapters use the columns above.
);

CREATE TABLE IF NOT EXISTS torrent_client (
    id              INTEGER PRIMARY KEY,
    label           TEXT NOT NULL,
    adapter_type    TEXT NOT NULL,          -- "qbittorrent" | "deluge" | "transmission" | "rutorrent" | "qui"
                                             -- (multi-client from v1, see SPEC.md §5)
    base_url        TEXT NOT NULL,
    username        TEXT,
    password        TEXT,                   -- encrypted at rest
    api_token       TEXT,                   -- encrypted at rest — adapter_type="qui" only (its X-API-Key,
                                             -- confirmed against a live instance's OpenAPI spec: SPEC.md §15).
                                             -- Missing from the original Phase 0 draft, found while implementing
                                             -- the dedicated qui adapter (a qui deployment is NOT the plain
                                             -- qBittorrent WebUI API pointed elsewhere, as first assumed).
    qui_instance_id INTEGER,                -- adapter_type="qui" only: one qui deployment manages several
                                             -- qBittorrent instances behind one host+api_token, so this pins
                                             -- one TorrentClient row to exactly one of them (add_torrent must
                                             -- target a specific instance, never pick one at runtime).
    enabled         BOOLEAN NOT NULL DEFAULT 1,
    -- Category and tags given to the torrents Nazgarr adds, only as labels (auto torrent
    -- management stays off: a category never moves the files). Categories are the client's own
    -- (picked from its list); null = none. Anime = TMDB genre Animation + original language ja.
    category_movie  TEXT,
    category_tv     TEXT,
    category_anime  TEXT,                   -- null = the movie/tv category
    tags_upload     TEXT,                   -- comma separated, for new uploads (e.g. "release")
    tags_reseed     TEXT,                   -- comma separated, for reseeds
    adapter_config_json TEXT                -- encrypted at rest: fields of a plugin adapter (app/plugins/config.py)
);

-- A disk can have several clients enabled at once (SPEC.md §5) — needs a
-- bridge table, not a single FK on disk. torrent_client_root_path lives
-- here, per (disk, client) pair, not on disk: different clients associated
-- with the same disk can see it mounted at different paths in their own
-- container — a single column on disk could not represent that for more
-- than one client at a time.
CREATE TABLE IF NOT EXISTS disk_torrent_client (
    disk_id                    INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    torrent_client_id          INTEGER NOT NULL REFERENCES torrent_client(id) ON DELETE CASCADE,
    torrent_client_root_path   TEXT,    -- root of THIS disk as seen by THIS client, if different from
                                         -- disk.root_path — null if this client and Nazgarr see the
                                         -- same path (common case, same host or same mount)
    PRIMARY KEY (disk_id, torrent_client_id)
);

-- Content-identification adapters, optional and never required by the
-- resolver (SPEC.md SS2/SS6). Multi-instance from the start, same
-- reasoning as tracker/torrent_client, even though no concrete adapter
-- consumes these yet (media_resolver's SOURCE lists "sonarr"/"radarr" as
-- future values) — the storage is prepared ahead of the adapter.
-- priority/timeout_seconds/basic_auth_* left nullable (no DEFAULT), even
-- though the app applies 0/15 defaults in Python: migrate_schema() (app/db.py)
-- only knows how to ALTER TABLE ADD COLUMN additive nullable columns, so the
-- model and this fresh-install schema must agree on that shape.
CREATE TABLE IF NOT EXISTS radarr_instance (
    id                    INTEGER PRIMARY KEY,
    label                 TEXT NOT NULL,
    base_url              TEXT NOT NULL,
    api_key               TEXT NOT NULL,    -- encrypted at rest
    enabled               BOOLEAN NOT NULL DEFAULT 1,
    priority              INTEGER,          -- higher = queried first, once a resolver adapter exists; null = 0
    timeout_seconds       INTEGER,          -- null = app default (15s)
    basic_auth_username   TEXT,             -- for Radarr behind a reverse proxy with HTTP basic auth
    basic_auth_password   TEXT              -- encrypted at rest
);

CREATE TABLE IF NOT EXISTS sonarr_instance (
    id                    INTEGER PRIMARY KEY,
    label                 TEXT NOT NULL,
    base_url              TEXT NOT NULL,
    api_key               TEXT NOT NULL,    -- encrypted at rest
    enabled               BOOLEAN NOT NULL DEFAULT 1,
    priority              INTEGER,
    timeout_seconds       INTEGER,
    basic_auth_username   TEXT,
    basic_auth_password   TEXT              -- encrypted at rest
);

-- Configuration of the adapters that have no row of their own (image hosts,
-- media resolvers, notifications) when they come from a plugin
-- (app/plugins/config.py). Built-in image hosts keep their app_settings keys.
CREATE TABLE IF NOT EXISTS adapter_config (
    kind            TEXT NOT NULL,
    adapter_type    TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT 1,
    config_json     TEXT,                   -- encrypted at rest; secrets never returned by the API
    PRIMARY KEY (kind, adapter_type)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
    -- e.g.: confidence_threshold_auto_media_to_torrent=0.95,
    --       confidence_threshold_auto_torrent_to_client=0.98 (higher threshold, see SPEC.md
    --       §3/§6 — indicative default, explicitly open point in SPEC.md §15),
    --       schedule_cron="0 4 * * *"
);

-- ============ RUN LOG (before PHYSICAL: media_file/seed_file/client_torrent_file
--   reference run_log.id via last_scan_id) ============

CREATE TABLE IF NOT EXISTS run_log (
    id                  INTEGER PRIMARY KEY,
    run_type            TEXT NOT NULL CHECK (run_type IN ('scheduled','manual','bulk_import')),
    started_at          TIMESTAMP NOT NULL,
    finished_at         TIMESTAMP,
    -- One value per real step of app/pipeline.py::run_bulk_import, committed
    -- as the run transitions through them (not just at start/end) so a live
    -- poller (GET /api/runs) sees genuine progress, not "scanning" for the
    -- whole run. null = not running.
    current_phase       TEXT CHECK (current_phase IN
                            ('scanning','resolving','indexing','matching','executing','reconciling')),
    phase_total         INTEGER,          -- total for the current phase, for live status (X/Y)
    phase_done          INTEGER,          -- done so far in the current phase
    phase_detail        TEXT,             -- what the current phase is on: disk/client/tracker, rate-limit wait
    cancel_requested_at TIMESTAMP,        -- "Stop run": the pipeline stops at its next progress update
    phases_json         TEXT,             -- per phase {status,done,total,skipped,started_at,finished_at},
                                          -- app/run_progress.py — the status popup's stepper
    items_total         INTEGER,          -- precounted when the run starts (total scan)
    items_scanned       INTEGER DEFAULT 0,
    matches_found        INTEGER DEFAULT 0,
    auto_executed         INTEGER DEFAULT 0,   -- renamed from auto_seeded: covers both directions
    pending_review       INTEGER DEFAULT 0,
    orphan_torrent_count  INTEGER DEFAULT 0,   -- new dashboard KPI, SPEC.md §10
    ignored_count         INTEGER DEFAULT 0,   -- ditto
    orphan_torrent_bytes  INTEGER,             -- sizes at the end of the run, for the trend of the
    ignored_bytes         INTEGER,             -- dashboard cards (not imported = ignored). Additive,
    duplicate_wasted_bytes INTEGER,            -- nullable.
    health_snapshot       REAL,                -- "library health" % at the end of the run, for the
                                                -- dashboard's historical chart (SPEC.md §10). Formula
                                                -- settled in Fase 5, see app/health.py.
    errors                INTEGER DEFAULT 0,
    snapshot_saved        BOOLEAN,             -- the per-file state snapshot was taken at the end of this run
                                                -- (app/file_changes.py). Additive, nullable.
    errors_json           TEXT,                -- JSON list of every error of the run, in order (at most 50),
                                                -- shown in the scan history. Additive, nullable.
    last_error            TEXT                 -- short summary of the last exception caught during this
                                                -- run (e.g. "torrent client 'X': <message>"), so it's
                                                -- visible in the UI without digging through the Logs tab —
                                                -- the full traceback still goes to logger.exception().
                                                -- Nullable, no DEFAULT: additive column, see migrate_schema()
                                                -- in app/db.py.
);

-- ============ PHYSICAL (written ONLY by the scan process — never by hand, never read by other tables) ============

-- Logical content identity — separate from the physical file (unlike
-- ratio-guardian) because the grid view (SPEC.md §7) needs to group several
-- physical files (episodes of a season, several versions) under one poster.
CREATE TABLE IF NOT EXISTS media_item (
    id                  INTEGER PRIMARY KEY,
    content_type        TEXT NOT NULL CHECK (content_type IN ('movie','tv')),
    tmdb_id             INTEGER NOT NULL,
    season_number       INTEGER,                -- null for a movie
    episode_number       INTEGER,                -- null for a movie or a complete season pack
    tmdb_poster_path    TEXT,                    -- relative TMDB path; the image itself is cached on the
                                                  -- filesystem (data/posters/{content_type}-{tmdb_id}.jpg,
                                                  -- movie and tv ids are separate namespaces on TMDB), never in the DB
    title               TEXT,                    -- movie title / series name, from Radarr/Sonarr or TMDB
    year                INTEGER,                 -- release year / first air year
    imdb_id             TEXT,                    -- from Radarr/Sonarr, for the detail sheet's IMDb link
    arr_kind            TEXT,                    -- 'radarr' | 'sonarr': who manages this content, if anyone
    arr_instance_id     INTEGER,                 -- radarr_instance.id / sonarr_instance.id (no FK: two tables)
    arr_slug            TEXT,                    -- titleSlug, for "Open in Radarr/Sonarr" ({base_url}/movie|series/{slug})
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- SQLite treats NULL as always distinct in UNIQUE: a plain unique constraint
-- on (tmdb_id, season_number, episode_number) would NOT stop two duplicate
-- movie rows (season/episode are always null). Two partial indexes, one per type.
CREATE UNIQUE INDEX IF NOT EXISTS idx_media_item_movie ON media_item(tmdb_id)
    WHERE content_type = 'movie';
CREATE UNIQUE INDEX IF NOT EXISTS idx_media_item_tv ON media_item(tmdb_id, season_number, episode_number)
    WHERE content_type = 'tv';

-- Persistent cache of TMDB search results, keyed by what the resolver
-- actually searches with (guessit's parsed title + year), not by any file
-- identity — many media_file rows share the same key (every episode of the
-- same show), so this is what stops a network call per file instead of per
-- distinct title. Only successful lookups are cached (tmdb_id NOT NULL): a
-- title TMDB doesn't know today could match new content added there
-- tomorrow, and there's no TTL/invalidation here yet to safely re-check a
-- cached miss — a resolved tmdb_id, on the other hand, never changes for
-- the same title/year, so caching it forever is safe. year defaults to 0
-- (never NULL) specifically so the UNIQUE constraint below still dedupes
-- title-only queries with no recognizable year — SQLite treats NULL as
-- always distinct in a UNIQUE, which would otherwise insert a fresh row
-- per file even for the exact same query.
CREATE TABLE IF NOT EXISTS tmdb_search_cache (
    id              INTEGER PRIMARY KEY,
    content_type    TEXT NOT NULL CHECK (content_type IN ('movie','tv')),
    query           TEXT NOT NULL,          -- guessit title, normalized (trimmed + lowercased)
    year            INTEGER NOT NULL DEFAULT 0,
    tmdb_id         INTEGER NOT NULL,
    poster_path     TEXT,
    result_title    TEXT,                   -- what TMDB returned, not what was searched
    result_year     INTEGER,
    resolved_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(content_type, query, year)
);

-- Physical, media library side. One row per file on disk under disk.media_rel_path.
CREATE TABLE IF NOT EXISTS media_file (
    id                      INTEGER PRIMARY KEY,
    disk_id                 INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path           TEXT NOT NULL,          -- relative to disk.root_path
    size_bytes              INTEGER NOT NULL,
    st_dev                  INTEGER NOT NULL,       -- "as of last scan" — never trusted beyond last_scan_id
    inode                   INTEGER NOT NULL,       -- ditto — the filesystem reassigns inodes over time
    nlink                   INTEGER,                -- >1 = hardlinked somewhere, a quick first signal
    content_hash            TEXT,                   -- fast partial-content hash (app/duplicates.py), to find
                                                      -- unintentional same-content copies across different inodes
    media_item_id           INTEGER REFERENCES media_item(id) ON DELETE SET NULL,     -- resolved by the resolver
    resolver_source         TEXT,                   -- "filename_parser" | "sonarr" | "radarr"
    mediainfo_unique_id     TEXT,                    -- computed on demand, cached
    last_scan_id            INTEGER NOT NULL REFERENCES run_log(id),
    last_seen_at            TIMESTAMP NOT NULL,
    UNIQUE(disk_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_media_file_media_item_id ON media_file(media_item_id);
CREATE INDEX IF NOT EXISTS idx_media_file_hardlink ON media_file(disk_id, st_dev, inode);
    -- used ONLY on write, by the end-of-scan writer that populates seed_file.media_file_id — never on read

-- Physical, torrent folder side. One row per hardlink sibling: content
-- cross-seeded across 3 different torrents/trackers produces 3 rows here,
-- each with the same (disk_id, st_dev, inode) but a different path and
-- client_torrent_file. Cross-seed is therefore a query, not a dedicated
-- table (see SPEC.md §4).
CREATE TABLE IF NOT EXISTS seed_file (
    id              INTEGER PRIMARY KEY,
    disk_id         INTEGER NOT NULL REFERENCES disk(id) ON DELETE CASCADE,
    relative_path   TEXT NOT NULL,          -- relative to disk.root_path
    size_bytes      INTEGER NOT NULL,
    st_dev          INTEGER NOT NULL,       -- "as of last scan"
    inode           INTEGER NOT NULL,       -- "as of last scan"
    media_file_id   INTEGER REFERENCES media_file(id) ON DELETE SET NULL,
        -- FK written ONLY by the end-of-scan bulk upsert (grouping by inode computed in memory
        -- during the same os.walk, never a runtime self-join — see SPEC.md §4). If several
        -- media_file rows share the same inode (rare: a duplicate hardlink inside the library
        -- itself), the first one found during the walk wins, for consistency with the same
        -- convention Auditorr already uses for similar cases — the others are still visible by
        -- querying media_file for (disk_id, st_dev, inode).
    last_scan_id    INTEGER NOT NULL REFERENCES run_log(id),
    last_seen_at    TIMESTAMP NOT NULL,     -- if older than the latest run_log, the row is stale: still
                                             -- shown in the UI (history), never used for the current
                                             -- state (SPEC.md §3) until it's reconfirmed
    UNIQUE(disk_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_seed_file_media_file_id ON seed_file(media_file_id);
CREATE INDEX IF NOT EXISTS idx_seed_file_hardlink ON seed_file(disk_id, st_dev, inode);
    -- used ONLY on write, same reason as idx_media_file_hardlink

-- ============ TORRENT CLIENT (multi-instance, SPEC.md §5) ============

-- One torrent for ONE client instance. Several rows for the same content
-- (different clients, or the same client with different torrents on the
-- same inode) are normal: that's how cross-seed becomes visible without a
-- dedicated table.
CREATE TABLE IF NOT EXISTS client_torrent (
    id                  INTEGER PRIMARY KEY,
    torrent_client_id   INTEGER NOT NULL REFERENCES torrent_client(id) ON DELETE CASCADE,
    info_hash           TEXT NOT NULL,
    name                TEXT NOT NULL,
    save_path           TEXT NOT NULL,
    category            TEXT,
    tracker_url         TEXT,
    state               TEXT NOT NULL,          -- value as reported by the client, not normalized here
                                                 -- (mapping to Nazgarr states happens in the app, not the DB)
    added_at            TIMESTAMP,
    last_polled_at      TIMESTAMP NOT NULL,
    ratio               REAL,                   -- as reported by the client (Not imported view). Additive, nullable.
    seeding_time_seconds INTEGER,               -- ditto
    UNIQUE(torrent_client_id, info_hash)
);

-- One file inside a client_torrent, as reported by the client's API.
CREATE TABLE IF NOT EXISTS client_torrent_file (
    id                  INTEGER PRIMARY KEY,
    client_torrent_id   INTEGER NOT NULL REFERENCES client_torrent(id) ON DELETE CASCADE,
    path_in_torrent     TEXT NOT NULL,          -- relative to client_torrent.save_path
    size_bytes          INTEGER NOT NULL,
    seed_file_id         INTEGER REFERENCES seed_file(id) ON DELETE SET NULL,
        -- FK resolved by PATH (save_path + path_in_torrent compared against disk.root_path +
        -- seed_file.relative_path), not by inode — more stable than seed_file.media_file_id, but
        -- still reverified on every scan (same last_scan_id) for consistency.
    last_scan_id        INTEGER NOT NULL REFERENCES run_log(id),
    UNIQUE(client_torrent_id, path_in_torrent)
        -- added in Phase 2 (missing from the first draft): without a unique constraint,
        -- the indexer (app/torrent_indexer.py) couldn't do an idempotent upsert on every
        -- poll the way media_file/seed_file/client_torrent do — it would instead have to
        -- delete and recreate rows every pass, breaking the pattern's consistency.
);
CREATE INDEX IF NOT EXISTS idx_ctf_seed_file_id ON client_torrent_file(seed_file_id);
CREATE INDEX IF NOT EXISTS idx_ctf_client_torrent_id ON client_torrent_file(client_torrent_id);

-- ============ DOMAIN — matching and reseeding (SPEC.md §6-8) ============

CREATE TABLE IF NOT EXISTS candidate (
    id                   INTEGER PRIMARY KEY,
    media_item_id        INTEGER NOT NULL REFERENCES media_item(id) ON DELETE CASCADE,
    tracker_id           INTEGER NOT NULL REFERENCES tracker(id),
    torrent_id_remote    TEXT NOT NULL,          -- id on the tracker
    info_hash            TEXT,
    name                 TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL,
    file_list_json       TEXT,                   -- if available from the API
    folder               TEXT,                   -- pack subfolder (UNIT3D "folder"), null for a single file
    download_link        TEXT,                   -- authenticated URL to the .torrent (needed for add_torrent)
    source               TEXT NOT NULL CHECK (source IN ('history','catalog_search')),
    direction            TEXT NOT NULL CHECK (direction IN ('media_to_torrent','torrent_to_client')),
        -- which of the two SPEC.md §3 directions produced this candidate — absent from
        -- ratio-guardian, which only ever knew media_to_torrent
    size_match           BOOLEAN,
    mediainfo_match       BOOLEAN,
    piece_verified        BOOLEAN,                -- piece-hash verification outcome (§6), null = not attempted
    piece_boundary_count  INTEGER,                -- pieces straddling an adjacent file in the torrent, not judgeable
    confidence            REAL NOT NULL,          -- 0.0-1.0, computed from explicit rules
    ambiguity_reason      TEXT,                   -- e.g. "season_pack_partial", "multiple_size_matches", "piece_mismatch"
    piece_length          INTEGER,                -- from the .torrent when downloaded: tolerance for missing extras
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Every file of a candidate's torrent and the local file it was matched to
-- (app/torrent_layout.py). A season pack has one row per episode plus its
-- extras (nfo, subtitles, sample); a single-file torrent has one row. The
-- executor recreates the torrent from these rows: every video must have a
-- local file (otherwise the candidate is "season_pack_partial", confidence
-- 0, never executable), an extra without one is left for the client to
-- download after the recheck. media_file_id for direction='media_to_torrent',
-- seed_file_id for 'torrent_to_client', both null = no local file.
CREATE TABLE IF NOT EXISTS candidate_file (
    id              INTEGER PRIMARY KEY,
    candidate_id    INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    torrent_path    TEXT NOT NULL,          -- inside the torrent, relative to candidate.folder
    size_bytes      INTEGER,
    is_video        BOOLEAN NOT NULL,
    media_file_id   INTEGER REFERENCES media_file(id) ON DELETE SET NULL,
    seed_file_id    INTEGER REFERENCES seed_file(id) ON DELETE SET NULL,
    size_match      BOOLEAN,
    mediainfo_match BOOLEAN,
    piece_verified  BOOLEAN
);

CREATE TABLE IF NOT EXISTS match_review (
    id              INTEGER PRIMARY KEY,
    candidate_id    INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    media_file_id   INTEGER REFERENCES media_file(id) ON DELETE CASCADE,
        -- valorizzato per direction='media_to_torrent': QUALE file fisico orfano
        -- questa decisione riguarda. Assente in ratio-guardian (dove media_item
        -- ERA il file fisico, 1:1) — qui serve perché un media_item può avere più
        -- media_file (versioni/qualità diverse), quindi candidate.media_item_id da
        -- solo non basta a sapere quale file fisico collegare all'approvazione.
    seed_file_id    INTEGER REFERENCES seed_file(id) ON DELETE CASCADE,
        -- valorizzato per direction='torrent_to_client': QUALE seed_file orfano
        -- (non tracciato da alcun client) ha innescato questa ricerca.
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','auto_approved')),
    decided_by      TEXT,                   -- "system" | username
    decided_at      TIMESTAMP,
    verify_status   TEXT,                   -- full piece check before executing: verifying|passed|failed
                                            -- (app/review.py::request_approval). Additive, nullable.
    verify_detail   TEXT,                   -- outcome of that check, shown in the queue
    verify_check_id TEXT                    -- in-memory check id (app/full_check.py), for progress
);

-- One row per (tracker, orphan file) already searched on that tracker, so a
-- run doesn't search the same unchanged orphan again on every run
-- (app/matching.py). Exactly one of media_file_id / seed_file_id is set, same
-- split as match_review: media_file_id for direction='media_to_torrent',
-- seed_file_id for 'torrent_to_client'. A file is searched again only when
-- the row is older than the rematch_interval_days setting, or when what the
-- search depends on changed (size_bytes, tmdb_id) — otherwise the candidates
-- and review already persisted from the last attempt stay as they are.
-- NULLs never collide in a SQLite UNIQUE, so the two UNIQUEs below don't
-- interfere with each other.
CREATE TABLE IF NOT EXISTS match_attempt (
    id              INTEGER PRIMARY KEY,
    tracker_id      INTEGER NOT NULL REFERENCES tracker(id) ON DELETE CASCADE,
    media_file_id   INTEGER REFERENCES media_file(id) ON DELETE CASCADE,
    seed_file_id    INTEGER REFERENCES seed_file(id) ON DELETE CASCADE,
    size_bytes      INTEGER NOT NULL,
    tmdb_id         INTEGER NOT NULL,
    attempted_at    TIMESTAMP NOT NULL,
    CHECK ((media_file_id IS NULL) <> (seed_file_id IS NULL)),
    UNIQUE(tracker_id, media_file_id),
    UNIQUE(tracker_id, seed_file_id)
);

-- Seeding torrents with no hardlink in the library, and why (app/not_imported.py,
-- "Not imported" view). Recomputed at every reliable scan, read-only.
CREATE TABLE IF NOT EXISTS not_imported_torrent (
    id                         INTEGER PRIMARY KEY,
    client_torrent_id          INTEGER NOT NULL UNIQUE REFERENCES client_torrent(id) ON DELETE CASCADE,
    category                   TEXT NOT NULL,   -- superseded | copy | removed | never_imported | extras_only
    detail                     TEXT,
    matched_by                 TEXT,            -- arr | name | hash
    content_type               TEXT,
    tmdb_id                    INTEGER,
    season_number              INTEGER,
    episode_number             INTEGER,
    main_path                  TEXT,
    replaced_by_media_file_id  INTEGER REFERENCES media_file(id) ON DELETE SET NULL,
    total_bytes                INTEGER NOT NULL,
    video_bytes                INTEGER NOT NULL,
    file_count                 INTEGER NOT NULL,
    excluded                   BOOLEAN,         -- main video (or every file) excluded: hidden by default
    run_id                     INTEGER REFERENCES run_log(id) ON DELETE SET NULL
);

-- Per-file state at the latest snapshot (app/file_changes.py): replaced at
-- every comparison, it's the baseline for "changes since last scan".
CREATE TABLE IF NOT EXISTS file_state_snapshot (
    id              INTEGER PRIMARY KEY,
    side            TEXT NOT NULL,        -- 'media' | 'torrent'
    disk_id         INTEGER NOT NULL,
    relative_path   TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    state           TEXT NOT NULL,
    stopped         BOOLEAN,
    UNIQUE(side, disk_id, relative_path)
);

-- Files added, removed or changing state between a scan and the previous
-- one (Dashboard, "Changes since last scan"). Kept for the last 30 compared scans.
CREATE TABLE IF NOT EXISTS file_change (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES run_log(id) ON DELETE CASCADE,
    side            TEXT NOT NULL,
    disk_id         INTEGER NOT NULL,
    relative_path   TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    change          TEXT NOT NULL,        -- added | removed | state | stopped | resumed
    state           TEXT,
    previous_state  TEXT,
    content_type    TEXT,
    tmdb_id         INTEGER
);

CREATE TABLE IF NOT EXISTS seed_job (
    id                          INTEGER PRIMARY KEY,
    candidate_id                INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    source_media_file_id        INTEGER REFERENCES media_file(id),
        -- set for direction='media_to_torrent': the local file the hardlink is created from
    source_seed_file_id         INTEGER REFERENCES seed_file(id),
        -- set for direction='torrent_to_client': the file already present, to be linked to the client
    result_seed_file_id         INTEGER REFERENCES seed_file(id),
        -- the hardlink created (media_to_torrent) or the confirmed seed_file (torrent_to_client) —
        -- known only once execution succeeds, filled in by whichever scan next picks it up
    result_client_torrent_id    INTEGER REFERENCES client_torrent(id),
        -- known only after the add to the client and the next poll — never at add_torrent time
    info_hash                   TEXT,
        -- known as soon as add_torrent() succeeds (returned by the client adapter) — used by
        -- reconcile_seed_job()/retry_seed_job() to query the client's real status. Missing from
        -- the first draft of this table (found while implementing the executor in Fase 4).
    hardlink_created_at         TIMESTAMP,
    torrent_added_at            TIMESTAMP,
    recheck_status               TEXT CHECK (recheck_status IN ('pending','ok','failed')),
    recheck_skipped              BOOLEAN,   -- client recheck skipped: Nazgarr verified 100% first (opt-in). Additive.
    final_status                 TEXT NOT NULL DEFAULT 'in_progress'
                                 CHECK (final_status IN ('in_progress','seeding','failed','rolled_back')),
    error_message                TEXT,
    expected_missing_bytes       INTEGER,
        -- bytes the client may legitimately still download after the recheck: extras of the
        -- torrent (nfo, subtitles, sample) with no local file, plus the pieces they share with
        -- neighbouring files (app/torrent_layout.py::expected_missing_bytes). Null/0 = the
        -- recheck must reach 100%, as always.
    -- Indicative layout — execution details to be refined in Phase 4 (docs/ROADMAP.md), in
    -- particular how/when result_seed_file_id and result_client_torrent_id get reconciled
    -- with the next scan instead of being written directly by the executor.
    torrent_client_id            INTEGER
        -- the client the torrent was added to: its recheck is checked there, not on "the first client"
);

-- Per-tracker health history (the dashboard's tracker filter, app/tracker_scope.py):
-- the same numbers run_log keeps globally, one row per scope ("configured" or a
-- tracker id) per finished scan. History for a scope starts from the first scan
-- after the scope existed; the global history stays on run_log.
CREATE TABLE IF NOT EXISTS tracker_health_snapshot (
    id                      INTEGER PRIMARY KEY,
    run_id                  INTEGER NOT NULL REFERENCES run_log(id) ON DELETE CASCADE,
    scope                   TEXT NOT NULL,
    health_snapshot         REAL,
    orphan_torrent_bytes    INTEGER,
    ignored_bytes           INTEGER,
    duplicate_wasted_bytes  INTEGER,
    UNIQUE(run_id, scope)
);
CREATE INDEX IF NOT EXISTS idx_tracker_health_snapshot_scope ON tracker_health_snapshot(scope, run_id);

-- ============ UPLOAD (SPEC.md §9) ============

CREATE TABLE IF NOT EXISTS tracker_upload_profile (
    tracker_id              INTEGER PRIMARY KEY REFERENCES tracker(id) ON DELETE CASCADE,
    category_id_map_json    TEXT,           -- {"movie": 1, "tv": 2}, real values to verify per tracker
    type_id_map_json        TEXT,           -- {"REMUX": 20, "WEBDL": 21, ...}
    resolution_id_map_json  TEXT,
    naming_convention       TEXT,           -- legacy single release-name template (before naming_rules_json)
    naming_rules_json       TEXT,           -- release-name rules (app/upload_naming.py): a template per release type
                                            -- + options; copied from the bundled profile with its version
    naming_version          INTEGER,        -- version of the bundled rules copied here (null = custom profile)
    naming_customized       BOOLEAN,        -- the user edited the rules: a new bundled version is only offered
    naming_update_available INTEGER,        -- newer bundled version waiting for the user's ok (null = none)
    description_template    TEXT,           -- Jinja2
    default_anonymous       BOOLEAN NOT NULL DEFAULT 0,
    default_personal_release BOOLEAN NOT NULL DEFAULT 0,
    freeleech_options_json  TEXT,           -- freeleech percentages this tracker lets the user set, e.g. [25, 50, 100];
                                            -- empty/null = no freeleech choice
    default_freeleech       INTEGER,        -- preselected percentage (null/0 = none)
    source_profile_key      TEXT            -- bundled file it was copied from when created (e.g. "itt"),
                                             -- reference only — never re-read at runtime after the copy
);

-- Upload flow v2 (SPEC.md §9 "Upload flow v2"): one job = one source (a file
-- or a folder) towards N trackers. The Phase 6 single-tracker upload_job is
-- dropped by app/db.py::migrate_legacy_upload_job (no data worth keeping).
CREATE TABLE IF NOT EXISTS upload_job (
    id                      INTEGER PRIMARY KEY,
    disk_id                 INTEGER REFERENCES disk(id) ON DELETE SET NULL,
    relative_path           TEXT NOT NULL,   -- as chosen in the browser, relative to the disk root
    source_path             TEXT NOT NULL,   -- absolute path, resolved through app/fs_scope.py
    is_dir                  BOOLEAN NOT NULL DEFAULT 0,
    kind                    TEXT CHECK (kind IN ('movie','episode','season_pack','complete_pack')),
        -- null until identified; season/complete pack only for folders
    status                  TEXT NOT NULL DEFAULT 'identifying'
                            CHECK (status IN ('identifying','awaiting_match','analyzing','awaiting_decision',
                                              'queued','running','done','partial','failed','cancelled')),
        -- awaiting_match / awaiting_decision are the two human gates; the worker
        -- (app/upload_worker.py) moves every other state forward on its own
    stage                   TEXT,            -- current step inside a worker state, for the progress display
    progress_done           INTEGER,
    progress_total          INTEGER,
    queue_position          INTEGER,         -- order among 'queued' jobs, lower first
    content_type            TEXT CHECK (content_type IN ('movie','tv')),
    tmdb_id                 INTEGER,
    imdb_id                 TEXT,
    tvdb_id                 INTEGER,
    mal_id                  INTEGER,
    title                   TEXT,
    year                    INTEGER,
    poster_path             TEXT,            -- TMDB relative path (e.g. "/abc.jpg")
    seasons_json            TEXT,            -- confirmed season numbers, e.g. [2] or [1,2,3]
    episode                 INTEGER,         -- only for kind = 'episode'
    forced_ids_json         TEXT,            -- ids the user forced at creation {"tmdb": ..., "imdb": ...}
    overrides_json          TEXT,            -- "Detected details" / "Advanced" overrides
    layout_json             TEXT,            -- what's inside the source (app/upload_source.py): videos, seasons, episodes
    candidates_json         TEXT,            -- identification candidates shown at the first gate
    analysis_json           TEXT,            -- client / Radarr-Sonarr findings
    mediainfo_text          TEXT,
    screenshot_urls_json    TEXT,
    anime                   BOOLEAN,         -- from TMDB at the first gate (genre Animation + original
                                             -- language ja): picks the client's anime category
    error_message           TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at             TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upload_target (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES upload_job(id) ON DELETE CASCADE,
    tracker_id              INTEGER NOT NULL REFERENCES tracker(id) ON DELETE CASCADE,
    torrent_client_id       INTEGER REFERENCES torrent_client(id) ON DELETE SET NULL,
        -- where the torrent will seed: the tracker's client by default
    status                  TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','checking','awaiting_decision','approved','verifying',
                                              'preparing','uploading','seeding','done','skipped','failed')),
    suggested_action        TEXT CHECK (suggested_action IN ('upload','reseed','skip')),
    action                  TEXT CHECK (action IN ('upload','reseed','skip')),  -- the user's choice at gate 2
    dupes_json              TEXT,            -- dupe-check results with their verdict (app/upload_dupes.py)
    reseed_torrent_id       TEXT,            -- the tracker torrent a passed full hash check matched: reseed it
    proposed_name           TEXT,
    approved_name           TEXT,
    flags_json              TEXT,            -- {"anonymous": ..., "personal_release": ..., "internal": ..., "stream": ...}
    category_id             INTEGER,
    type_id                 INTEGER,
    resolution_id           INTEGER,
    description_rendered    TEXT,
    torrent_path            TEXT,
    info_hash               TEXT,
    torrent_id_remote       TEXT,
    client_category         TEXT,            -- category / tags in the client, approved at gate 2
    client_tags             TEXT,            -- (defaults from the client, torrent_client.category_* / tags_*)
    error_message           TEXT,
    finished_at             TIMESTAMP,
    UNIQUE(job_id, tracker_id)
);

-- Append-only log of every step of a job, for live monitoring and history.
-- code + params_json instead of a sentence, so the frontend translates it.
CREATE TABLE IF NOT EXISTS upload_event (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES upload_job(id) ON DELETE CASCADE,
    target_id               INTEGER REFERENCES upload_target(id) ON DELETE CASCADE,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level                   TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info','warning','error')),
    code                    TEXT NOT NULL,
    params_json             TEXT
);

-- Indexes on the most-queried foreign keys (SQLite doesn't index them on
-- its own): without these, dashboard counts (join/exists on
-- candidate/seed_job) can slow down considerably as those tables grow,
-- especially alongside a run's concurrent writes.
CREATE INDEX IF NOT EXISTS idx_candidate_media_item_id ON candidate(media_item_id);
CREATE INDEX IF NOT EXISTS idx_candidate_tracker_id ON candidate(tracker_id);
CREATE INDEX IF NOT EXISTS idx_candidate_file_candidate_id ON candidate_file(candidate_id);
CREATE INDEX IF NOT EXISTS idx_match_review_candidate_id ON match_review(candidate_id);
CREATE INDEX IF NOT EXISTS idx_match_review_media_file_id ON match_review(media_file_id);
CREATE INDEX IF NOT EXISTS idx_match_review_seed_file_id ON match_review(seed_file_id);
CREATE INDEX IF NOT EXISTS idx_seed_job_candidate_id ON seed_job(candidate_id);
CREATE INDEX IF NOT EXISTS idx_seed_job_source_media_file_id ON seed_job(source_media_file_id);
CREATE INDEX IF NOT EXISTS idx_seed_job_source_seed_file_id ON seed_job(source_seed_file_id);
CREATE INDEX IF NOT EXISTS idx_upload_job_status ON upload_job(status);
CREATE INDEX IF NOT EXISTS idx_upload_target_job_id ON upload_target(job_id);
CREATE INDEX IF NOT EXISTS idx_upload_event_job_id ON upload_event(job_id);
CREATE INDEX IF NOT EXISTS idx_file_change_run_id ON file_change(run_id);
