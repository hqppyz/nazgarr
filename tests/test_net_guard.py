import socket

import pytest

from nazgarr.core import net_guard


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/", "http://0.0.0.0:8080/",
    "http://[fd00:ec2::254]/", "http://[::ffff:169.254.169.254]/",
    "http://100.100.100.200/latest/meta-data/",          # metadati Alibaba Cloud
    "http://[64:ff9b::a9fe:a9fe]/",                      # NAT64 di 169.254.169.254
    "http://[2002:a9fe:a9fe::1]/",                       # 6to4 di 169.254.169.254
    "http://2852039166/", "http://0xa9fea9fe/",          # 169.254.169.254 decimale ed esadecimale
    "http://224.0.0.1/", "http://[ff02::1]/",            # multicast
])
def test_metadata_and_link_local_are_forbidden(url):
    with pytest.raises(net_guard.ForbiddenDestination):
        net_guard.check_url(url)


@pytest.mark.parametrize("url", [
    "http://192.168.1.10:8080/", "http://10.0.0.5/", "http://127.0.0.1:7878/",
    "http://100.101.102.103/",  # Tailscale (100.64.0.0/10): resta raggiungibile
    "http://[64:ff9b::c0a8:10a]/",  # NAT64 di 192.168.1.10
])
def test_the_lan_stays_reachable(url):
    net_guard.check_url(url)  # client torrent, Radarr e Sonarr vivono qui


def test_a_url_without_a_host_is_refused():
    with pytest.raises(net_guard.ForbiddenDestination):
        net_guard.check_url("file:///etc/passwd")


def _resolver(table):
    def resolve(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in table[host]]
    return resolve


def test_a_name_is_checked_on_every_address_it_resolves_to(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({
        "meta.example": ["169.254.169.254"],
        "mixed.example": ["192.168.1.10", "169.254.169.254"],  # basta un indirizzo vietato
        "nas.example": ["192.168.1.10", "10.0.0.5"],
        "group.example": ["239.1.2.3"],
    }))

    for host in ("meta.example", "mixed.example", "group.example"):
        with pytest.raises(net_guard.ForbiddenDestination):
            net_guard.check_url(f"http://{host}:8080/")
    net_guard.check_url("http://nas.example:8080/")


def test_a_name_that_does_not_resolve_passes_and_fails_at_the_request(monkeypatch):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({}))
    net_guard.check_url("https://nowhere.example/")


def test_a_host_that_cannot_be_encoded_is_refused_not_a_raw_unicode_error():
    # getaddrinfo solleva UnicodeError (non gaierror) per un'etichetta vuota o
    # più lunga di 63 caratteri: usciva grezzo da chi chiama check_url.
    for url in ("https://x..tracker.example/", "https://" + "a" * 70 + ".example/"):
        with pytest.raises(net_guard.ForbiddenDestination, match="Invalid host"):
            net_guard.check_url(url)
