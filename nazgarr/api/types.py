"""Tipi condivisi dai modelli delle richieste API."""

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator

from nazgarr.core import net_guard


def _http_url(value: str) -> str:
    """Solo http(s) con un host: un URL salvato finisce nei link della UI, e
    un "javascript:..." eseguirebbe codice al clic (XSS)."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("must be an http(s) URL")
    net_guard.check_url(value)  # mai i metadati del cloud o un link-local
    return value


HttpUrlStr = Annotated[str, AfterValidator(_http_url)]


def _netloc(url: str | None) -> str:
    return urlsplit(url or "").netloc.lower()


def host_changed(old_url: str | None, new_url: str | None) -> bool:
    return new_url is not None and _netloc(new_url) != _netloc(old_url)


def require_secrets_for_new_host(old_url: str | None, new_url: str | None, missing: list[str]) -> None:
    """Cambiare l'indirizzo di un servizio senza reinserirne i segreti li
    manderebbe al nuovo host: chi può modificare le impostazioni (anche una
    API key di scrittura) punterebbe un tracker a un proprio server e si
    farebbe mandare il token alla prima ricerca. Se l'host cambia, i segreti
    salvati (missing: quelli non reinseriti) vanno reinseriti nella stessa
    richiesta."""
    from fastapi import HTTPException

    from nazgarr.core.errors import coded_detail

    if not host_changed(old_url, new_url) or not missing:
        return
    raise HTTPException(status_code=400, detail=coded_detail("secret_required_for_new_host", fields=", ".join(missing)))
