"""Installazione e caricamento dei plugin (docs/ROADMAP.md Fase 10).

I plugin sono pacchetti pip (decisione dell'utente, 2026-09-30), elencati in
NAZGARR_PLUGINS (separati da spazi o virgole) o, se la variabile non c'è, in
data_dir/plugins.txt (uno per riga, # per i commenti). All'avvio si
installano con pip in data_dir/plugins/site, un ambiente che sopravvive ai
riavvii e agli aggiornamenti del container; pip riparte solo quando la lista
cambia.

Un plugin si fa trovare con un entry point del gruppo "nazgarr.plugins":

    [project.entry-points."nazgarr.plugins"]
    flood = "nazgarr_flood:setup"

Il modulo dichiara con quali versioni dell'SDK funziona (REQUIRES_SDK, es.
">=1.0,<2") e setup() registra i suoi adapter con nazgarr_sdk.register.
Un plugin che non si installa, non si carica o è incompatibile viene
disattivato, con il suo errore (Settings > Plugins); quello che aveva già
registrato si annulla, e il resto di Nazgarr funziona come sempre.

I plugin girano dentro Nazgarr, con i suoi stessi permessi: vanno installati
solo quelli di cui ci si fida.
"""

import contextlib
import fcntl
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from nazgarr.plugins.registry import REGISTRY, registering_as

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "nazgarr.plugins"
ENV_VAR = "NAZGARR_PLUGINS"
PIP_TIMEOUT_SECONDS = 600


@dataclass
class PluginStatus:
    name: str  # il nome dell'entry point, o il pacchetto se non si è installato
    distribution: str | None = None
    version: str | None = None
    status: str = "loaded"  # loaded | failed | incompatible | install_failed
    error: str | None = None
    requires_sdk: str | None = None
    adapters: list[str] = field(default_factory=list)  # "kind:adapter_type"


@dataclass
class PluginState:
    source: str | None = None  # "env" | "file" | None (nessuna lista)
    requested: list[str] = field(default_factory=list)
    plugins: list[PluginStatus] = field(default_factory=list)
    install_error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


STATE = PluginState()


def requested_plugins(data_dir: str) -> tuple[str | None, list[str]]:
    """(da dove, lista dei pacchetti richiesti)."""
    raw = os.environ.get(ENV_VAR)
    if raw is not None:
        return "env", [p for p in re.split(r"[\s,]+", raw) if p]
    path = os.path.join(data_dir, "plugins.txt")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lines = [line.split("#", 1)[0].strip() for line in f]
        return "file", [line for line in lines if line]
    return None, []


def site_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "plugins", "site")


# Cartelle che pip e gli editor riempiono da soli, da non contare.
_IGNORED_DIRS = {"build", "dist", "__pycache__", ".git", ".venv", ".pytest_cache", ".ruff_cache", "node_modules"}


def local_folder_signature(path: str) -> str:
    """Il contenuto di un plugin indicato come cartella locale (sviluppo):
    percorso, dimensione e data di ogni file. Cambia appena si modifica il
    codice, così il riavvio successivo lo reinstalla da solo."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            with contextlib.suppress(OSError):
                st = os.stat(full)
                entries.append(f"{os.path.relpath(full, path)}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def _fingerprint(requested: list[str]) -> str:
    """La lista, più il contenuto delle cartelle locali: un plugin in sviluppo
    si reinstalla quando cambia il suo codice, uno da PyPI o da git solo
    quando cambia la riga."""
    parts = [
        f"{item}@{local_folder_signature(item)}" if os.path.isdir(item) else item
        for item in sorted(requested)
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def invalid_requirements(requested: list[str]) -> list[str]:
    """Le righe che pip leggerebbe come opzioni (--index-url, -e, ...): mai,
    un'opzione può far installare pacchetti da un indice di chiunque."""
    return [item for item in requested if item.startswith("-")]


def install(data_dir: str, requested: list[str]) -> str | None:
    """Installa i pacchetti con pip se la lista è cambiata dall'ultima volta,
    da zero in una cartella nuova che poi sostituisce la vecchia: un plugin
    tolto dalla lista sparisce davvero. Restituisce l'errore, o None. Un
    lock evita due installazioni insieme."""
    bad = invalid_requirements(requested)
    if bad:
        return f"not a package, refused: {' '.join(bad)} (options are not allowed in the plugin list)"
    target = site_dir(data_dir)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    marker = os.path.join(data_dir, "plugins", "installed.json")
    wanted = _fingerprint(requested)
    with open(os.path.join(data_dir, "plugins", ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with contextlib.suppress(OSError, ValueError):
            with open(marker, encoding="utf-8") as f:
                if json.load(f).get("fingerprint") == wanted:
                    return None
        fresh = f"{target}.new"
        shutil.rmtree(fresh, ignore_errors=True)
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                   "--target", fresh, *requested]
        logger.info("Installazione dei plugin: %s", " ".join(requested))
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=PIP_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return str(exc)
        if result.returncode != 0:
            shutil.rmtree(fresh, ignore_errors=True)
            return (result.stderr or result.stdout).strip()[-2000:]
        shutil.rmtree(target, ignore_errors=True)
        os.replace(fresh, target)
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"fingerprint": wanted, "packages": requested}, f)
    return None


def _requires_sdk(obj) -> str | None:
    module = inspect.getmodule(obj)
    return getattr(obj, "REQUIRES_SDK", None) or getattr(module, "REQUIRES_SDK", None)


def _compatible(requirement: str | None, sdk_version: str) -> str | None:
    """None se va bene, se no il perché."""
    if not requirement:
        return "il plugin non dichiara REQUIRES_SDK"
    try:
        spec = SpecifierSet(requirement)
    except InvalidSpecifier:
        return f"REQUIRES_SDK non valido: {requirement!r}"
    if Version(sdk_version) not in spec:
        return f"richiede l'SDK {requirement}, Nazgarr ha {sdk_version}"
    return None


def load_entry_points(entry_points=None, sdk_version: str | None = None) -> list[PluginStatus]:
    """Carica ogni plugin trovato. Un errore resta al suo plugin."""
    from nazgarr_sdk import SDK_VERSION

    sdk_version = sdk_version or SDK_VERSION
    found = entry_points if entry_points is not None else importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    statuses = []
    for ep in found:
        dist = getattr(ep, "dist", None)
        status = PluginStatus(name=ep.name, distribution=dist.name if dist else None,
                              version=dist.version if dist else None)
        owner = status.distribution or ep.name
        try:
            obj = ep.load()
            status.requires_sdk = _requires_sdk(obj)
            reason = _compatible(status.requires_sdk, sdk_version)
            if reason:
                status.status, status.error = "incompatible", reason
            else:
                with registering_as(owner):
                    if callable(obj):
                        obj()
        except Exception as exc:  # un plugin rotto non ferma gli altri
            logger.exception("Plugin %s non caricato", ep.name)
            status.status, status.error = "failed", f"{type(exc).__name__}: {exc}"
        if status.status != "loaded":
            for spec in REGISTRY.of_plugin(owner):
                REGISTRY.unregister(spec.kind, spec.adapter_type)
        status.adapters = [f"{spec.kind}:{spec.adapter_type}" for spec in REGISTRY.of_plugin(owner)]
        if status.status == "loaded":
            logger.info("Plugin %s %s caricato: %s", ep.name, status.version or "", ", ".join(status.adapters) or "-")
        statuses.append(status)
    return statuses


def load(data_dir: str) -> PluginState:
    """All'avvio: installa (se serve) e carica i plugin richiesti."""
    source, requested = requested_plugins(data_dir)
    STATE.source, STATE.requested, STATE.install_error, STATE.plugins = source, requested, None, []
    if not requested:
        # Lista vuota: niente plugin, e niente resti di quelli di prima.
        shutil.rmtree(site_dir(data_dir), ignore_errors=True)
        with contextlib.suppress(OSError):
            os.remove(os.path.join(data_dir, "plugins", "installed.json"))
        return STATE
    STATE.install_error = install(data_dir, requested)
    if STATE.install_error:
        logger.error("Installazione dei plugin fallita: %s", STATE.install_error)
    target = site_dir(data_dir)
    # In coda: una dipendenza che un plugin porta con sé non sostituisce mai
    # quella di Nazgarr (es. un httpx di un'altra versione).
    if target not in sys.path:
        sys.path.append(target)
    importlib.invalidate_caches()
    STATE.plugins = load_entry_points(installed_entry_points(target))
    return STATE


def installed_entry_points(target: str) -> list:
    """Solo i plugin che Nazgarr ha installato in data_dir/plugins/site: un
    pacchetto con l'entry point nazgarr.plugins finito altrove nel percorso
    di Python non si carica."""
    root = os.path.realpath(target)
    found = []
    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        dist = getattr(ep, "dist", None)
        try:
            location = os.path.realpath(str(dist.locate_file(""))) if dist is not None else ""
        except Exception:
            location = ""
        if location == root:
            found.append(ep)
    return found
