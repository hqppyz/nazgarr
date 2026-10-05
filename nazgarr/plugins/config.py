"""Configurazione degli adapter dei plugin (docs/ROADMAP.md Fase 10): i
valori dei campi che un adapter dichiara (ConfigField), validati qui, salvati
cifrati e mai restituiti se segreti.

Dove stanno:
- adapter con una riga propria (tracker, client torrent): in
  adapter_config_json di quella riga;
- adapter globali (host di immagini, resolver, notifiche): nella tabella
  adapter_config, una riga per (kind, adapter_type), con un interruttore.

Gli adapter integrati non dichiarano campi e usano le colonne di sempre.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from nazgarr.core import net_guard
from nazgarr.core.errors import CodedError
from nazgarr.core.models import AdapterConfig
from nazgarr.plugins.registry import AdapterSpec, ConfigField


class AdapterConfigError(CodedError):
    """Un valore che non va con i campi dichiarati dall'adapter."""


def _coerce(field: ConfigField, value: Any) -> Any:
    if value is None or value == "":
        return None
    if field.type == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).lower() in ("false", "0", "no", "off"):
            return False
        raise AdapterConfigError("adapter_config_invalid", field=field.key)
    if field.type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise AdapterConfigError("adapter_config_invalid", field=field.key) from exc
        return int(number) if number.is_integer() else number
    text = str(value).strip()
    if field.type == "choice" and field.choices and text not in field.choices:
        raise AdapterConfigError("adapter_config_invalid", field=field.key)
    if field.type == "url":
        if not text.lower().startswith(("http://", "https://")):
            raise AdapterConfigError("adapter_config_invalid", field=field.key)
        try:
            net_guard.check_url(text)
        except net_guard.ForbiddenDestination as exc:
            raise AdapterConfigError("adapter_config_invalid", field=field.key) from exc
    return text


def validate(spec: AdapterSpec, incoming: dict | None, existing: dict | None = None) -> dict:
    """I nuovi valori sopra quelli che c'erano. Un segreto non inviato (o
    null) resta com'era, uno inviato vuoto si cancella. Un campo che l'adapter
    non dichiara è un errore; uno obbligatorio mancante pure."""
    fields = {f.key: f for f in spec.config_fields}
    incoming = incoming or {}
    unknown = sorted(set(incoming) - set(fields))
    if unknown:
        raise AdapterConfigError("adapter_config_unknown_field", field=unknown[0])
    config = dict(existing or {})
    for key, field in fields.items():
        if key not in incoming or (field.type == "secret" and incoming[key] is None):
            continue
        value = _coerce(field, incoming[key])
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    missing = [f.key for f in spec.required_fields if config.get(f.key) in (None, "")]
    if missing:
        raise AdapterConfigError("adapter_config_missing_field", field=missing[0])
    return config


def with_defaults(spec: AdapterSpec, config: dict | None) -> dict:
    """Quello che riceve l'adapter: i valori salvati, se no i default."""
    config = config or {}
    return {f.key: config.get(f.key, f.default) for f in spec.config_fields}


def public(spec: AdapterSpec | None, config: dict | None) -> dict:
    """Per l'API: i valori non segreti, e quali segreti sono impostati."""
    config = config or {}
    fields = spec.config_fields if spec else ()
    return {
        "values": {f.key: config.get(f.key) for f in fields if f.type != "secret"},
        "secrets_set": [f.key for f in fields if f.type == "secret" and config.get(f.key)],
    }


def loads(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def dumps(config: dict) -> str | None:
    return json.dumps(config) if config else None


def global_config(session: Session, kind: str, adapter_type: str) -> AdapterConfig | None:
    return session.get(AdapterConfig, (kind, adapter_type))


def save_global(session: Session, spec: AdapterSpec, incoming: dict | None, enabled: bool | None) -> AdapterConfig:
    row = global_config(session, spec.kind, spec.adapter_type)
    if row is None:
        row = AdapterConfig(kind=spec.kind, adapter_type=spec.adapter_type, enabled=True)
        session.add(row)
    row.config_json = dumps(validate(spec, incoming, loads(row.config_json)))
    if enabled is not None:
        row.enabled = enabled
    session.commit()
    return row


def usable_global(session: Session, spec: AdapterSpec) -> dict | None:
    """La configurazione di un adapter globale di un plugin, se è acceso e
    ha tutti i campi obbligatori; None se no (l'adapter si salta)."""
    row = global_config(session, spec.kind, spec.adapter_type)
    config = loads(row.config_json) if row else {}
    if row is not None and not row.enabled:
        return None
    if row is None and spec.required_fields:
        return None
    if any(config.get(f.key) in (None, "") for f in spec.required_fields):
        return None
    return with_defaults(spec, config)


def apply_to_row(row, kind: str, incoming: dict | None, *, creating: bool) -> None:
    """I campi di un adapter di un plugin sulla riga di tracker o client
    (adapter_config_json). Un adapter senza campi non ne ha: niente da fare."""
    from nazgarr.plugins.registry import REGISTRY

    spec = REGISTRY.get(kind, row.adapter_type)
    if spec is None or not spec.config_fields:
        if incoming:
            raise AdapterConfigError("adapter_config_unknown_field", field=sorted(incoming)[0])
        return
    if incoming is None and not creating:
        return
    existing = None if creating else loads(row.adapter_config_json)
    row.adapter_config_json = dumps(validate(spec, incoming, existing))


def public_for_row(row, kind: str) -> dict:
    from nazgarr.plugins.registry import REGISTRY

    return public(REGISTRY.get(kind, row.adapter_type), loads(getattr(row, "adapter_config_json", None)))


def secrets_not_resent(row, kind: str, incoming: dict | None) -> list[str]:
    """I campi segreti salvati sulla riga di un adapter di un plugin che la
    richiesta non reinvia (per require_secrets_for_new_host)."""
    from nazgarr.plugins.registry import REGISTRY

    spec = REGISTRY.get(kind, row.adapter_type)
    if spec is None:
        return []
    stored = loads(getattr(row, "adapter_config_json", None))
    incoming = incoming or {}
    return [f.key for f in spec.config_fields
            if f.type == "secret" and stored.get(f.key) and incoming.get(f.key) in (None, "")]
