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
connessione, come prima."""

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpcore  # di httpx, che lo richiede: il suo trasporto di rete
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
    sono; i proxy delle variabili d'ambiente (HTTPS_PROXY, ...) anche: lì è
    il proxy a risolvere il nome, e resta il controllo di check_url prima
    della richiesta. Se httpx non ha più il trasporto che ci si aspetta, si
    fallisce invece di lasciare la finestra aperta in silenzio."""
    transport = getattr(client, "_transport", None)
    if not isinstance(client, httpx.Client) or type(transport) is not httpx.HTTPTransport:
        return client
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if not isinstance(pool, httpcore.ConnectionPool) or backend is None:
        raise RuntimeError("httpx transport without the expected connection pool: net_guard cannot pin it")
    if not isinstance(backend, _CheckedBackend):
        pool._network_backend = _CheckedBackend(backend)
    return client


def http_client(**kwargs) -> httpx.Client:
    """httpx.Client(**kwargs) per gli URL che vengono da utenti o tracker:
    connesso solo a indirizzi controllati nel momento della connessione
    (pin). Chi chiama tiene il suo check_url prima di ogni richiesta, che
    dà l'errore chiaro di una destinazione vietata."""
    return pin(httpx.Client(**kwargs))
