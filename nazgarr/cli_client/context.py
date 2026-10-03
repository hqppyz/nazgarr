"""L'istanza a cui parla un comando: profilo, URL e API key dalle opzioni
globali, dalle variabili d'ambiente o da cli.toml (nazgarr/cli_client/profiles.py)."""

import typer

from nazgarr.cli_client import profiles
from nazgarr.cli_client.http import Api
from nazgarr.cli_client.output import EXIT_UNAUTHORIZED, State, fail


def state(ctx: typer.Context) -> State:
    root = ctx.find_root()
    if not isinstance(root.obj, State):
        root.obj = State()
    return root.obj


def api(ctx: typer.Context) -> Api:
    current = state(ctx)
    profile = profiles.resolve(current.profile, current.url)
    if profile is None or not profile.url:
        raise fail("No Nazgarr instance configured. Run: nazgarr login --url http://HOST:8080", EXIT_UNAUTHORIZED)
    if not profile.api_key:
        raise fail(f"Not logged in to {profile.url}. Run: nazgarr login", EXIT_UNAUTHORIZED)
    return Api(profile.url, api_key=profile.api_key)
