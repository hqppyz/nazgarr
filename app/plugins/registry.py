"""Registro degli adapter (docs/ROADMAP.md Fase 10): quelli integrati e
quelli dei plugin si iscrivono allo stesso modo, e le factory
(app/adapter_factory.py) costruiscono un adapter da qui invece che da una
catena di if.

Un adapter è descritto da una AdapterSpec: di che tipo è (kind), il suo
nome come lo salva il DB (adapter_type: "qbittorrent", "unit3d", "ptpimg",
...), come si chiama nella UI, i campi di configurazione che chiede e la
funzione che lo costruisce da un AdapterContext. Un adapter_type è unico per
kind: un plugin non può sostituire un adapter integrato.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

AdapterKind = Literal["tracker", "torrent_client", "media_resolver", "image_host", "notification"]
KINDS: tuple[str, ...] = ("tracker", "torrent_client", "media_resolver", "image_host", "notification")

FieldType = Literal["text", "secret", "url", "number", "boolean", "choice"]


@dataclass(frozen=True)
class ConfigField:
    """Un campo di configurazione di un adapter: la UI ne genera il form e un
    campo "secret" si salva cifrato e non torna mai dall'API."""

    key: str
    label: str
    type: FieldType = "text"
    required: bool = False
    default: Any = None
    help: str | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterContext:
    """Da dove un adapter prende quello che gli serve:
    - config: i valori dei suoi ConfigField;
    - row: la riga del DB che lo descrive, per tracker e client (sola lettura);
    - session: la sessione del DB, per gli adapter che leggono impostazioni."""

    config: dict[str, Any] = field(default_factory=dict)
    row: Any = None
    session: Any = None


@dataclass(frozen=True)
class AdapterSpec:
    kind: AdapterKind
    adapter_type: str
    label: str
    build: Callable[[AdapterContext], Any]
    config_fields: tuple[ConfigField, ...] = ()
    description: str | None = None
    plugin: str | None = None  # None = integrato; se no il nome del pacchetto del plugin

    @property
    def required_fields(self) -> tuple[ConfigField, ...]:
        return tuple(f for f in self.config_fields if f.required)


class AdapterAlreadyRegisteredError(ValueError):
    pass


class Registry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], AdapterSpec] = {}

    def register(self, spec: AdapterSpec) -> AdapterSpec:
        if spec.kind not in KINDS:
            raise ValueError(f"kind sconosciuto: {spec.kind!r} (validi: {', '.join(KINDS)})")
        key = (spec.kind, spec.adapter_type)
        if key in self._specs:
            owner = self._specs[key].plugin or "Nazgarr"
            raise AdapterAlreadyRegisteredError(f"{spec.kind} {spec.adapter_type!r} è già registrato da {owner}")
        self._specs[key] = spec
        return spec

    def unregister(self, kind: str, adapter_type: str) -> None:
        self._specs.pop((kind, adapter_type), None)

    def get(self, kind: str, adapter_type: str | None) -> AdapterSpec | None:
        return self._specs.get((kind, adapter_type or ""))

    def of_kind(self, kind: str) -> list[AdapterSpec]:
        return [spec for (k, _t), spec in self._specs.items() if k == kind]

    def types(self, kind: str) -> set[str]:
        return {spec.adapter_type for spec in self.of_kind(kind)}


REGISTRY = Registry()


def register(spec: AdapterSpec) -> AdapterSpec:
    return REGISTRY.register(spec)
