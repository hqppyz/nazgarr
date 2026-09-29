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

import yaml
from sqlalchemy.orm import Session

from app.api_errors import CodedError
from app.models import Tracker, TrackerUploadProfile

logger = logging.getLogger(__name__)

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "tracker_profiles")


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


def create_upload_profile(session: Session, tracker: Tracker, profile_key: str | None) -> TrackerUploadProfile:
    """profile_key=None crea un profilo custom vuoto (docs/SPEC.md §9:
    "profilo custom da zero" è sempre un'opzione), altrimenti copia i
    valori dal file bundlato corrispondente."""
    if profile_key is None:
        profile = TrackerUploadProfile(tracker_id=tracker.id)
    else:
        data = _load_bundled_profile(profile_key)
        upload = data.get("upload", {})
        flags = upload.get("default_flags", {})
        profile = TrackerUploadProfile(
            tracker_id=tracker.id,
            category_id_map_json=json.dumps(upload.get("category_id", {})),
            type_id_map_json=json.dumps(upload.get("type_id", {})),
            resolution_id_map_json=json.dumps(upload.get("resolution_id", {})),
            naming_convention=upload.get("naming_convention"),
            naming_rules_json=json.dumps(upload["naming"]) if upload.get("naming") else None,
            naming_version=(upload.get("naming") or {}).get("version"),
            naming_customized=False,
            description_template=upload.get("description_template"),
            default_anonymous=bool(flags.get("anonymous", False)),
            default_personal_release=bool(flags.get("personal_release", False)),
            source_profile_key=profile_key,
        )
    session.add(profile)
    session.commit()
    return profile


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


def update_naming_from_bundled(session: Session, profile: TrackerUploadProfile) -> None:
    """Il pulsante "usa le regole nuove": le regole bundlate al posto di
    quelle modificate dall'utente."""
    naming = _bundled_naming(profile.source_profile_key) if profile.source_profile_key else None
    if not naming:
        raise ProfileNotFoundError("bundled_profile_not_found", key=profile.source_profile_key)
    apply_bundled_naming(profile, naming)
    session.commit()
