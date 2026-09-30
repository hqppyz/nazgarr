"""Modelli SQLAlchemy che mappano le tabelle create da docs/schema.sql.

docs/schema.sql resta la fonte di verità per la DDL (vedi app/db.py). Questi
modelli non generano schema (niente Base.metadata.create_all): servono solo
per l'accesso ORM, e vanno tenuti manualmente in sync con schema.sql quando
quest'ultimo cambia.

Fase 0 (docs/ROADMAP.md): solo le tabelle di CONFIGURAZIONE. Fase 1
aggiunge run_log e le tabelle FISICO (media_file/seed_file). Fase 2
aggiunge CLIENT TORRENT (client_torrent/client_torrent_file). Fase 3
aggiunge media_item (identità logica). Fase 4 aggiunge DOMINIO (candidate/
match_review/seed_job). Fase 6 aggiunge UPLOAD (tracker_upload_profile/
upload_job) — esistevano come tabelle vuote in schema.sql fin dalla Fase
0, mappate in ORM solo ora che c'è codice che le usa davvero.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import String, TypeDecorator

from app import crypto


class Base(DeclarativeBase):
    pass


class EncryptedString(TypeDecorator):
    """Cifra/decifra trasparentemente i segreti salvati a riposo (api_token,
    password) — vedi app/crypto.py e docs/schema.sql."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return crypto.encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return crypto.decrypt(value)


# ============ CONFIGURAZIONE ============


class Disk(Base):
    __tablename__ = "disk"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    root_path: Mapped[str] = mapped_column(nullable=False, unique=True)
    st_dev: Mapped[int | None]
    media_rel_path: Mapped[str | None]
    torrents_rel_path: Mapped[str | None]
    new_torrent_rel_path: Mapped[str | None]
    upload_rel_path: Mapped[str | None]
    media_scan_id: Mapped[int | None]
    seed_scan_id: Mapped[int | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("CURRENT_TIMESTAMP"))

    @property
    def effective_new_torrent_rel_path(self) -> str | None:
        """Cartella dove va creato un NUOVO hardlink (e il save_path da
        comunicare al client) se configurata, altrimenti torrents_rel_path
        (vedi docs/SPEC.md, ereditato da ratio-guardian §3). Riguarda SOLO
        dove posizionare cose nuove: la ricerca "già in seeding" resta
        sempre sull'intero torrents_rel_path."""
        return self.new_torrent_rel_path or self.torrents_rel_path

    @property
    def effective_upload_rel_path(self) -> str | None:
        """Dove il flusso di upload crea gli hardlink e fa seedare i torrent
        (docs/SPEC.md §9): la cartella per gli upload se configurata,
        altrimenti torrents_rel_path (decisione dell'utente, 2026-09-30)."""
        return self.upload_rel_path or self.torrents_rel_path


class Tracker(Base):
    __tablename__ = "tracker"
    __table_args__ = (
        CheckConstraint("history_mode IN ('api','scrape','unsupported')", name="ck_tracker_history_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    adapter_type: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False)
    api_token: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    announce_url: Mapped[str | None]
    # Chiave dei link di download UNIT3D, vedi docs/schema.sql: appresa in
    # automatico dalle risposte dell'API, impostabile a mano ma non dovrebbe
    # servire. Mai restituita dall'API di configurazione.
    rss_key: Mapped[str | None] = mapped_column(EncryptedString)
    history_mode: Mapped[str] = mapped_column(nullable=False, server_default=text("'unsupported'"))
    history_session_cookie: Mapped[str | None]
    rate_limit_per_min: Mapped[int | None] = mapped_column(server_default=text("30"))
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    # Client in cui aggiungere i torrent di questo tracker (es. l'istanza per
    # i tracker privati); None = il primo client abilitato.
    torrent_client_id: Mapped[int | None]
    language: Mapped[str | None]
    adapter_config_json: Mapped[str | None] = mapped_column(EncryptedString)


class TorrentClient(Base):
    __tablename__ = "torrent_client"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    adapter_type: Mapped[str] = mapped_column(nullable=False)  # qbittorrent | deluge | transmission | rutorrent | qui
    base_url: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[str | None]
    password: Mapped[str | None] = mapped_column(EncryptedString)
    # Solo per adapter_type="qui": la sua X-API-Key (un'unica chiave copre
    # tutte le istanze qBittorrent gestite da un deployment qui, docs/SPEC.md
    # sezione 15) e l'id dell'istanza specifica a cui questa riga è ancorata —
    # qui aggrega più istanze dietro un solo host, ma add_torrent deve sapere
    # esattamente su quale scrivere, quindi un TorrentClient per istanza.
    api_token: Mapped[str | None] = mapped_column(EncryptedString)
    qui_instance_id: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    category_movie: Mapped[str | None]
    category_tv: Mapped[str | None]
    category_anime: Mapped[str | None]
    tags_upload: Mapped[str | None]
    tags_reseed: Mapped[str | None]
    adapter_config_json: Mapped[str | None] = mapped_column(EncryptedString)


class DiskTorrentClient(Base):
    """Tabella ponte: un disco può avere più client torrent abilitati
    contemporaneamente (docs/SPEC.md §5). torrent_client_root_path vive QUI,
    non su Disk: client diversi associati allo stesso disco possono vederlo
    montato a path diversi nei rispettivi container — un solo campo su Disk
    non potrebbe rappresentarlo per più di un client alla volta.
    Association object (non un plain secondary=) proprio per poter portare
    questa colonna: niente collezioni di convenienza disk.torrent_clients/
    torrent_client.disks, le query vanno dirette su questa tabella."""

    __tablename__ = "disk_torrent_client"

    disk_id: Mapped[int] = mapped_column(ForeignKey("disk.id", ondelete="CASCADE"), primary_key=True)
    torrent_client_id: Mapped[int] = mapped_column(
        ForeignKey("torrent_client.id", ondelete="CASCADE"), primary_key=True
    )
    torrent_client_root_path: Mapped[str | None]

    disk: Mapped["Disk"] = relationship()
    torrent_client: Mapped["TorrentClient"] = relationship()


class RadarrInstance(Base):
    """Adapter di content-identification opzionale, mai richiesto dal
    resolver (docs/SPEC.md SS2/SS6) — nessun adapter concreto lo consuma
    ancora, questa è solo la tabella multi-istanza preparata in anticipo
    (stesso pattern di Tracker/TorrentClient: multi-istanza da subito,
    non un flat key/value singolo su app_settings)."""

    __tablename__ = "radarr_instance"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False)
    api_key: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    # Colonne aggiunte dopo la creazione della tabella: nullable e senza
    # server_default, perché migrate_schema() (app/db.py) sa solo fare
    # ALTER TABLE ADD COLUMN additivi su colonne nullable — il default
    # "vero" (0 / 15) si applica lato Python in from_model(), stesso
    # trattamento di Disk.new_torrent_rel_path.
    priority: Mapped[int | None]  # più alto = interrogato prima, quando esisterà un resolver che li consuma
    timeout_seconds: Mapped[int | None]
    basic_auth_username: Mapped[str | None]  # per Radarr dietro un reverse proxy con HTTP basic auth
    basic_auth_password: Mapped[str | None] = mapped_column(EncryptedString)


class SonarrInstance(Base):
    """Vedi RadarrInstance — stesso ruolo e stesso stato (non ancora
    consumato da nessun adapter), per Sonarr."""

    __tablename__ = "sonarr_instance"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False)
    api_key: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    priority: Mapped[int | None]
    timeout_seconds: Mapped[int | None]
    basic_auth_username: Mapped[str | None]
    basic_auth_password: Mapped[str | None] = mapped_column(EncryptedString)


class Webhook(Base):
    """Un webhook (app/webhooks.py): POST firmati per gli eventi scelti."""

    __tablename__ = "webhook"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(nullable=False)
    secret: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    events_json: Mapped[str] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class Event(Base):
    """Un evento da consegnare (app/events.py), con le sue consegne."""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    payload_json: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    deliveries: Mapped[list["EventDelivery"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True,
    )


class EventDelivery(Base):
    __tablename__ = "event_delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id", ondelete="CASCADE"), nullable=False)
    webhook_id: Mapped[int | None] = mapped_column(ForeignKey("webhook.id", ondelete="CASCADE"))
    notification_type: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None]
    last_status_code: Mapped[int | None]
    last_error: Mapped[str | None]
    delivered_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    event: Mapped["Event"] = relationship(back_populates="deliveries")
    webhook: Mapped["Webhook | None"] = relationship()


class ApiKey(Base):
    """Una API key (app/api_keys.py): solo l'hash, la chiave si vede una volta."""

    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    prefix: Mapped[str] = mapped_column(nullable=False)
    key_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    level: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class AdapterConfig(Base):
    """Configurazione di un adapter di un plugin senza una riga sua (host
    di immagini, resolver, notifiche): app/plugins/config.py."""

    __tablename__ = "adapter_config"

    kind: Mapped[str] = mapped_column(primary_key=True)
    adapter_type: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("1"))
    config_json: Mapped[str | None] = mapped_column(EncryptedString)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(nullable=False)


# ============ RUN LOG ============


class RunLog(Base):
    __tablename__ = "run_log"
    __table_args__ = (
        CheckConstraint("run_type IN ('scheduled','manual','bulk_import')", name="ck_run_log_run_type"),
        CheckConstraint(
            "current_phase IS NULL OR current_phase IN "
            "('scanning','resolving','indexing','matching','executing','reconciling')",
            name="ck_run_log_current_phase",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]
    current_phase: Mapped[str | None]
    phase_total: Mapped[int | None]
    phase_done: Mapped[int | None]
    phase_detail: Mapped[str | None]
    phases_json: Mapped[str | None]
    cancel_requested_at: Mapped[datetime | None]
    items_total: Mapped[int | None]
    items_scanned: Mapped[int] = mapped_column(server_default=text("0"))
    matches_found: Mapped[int] = mapped_column(server_default=text("0"))
    auto_executed: Mapped[int] = mapped_column(server_default=text("0"))
    pending_review: Mapped[int] = mapped_column(server_default=text("0"))
    orphan_torrent_count: Mapped[int] = mapped_column(server_default=text("0"))
    ignored_count: Mapped[int] = mapped_column(server_default=text("0"))
    health_snapshot: Mapped[float | None]
    # Dimensioni a fine run, per l'andamento delle card della dashboard.
    orphan_torrent_bytes: Mapped[int | None]
    ignored_bytes: Mapped[int | None]
    duplicate_wasted_bytes: Mapped[int | None]
    errors: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None]
    errors_json: Mapped[str | None]  # JSON: ogni errore della run, in ordine (app/pipeline.py::_note_error)
    # Fotografia dello stato dei file scattata a fine run (app/file_changes.py).
    snapshot_saved: Mapped[bool | None]


# ============ FISICO (scritto SOLO dal processo di scan, app/scanner.py) ============


class TrackerHealthSnapshot(Base):
    """Vedi docs/schema.sql: lo storico della dashboard per un filtro per
    tracker (app/tracker_scope.py), una riga per scansione."""

    __tablename__ = "tracker_health_snapshot"
    __table_args__ = (UniqueConstraint("run_id", "scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run_log.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(nullable=False)
    health_snapshot: Mapped[float | None]
    orphan_torrent_bytes: Mapped[int | None]
    ignored_bytes: Mapped[int | None]
    duplicate_wasted_bytes: Mapped[int | None]

    run: Mapped["RunLog"] = relationship()


class MediaItem(Base):
    """Identità logica risolta — separata dal file fisico (MediaFile)
    perché la vista a griglia (Fase 4) deve raggruppare più file fisici
    (episodi di una stagione, più versioni) sotto un solo poster."""

    __tablename__ = "media_item"
    __table_args__ = (CheckConstraint("content_type IN ('movie','tv')", name="ck_media_item_content_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(nullable=False)
    tmdb_id: Mapped[int] = mapped_column(nullable=False)
    season_number: Mapped[int | None]
    episode_number: Mapped[int | None]
    tmdb_poster_path: Mapped[str | None]
    title: Mapped[str | None]
    year: Mapped[int | None]
    imdb_id: Mapped[str | None]
    # Chi gestisce questo contenuto (Radarr/Sonarr), per il link diretto
    # nella scheda di dettaglio: tipo, istanza e titleSlug della sua pagina.
    arr_kind: Mapped[str | None]
    arr_instance_id: Mapped[int | None]
    arr_slug: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("CURRENT_TIMESTAMP"))


class TmdbSearchCache(Base):
    """Vedi docs/schema.sql: cache persistente delle ricerche TMDB, chiave =
    ciò che il resolver cerca (titolo/anno guessit), non il file — molti
    media_file condividono la stessa chiave (episodi di una stessa serie)."""

    __tablename__ = "tmdb_search_cache"
    __table_args__ = (
        CheckConstraint("content_type IN ('movie','tv')", name="ck_tmdb_search_cache_content_type"),
        UniqueConstraint("content_type", "query", "year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(nullable=False)
    query: Mapped[str] = mapped_column(nullable=False)
    year: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    tmdb_id: Mapped[int] = mapped_column(nullable=False)
    poster_path: Mapped[str | None]
    result_title: Mapped[str | None]
    result_year: Mapped[int | None]
    resolved_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class MediaFile(Base):
    __tablename__ = "media_file"
    __table_args__ = (UniqueConstraint("disk_id", "relative_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("disk.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    st_dev: Mapped[int] = mapped_column(nullable=False)
    inode: Mapped[int] = mapped_column(nullable=False)
    nlink: Mapped[int | None]
    # Fast partial-content hash (app/duplicates.py) — per trovare copie non
    # intenzionali dello stesso contenuto su inode diversi, mai per il
    # matching col tracker (quello resta mediainfo_unique_id sotto).
    content_hash: Mapped[str | None]
    media_item_id: Mapped[int | None] = mapped_column(ForeignKey("media_item.id", ondelete="SET NULL"))
    resolver_source: Mapped[str | None]
    mediainfo_unique_id: Mapped[str | None]
    last_scan_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)

    disk: Mapped["Disk"] = relationship()
    media_item: Mapped["MediaItem | None"] = relationship()


class SeedFile(Base):
    __tablename__ = "seed_file"
    __table_args__ = (UniqueConstraint("disk_id", "relative_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("disk.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    st_dev: Mapped[int] = mapped_column(nullable=False)
    inode: Mapped[int] = mapped_column(nullable=False)
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id", ondelete="SET NULL"))
    last_scan_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)

    media_file: Mapped["MediaFile | None"] = relationship()
    disk: Mapped["Disk"] = relationship()


# ============ CLIENT TORRENT (multi-istanza, scritto SOLO da app/torrent_indexer.py — Fase 2) ============


class ClientTorrent(Base):
    __tablename__ = "client_torrent"
    __table_args__ = (UniqueConstraint("torrent_client_id", "info_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    torrent_client_id: Mapped[int] = mapped_column(ForeignKey("torrent_client.id", ondelete="CASCADE"), nullable=False)
    info_hash: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    save_path: Mapped[str] = mapped_column(nullable=False)
    category: Mapped[str | None]
    tracker_url: Mapped[str | None]
    state: Mapped[str] = mapped_column(nullable=False)  # valore nativo del client, non normalizzato qui
    added_at: Mapped[datetime | None]
    ratio: Mapped[float | None]
    seeding_time_seconds: Mapped[int | None]
    last_polled_at: Mapped[datetime] = mapped_column(nullable=False)


class ClientTorrentFile(Base):
    __tablename__ = "client_torrent_file"
    __table_args__ = (UniqueConstraint("client_torrent_id", "path_in_torrent"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_torrent_id: Mapped[int] = mapped_column(
        ForeignKey("client_torrent.id", ondelete="CASCADE"), nullable=False
    )
    path_in_torrent: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id", ondelete="SET NULL"))
    last_scan_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"), nullable=False)


# ============ DOMINIO — matching e reseeding (Fase 4, docs/SPEC.md sezione 6-8) ============


class Candidate(Base):
    __tablename__ = "candidate"
    __table_args__ = (
        CheckConstraint("source IN ('history','catalog_search')", name="ck_candidate_source"),
        CheckConstraint(
            "direction IN ('media_to_torrent','torrent_to_client')", name="ck_candidate_direction"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id", ondelete="CASCADE"), nullable=False)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("tracker.id"), nullable=False)
    torrent_id_remote: Mapped[str] = mapped_column(nullable=False)
    info_hash: Mapped[str | None]
    name: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    file_list_json: Mapped[str | None]
    folder: Mapped[str | None]
    download_link: Mapped[str | None]
    source: Mapped[str] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(nullable=False)
    size_match: Mapped[bool | None]
    mediainfo_match: Mapped[bool | None]
    piece_verified: Mapped[bool | None]
    piece_boundary_count: Mapped[int | None]
    confidence: Mapped[float] = mapped_column(nullable=False)
    ambiguity_reason: Mapped[str | None]
    piece_length: Mapped[int | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("CURRENT_TIMESTAMP"))

    media_item: Mapped["MediaItem"] = relationship()
    tracker: Mapped["Tracker"] = relationship()
    files: Mapped[list["CandidateFile"]] = relationship(
        order_by="CandidateFile.id", cascade="all, delete-orphan", back_populates="candidate"
    )


class CandidateFile(Base):
    """Vedi docs/schema.sql: un file del torrent di un candidato e il file
    locale a cui è stato abbinato (app/torrent_layout.py)."""

    __tablename__ = "candidate_file"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False)
    torrent_path: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int | None]
    is_video: Mapped[bool] = mapped_column(nullable=False)
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id", ondelete="SET NULL"))
    seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id", ondelete="SET NULL"))
    size_match: Mapped[bool | None]
    mediainfo_match: Mapped[bool | None]
    piece_verified: Mapped[bool | None]

    candidate: Mapped["Candidate"] = relationship(back_populates="files")
    media_file: Mapped["MediaFile | None"] = relationship()
    seed_file: Mapped["SeedFile | None"] = relationship()


class TrackerUploadProfile(Base):
    """1:1 con tracker (PK = FK, non un id proprio) — presenza della riga =
    quel tracker fa upload. Copiata da un profilo bundlato (app/tracker_profiles/*.yaml)
    alla creazione del Tracker, poi mai più riletta dal file (docs/SPEC.md §9)."""

    __tablename__ = "tracker_upload_profile"

    tracker_id: Mapped[int] = mapped_column(ForeignKey("tracker.id", ondelete="CASCADE"), primary_key=True)
    category_id_map_json: Mapped[str | None]
    type_id_map_json: Mapped[str | None]
    resolution_id_map_json: Mapped[str | None]
    naming_convention: Mapped[str | None]
    naming_rules_json: Mapped[str | None]
    naming_version: Mapped[int | None]
    naming_customized: Mapped[bool | None]
    naming_update_available: Mapped[int | None]
    description_template: Mapped[str | None]
    default_anonymous: Mapped[bool] = mapped_column(nullable=False, server_default=text("0"))
    default_personal_release: Mapped[bool] = mapped_column(nullable=False, server_default=text("0"))
    freeleech_options_json: Mapped[str | None]
    default_freeleech: Mapped[int | None]
    source_profile_key: Mapped[str | None]

    tracker: Mapped["Tracker"] = relationship()


UPLOAD_JOB_STATUSES = (
    "identifying", "awaiting_match", "analyzing", "awaiting_decision",
    "queued", "running", "done", "partial", "failed", "cancelled",
)
UPLOAD_TARGET_STATUSES = (
    "pending", "checking", "awaiting_decision", "approved", "verifying",
    "preparing", "uploading", "seeding", "done", "skipped", "failed",
)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


class UploadJob(Base):
    """Vedi docs/schema.sql e docs/SPEC.md §9 "Upload flow v2": la sorgente
    (file o cartella) di un upload verso N tracker, uno per UploadTarget."""

    __tablename__ = "upload_job"
    __table_args__ = (
        CheckConstraint(_in_check("status", UPLOAD_JOB_STATUSES), name="ck_upload_job_status"),
        CheckConstraint(
            "kind IN ('movie','episode','season_pack','complete_pack')", name="ck_upload_job_kind"
        ),
        CheckConstraint("content_type IN ('movie','tv')", name="ck_upload_job_content_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int | None] = mapped_column(ForeignKey("disk.id", ondelete="SET NULL"))
    relative_path: Mapped[str] = mapped_column(nullable=False)
    source_path: Mapped[str] = mapped_column(nullable=False)
    is_dir: Mapped[bool] = mapped_column(nullable=False, server_default=text("0"))
    kind: Mapped[str | None]
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'identifying'"))
    stage: Mapped[str | None]
    progress_done: Mapped[int | None]
    progress_total: Mapped[int | None]
    queue_position: Mapped[int | None]
    content_type: Mapped[str | None]
    tmdb_id: Mapped[int | None]
    imdb_id: Mapped[str | None]
    tvdb_id: Mapped[int | None]
    mal_id: Mapped[int | None]
    title: Mapped[str | None]
    year: Mapped[int | None]
    poster_path: Mapped[str | None]
    seasons_json: Mapped[str | None]
    episode: Mapped[int | None]
    forced_ids_json: Mapped[str | None]
    overrides_json: Mapped[str | None]
    layout_json: Mapped[str | None]
    candidates_json: Mapped[str | None]
    analysis_json: Mapped[str | None]
    mediainfo_text: Mapped[str | None]
    screenshot_urls_json: Mapped[str | None]
    anime: Mapped[bool | None]
    error_message: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None]

    disk: Mapped["Disk | None"] = relationship()
    targets: Mapped[list["UploadTarget"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="UploadTarget.id"
    )
    events: Mapped[list["UploadEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="UploadEvent.id"
    )


class UploadTarget(Base):
    """Un tracker di un UploadJob: azione scelta (upload/reseed/skip), nome,
    flag, dupe-check ed esito, indipendenti da quelli degli altri tracker."""

    __tablename__ = "upload_target"
    __table_args__ = (
        CheckConstraint(_in_check("status", UPLOAD_TARGET_STATUSES), name="ck_upload_target_status"),
        CheckConstraint("suggested_action IN ('upload','reseed','skip')", name="ck_upload_target_suggested"),
        CheckConstraint("action IN ('upload','reseed','skip')", name="ck_upload_target_action"),
        UniqueConstraint("job_id", "tracker_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("upload_job.id", ondelete="CASCADE"), nullable=False)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("tracker.id", ondelete="CASCADE"), nullable=False)
    torrent_client_id: Mapped[int | None] = mapped_column(ForeignKey("torrent_client.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'pending'"))
    suggested_action: Mapped[str | None]
    action: Mapped[str | None]
    dupes_json: Mapped[str | None]
    reseed_torrent_id: Mapped[str | None]
    proposed_name: Mapped[str | None]
    approved_name: Mapped[str | None]
    flags_json: Mapped[str | None]
    category_id: Mapped[int | None]
    type_id: Mapped[int | None]
    resolution_id: Mapped[int | None]
    description_rendered: Mapped[str | None]
    torrent_path: Mapped[str | None]
    info_hash: Mapped[str | None]
    torrent_id_remote: Mapped[str | None]
    client_category: Mapped[str | None]
    client_tags: Mapped[str | None]
    error_message: Mapped[str | None]
    finished_at: Mapped[datetime | None]

    job: Mapped["UploadJob"] = relationship(back_populates="targets")
    tracker: Mapped["Tracker"] = relationship()
    torrent_client: Mapped["TorrentClient | None"] = relationship()


class UploadEvent(Base):
    """Registro append-only dei passi di un UploadJob: code + params, mai una
    frase, così il frontend lo traduce (stesso principio dei CodedError)."""

    __tablename__ = "upload_event"
    __table_args__ = (CheckConstraint("level IN ('info','warning','error')", name="ck_upload_event_level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("upload_job.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("upload_target.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    level: Mapped[str] = mapped_column(nullable=False, server_default=text("'info'"))
    code: Mapped[str] = mapped_column(nullable=False)
    params_json: Mapped[str | None]

    job: Mapped["UploadJob"] = relationship(back_populates="events")


class MatchReview(Base):
    __tablename__ = "match_review"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','auto_approved')", name="ck_match_review_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False)
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id", ondelete="CASCADE"))
    seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'pending'"))
    decided_by: Mapped[str | None]
    decided_at: Mapped[datetime | None]
    # Controllo completo dei piece prima di eseguire (app/review.py::request_approval):
    # verifying | passed | failed, NULL se mai chiesto. La review resta in coda
    # (status invariato) finché il controllo non passa.
    verify_status: Mapped[str | None]
    verify_detail: Mapped[str | None]
    verify_check_id: Mapped[str | None]  # id del controllo in memoria (app/full_check.py), per l'avanzamento

    candidate: Mapped["Candidate"] = relationship()
    media_file: Mapped["MediaFile | None"] = relationship()
    seed_file: Mapped["SeedFile | None"] = relationship()


class NotImportedTorrent(Base):
    """Vedi docs/schema.sql: un torrent in seed senza alcun hardlink in
    libreria, con il perché (app/not_imported.py). Ricalcolata a ogni
    scansione affidabile; sola lettura."""

    __tablename__ = "not_imported_torrent"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_torrent_id: Mapped[int] = mapped_column(
        ForeignKey("client_torrent.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    category: Mapped[str] = mapped_column(nullable=False)  # superseded | copy | removed | never_imported | extras_only
    detail: Mapped[str | None]
    matched_by: Mapped[str | None]  # arr | name | hash: come si è arrivati alla categoria
    content_type: Mapped[str | None]
    tmdb_id: Mapped[int | None]
    season_number: Mapped[int | None]
    episode_number: Mapped[int | None]
    main_path: Mapped[str | None]  # il video principale del torrent (percorso nel torrent)
    replaced_by_media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id", ondelete="SET NULL"))
    total_bytes: Mapped[int] = mapped_column(nullable=False)
    video_bytes: Mapped[int] = mapped_column(nullable=False)
    file_count: Mapped[int] = mapped_column(nullable=False)
    # Video principale (o, senza video, ogni file) escluso da Configuration >
    # Exclusions: nascosto di default e fuori dai conteggi, come nel resto.
    excluded: Mapped[bool | None]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run_log.id", ondelete="SET NULL"))

    client_torrent: Mapped["ClientTorrent"] = relationship()
    replaced_by: Mapped["MediaFile | None"] = relationship()


class FileStateSnapshot(Base):
    """Vedi docs/schema.sql: stato di ogni file all'ultima fotografia
    (app/file_changes.py), base del confronto della scansione successiva."""

    __tablename__ = "file_state_snapshot"
    __table_args__ = (UniqueConstraint("side", "disk_id", "relative_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    side: Mapped[str] = mapped_column(nullable=False)  # "media" | "torrent"
    disk_id: Mapped[int] = mapped_column(nullable=False)
    relative_path: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(nullable=False)
    stopped: Mapped[bool | None]


class FileChange(Base):
    """Vedi docs/schema.sql: un file nuovo, sparito o cambiato di stato fra
    una scansione e la precedente (app/file_changes.py)."""

    __tablename__ = "file_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run_log.id", ondelete="CASCADE"), nullable=False)
    side: Mapped[str] = mapped_column(nullable=False)
    disk_id: Mapped[int] = mapped_column(nullable=False)
    relative_path: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    change: Mapped[str] = mapped_column(nullable=False)  # added | removed | state | stopped | resumed
    state: Mapped[str | None]  # stato dopo (None se rimosso)
    previous_state: Mapped[str | None]  # stato prima (None se nuovo)
    content_type: Mapped[str | None]  # per aprire la scheda di dettaglio
    tmdb_id: Mapped[int | None]


class MatchAttempt(Base):
    """Vedi docs/schema.sql: ultima ricerca di un file orfano su un tracker,
    per non ripeterla a ogni run finché il file (size, identità) non cambia
    o non passa rematch_interval_days."""

    __tablename__ = "match_attempt"
    __table_args__ = (
        CheckConstraint("(media_file_id IS NULL) <> (seed_file_id IS NULL)", name="ck_match_attempt_one_file"),
        UniqueConstraint("tracker_id", "media_file_id"),
        UniqueConstraint("tracker_id", "seed_file_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("tracker.id", ondelete="CASCADE"), nullable=False)
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id", ondelete="CASCADE"))
    seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id", ondelete="CASCADE"))
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    tmdb_id: Mapped[int] = mapped_column(nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(nullable=False)


class SeedJob(Base):
    __tablename__ = "seed_job"
    __table_args__ = (
        CheckConstraint(
            "recheck_status IS NULL OR recheck_status IN ('pending','ok','failed')",
            name="ck_seed_job_recheck_status",
        ),
        CheckConstraint(
            "final_status IN ('in_progress','seeding','failed','rolled_back')", name="ck_seed_job_final_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False)
    source_media_file_id: Mapped[int | None] = mapped_column(ForeignKey("media_file.id"))
    source_seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id"))
    result_seed_file_id: Mapped[int | None] = mapped_column(ForeignKey("seed_file.id"))
    result_client_torrent_id: Mapped[int | None] = mapped_column(ForeignKey("client_torrent.id"))
    info_hash: Mapped[str | None]
    hardlink_created_at: Mapped[datetime | None]
    torrent_added_at: Mapped[datetime | None]
    recheck_status: Mapped[str | None]
    # Recheck del client saltato perché Nazgarr aveva appena verificato il 100%
    # (opzione skip_client_recheck_when_verified, app/review.py).
    recheck_skipped: Mapped[bool | None]
    final_status: Mapped[str] = mapped_column(nullable=False, server_default=text("'in_progress'"))
    error_message: Mapped[str | None]
    expected_missing_bytes: Mapped[int | None]
    torrent_client_id: Mapped[int | None]  # dove è stato aggiunto il torrent (e dove se ne controlla il recheck)

    candidate: Mapped["Candidate"] = relationship()
