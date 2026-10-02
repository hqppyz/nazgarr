"""Nessuna credenziale in chiaro nei log (nazgarr/logging_config.py): httpx
logga ogni URL e i traceback lo ripetono, e i log si leggono dalla UI."""

import logging

from nazgarr.logging_config import RedactingFormatter, redact


def test_download_keys_passkeys_and_tokens_are_redacted():
    assert redact("GET https://t.example/torrent/download/6364.a062304171ce83b4 302") == (
        "GET https://t.example/torrent/download/6364.<redacted> 302"
    )
    assert redact("https://t.example/announce/0123456789abcdef0123") == "https://t.example/announce/<redacted>"
    assert redact("/api/x?api_token=abc&apikey=def&page=2") == "/api/x?api_token=<redacted>&apikey=<redacted>&page=2"


def test_formatter_redacts_tracebacks_too():
    formatter = RedactingFormatter("%(message)s")
    try:
        raise ValueError("failed https://t.example/torrent/download/1.secretkey")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "download failed", None, sys.exc_info())
    out = formatter.format(record)
    assert "secretkey" not in out
    assert "/torrent/download/1.<redacted>" in out
