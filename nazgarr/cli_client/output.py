"""Come il CLI scrive: tabelle e testo per una persona, JSON grezzo con
--json (per jq e gli script). Gli errori su stderr, con un codice di uscita:
0 ok, 1 errore, 2 uso sbagliato, 3 conferma rifiutata, 4 non autorizzato."""

import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import typer
from rich.console import Console
from rich.table import Table

EXIT_ERROR, EXIT_USAGE, EXIT_DECLINED, EXIT_UNAUTHORIZED = 1, 2, 3, 4

console = Console(highlight=False, soft_wrap=False)
err_console = Console(stderr=True, highlight=False)


@dataclass
class State:
    """Le opzioni globali (nazgarr --profile/--url/--json …)."""

    profile: str | None = None
    url: str | None = None
    json: bool = False
    extra: dict = field(default_factory=dict)


def emit(state: State, data, render: Callable[[object], None]) -> None:
    if state.json:
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")
    else:
        render(data)


def table(columns: Iterable[str], rows: Iterable[Iterable[object]], title: str | None = None) -> None:
    out = Table(title=title, show_lines=False, header_style="bold", title_justify="left")
    for column in columns:
        out.add_column(column, overflow="fold")
    for row in rows:
        out.add_row(*("" if v is None else str(v) for v in row))
    console.print(out)


def fail(text: str, code: int = EXIT_ERROR) -> typer.Exit:
    err_console.print(f"[red]Error:[/red] {text}")
    return typer.Exit(code)


def confirm(question: str, yes: bool) -> None:
    """Le azioni che toccano file o client chiedono sempre conferma (--yes per
    gli script); un no esce con il codice 3."""
    if yes:
        return
    if not sys.stdin.isatty():
        raise fail(f"{question} Run it again with --yes to confirm without a prompt.", EXIT_DECLINED)
    if not typer.confirm(question, default=False):
        err_console.print("Nothing done.")
        raise typer.Exit(EXIT_DECLINED)


def size(value: int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(number) < 1000 or unit == "TB":
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1000
    return str(value)
