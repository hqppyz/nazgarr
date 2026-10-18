"""Nessuna credenziale in chiaro nei log (nazgarr/core/logs.py): httpx
logga ogni URL e i traceback lo ripetono, e i log si leggono dalla UI."""

import logging

from nazgarr.core.logs import RedactingFormatter, redact


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


def test_the_uvicorn_access_log_hides_a_webhook_token():
    # Il log degli accessi di uvicorn ha il suo handler (propagate=False) e non
    # passava dal RedactingFormatter: ?token= finiva in chiaro su stdout
    # (docker logs, Dozzle; audit 2026-10-18).
    import io
    import logging.config

    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter

    from nazgarr.core.logs import configure_logging

    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).filters[:],
                    logging.getLogger(name).propagate, logging.getLogger(name).level) for name in names}
    try:
        logging.config.dictConfig(LOGGING_CONFIG)  # come fa uvicorn prima di importare l'app
        configure_logging()
        access = logging.getLogger("uvicorn.access")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
        access.addHandler(handler)
        access.info('%s - "%s %s HTTP/%s" %d', "10.0.0.5:1234", "POST",
                    "/api/arr-hooks/radarr/1?token=SECRETPW123", "1.1", 200)
        line = stream.getvalue()
        assert "SECRETPW123" not in line and "token=<redacted>" in line and "200" in line
        configure_logging()  # una seconda volta non aggiunge un altro filtro
        assert sum(type(f).__name__ == "RedactingFilter" for f in access.filters) == 1
    finally:
        for name, (handlers, filters, propagate, level) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers, logger.filters, logger.propagate = handlers, filters, propagate
            logger.setLevel(level)


def test_secrets_in_the_url_path_and_userinfo_are_redacted():
    """Il token del bot di Telegram e quello di un webhook di Discord stanno
    nel percorso, e finivano in chiaro nel log a ogni notifica (audit 2026-10-18)."""
    assert redact("POST https://api.telegram.org/bot123456:AAH-SECRETtoken_x/sendMessage") == (
        "POST https://api.telegram.org/bot<redacted>/sendMessage")
    assert redact("POST https://discord.com/api/webhooks/1234567890/abcDEF-secret_webhook 204") == (
        "POST https://discord.com/api/webhooks/1234567890/<redacted> 204")
    assert redact("http://admin:hunter2@qbit:8080/api") == "http://admin:<redacted>@qbit:8080/api"
    assert redact("git+https://ghp_SECRETPAT@github.com/me/plugin.git") == (
        "git+https://<redacted>@github.com/me/plugin.git")
    assert redact('{"url": "https://u:p4ss@h/x"}') == '{"url": "https://u:<redacted>@h/x"}'
    # Niente da togliere: resta com'era.
    for text in ("https://example.com/@user/feed", "see https://t.example/api/torrents", "a: b@c"):
        assert redact(text) == text


def test_the_httpx_request_line_keeps_only_method_host_and_status():
    import io

    import httpx

    from nazgarr.core.logs import HttpxRequestFilter, VerbosityFilter

    httpx_logger = logging.getLogger("httpx")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(VerbosityFilter())
    request_filter = HttpxRequestFilter()
    saved_level = httpx_logger.level
    httpx_logger.addHandler(handler)
    httpx_logger.addFilter(request_filter)
    httpx_logger.setLevel(logging.INFO)
    try:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        with httpx.Client(transport=transport) as client:
            client.post("https://api.telegram.org/bot123456:AAH-SECRET/sendMessage?chat_id=5")
            client.get("http://user:pw@[::1]:8080/x")
    finally:
        httpx_logger.removeHandler(handler)
        httpx_logger.removeFilter(request_filter)
        httpx_logger.setLevel(saved_level)
    lines = stream.getvalue().splitlines()
    assert lines[0] == 'DEBUG httpx: HTTP Request: POST https://api.telegram.org "HTTP/1.1 200 OK"'
    assert lines[1] == 'DEBUG httpx: HTTP Request: GET http://[::1]:8080 "HTTP/1.1 200 OK"'


def test_configure_logging_filters_the_httpx_logger_once():
    from nazgarr.core.logs import HttpxRequestFilter, configure_logging

    root = logging.getLogger()
    saved_handlers, saved_root_level = root.handlers[:], root.level
    httpx_logger = logging.getLogger("httpx")
    saved_filters, saved_level = httpx_logger.filters[:], httpx_logger.level
    try:
        configure_logging()
        configure_logging()
        assert sum(isinstance(f, HttpxRequestFilter) for f in httpx_logger.filters) == 1
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_root_level)
        httpx_logger.filters = saved_filters
        httpx_logger.setLevel(saved_level)


def test_the_plugin_list_never_shows_a_token(client, monkeypatch):
    from nazgarr.plugins import loader

    monkeypatch.setattr(loader.STATE, "requested", ["git+https://ghp_SECRETPAT@github.com/me/plugin.git"])
    monkeypatch.setattr(loader.STATE, "install_error", "fatal: https://ghp_SECRETPAT@github.com/me/plugin.git")
    body = client.get("/api/plugins").json()
    assert "SECRETPAT" not in str(body)
    assert body["requested"] == ["git+https://<redacted>@github.com/me/plugin.git"]


def test_every_error_and_detail_column_is_redacted_when_saved():
    """errors_json (quello che /api/runs mostra) e detail sfuggivano alla
    pulizia prima della scrittura (audit 2026-10-18)."""
    from nazgarr.core import redaction
    from nazgarr.core.models import Base

    columns = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith(("_error", "_detail")) or column.name in ("errors_json", "detail", "error_message")
    }
    assert columns and columns <= redaction.COLUMNS


def test_a_run_keeps_no_credential_in_its_error_list(db_session):
    import json
    from datetime import UTC, datetime

    from nazgarr.core.models import RunLog

    secret = "failed https://t.example/api/x?api_key=SUPERSECRET"
    run = RunLog(run_type="manual", started_at=datetime.now(UTC), last_error=secret, errors_json=json.dumps([secret]))
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    assert "SUPERSECRET" not in run.errors_json and "SUPERSECRET" not in run.last_error
    assert json.loads(run.errors_json) == ["failed https://t.example/api/x?api_key=<redacted>"]
