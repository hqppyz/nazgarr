import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpcore
import httpx
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


# --- la connessione va all'indirizzo controllato (audit 2026-10-18) ----------------

def _changing_resolver(answers):
    """Un DNS che a ogni domanda per un nome dà la risposta successiva (un
    rebinding: prima un indirizzo pubblico, poi i metadati del cloud)."""
    asked = []

    def resolve(host, port, *args, **kwargs):
        asked.append(host)
        table = answers[host]
        ips = table.pop(0) if len(table) > 1 else table[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in ips]
    return resolve, asked


@pytest.fixture
def connects(monkeypatch):
    """Ogni connect_tcp che arriva al backend vero di httpcore, che qui non
    apre niente (nessuna rete nei test)."""
    calls = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        calls.append((host, port))
        raise httpcore.ConnectError("no network in tests")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)
    return calls


def test_a_name_rebound_after_the_check_is_never_connected_to(monkeypatch, connects):
    resolve, asked = _changing_resolver({"tracker.example": [["93.184.216.34"], ["169.254.169.254"]]})
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    client = net_guard.http_client()

    net_guard.check_url("http://tracker.example/latest/meta-data/")  # al controllo: un indirizzo pubblico
    with pytest.raises(httpx.ConnectError, match="not a destination"):
        client.get("http://tracker.example/latest/meta-data/")

    assert asked == ["tracker.example", "tracker.example"]  # risolto di nuovo solo per connettersi
    assert connects == []  # mai un socket verso i metadati


def test_the_socket_goes_to_the_checked_address_and_tls_keeps_the_name(monkeypatch):
    """Il socket va all'IP controllato; SNI e verifica del certificato
    (server_hostname) restano sul nome dell'URL, e così l'header Host."""
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _changing_resolver(
        {"tracker.example": [["93.184.216.34", "93.184.216.35"]]})[0])
    seen = {}

    class Stream(httpcore.NetworkStream):
        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            seen["server_hostname"] = server_hostname
            raise httpcore.ConnectError("stop after the handshake would start")

        def close(self):
            pass

    attempts = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        attempts.append(host)
        if host == "93.184.216.34":
            raise httpcore.ConnectError("unreachable")  # il primo non risponde: si prova il secondo
        return Stream()

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)
    with pytest.raises(httpx.ConnectError):
        net_guard.http_client().get("https://tracker.example/api/torrents")

    assert attempts == ["93.184.216.34", "93.184.216.35"]
    assert seen["server_hostname"] == "tracker.example"


def test_a_pinned_client_still_talks_http_with_the_original_host(monkeypatch):
    hosts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hosts.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    real_getaddrinfo = socket.getaddrinfo

    def resolve(host, *args, **kwargs):
        return real_getaddrinfo("127.0.0.1" if host == "arr.example" else host, *args, **kwargs)

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    try:
        with net_guard.http_client(timeout=5) as client:
            response = client.get(f"http://arr.example:{port}/api/v3/system/status")
    finally:
        server.shutdown()
        server.server_close()

    assert (response.status_code, response.text) == (200, "ok")
    assert hosts == [f"arr.example:{port}"]


def test_a_name_that_does_not_resolve_when_connecting_is_a_connect_error(monkeypatch, connects):
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({}))
    with pytest.raises(httpx.ConnectError, match="Cannot resolve"):
        net_guard.http_client().get("http://gone.example/")
    assert connects == []


def test_pin_leaves_clients_with_their_own_transport_alone():
    mock = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204)))
    assert net_guard.pin(mock) is mock and mock.get("http://169.254.169.254/").status_code == 204
    pinned = net_guard.http_client()
    backend = pinned._transport._pool._network_backend
    assert net_guard.pin(pinned)._transport._pool._network_backend is backend  # una volta sola


def test_every_client_for_a_user_or_tracker_url_is_pinned(monkeypatch, tmp_path, db_session):
    """I client costruiti per gli URL che vengono da utenti o tracker:
    tracker, Radarr/Sonarr (e la loro prova), altre istanze, webhook (e la
    loro prova), icone dei tracker."""
    from types import SimpleNamespace

    from nazgarr.adapters.tracker.base import Unit3dTrackerAdapter
    from nazgarr.api import arr_instances
    from nazgarr.integrations import arr, instances, webhooks
    from nazgarr.torrents import tracker_icons

    def pinned(client) -> bool:
        return isinstance(client._transport._pool._network_backend, net_guard._CheckedBackend)

    instance = SimpleNamespace(basic_auth_username=None, basic_auth_password=None, label="r", id=1,
                               base_url="http://radarr:7878", api_key="k", timeout_seconds=15)
    assert pinned(Unit3dTrackerAdapter("https://t.example", "token")._client)
    assert pinned(arr.ArrApi(instance)._client)
    assert pinned(arr_instances.status_client(None, 5))
    assert pinned(instances._default_client("https://other.example", "key"))

    built = []
    real = net_guard.http_client
    monkeypatch.setattr(net_guard, "http_client", lambda **kw: built.append(kw) or real(**kw))
    webhooks.deliver_due(db_session)
    tracker_icons.fetch_icon(str(tmp_path), 1, "https://t.example")  # nessun DNS: nessuna icona
    assert len(built) == 2
