"""Pezzi comuni ai comandi: trovare un disco, un client o un tracker per
nome o per ID, chiedere un segreto senza mostrarlo, e il login temporaneo
per quello che una API key non può fare."""

import os
import re
import sys

import typer

from nazgarr.cli_client import profiles
from nazgarr.cli_client.context import state
from nazgarr.cli_client.http import Api
from nazgarr.cli_client.output import EXIT_USAGE, fail


def find(items: list[dict], ref: str, what: str, key: str = "label") -> dict:
    """L'elemento con quell'ID o quel nome (senza maiuscole/minuscole)."""
    if ref.isdigit():
        found = [i for i in items if i["id"] == int(ref)]
    else:
        found = [i for i in items if str(i.get(key, "")).lower() == ref.lower()]
    if not found:
        names = ", ".join(f"{i.get(key)} (#{i['id']})" for i in items) or "none"
        raise fail(f"No {what} {ref!r}. Available: {names}.", EXIT_USAGE)
    return found[0]


def secret(prompt: str, stdin: bool = False) -> str:
    """Un segreto chiesto a schermo (mai come argomento: finirebbe nella
    cronologia della shell e in ps), o letto da stdin, o da una variabile
    d'ambiente con @env:NOME."""
    if stdin:
        return sys.stdin.readline().rstrip("\n")
    return typer.prompt(prompt, hide_input=True)


def env_secret(value: str | None) -> str | None:
    """${NOME} → la variabile d'ambiente (per config import)."""
    if value is None:
        return None
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
    if not match:
        return value
    return os.environ.get(match.group(1))


def login_api(ctx: typer.Context, password_stdin: bool = False) -> Api:
    """Un login con la password, per una sola operazione: le impostazioni
    segrete e quelle di sicurezza non si cambiano con una API key
    (nazgarr/api/settings.py), apposta. Il token non viene salvato."""
    current = state(ctx)
    profile = profiles.resolve(current.profile, current.url)
    if profile is None or not profile.url:
        raise fail("Which instance? Run nazgarr login --url http://HOST:8080 first.", EXIT_USAGE)
    username = os.environ.get("NAZGARR_USERNAME") or typer.prompt("Username (this needs your password)")
    password = sys.stdin.readline().rstrip("\n") if password_stdin else typer.prompt("Password", hide_input=True)
    token = Api(profile.url).post("/api/auth/login", {"username": username, "password": password})["access_token"]
    return Api(profile.url, token=token)


def duration(text: str) -> int:
    """"7d", "36h", "90m" o secondi → secondi."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([dhms]?)\s*", text.lower())
    if not match:
        raise fail(f"Not a duration: {text!r} (use e.g. 7d, 36h, 90m).", EXIT_USAGE)
    number, unit = float(match.group(1)), match.group(2) or "s"
    return int(number * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit])


def human_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds}s"
