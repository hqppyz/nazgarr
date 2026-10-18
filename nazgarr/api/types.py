"""Tipi condivisi dai modelli delle richieste API."""

import ipaddress
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator

from nazgarr.core import net_guard


def _ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


def _http_url(value: str) -> str:
    """Solo http(s) con un host: un URL salvato finisce nei link della UI, e
    un "javascript:..." eseguirebbe codice al clic (XSS).

    Di net_guard qui solo gli indirizzi IP scritti per esteso, che non si
    risolvono: i validatori girano sul loop di FastAPI, e una risoluzione DNS
    lenta fermava ogni richiesta del processo. I nomi li controlla
    check_destinations nell'endpoint, nel threadpool (audit 2026-10-18)."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or not parts.hostname:
        raise ValueError("must be an http(s) URL")
    if _ip_literal(parts.hostname):
        net_guard.check_url(value)  # mai i metadati del cloud o un link-local
    return value


# Solo la forma dell'URL (e gli IP scritti per esteso): un endpoint che riceve
# un HttpUrlStr deve chiamare check_destinations, se no un nome che punta ai
# metadati del cloud passa. tests/test_api_url_types.py prova ogni route che
# ne ha uno.
HttpUrlStr = Annotated[str, AfterValidator(_http_url)]


def check_destinations(*urls: str | None) -> None:
    """net_guard per i nomi degli HttpUrlStr di una richiesta (mai i metadati
    del cloud o un link-local, anche dietro un nome): da chiamare
    nell'endpoint (def, nel threadpool), mai nel validatore. Nell'errore solo
    l'host: un announce URL ha la passkey nel percorso."""
    from fastapi import HTTPException

    from nazgarr.core.errors import coded_detail

    for url in urls:
        if not url:
            continue
        try:
            net_guard.check_url(url)
        except net_guard.ForbiddenDestination as exc:
            raise HTTPException(status_code=422, detail=coded_detail(
                "instance_url_forbidden", url=urlsplit(url).hostname or "")) from exc


def _destination(url: str | None) -> tuple[str, str]:
    parts = urlsplit(url or "")
    return parts.scheme.lower(), parts.netloc.lower()


def _change(old_url: str | None, new_url: str | None) -> str | None:
    """"host" se l'host è un altro, "insecure" se è lo stesso passato da https
    a http, None se no (o se l'indirizzo non cambia)."""
    if new_url is None:
        return None
    old_scheme, old_netloc = _destination(old_url)
    new_scheme, new_netloc = _destination(new_url)
    if new_netloc != old_netloc:
        return "host"
    return "insecure" if old_scheme == "https" and new_scheme == "http" else None


def host_changed(old_url: str | None, new_url: str | None) -> bool:
    """Un altro host, o lo stesso passato da https a http: in tutti e due i
    casi i segreti salvati arriverebbero a chi prima non li vedeva (nel
    secondo in chiaro, a chiunque sia sulla strada; audit 2026-10-18)."""
    return _change(old_url, new_url) is not None


def require_secrets_for_new_host(old_url: str | None, new_url: str | None, missing: list[str]) -> None:
    """Cambiare l'indirizzo di un servizio senza reinserirne i segreti li
    manderebbe al nuovo host: chi può modificare le impostazioni (anche una
    API key di scrittura) punterebbe un tracker a un proprio server e si
    farebbe mandare il token alla prima ricerca. Se l'host cambia (o passa da
    https a http), i segreti salvati (missing: quelli non reinseriti) vanno
    reinseriti nella stessa richiesta. Per il passaggio a http un codice a
    parte: il messaggio dell'altro parla di un nuovo host."""
    from fastapi import HTTPException

    from nazgarr.core.errors import coded_detail

    change = _change(old_url, new_url)
    if change is None or not missing:
        return
    code = "secret_required_for_new_host" if change == "host" else "secret_required_for_insecure_scheme"
    raise HTTPException(status_code=400, detail=coded_detail(code, fields=", ".join(missing)))
