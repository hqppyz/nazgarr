"""Il client HTTP del CLI: le stesse API JSON della web UI, con una API key
(X-Api-Key) o, solo per login e setup, il token del login. Gli errori del
server arrivano come codice e parametri e si mostrano con lo stesso testo
inglese dell'interfaccia (messages_en.json)."""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from nazgarr.core.errors import english

TIMEOUT_SECONDS = 60.0


def _default_client(base_url: str, headers: dict[str, str]) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT_SECONDS)


# Sostituibile nei test (un TestClient sull'app, senza rete).
CLIENT_FACTORY: Callable[[str, dict[str, str]], httpx.Client] = _default_client


def message(code: str, params: dict | None = None) -> str:
    return english(code, params)


class ApiError(Exception):
    def __init__(self, status: int, code: str, params: dict | None = None, text: str | None = None):
        self.status, self.code, self.params = status, code, params or {}
        super().__init__(text or message(code, params))


def _error(response: httpx.Response) -> ApiError:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict) and "code" in detail:
        return ApiError(response.status_code, detail["code"], detail.get("params"))
    if isinstance(detail, list):  # validazione di FastAPI
        text = "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
        return ApiError(response.status_code, "invalid_request", text=f"Invalid request: {text}")
    return ApiError(response.status_code, f"http_{response.status_code}",
                    text=str(detail) if detail else f"HTTP {response.status_code}")


def _public_address(host: str) -> bool:
    """Un host che si risolve in un indirizzo di internet. Uno che non si
    risolve no: la richiesta fallirà comunque, e non si avvisa a vuoto."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_global:  # non LAN, loopback, link-local né 100.64.0.0/10 (Tailscale)
            return True
    return False


_WARNED: set[str] = set()


def warn_if_insecure(url: str) -> None:
    """Un avviso, una volta per indirizzo, se password e API key andrebbero
    in chiaro su internet: http:// verso un indirizzo pubblico (audit
    2026-10-18). La LAN, una VPN e il loopback in http vanno bene
    (docs/SPEC.md, la stessa regola delle altre istanze), e il container usa
    http://127.0.0.1:3019. Solo un avviso: l'istanza può essere dietro un
    tunnel che il CLI non vede."""
    parts = urlsplit(url)
    if parts.scheme.lower() != "http" or not parts.hostname or url in _WARNED:
        return
    _WARNED.add(url)
    if _public_address(parts.hostname):
        from nazgarr.cli_client.output import err_console

        err_console.print(f"[yellow]Warning:[/yellow] {url} is a public address over http://: your password and "
                          "API key travel in clear. Use https:// (a reverse proxy with TLS) or a VPN.")


class Api:
    def __init__(self, url: str, api_key: str | None = None, token: str | None = None):
        warn_if_insecure(url.rstrip("/"))
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-Api-Key"] = api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.url = url.rstrip("/")
        self._client = CLIENT_FACTORY(self.url, headers)

    def request(self, method: str, path: str, *, json_body=None, params: dict | None = None):
        try:
            response = self._client.request(method, path, json=json_body,
                                            params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise ApiError(0, "connection_failed", text=f"Cannot reach {self.url}: {exc}") from exc
        if response.status_code >= 400:
            raise _error(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, **params):
        return self.request("GET", path, params=params)

    def post(self, path: str, body=None):
        return self.request("POST", path, json_body=body)

    def patch(self, path: str, body=None):
        return self.request("PATCH", path, json_body=body)

    def put(self, path: str, body=None):
        return self.request("PUT", path, json_body=body)

    def delete(self, path: str):
        return self.request("DELETE", path)
