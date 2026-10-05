"""Registro degli adapter (docs/ROADMAP.md Fase 10): quelli integrati e
quelli dei plugin si iscrivono allo stesso modo, e le factory
(nazgarr/integrations/adapter_factory.py) costruiscono un adapter da qui invece che da una
catena di if.

Un adapter è descritto da una AdapterSpec: di che tipo è (kind), il suo
nome come lo salva il DB (adapter_type: "qbittorrent", "unit3d", "ptpimg",
...), come si chiama nella UI, i campi di configurazione che chiede e la
funzione che lo costruisce da un AdapterContext. Un adapter_type è unico per
kind: un plugin non può sostituire un adapter integrato.
"""

import contextlib
import contextvars
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
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
    # Un'icona per la UI, come immagine "data:image/..." (un SVG o un PNG
    # piccolo): la UI la mostra in un <img>, dove uno script non gira. Gli
    # adapter integrati hanno la loro nella UI.
    icon: str | None = None

    @property
    def required_fields(self) -> tuple[ConfigField, ...]:
        return tuple(f for f in self.config_fields if f.required)


MAX_ICON = 64 * 1024


class AdapterAlreadyRegisteredError(ValueError):
    pass


# Il plugin che si sta caricando (nazgarr/plugins/loader.py): quello che registra
# finisce a suo nome, e se il caricamento fallisce si annulla.
_current_plugin: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_plugin", default=None)


@contextlib.contextmanager
def registering_as(plugin: str) -> Iterator[None]:
    token = _current_plugin.set(plugin)
    try:
        yield
    finally:
        _current_plugin.reset(token)


class Registry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], AdapterSpec] = {}
        self._builtins_loaded = False

    def _ensure_builtins(self) -> None:
        """Gli adapter integrati e i plugin inclusi (nazgarr/plugins/builtin.py)
        si registrano al primo uso del registro, non all'import del pacchetto:
        un plugin incluso importa nazgarr.sdk, che importa questo modulo, e
        caricarli all'import farebbe un giro di import a metà."""
        if self._builtins_loaded:
            return
        self._builtins_loaded = True
        import nazgarr.plugins.builtin  # noqa: F401

    def register(self, spec: AdapterSpec) -> AdapterSpec:
        self._ensure_builtins()
        plugin = _current_plugin.get()
        if plugin is not None:
            spec = replace(spec, plugin=plugin)
        if spec.kind not in KINDS:
            raise ValueError(f"kind sconosciuto: {spec.kind!r} (validi: {', '.join(KINDS)})")
        if spec.icon is not None and (not spec.icon.startswith("data:image/") or len(spec.icon) > MAX_ICON):
            raise ValueError(f"icona di {spec.adapter_type!r}: serve un'immagine data:image/... di al massimo "
                             f"{MAX_ICON // 1024} KB")
        key = (spec.kind, spec.adapter_type)
        if key in self._specs:
            owner = self._specs[key].plugin or "Nazgarr"
            raise AdapterAlreadyRegisteredError(f"{spec.kind} {spec.adapter_type!r} è già registrato da {owner}")
        self._specs[key] = spec
        return spec

    def unregister(self, kind: str, adapter_type: str) -> None:
        self._specs.pop((kind, adapter_type), None)

    def get(self, kind: str, adapter_type: str | None) -> AdapterSpec | None:
        self._ensure_builtins()
        return self._specs.get((kind, adapter_type or ""))

    def all(self) -> list[AdapterSpec]:
        self._ensure_builtins()
        return list(self._specs.values())

    def of_plugin(self, plugin: str) -> list[AdapterSpec]:
        self._ensure_builtins()
        return [spec for spec in self._specs.values() if spec.plugin == plugin]

    def of_kind(self, kind: str) -> list[AdapterSpec]:
        self._ensure_builtins()
        return [spec for (k, _t), spec in self._specs.items() if k == kind]

    def types(self, kind: str) -> set[str]:
        return {spec.adapter_type for spec in self.of_kind(kind)}


REGISTRY = Registry()


def register(spec: AdapterSpec) -> AdapterSpec:
    return REGISTRY.register(spec)
