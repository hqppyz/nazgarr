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
        def do_GET(self):  # il nome lo vuole BaseHTTPRequestHandler
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


def test_the_torrent_client_adapters_are_pinned_and_keep_the_lan(monkeypatch, connects):
    """Deluge, qui, Transmission e rTorrent (httpx) si connettono solo
    all'indirizzo controllato nel momento della connessione, come gli altri
    URL scritti da un utente (audit 2026-10-18, #79): un nome del client
    che dopo il salvataggio risolve ai metadati del cloud non si raggiunge
    mai. La LAN, dove vivono i client, resta raggiungibile."""
    from nazgarr.adapters.torrent_client.deluge import DelugeAdapter
    from nazgarr.adapters.torrent_client.qui import QuiTorrentClientAdapter
    from nazgarr.adapters.torrent_client.rtorrent import RTorrentAdapter
    from nazgarr.adapters.torrent_client.transmission import TransmissionAdapter

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({
        "nas.example": ["192.168.1.10"], "rebound.example": ["169.254.169.254"]}))
    adapters = [
        DelugeAdapter("http://nas.example:8112", "pw"),
        QuiTorrentClientAdapter("http://nas.example:7476", "key", instance_id=1),
        TransmissionAdapter("http://nas.example:9091", "u", "p"),
        RTorrentAdapter("http://nas.example/RPC2", "u", "p"),
    ]
    for adapter in adapters:
        assert isinstance(adapter._client._transport._pool._network_backend, net_guard._CheckedBackend)
        with pytest.raises(httpx.ConnectError, match="not a destination"):
            adapter._client.get("http://rebound.example/latest/meta-data/")
        with pytest.raises(httpx.ConnectError, match="no network in tests"):
            adapter._client.get("http://nas.example:8080/")  # arriva al socket, verso la LAN
    assert connects == [("192.168.1.10", 8080)] * len(adapters)

    with pytest.raises(httpx.ConnectError, match="not a destination"):
        QuiTorrentClientAdapter.list_instances("http://rebound.example:7476", "key")


def test_qbittorrent_checks_its_host_whenever_an_adapter_is_built(monkeypatch):
    """L'host si ricontrolla a ogni adapter costruito (uno per operazione),
    non solo al salvataggio, per l'errore chiaro; la connessione poi va solo
    a indirizzi controllati (test_qbittorrent_connects_only_to_checked_addresses)."""
    from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({
        "nas.example": ["192.168.1.10"], "rebound.example": ["169.254.169.254"]}))
    QBittorrentAdapter("http://nas.example:8080", "u", "p")
    QBittorrentAdapter("nas.example:8080", "u", "p")  # senza schema, come lo accetta qbittorrent-api
    for url in ("http://rebound.example:8080", "rebound.example:8080"):
        with pytest.raises(net_guard.ForbiddenDestination):
            QBittorrentAdapter(url, "u", "p")


def test_the_notification_services_are_pinned_too(monkeypatch, connects):
    """Discord e Telegram hanno host fissi, ma il loro nome passa per lo
    stesso DNS: anche loro col client che si connette solo all'indirizzo
    controllato (audit 2026-10-18, #79), non un httpx.Client dopo check_url."""
    from nazgarr.adapters.notification.base import Notification, NotificationError
    from nazgarr.adapters.notification.discord import DiscordNotificationAdapter
    from nazgarr.adapters.notification.telegram import TelegramNotificationAdapter

    resolve, _asked = _changing_resolver({
        "discord.com": [["162.159.135.232"], ["169.254.169.254"]],
        "api.telegram.org": [["149.154.167.220"], ["169.254.169.254"]],
    })
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    built = []
    real = net_guard.http_client

    def recording(**kwargs):
        built.append(real(**kwargs))
        return built[-1]

    monkeypatch.setattr(net_guard, "http_client", recording)
    note = Notification(event="upload.finished", title="t", body="b")
    for adapter in (DiscordNotificationAdapter("https://discord.com/api/webhooks/1/abc"),
                    TelegramNotificationAdapter("1:secret", "42")):
        with pytest.raises(NotificationError, match="not reachable"):
            adapter.send(note)  # al controllo un indirizzo pubblico, alla connessione i metadati

    assert len(built) == 2
    assert all(isinstance(c._transport._pool._network_backend, net_guard._CheckedBackend) for c in built)
    assert connects == []  # mai un socket verso i metadati



# --- requests (qbittorrent-api) e proxy (revisione dell'audit 2026-10-18) ---------

def _http_server(hosts):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # il nome lo vuole BaseHTTPRequestHandler
            hosts.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _requests_session():
    import requests

    session = requests.Session()
    adapter = net_guard.requests_adapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def test_requests_connects_to_the_checked_address_with_the_original_host(monkeypatch):
    hosts = []
    server = _http_server(hosts)
    port = server.server_address[1]
    real_getaddrinfo = socket.getaddrinfo
    asked = []

    def resolve(host, *args, **kwargs):
        asked.append(host)
        return real_getaddrinfo("127.0.0.1" if host == "qbit.example" else host, *args, **kwargs)

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    try:
        response = _requests_session().get(f"http://qbit.example:{port}/api/v2/app/version", timeout=5)
    finally:
        server.shutdown()
        server.server_close()

    assert (response.status_code, response.text) == (200, "ok")
    assert hosts == [f"qbit.example:{port}"]
    assert asked[0] == "qbit.example" and "qbit.example" not in asked[1:]  # risolto una volta, poi l'IP


def test_requests_never_connects_to_a_name_rebound_after_the_check(monkeypatch):
    import requests

    resolve, asked = _changing_resolver({"qbit.example": [["93.184.216.34"], ["169.254.169.254"]]})
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", resolve)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)

    net_guard.check_url("http://qbit.example:8080/")  # al controllo: un indirizzo pubblico
    with pytest.raises(requests.exceptions.ConnectionError, match="not a destination"):
        _requests_session().get("http://qbit.example:8080/api/v2/app/version", timeout=5)
    assert asked == ["qbit.example", "qbit.example"]


def test_qbittorrent_connects_only_to_checked_addresses(monkeypatch):
    """qbittorrent-api va con requests: prima restava la finestra fra il
    controllo dell'host e la risoluzione di requests. Ogni sessione che il
    client costruisce, anche dopo averla rifatta, usa l'adapter di net_guard."""
    from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({"nas.example": ["192.168.1.10"]}))
    client = QBittorrentAdapter("http://nas.example:8080", "u", "p")._client
    checked = type(net_guard.requests_adapter())

    for _ in range(2):
        session = client._session
        assert isinstance(session.get_adapter("http://nas.example"), checked)
        assert isinstance(session.get_adapter("https://nas.example"), checked)
        assert session.get_adapter("http://nas.example").max_retries.total == 1  # i tentativi di qbittorrent-api
        client._trigger_session_initialization()  # come dopo la scelta dello schema


def test_no_thread_gets_a_qbittorrent_session_before_it_is_pinned(monkeypatch):
    """Revisione dell'audit 2026-10-18: qbittorrent-api pubblica la sessione
    nuova prima di montarci il suo adapter, e i thread dei file
    dell'indicizzazione potevano prenderla lì, con l'adapter senza controlli.
    Qui la costruzione si allarga apposta, mentre altri thread la chiedono."""
    import threading
    import time

    import qbittorrentapi

    from nazgarr.adapters.torrent_client.qbittorrent import QBittorrentAdapter

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({"nas.example": ["192.168.1.10"]}))
    client = QBittorrentAdapter("http://nas.example:8080", "u", "p")._client
    checked = type(net_guard.requests_adapter())
    original = qbittorrentapi.Client._session.fget

    def slow_session(self):
        fresh = self._http_session is None
        session = original(self)
        if fresh:
            time.sleep(0.01)  # la sessione è già pubblicata, il nostro adapter non ancora montato
        return session

    monkeypatch.setattr(qbittorrentapi.Client, "_session", property(slow_session))
    seen, stop = [], threading.Event()

    def worker():
        while not stop.is_set():
            seen.append(isinstance(client._session.get_adapter("https://nas.example"), checked))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(10):
        client._trigger_session_initialization()  # come dopo un errore di connessione
        time.sleep(0.005)
    stop.set()
    for thread in threads:
        thread.join(5)

    assert seen and all(seen)


def test_a_request_through_a_proxy_checks_its_host_first(monkeypatch):
    """Lì il nome lo risolve il proxy: prima si fidava del solo check_url di
    chi chiamava, che Radarr/Sonarr, le istanze e i client non facevano a ogni
    richiesta."""
    import requests

    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({
        "meta.example": ["169.254.169.254"], "ok.example": ["93.184.216.34"]}))
    proxied = []
    mock = httpx.MockTransport(lambda request: proxied.append(request.url.host) or httpx.Response(204))
    client = net_guard.http_client(mounts={"all://": mock})

    with pytest.raises(httpx.ConnectError, match="not a destination"):
        client.get("https://meta.example/latest/meta-data/")
    assert client.get("https://ok.example/").status_code == 204 and proxied == ["ok.example"]
    assert len(net_guard.pin(client).event_hooks["request"]) == 1  # un hook solo

    session = _requests_session()
    session.proxies = {"https": "http://proxy.example:3128"}
    with pytest.raises(requests.exceptions.ConnectionError, match="not a destination"):
        session.get("https://meta.example/latest/meta-data/", timeout=5)


def test_the_environment_proxies_are_checked_too(monkeypatch, connects):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", _resolver({"meta.example": ["169.254.169.254"]}))

    with pytest.raises(httpx.ConnectError, match="not a destination"):
        net_guard.http_client().get("https://meta.example/")
    assert connects == []
