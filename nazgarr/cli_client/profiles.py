"""Dove il CLI ricorda le istanze a cui parla: ~/.config/nazgarr/cli.toml
(macOS: ~/Library/Application Support/Nazgarr/cli.toml), leggibile solo dal
proprietario, come gh. Ogni profilo ha l'URL e una API key creata da
`nazgarr login`; NAZGARR_URL e NAZGARR_API_KEY hanno la precedenza (script,
cron, container).

La chiave di un profilo va solo al suo indirizzo (audit 2026-10-18): un
--url (o NAZGARR_URL) diverso usa la chiave del profilo salvato per
quell'indirizzo, se c'è, se no nessuna (NAZGARR_API_KEY, o "Not logged
in"). Prima la chiave del profilo di default partiva verso qualunque host
passato con --url, anche in http. E un profilo scelto (--profile o
NAZGARR_PROFILE) va al suo indirizzo anche con NAZGARR_URL impostato, come
nel container (NAZGARR_URL=http://127.0.0.1:3019): prima `-P seedbox` lì
mandava la chiave della seedbox all'istanza locale."""

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PROFILE = "default"


@dataclass
class Profile:
    name: str
    url: str
    api_key: str | None = None
    key_id: int | None = None


def config_path() -> Path:
    if os.environ.get("NAZGARR_CLI_CONFIG"):
        return Path(os.environ["NAZGARR_CLI_CONFIG"])
    from nazgarr.cli import default_dirs

    return default_dirs()[0] / "cli.toml"


def load() -> tuple[str, dict[str, Profile]]:
    """(profilo di default, profili)."""
    path = config_path()
    if not path.exists():
        return DEFAULT_PROFILE, {}
    data = tomllib.loads(path.read_text())
    profiles = {
        name: Profile(name=name, url=values.get("url", ""), api_key=values.get("api_key"), key_id=values.get("key_id"))
        for name, values in (data.get("profiles") or {}).items()
    }
    return data.get("default", DEFAULT_PROFILE), profiles


def save(default: str, profiles: dict[str, Profile]) -> Path:
    """Il file intero, con permessi 600: contiene le API key."""
    lines = [f"default = {json.dumps(default)}", ""]
    for name, profile in sorted(profiles.items()):
        lines.append(f"[profiles.{json.dumps(name)}]")
        lines.append(f"url = {json.dumps(profile.url)}")
        if profile.api_key:
            lines.append(f"api_key = {json.dumps(profile.api_key)}")
        if profile.key_id is not None:
            lines.append(f"key_id = {int(profile.key_id)}")
        lines.append("")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    os.chmod(path, 0o600)
    return path


def same_url(a: str | None, b: str | None) -> bool:
    """Lo stesso indirizzo: schema, host e porta (con quelle di default),
    percorso senza / finale."""
    def key(url: str | None):
        parts = urlsplit((url or "").strip())
        scheme = parts.scheme.lower()
        try:
            port = parts.port or {"http": 80, "https": 443}.get(scheme)
        except ValueError:
            port = None
        return scheme, (parts.hostname or "").lower(), port, parts.path.rstrip("/")

    return bool(a and b) and key(a) == key(b)


def resolve(name: str | None, url: str | None) -> Profile | None:
    """Il profilo da usare: --profile (o NAZGARR_PROFILE), poi quello di
    default. url è un --url scritto sul comando, e vince sempre;
    NAZGARR_URL vale solo se il profilo non è stato scelto o non ha un
    indirizzo. Con un indirizzo diverso da quello del profilo la chiave è
    quella del profilo salvato per quell'indirizzo, o nessuna;
    NAZGARR_API_KEY sopra tutto."""
    default, profiles = load()
    explicit = name or os.environ.get("NAZGARR_PROFILE")
    chosen = explicit or default
    saved = profiles.get(chosen)
    env_url, env_key = os.environ.get("NAZGARR_URL"), os.environ.get("NAZGARR_API_KEY")
    override = url or (env_url if not (explicit and saved and saved.url) else None)
    if saved is None and not override:
        return None
    profile = Profile(name=chosen, url=saved.url if saved else "", api_key=saved.api_key if saved else None,
                      key_id=saved.key_id if saved else None)
    if override and not same_url(override, profile.url):
        match = next((p for p in profiles.values() if same_url(p.url, override)), None)
        profile = Profile(name=match.name if match else chosen, url=override,
                          api_key=match.api_key if match else None, key_id=match.key_id if match else None)
    elif override:
        profile.url = override
    if env_key:
        profile.api_key = env_key
    return profile
