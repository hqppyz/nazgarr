"""Destinazioni che una richiesta del server non raggiunge mai, qualunque
URL l'abbia chiesta (un tracker, un webhook, un link restituito da un
servizio esterno): indirizzi link-local, dove nei cloud vivono i metadati
con le credenziali dell'istanza (169.254.169.254, fd00:ec2::254), e gli
indirizzi "non specificati". La LAN resta raggiungibile: client torrent,
Radarr e Sonarr ci vivono di solito."""

import ipaddress
import socket
from urllib.parse import urlsplit

_METADATA = {ipaddress.ip_address("fd00:ec2::254")}


class ForbiddenDestination(ValueError):
    pass


def _forbidden(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
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
    if any(_forbidden(address) for address in addresses):
        raise ForbiddenDestination(f"{host} is not a destination Nazgarr calls")
