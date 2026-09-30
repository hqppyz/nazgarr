"""Tipi condivisi dai modelli delle richieste API."""

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator


def _http_url(value: str) -> str:
    """Solo http(s) con un host: un URL salvato finisce nei link della UI, e
    un "javascript:..." eseguirebbe codice al clic (XSS)."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("must be an http(s) URL")
    return value


HttpUrlStr = Annotated[str, AfterValidator(_http_url)]
