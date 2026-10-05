"""nazgarr api: qualsiasi endpoint, per quello che non ha (ancora) un
comando suo. Come `gh api`."""

import json
from pathlib import Path

import typer

from nazgarr.cli_client.context import api
from nazgarr.cli_client.output import EXIT_USAGE, fail


def raw(
    ctx: typer.Context,
    method: str = typer.Argument(..., help="GET, POST, PUT, PATCH or DELETE."),
    path: str = typer.Argument(..., help="The endpoint, e.g. /api/dashboard (see http://HOST:3019/docs)."),
    data: str = typer.Option(None, "--data", "-d", help="JSON body, or @file.json."),
    param: list[str] = typer.Option(None, "--param", "-p", help="Query parameter key=value (repeatable)."),
):
    """Call any API endpoint and print the JSON answer."""
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise fail(f"Unknown method {method}.", EXIT_USAGE)
    body = None
    if data:
        text = Path(data[1:]).read_text() if data.startswith("@") else data
        try:
            body = json.loads(text)
        except ValueError as exc:
            raise fail(f"--data is not valid JSON: {exc}", EXIT_USAGE) from exc
    params = dict(item.split("=", 1) for item in (param or []) if "=" in item)
    result = api(ctx).request(method, path if path.startswith("/") else f"/{path}", json_body=body, params=params)
    if result is not None:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False) if not isinstance(result, str) else result)
