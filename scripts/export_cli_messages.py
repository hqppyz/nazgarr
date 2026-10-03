"""I messaggi d'errore inglesi dell'interfaccia (frontend/src/locales/en/errors.ts)
per il CLI (nazgarr/cli_client/messages_en.json): lo stesso testo per lo
stesso codice, senza Node nel pacchetto. Da rilanciare quando cambiano;
tests/test_cli_client.py controlla che siano allineati.

    python scripts/export_cli_messages.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "src" / "locales" / "en" / "errors.ts"
TARGET = ROOT / "nazgarr" / "cli_client" / "messages_en.json"

_ENTRY = re.compile(
    r"""'errors\.([A-Za-z0-9_]+)':\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`)""",
    re.S,
)


def _unquote(literal: str) -> str:
    body = literal[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def messages() -> dict[str, str]:
    return {code: _unquote(text) for code, text in _ENTRY.findall(SOURCE.read_text())}


def main() -> int:
    TARGET.write_text(json.dumps(messages(), indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"{TARGET.relative_to(ROOT)}: {len(messages())} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
