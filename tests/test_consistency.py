"""Cose scritte due volte che devono restare uguali: lo schema SQL e i
modelli, i percorsi che la CLI chiama e quelli che l'API espone."""

import ast
import re
import sqlite3
from pathlib import Path

from nazgarr import models
from nazgarr.db import SCHEMA_PATH

ROOT = Path(__file__).resolve().parent.parent


def test_schema_sql_and_the_models_have_the_same_tables_and_columns():
    """docs/schema.sql crea il DB, i modelli lo leggono: una colonna solo da
    una parte si scopriva in produzione (i test aggiungono le colonne
    mancanti con migrate_schema, e la differenza non si vedeva)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text())
    tables = [name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    in_sql = {t: {row[1] for row in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    in_models = {t.name: {c.name for c in t.columns} for t in models.Base.metadata.sorted_tables}
    assert in_sql == in_models


_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE"}


def _template(node: ast.expr) -> str | None:
    """Il percorso di una chiamata: una stringa, o una f-string con i valori
    al posto dei parametri ({} -> un segmento qualsiasi)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant) else "{}" for p in node.values)
    return None


def _cli_calls() -> set[tuple[str, str]]:
    calls = set()
    for path in (ROOT / "nazgarr" / "cli_client").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
                continue
            name = node.func.attr
            if name == "request" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                method, target = str(node.args[0].value).upper(), _template(node.args[1])
            elif name in _METHODS:
                method, target = _METHODS[name], _template(node.args[0])
            else:
                continue
            if target and target.startswith("/api/"):
                calls.add((method, target.split("?")[0]))
    return calls


def test_every_path_the_cli_calls_exists_in_the_api():
    """La CLI scrive a mano circa 70 percorsi: uno rinominato nell'API la
    rompeva senza che nessun test lo vedesse."""
    from nazgarr.main import app

    # I percorsi dell'API con un valore al posto dei parametri; quelli della
    # CLI come espressioni, dove {} è un segmento qualsiasi (anche "radarr"
    # in /api/{kind}-instances).
    routes = [
        (method.upper(), re.sub(r"\{[^}]+\}", "x", path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    ]
    calls = _cli_calls()
    assert len(calls) > 30  # il test legge davvero le chiamate della CLI

    def exists(method: str, template: str) -> bool:
        pattern = re.compile("^" + "[^/]+".join(map(re.escape, template.rstrip("/").split("{}"))) + "$")
        return any(m == method and pattern.match(path) for m, path in routes)

    missing = sorted((method, target) for method, target in calls if not exists(method, target))
    assert missing == []


def test_the_cli_and_the_api_agree_on_the_protected_settings():
    """Il CLI chiede la password per cambiare le protezioni; l'API le vieta
    alle API key (nazgarr/settings_registry.py)."""
    from nazgarr.cli_client.settings_catalog import CATALOG
    from nazgarr.settings_registry import SAFETY_KEYS

    assert {s.key for s in CATALOG if s.safety} == SAFETY_KEYS
