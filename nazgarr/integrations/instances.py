"""Altre istanze di Nazgarr viste da questa (decisione dell'utente, 2026-10-03).

La web UI di questa istanza può passare a un'altra: tutte le chiamate vanno
qui, che le inoltra a quella con una sua API key (/api/remote/{id}/…,
nazgarr/api/instances.py). Il browser non vede mai la chiave e non serve CORS.
Il livello della chiave decide cosa si può fare: una di sola lettura
guarda e basta. Segreti, impostazioni di sicurezza e API key restano
dell'interfaccia di quell'istanza: una API key non li tocca.

Indirizzi: un'istanza in LAN o in VPN (indirizzi privati, Tailscale) anche
in http://; una con un indirizzo pubblico solo in https://, perché la chiave
non viaggi in chiaro su internet. Mai i metadati del cloud (nazgarr/core/net_guard.py).

Versioni (decisione dell'utente): l'interfaccia di questa istanza parla le
API della sua versione. Un'istanza remota più vecchia di una minor: avviso;
con una major diversa, o più nuova di questa: bloccata, finché non si
aggiornano allo stesso livello.
"""

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from nazgarr.core import http_limits, net_guard
from nazgarr.core.errors import CodedError
from nazgarr.core.version import __version__

TIMEOUT_SECONDS = 20.0
# La prova legge due risposte di poche centinaia di byte: un'istanza ostile
# (o compromessa) non le fa diventare gigabyte in memoria (audit 2026-10-18).
PROBE_MAX_BYTES = 64 * 1024
HEALTH_TTL_SECONDS = 60.0
# Tailscale e simili (CGNAT, 100.64.0.0/10): non pubblico, come la LAN.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class InstanceError(CodedError):
    pass


def _default_client(base_url: str, api_key: str | None) -> httpx.Client:
    headers = {"X-Api-Key": api_key} if api_key else {}
    return httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=False)


# Sostituibile nei test.
CLIENT_FACTORY: Callable[[str, str | None], httpx.Client] = _default_client


def normalize_url(url: str) -> str:
    """L'indirizzo pulito (senza / finale), o InstanceError: schema http(s),
    un host, niente metadati del cloud, https se l'host è pubblico."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InstanceError("instance_url_invalid", url=url)
    try:
        net_guard.check_url(url)
    except net_guard.ForbiddenDestination as exc:
        raise InstanceError("instance_url_forbidden", url=url) from exc
    if parts.scheme == "http" and is_public(parts.hostname):
        raise InstanceError("instance_needs_https", url=url)
    return url


def is_public(host: str) -> bool:
    """Un host che si risolve in un indirizzo pubblico (internet). Un nome
    che non si risolve conta come pubblico: nel dubbio, https."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return True
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not (ip.is_private or ip.is_loopback or (ip.version == 4 and ip in _CGNAT)):
            return True
    return False


_VERSION = re.compile(r"^(\d+)\.(\d+)")


def _major_minor(version: str | None) -> tuple[int, int] | None:
    match = _VERSION.match(version or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def compatibility(remote_version: str | None, local_version: str = __version__) -> str:
    """ok, warn (l'altra è più vecchia di una minor), block_major (major
    diversa), block_newer (l'altra è più nuova di questa: questa interfaccia
    non conosce le sue API). unknown se non si legge la versione."""
    local, remote = _major_minor(local_version), _major_minor(remote_version)
    if local is None or remote is None:
        return "unknown"
    if remote[0] != local[0]:
        return "block_major"
    if remote > local:
        return "block_newer"
    if remote < local:
        return "warn"
    return "ok"


def blocked(status: str) -> bool:
    return status.startswith("block")


def _get_capped(client: httpx.Client, path: str, deadline: float) -> tuple[int, bytes]:
    """Stato e corpo (al massimo PROBE_MAX_BYTES, decompressi qui a passi
    limitati, nazgarr/core/http_limits.py) di un GET; il corpo di un errore
    non si legge. ResponseLimitExceeded se è più grande o troppo lento."""
    with client.stream("GET", path, headers={"Accept-Encoding": http_limits.ACCEPT_ENCODING}) as response:
        if response.status_code >= 400:
            return response.status_code, b""
        return response.status_code, http_limits.read_limited(response, PROBE_MAX_BYTES, deadline)


def _object(body: bytes) -> dict:
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def probe(base_url: str, api_key: str) -> dict:
    """La prova di un'istanza: raggiungibile, versione, la chiave (valida, e
    di lettura o di scrittura), compatibilità con questa."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with CLIENT_FACTORY(base_url, api_key) as client:
            status, body = _get_capped(client, "/api/health", deadline)
            if status >= 400:
                raise ValueError(f"/api/health answered HTTP {status}")
            version = _object(body).get("version")
            try:
                who_status, who_body = _get_capped(client, "/api/system/whoami", deadline)
            except http_limits.ResponseLimitExceeded:
                who_status, who_body = 200, b""  # non è whoami: livello sconosciuto, come sotto
    except (httpx.HTTPError, ValueError, http_limits.ResponseLimitExceeded) as exc:
        return {"status": "unreachable", "error": str(exc), "version": None, "level": None,
                "compatibility": "unknown"}
    if who_status in (401, 403):
        return {"status": "bad_key", "error": None, "version": version, "level": None,
                "compatibility": compatibility(version)}
    # Un'istanza di prima di /api/system/whoami (0.7.x) non sa dire il livello
    # della chiave: connessa lo stesso, livello sconosciuto.
    try:
        level = _object(who_body).get("level") if who_status == 200 else None
    except ValueError:
        level = None
    return {"status": "ok", "error": None, "version": version, "level": level,
            "compatibility": compatibility(version)}


# L'ultima prova di ogni istanza, per non chiedere la versione a ogni
# chiamata inoltrata (il proxy rifiuta un'istanza bloccata).
_health: dict[int, tuple[float, dict]] = {}


def cached_probe(instance_id: int, base_url: str, api_key: str, fresh: bool = False) -> dict:
    now = time.monotonic()
    hit = _health.get(instance_id)
    if not fresh and hit and now - hit[0] < HEALTH_TTL_SECONDS:
        return hit[1]
    result = probe(base_url, api_key)
    _health[instance_id] = (now, result)
    return result


def forget(instance_id: int) -> None:
    _health.pop(instance_id, None)


# Cosa il proxy non inoltra mai: il login e le chiavi dell'altra istanza, e
# le istanze/il proxy stesso (niente catene).
_DENIED = frozenset({"auth", "api-keys", "instances", "remote"})


def proxied_path(path: str) -> str:
    """Il percorso da chiamare sull'altra istanza, controllato segmento per
    segmento. Prima il controllo era sulla stringa: "api/./auth/..."
    passava, e httpx lo normalizzava in /api/auth/... prima di mandarlo
    (audit 2026-10-18). Ora un segmento vuoto, "." o "..", o un "%" (un
    segmento codificato due volte) è un rifiuto, e il percorso mandato è
    quello fatto dei segmenti controllati."""
    path = path.lstrip("/")
    trailing = path.endswith("/")
    segments = (path[:-1] if trailing else path).split("/")
    if ("%" in path or len(segments) < 2 or segments[0] != "api"
            or any(segment in ("", ".", "..") for segment in segments)
            or segments[1].lower() in _DENIED):
        raise InstanceError("instance_path_not_allowed", path=path)
    return "/" + "/".join(segments) + ("/" if trailing else "")
