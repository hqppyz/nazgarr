"""Profili tracker per l'upload: file bundlati come seed data versionata
nel repo (docs/SPEC.md §9), copiati nella riga DB (tracker_upload_profile)
alla creazione — mai più riletti dal file dopo la copia, così un
aggiornamento dell'app può correggere/aggiungere profili bundlati senza
toccare l'istanza già configurata di un utente esistente.

Unica eccezione, le regole di naming (decisione dell'utente, 2026-09-30):
hanno una versione, e quando un tracker cambia le sue regole il codice può
aggiornarle. All'avvio (sync_naming_rules) una versione bundlata più alta
si applica da sola se l'utente non ha modificato le regole, altrimenti gli
viene offerta (naming_update_available); con "force: true" si applica
sempre. Categoria, tipo e risoluzione non si toccano mai."""

import json
import logging
import os
from urllib.parse import urlsplit

import yaml
from sqlalchemy.orm import Session

from nazgarr.core.errors import CodedError
from nazgarr.core.models import Tracker, TrackerUploadProfile

logger = logging.getLogger(__name__)

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "tracker_profiles")


class ProfileNotFoundError(CodedError):
    pass


def list_bundled_profiles() -> list[dict]:
    if not os.path.isdir(PROFILES_DIR):
        return []
    profiles = []
    for filename in sorted(os.listdir(PROFILES_DIR)):
        if not filename.endswith(".yaml"):
            continue
        with open(os.path.join(PROFILES_DIR, filename)) as f:
            data = yaml.safe_load(f)
        profiles.append({
            "key": data["key"], "label": data["label"], "adapter_type": data["adapter_type"],
            "base_url": data.get("base_url"),
        })
    return profiles


def _load_bundled_profile(key: str) -> dict:
    path = os.path.join(PROFILES_DIR, f"{key}.yaml")
    if not os.path.isfile(path):
        raise ProfileNotFoundError("bundled_profile_not_found", key=key)
    with open(path) as f:
        return yaml.safe_load(f)


def _host(url: str | None) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host.removeprefix("www.")


def bundled_key_for_url(url: str | None) -> str | None:
    """Il profilo bundlato del tracker a quell'indirizzo (stesso host del suo
    base_url, con o senza www.), se c'è."""
    host = _host(url)
    if not host:
        return None
    return next((p["key"] for p in list_bundled_profiles() if _host(p.get("base_url")) == host), None)


def _apply_bundled(profile: TrackerUploadProfile, tracker: Tracker, data: dict, profile_key: str) -> None:
    """Tutti i valori del profilo bundlato nella riga, come alla creazione."""
    upload = data.get("upload", {})
    flags = upload.get("default_flags", {})
    if tracker.language is None and upload.get("language"):
        tracker.language = upload["language"]
    profile.category_id_map_json = json.dumps(upload.get("category_id", {}))
    profile.type_id_map_json = json.dumps(upload.get("type_id", {}))
    profile.resolution_id_map_json = json.dumps(upload.get("resolution_id", {}))
    profile.naming_convention = upload.get("naming_convention")
    profile.naming_rules_json = json.dumps(upload["naming"]) if upload.get("naming") else None
    profile.naming_version = (upload.get("naming") or {}).get("version")
    profile.naming_customized = False
    profile.naming_update_available = None
    profile.description_template = upload.get("description_template")
    profile.default_anonymous = bool(flags.get("anonymous", False))
    profile.default_personal_release = bool(flags.get("personal_release", False))
    profile.default_internal = bool(flags.get("internal", False))
    profile.freeleech_options_json = json.dumps((upload.get("freeleech") or {}).get("options") or [])
    profile.default_freeleech = (upload.get("freeleech") or {}).get("default") or None
    profile.source_profile_key = profile_key


def create_upload_profile(session: Session, tracker: Tracker, profile_key: str | None) -> TrackerUploadProfile:
    """profile_key=None crea un profilo custom vuoto (docs/SPEC.md §9:
    "profilo custom da zero" è sempre un'opzione), altrimenti copia i
    valori dal file bundlato corrispondente."""
    profile = TrackerUploadProfile(tracker_id=tracker.id)
    if profile_key is not None:
        _apply_bundled(profile, tracker, _load_bundled_profile(profile_key), profile_key)
    session.add(profile)
    session.commit()
    return profile


def restore_upload_profile(session: Session, profile: TrackerUploadProfile, profile_key: str | None) -> None:
    """Il profilo bundlato al posto di quello che c'è, modifiche comprese
    (mappe degli id, regole di naming, descrizione, default): quello da cui
    era nato se profile_key è None."""
    key = profile_key or profile.source_profile_key
    if not key:
        raise ProfileNotFoundError("bundled_profile_not_found", key=key)
    _apply_bundled(profile, profile.tracker, _load_bundled_profile(key), key)
    session.commit()


def _bundled_naming(key: str) -> dict | None:
    try:
        return (_load_bundled_profile(key).get("upload") or {}).get("naming")
    except ProfileNotFoundError:
        return None


def apply_bundled_naming(profile: TrackerUploadProfile, naming: dict) -> None:
    profile.naming_rules_json = json.dumps(naming)
    profile.naming_version = naming.get("version")
    profile.naming_customized = False
    profile.naming_update_available = None


def sync_tracker_languages(session: Session) -> list[str]:
    """All'avvio, una volta: la lingua che stava nelle regole di naming
    (title_language, prima che fosse un'impostazione del tracker) passa al
    tracker, e dalle regole sparisce, così un tracker lasciato senza lingua
    dall'utente resta tale. Senza, quella del profilo bundlato."""
    updated = []
    for profile in session.query(TrackerUploadProfile):
        tracker = profile.tracker
        if tracker is None:
            continue
        rules = json.loads(profile.naming_rules_json) if profile.naming_rules_json else None
        legacy = (rules or {}).pop("title_language", None)
        if rules is not None and legacy is not None:
            profile.naming_rules_json = json.dumps(rules)
        if tracker.language is not None or legacy is None:
            continue
        tracker.language = legacy
        updated.append(tracker.label)
        logger.info("Lingua di %s spostata dalle regole di naming al tracker: %s", tracker.label, legacy)
    session.commit()
    return updated


def sync_naming_rules(session: Session) -> list[str]:
    """All'avvio: porta le regole di naming dei profili bundlati alla
    versione del codice, secondo le regole in cima al file. Restituisce i
    tracker aggiornati, per il log."""
    updated = []
    for profile in session.query(TrackerUploadProfile).filter(TrackerUploadProfile.source_profile_key.isnot(None)):
        naming = _bundled_naming(profile.source_profile_key)
        if not naming or not naming.get("version"):
            continue
        if (profile.naming_version or 0) >= naming["version"]:
            continue
        label = profile.tracker.label if profile.tracker else str(profile.tracker_id)
        if not profile.naming_customized or naming.get("force"):
            apply_bundled_naming(profile, naming)
            updated.append(label)
            logger.info("Regole di naming di %s aggiornate alla versione %s", label, naming["version"])
        elif profile.naming_update_available != naming["version"]:
            profile.naming_update_available = naming["version"]
            logger.info("Regole di naming %s disponibili per %s (modificate dall'utente)", naming["version"], label)
    session.commit()
    return updated


def sync_description_templates(session: Session) -> list[str]:
    """All'avvio: un profilo con ancora una descrizione bundlata di prima
    (replaces_description_templates, quindi mai modificata dall'utente)
    passa a quella attuale. Una descrizione modificata non si tocca."""
    updated = []
    for profile in session.query(TrackerUploadProfile).filter(TrackerUploadProfile.source_profile_key.isnot(None)):
        try:
            upload = _load_bundled_profile(profile.source_profile_key).get("upload") or {}
        except ProfileNotFoundError:
            continue
        current = upload.get("description_template")
        if current and profile.description_template in (upload.get("replaces_description_templates") or []):
            profile.description_template = current
            label = profile.tracker.label if profile.tracker else str(profile.tracker_id)
            updated.append(label)
            logger.info("Descrizione di %s aggiornata a quella bundlata attuale", label)
    session.commit()
    return updated


def update_naming_from_bundled(session: Session, profile: TrackerUploadProfile) -> None:
    """Il pulsante "usa le regole nuove": le regole bundlate al posto di
    quelle modificate dall'utente."""
    naming = _bundled_naming(profile.source_profile_key) if profile.source_profile_key else None
    if not naming:
        raise ProfileNotFoundError("bundled_profile_not_found", key=profile.source_profile_key)
    apply_bundled_naming(profile, naming)
    session.commit()


def freeleech_options(profile: TrackerUploadProfile | None) -> list[int]:
    if profile is None or not profile.freeleech_options_json:
        return []
    return sorted({int(v) for v in json.loads(profile.freeleech_options_json) if 0 < int(v) <= 100})
