"""Accendere e spegnere un plugin, incluso o installato, senza riavviare
(Impostazioni › Plugin). Spento, i suoi adapter escono dal registro: un host
di immagini sparisce dalla catena, un tipo di tracker o di client non si può
più usare. Riacceso, il suo setup() li registra di nuovo. I plugin spenti
stanno in app_settings.plugins_disabled e restano spenti ai riavvii
(apply_disabled all'avvio, dopo il caricamento)."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from nazgarr.core import settings_repo
from nazgarr.plugins.registry import REGISTRY, AdapterSpec, registering_as

SETTING = "plugins_disabled"

# Il setup() di ogni plugin caricato, per riaccenderlo: i plugin inclusi
# (nazgarr/plugins/builtin.py) e quelli installati (nazgarr/plugins/loader.py).
_SETUPS: dict[str, Callable[[], object]] = {}
# Gli adapter che ogni plugin ha registrato la prima volta: la pagina dei
# plugin li mostra anche quando è spento (e non sono più nel registro).
_SPECS: dict[str, list[AdapterSpec]] = {}


def remember(name: str, setup: Callable[[], object]) -> None:
    """Dopo il setup() riuscito di un plugin, con i suoi adapter già nel registro."""
    _SETUPS[name] = setup
    _SPECS[name] = REGISTRY.of_plugin(name)


def specs_of(name: str) -> list[AdapterSpec]:
    return REGISTRY.of_plugin(name) or _SPECS.get(name, [])


def known(name: str) -> bool:
    return name in _SETUPS


def disabled(session: Session) -> set[str]:
    raw = settings_repo.get_setting(session, SETTING) or ""
    return {name for name in raw.split(",") if name}


def _unregister(name: str) -> None:
    for spec in REGISTRY.of_plugin(name):
        REGISTRY.unregister(spec.kind, spec.adapter_type)


def apply_disabled(session: Session) -> None:
    """All'avvio, dopo che inclusi e installati si sono registrati."""
    for name in disabled(session):
        _unregister(name)


def set_enabled(session: Session, name: str, enabled: bool) -> None:
    if name not in _SETUPS:
        raise KeyError(name)
    names = disabled(session)
    if enabled:
        names.discard(name)
        if not REGISTRY.of_plugin(name):
            with registering_as(name):
                _SETUPS[name]()
    else:
        names.add(name)
        _unregister(name)
    settings_repo.set_setting(session, SETTING, ",".join(sorted(names)))
