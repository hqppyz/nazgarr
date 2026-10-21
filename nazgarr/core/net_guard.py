"""Destinazioni che una richiesta del server non raggiunge mai, qualunque
URL l'abbia chiesta (un tracker, un webhook, un link restituito da un
servizio esterno): indirizzi link-local, dove nei cloud vivono i metadati
con le credenziali dell'istanza (169.254.169.254, fd00:ec2::254, Alibaba
100.100.100.200), multicast e gli indirizzi "non specificati". Un IPv4
dentro un IPv6 (::ffff:a.b.c.d, NAT64 64:ff9b::/96, 6to4 2002::/16) vale
come l'IPv4 che porta. La LAN resta raggiungibile: client torrent, Radarr
e Sonarr ci vivono di solito, e il resto di 100.64.0.0/10 è Tailscale.

check_url risolve il nome quando lo si chiama, non quando il client HTTP
si connette: chi lo usa lo chiama prima di ogni richiesta (non solo quando
l'URL si salva), così un DNS cambiato dopo resta coperto. Fra quella
risoluzione e la connessione httpx risolveva di nuovo da sé, e un DNS che
cambia risposta in mezzo (DNS rebinding) portava la richiesta dove voleva.
Per gli URL che vengono da utenti o tracker la finestra è chiusa da
http_client (audit 2026-10-18): il client si connette solo agli indirizzi
controllati nel momento stesso della connessione, risolti una volta sola.
Host, SNI e verifica del certificato restano quelli del nome: si cambia
solo dove va il socket. Un nome che lì non si risolve è un errore di
connessione, come prima. Lo stesso per requests, su cui va qbittorrent-api
(requests_adapter, revisione dell'audit 2026-10-18).

Una richiesta attraverso un proxy (HTTPS_PROXY e simili, o un proxy dato al
client) la risolve il proxy, e il socket va al proxy: lì si controlla
l'host dell'URL prima di ogni richiesta (check_url), sia con httpx (pin) sia
con requests, così chi chiama non deve ricordarsene."""

import functools
import ipaddress
import socket
import sys
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpcore  # il trasporto di rete di httpx, dipendenza diretta (requirements.in)
import httpx

_METADATA = {ipaddress.ip_address("fd00:ec2::254"), ipaddress.ip_address("100.100.100.200")}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class ForbiddenDestination(ValueError):
    pass


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.sixtofour


def _forbidden(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        ip = _embedded_ipv4(ip) or ip
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip in _METADATA


def check_url(url: str) -> None:
    """ForbiddenDestination se l'host è (o si risolve in) una destinazione
    vietata. Un host che non si risolve passa: fallirà la richiesta stessa."""
    host = urlsplit(url).hostname
    if not host:
        raise ForbiddenDestination(f"URL without a host: {url!r}")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return
    except UnicodeError as exc:
        # Un'etichetta vuota o di più di 63 caratteri (x..tracker.example):
        # getaddrinfo non la codifica in IDNA, e non è un gaierror.
        raise ForbiddenDestination(f"Invalid host {host!r}") from exc
    if any(_forbidden(address) for address in addresses):
        raise ForbiddenDestination(f"{host} is not a destination Nazgarr calls")


# Le classi vere, prese all'import: un test può sostituire httpx.Client con
# un finto, che pin deve riconoscere e lasciare stare.
_CLIENT, _TRANSPORT = httpx.Client, httpx.HTTPTransport


class ForbiddenConnection(httpcore.ConnectError):
    """Una connessione verso una destinazione vietata, rifiutata nel momento
    in cui si apre: httpx la rende un httpx.ConnectError (col messaggio),
    che chi chiama gestisce già come un host che non risponde."""


def connect_addresses(host: str, port: int) -> list[str]:
    """Gli indirizzi a cui connettersi per host, risolti adesso, solo se
    nessuno è vietato (come check_url: ne basta uno). Un nome che non si
    risolve è un errore di connessione."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise httpcore.ConnectError(f"Cannot resolve {host}: {exc}") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise httpcore.ConnectError(f"Cannot resolve {host}")
    if any(_forbidden(address) for address in addresses):
        raise ForbiddenConnection(f"{host} is not a destination Nazgarr calls")
    return addresses


class _CheckedBackend(httpcore.NetworkBackend):
    """Il trasporto di rete di httpcore, ma la connessione TCP va a un
    indirizzo appena controllato (connect_addresses), nell'ordine di
    getaddrinfo come socket.create_connection, mai a un nome che il backend
    risolverebbe di nuovo. TLS si apre poi sul socket col nome dell'URL
    (SNI e verifica del certificato), come sempre."""

    def __init__(self, inner: httpcore.NetworkBackend):
        self._inner = inner

    def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                    socket_options: Iterable | None = None) -> httpcore.NetworkStream:
        last: Exception | None = None
        for address in connect_addresses(host, port):
            try:
                return self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                               socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Iterable | None = None) -> httpcore.NetworkStream:
        return self._inner.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def pin(client: httpx.Client) -> httpx.Client:
    """Fa connettere il client solo a indirizzi controllati al momento della
    connessione (_CheckedBackend), sul suo trasporto di rete. Un client con
    un trasporto suo (httpx.MockTransport nei test) o un finto restano come
    sono. Una richiesta che passa da un proxy (le variabili d'ambiente
    HTTPS_PROXY..., i mounts) la risolve il proxy: lì un hook controlla
    l'host prima di ogni richiesta (_check_proxied), con lo stesso errore di
    connessione (revisione dell'audit 2026-10-18: prima restava il solo
    check_url di chi chiamava, e Radarr/Sonarr, le istanze e i client non lo
    facevano a ogni richiesta). Se httpx non ha più il trasporto che ci si
    aspetta, si fallisce invece di lasciare la finestra aperta in silenzio."""
    transport = getattr(client, "_transport", None)
    if not isinstance(client, _CLIENT) or type(transport) is not _TRANSPORT:
        return client
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if not isinstance(pool, httpcore.ConnectionPool) or backend is None:
        raise RuntimeError("httpx transport without the expected connection pool: net_guard cannot pin it")
    if not isinstance(backend, _CheckedBackend):
        pool._network_backend = _CheckedBackend(backend)
    if any(mounted is not None for mounted in getattr(client, "_mounts", {}).values()):
        hooks = client.event_hooks
        if not any(getattr(hook, "_net_guard", False) for hook in hooks.get("request", [])):
            hooks["request"] = [*hooks.get("request", []), _check_proxied(client)]
            client.event_hooks = hooks
    return client


def _check_proxied(client: httpx.Client):
    """L'hook di richiesta di un client con dei proxy: l'host dell'URL si
    controlla adesso se la richiesta passa da un proxy (un altro trasporto
    del client: il suo è quello con gli indirizzi controllati). Senza il
    metodo di httpx che lo dice, si controlla ogni richiesta."""

    def check(request: httpx.Request) -> None:
        transport_for = getattr(client, "_transport_for_url", None)
        if callable(transport_for) and transport_for(request.url) is client._transport:
            return
        try:
            check_url(str(request.url))
        except ForbiddenDestination as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc

    check._net_guard = True  # type: ignore[attr-defined]
    return check


def http_client(**kwargs) -> httpx.Client:
    """httpx.Client(**kwargs) per gli URL che vengono da utenti o tracker:
    connesso solo a indirizzi controllati nel momento della connessione
    (pin). Chi chiama tiene il suo check_url prima di ogni richiesta, che
    dà l'errore chiaro di una destinazione vietata."""
    return pin(httpx.Client(**kwargs))


def requests_adapter(**kwargs):
    """Un requests.adapters.HTTPAdapter(**kwargs) che si connette solo a
    indirizzi controllati nel momento della connessione, come http_client:
    per qbittorrent-api, che va con requests (revisione dell'audit
    2026-10-18: lì restava la finestra fra il controllo del suo host,
    a ogni adapter costruito, e la risoluzione di requests). Host, SNI e
    certificato restano sul nome. Una richiesta attraverso un proxy si
    controlla con check_url prima di mandarla. requests e urllib3 ci sono
    con qbittorrent-api (requirements.txt), e si importano solo qui."""
    return _requests_classes()(**kwargs)


@functools.cache
def _requests_classes():
    import requests
    from requests.adapters import HTTPAdapter
    from requests.utils import select_proxy
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
    from urllib3.util.connection import create_connection

    class _Checked:
        """_new_conn di urllib3, ma il socket va a uno degli indirizzi appena
        controllati (connect_addresses), nell'ordine di getaddrinfo, mai al
        nome. TLS poi si apre sul socket col nome (server_hostname)."""

        def _new_conn(self):
            host = getattr(self, "_dns_host", None) or self.host
            try:
                addresses = connect_addresses(host, self.port)
            except httpcore.ConnectError as exc:  # vietato, o un nome che non si risolve
                raise NewConnectionError(self, str(exc)) from exc
            last: Exception | None = None
            for address in addresses:
                try:
                    sock = create_connection((address, self.port), self.timeout, source_address=self.source_address,
                                             socket_options=self.socket_options)
                except TimeoutError as exc:
                    last = ConnectTimeoutError(
                        self, f"Connection to {self.host} timed out. (connect timeout={self.timeout})")
                    last.__cause__ = exc
                except OSError as exc:
                    last = NewConnectionError(self, f"Failed to establish a new connection: {exc}")
                    last.__cause__ = exc
                else:
                    sys.audit("http.client.connect", self, self.host, self.port)
                    return sock
            assert last is not None
            raise last

    class _CheckedHTTPConnection(_Checked, HTTPConnection):
        pass

    class _CheckedHTTPSConnection(_Checked, HTTPSConnection):
        pass

    class _CheckedHTTPPool(HTTPConnectionPool):
        ConnectionCls = _CheckedHTTPConnection

    class _CheckedHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = _CheckedHTTPSConnection

    class CheckedHTTPAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            classes = getattr(self.poolmanager, "pool_classes_by_scheme", None)
            if not isinstance(classes, dict):
                raise RuntimeError("urllib3 without pool_classes_by_scheme: net_guard cannot pin requests")
            self.poolmanager.pool_classes_by_scheme = {**classes, "http": _CheckedHTTPPool,
                                                       "https": _CheckedHTTPSPool}

        def send(self, request, **kwargs):
            if select_proxy(request.url, kwargs.get("proxies") or {}):
                try:
                    check_url(request.url)
                except ForbiddenDestination as exc:
                    raise requests.exceptions.ConnectionError(str(exc), request=request) from exc
            return super().send(request, **kwargs)

    return CheckedHTTPAdapter
