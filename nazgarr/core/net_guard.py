"""Destinazioni che una richiesta del server non raggiunge mai, qualunque
URL l'abbia chiesta (un tracker, un webhook, un link restituito da un
servizio esterno): indirizzi link-local, dove nei cloud vivono i metadati
con le credenziali dell'istanza (169.254.169.254, fd00:ec2::254, Alibaba
100.100.100.200), multicast e gli indirizzi "non specificati". Un IPv4
dentro un IPv6 (::ffff:a.b.c.d, NAT64 64:ff9b::/96, 6to4 2002::/16) vale
come l'IPv4 che porta. La LAN resta raggiungibile: client torrent, Radarr
e Sonarr ci vivono di solito, e il resto di 100.64.0.0/10 è Tailscale.

Il controllo risolve il nome quando lo si chiama, non quando il client
HTTP si connette: chi lo usa lo chiama prima di ogni richiesta (non solo
quando l'URL si salva), così un DNS cambiato dopo resta coperto; la
finestra fra la risoluzione e la connessione resta (audit 2026-10-18)."""

import ipaddress
import socket
from urllib.parse import urlsplit

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
