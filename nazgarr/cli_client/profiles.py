"""Dove il CLI ricorda le istanze a cui parla: ~/.config/nazgarr/cli.toml
(macOS: ~/Library/Application Support/Nazgarr/cli.toml), leggibile solo dal
proprietario, come gh. Ogni profilo ha l'URL e una API key creata da
`nazgarr login`; NAZGARR_URL e NAZGARR_API_KEY hanno la precedenza (script,
cron, container)."""

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

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


def resolve(name: str | None, url: str | None) -> Profile | None:
    """Il profilo da usare: --profile, poi quello di default; NAZGARR_URL e
    NAZGARR_API_KEY (e --url) sopra quello che c'è nel file."""
    default, profiles = load()
    chosen = name or os.environ.get("NAZGARR_PROFILE") or default
    profile = profiles.get(chosen)
    env_url, env_key = url or os.environ.get("NAZGARR_URL"), os.environ.get("NAZGARR_API_KEY")
    if profile is None and not env_url:
        return None
    profile = Profile(name=chosen, url=profile.url if profile else "", api_key=profile.api_key if profile else None,
                      key_id=profile.key_id if profile else None)
    if env_url:
        profile.url = env_url
    if env_key:
        profile.api_key = env_key
    return profile
