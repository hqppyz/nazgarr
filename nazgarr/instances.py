"""Altre istanze di Nazgarr viste da questa (decisione dell'utente, 2026-10-03).

La web UI di questa istanza può passare a un'altra: tutte le chiamate vanno
qui, che le inoltra a quella con una sua API key (/api/remote/{id}/…,
nazgarr/api/instances.py). Il browser non vede mai la chiave e non serve CORS.
Il livello della chiave decide cosa si può fare: una di sola lettura
guarda e basta. Segreti, impostazioni di sicurezza e API key restano
dell'interfaccia di quell'istanza: una API key non li tocca.

Indirizzi: un'istanza in LAN o in VPN (indirizzi privati, Tailscale) anche
in http://; una con un indirizzo pubblico solo in https://, perché la chiave
non viaggi in chiaro su internet. Mai i metadati del cloud (nazgarr/net_guard.py).

Versioni (decisione dell'utente): l'interfaccia di questa istanza parla le
API della sua versione. Un'istanza remota più vecchia di una minor: avviso;
con una major diversa, o più nuova di questa: bloccata, finché non si
aggiornano allo stesso livello.
"""

import ipaddress
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from nazgarr import net_guard
from nazgarr.api_errors import CodedError
from nazgarr.version import __version__

TIMEOUT_SECONDS = 20.0
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


def probe(base_url: str, api_key: str) -> dict:
    """La prova di un'istanza: raggiungibile, versione, la chiave (valida, e
    di lettura o di scrittura), compatibilità con questa."""
    try:
        with CLIENT_FACTORY(base_url, api_key) as client:
            health = client.get("/api/health")
            health.raise_for_status()
            version = health.json().get("version")
            who = client.get("/api/system/whoami")
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "unreachable", "error": str(exc), "version": None, "level": None,
                "compatibility": "unknown"}
    if who.status_code in (401, 403):
        return {"status": "bad_key", "error": None, "version": version, "level": None,
                "compatibility": compatibility(version)}
    level = who.json().get("level") if who.status_code == 200 else None
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
_DENIED = ("api/auth", "api/api-keys", "api/instances", "api/remote")


def proxied_path(path: str) -> str:
    path = path.lstrip("/")
    if not path.startswith("api/") or any(path == d or path.startswith(d + "/") for d in _DENIED) or ".." in path:
        raise InstanceError("instance_path_not_allowed", path=path)
    return "/" + path
