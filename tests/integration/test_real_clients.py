"""Gli adapter dei client torrent contro client veri, in Docker.

Saltati salvo NAZGARR_IT_CLIENTS=1: li avvia scripts/test_real_clients.sh,
che fa partire i container, imposta le variabili qui sotto e poi li toglie.
Mai in CI.

Per ogni client:
- NAZGARR_IT_DIR/<client>/seed è montata nel container come /srv/seed, un
  percorso che qui non esiste: la save path passa da nazgarr/client_paths.py
  (Nazgarr <client>/seed = client /srv/seed), e un .torrent passato per
  percorso invece che per contenuto non verrebbe trovato dal client;
- i .torrent (torf) stanno in NAZGARR_IT_DIR/<client>/nazgarr, che il client
  non vede;
- un .torrent servito via HTTP (host.docker.internal) prova che un URL resta
  un URL e lo scarica il client.

Variabili: NAZGARR_IT_<CLIENT>_URL (TRANSMISSION, DELUGE, RTORRENT,
RUTORRENT), NAZGARR_IT_<CLIENT>_USER/_PASSWORD, NAZGARR_IT_HTTP_HOST (come i
container raggiungono questa macchina).
"""

import http.server
import os
import shutil
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
import torf

from nazgarr import adapter_factory, client_paths
from nazgarr.adapters.torrent_client.base import TorrentAlreadyInClientError

pytestmark = pytest.mark.skipif(
    os.environ.get("NAZGARR_IT_CLIENTS") != "1", reason="real clients only with NAZGARR_IT_CLIENTS=1"
)

CLIENT_ROOT = "/srv/seed"
TRACKER = "http://tracker.invalid/announce"
# client -> (adapter_type, cartella condivisa: rTorrent e ruTorrent sono lo stesso container)
CLIENTS = {
    "transmission": ("transmission", "transmission"),
    "deluge": ("deluge", "deluge"),
    "rtorrent": ("rutorrent", "rtorrent"),
    "rutorrent": ("rutorrent", "rtorrent"),
}


def _env(name: str, key: str) -> str | None:
    return os.environ.get(f"NAZGARR_IT_{name.upper()}_{key}")


def _adapter(name: str):
    url = _env(name, "URL")
    if not url:
        pytest.skip(f"{name}: NAZGARR_IT_{name.upper()}_URL not set")
    row = SimpleNamespace(id=name, adapter_type=CLIENTS[name][0], base_url=url, username=_env(name, "USER"),
                          password=_env(name, "PASSWORD"), adapter_config_json=None)
    adapter = adapter_factory.build_torrent_client_adapter(row)
    if name == "deluge":
        # Preparazione del client per il test, non dell'adapter: la categoria
        # in Deluge è una label del plugin Label, che Nazgarr non accende mai.
        adapter._call("core.enable_plugin", "Label")
    if name == "rutorrent":
        # Come aprire la UI di ruTorrent una volta: inizializza i suoi plugin
        # (erasedata, che cancella i file di un torrent rimosso coi dati) e i
        # nomi dei comandi per la versione di rTorrent.
        httpx.get(url.rstrip("/") + "/php/getplugins.php", timeout=60).raise_for_status()
    return adapter


def _wait(fn, timeout=90.0, every=0.5):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(every)


def _settled(adapter, info_hash):
    """Lo stato dopo il recheck: si aspetta che non sia più pending."""
    seen = []

    def check():
        status = adapter.get_torrent_status(info_hash)
        seen.append(status.state)
        return status if status.recheck_status != "pending" else None

    status = _wait(check)
    assert status is not None, f"recheck never finished: {seen[-5:]}"
    return status, seen


@pytest.fixture
def workspace(request):
    name = request.param
    base = os.path.join(os.environ["NAZGARR_IT_DIR"], CLIENTS[name][1])
    seed, data = os.path.join(base, "seed"), os.path.join(base, f"nazgarr-{name}")
    os.makedirs(seed, exist_ok=True)
    os.makedirs(data, exist_ok=True)
    tag = f"{name}-{uuid.uuid4().hex[:6]}"
    mapping = client_paths.Mapping(disk_root=base, client_root=CLIENT_ROOT, local_rel="seed")
    yield SimpleNamespace(name=name, seed=seed, data=data, tag=tag, mapping=mapping)
    shutil.rmtree(data, ignore_errors=True)


def _make_torrent(ws, source: str, private=True) -> tuple[str, torf.Torrent]:
    torrent = torf.Torrent(path=source, trackers=[TRACKER], private=private, piece_size=16384)
    torrent.generate()
    out = os.path.join(ws.data, os.path.basename(source) + ".torrent")
    torrent.write(out, overwrite=True)
    return out, torrent


def _payload_single(ws) -> str:
    path = os.path.join(ws.seed, f"nzg-it-{ws.tag}.mkv")
    with open(path, "wb") as f:
        f.write(os.urandom(300_000))
    return path


def _payload_multi(ws) -> str:
    # Spazio e virgola nel nome: niente quoting fatto a mano nei comandi.
    folder = os.path.join(ws.seed, f"NZG IT, multi {ws.tag}")
    os.makedirs(os.path.join(folder, "Extras"))
    with open(os.path.join(folder, "movie.mkv"), "wb") as f:
        f.write(os.urandom(250_000))
    with open(os.path.join(folder, "Extras", "sample.mkv"), "wb") as f:
        f.write(os.urandom(70_000))
    return folder


def _files_of(torrent: torf.Torrent) -> dict[str, int]:
    return {str(f): f.size for f in torrent.files}


@pytest.mark.parametrize("workspace", list(CLIENTS), indirect=True)
@pytest.mark.parametrize("layout", ["single", "multi"])
def test_add_recheck_info_and_remove(workspace, layout):
    ws = workspace
    adapter = _adapter(ws.name)
    source = _payload_single(ws) if layout == "single" else _payload_multi(ws)
    torrent_path, torrent = _make_torrent(ws, source)
    save_path = client_paths.to_client(ws.mapping, ws.seed)
    assert save_path == CLIENT_ROOT and not os.path.exists(CLIENT_ROOT)
    # Deluge accetta solo label [a-z0-9_-]; per rTorrent spazio e virgola
    # provano che il comando del load non va spezzato.
    category = f"nzg-{ws.tag}" if ws.name in ("transmission", "deluge") else f"NZG it, {ws.tag}"

    info_hash = adapter.add_torrent(torrent_path, save_path=save_path, category=category, tags=["nzg-it"])

    assert info_hash == torrent.infohash
    status, seen = _settled(adapter, info_hash)
    assert status.recheck_status == "ok", seen
    assert status.progress == pytest.approx(1.0) and not status.incomplete and status.amount_left == 0

    info = adapter.get_torrent_info(info_hash)
    assert info.info_hash == info_hash
    assert info.save_path == CLIENT_ROOT
    assert {f.path_in_torrent: f.size_bytes for f in info.files} == _files_of(torrent)
    for f in info.files:  # dal client a Nazgarr: ogni file esiste dov'è atteso
        rel = client_paths.to_disk_relative(ws.mapping, os.path.join(info.save_path, f.path_in_torrent))
        assert os.path.isfile(os.path.join(ws.mapping.disk_root, rel))
    if ws.name == "transmission":
        assert info.category is None and adapter.list_categories() == []
        labels = adapter._rpc("torrent-get", {"ids": [info_hash], "fields": ["labels"]})["torrents"][0]["labels"]
        assert labels == [category, "nzg-it"]
    else:
        assert info.category == category
        assert category in adapter.list_categories()
    assert info.tracker_url == TRACKER
    assert info_hash in {t.info_hash for t in adapter.list_torrents()}

    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent(torrent_path, save_path=save_path, expected_info_hash=info_hash)
    with pytest.raises(TorrentAlreadyInClientError):
        adapter.add_torrent(torrent_path, save_path=save_path)

    # Via senza i file, poi di nuovo e via coi file.
    adapter.remove_torrent(info_hash, delete_files=False)
    assert _wait(lambda: info_hash not in {t.info_hash for t in adapter.list_torrents()}, timeout=30)
    assert os.path.exists(source)

    adapter.add_torrent(torrent_path, save_path=save_path)
    assert _settled(adapter, info_hash)[0].recheck_status == "ok"
    before_seed = os.listdir(ws.seed)
    adapter.remove_torrent(info_hash, delete_files=True)
    assert _wait(lambda: info_hash not in {t.info_hash for t in adapter.list_torrents()}, timeout=30)
    # ruTorrent cancella i file col suo plugin erasedata, ogni 15 secondi.
    assert _wait(lambda: not os.path.exists(source), timeout=60), "files not deleted"
    assert sorted(os.listdir(ws.seed)) == sorted(n for n in before_seed if n != os.path.basename(source))


@pytest.mark.parametrize("workspace", list(CLIENTS), indirect=True)
def test_recheck_really_reads_the_data(workspace):
    """Un torrent i cui dati non ci sono: dopo il recheck il client lo
    riporta incompleto, mai completo."""
    ws = workspace
    adapter = _adapter(ws.name)
    source = _payload_single(ws)
    torrent_path, torrent = _make_torrent(ws, source)
    with open(source, "r+b") as f:  # stessa dimensione, contenuto diverso
        f.write(os.urandom(300_000))

    info_hash = adapter.add_torrent(torrent_path, save_path=CLIENT_ROOT, skip_check_verified=False)

    try:
        status, seen = _settled(adapter, info_hash)
        assert status.recheck_status == "failed" and status.incomplete, seen
        assert status.progress < 1.0
    finally:
        adapter.remove_torrent(info_hash, delete_files=True)


@pytest.mark.parametrize("workspace", list(CLIENTS), indirect=True)
def test_skip_check_verified(workspace):
    """Un upload appena creato da Nazgarr: Deluge lo aggiunge già completo
    (seed_mode); Transmission e rTorrent non sanno farlo e lo ricontrollano."""
    ws = workspace
    adapter = _adapter(ws.name)
    source = _payload_single(ws)
    torrent_path, torrent = _make_torrent(ws, source)

    info_hash = adapter.add_torrent(torrent_path, save_path=CLIENT_ROOT, skip_check_verified=True)

    try:
        assert adapter.can_skip_recheck is (ws.name == "deluge")
        status, seen = _settled(adapter, info_hash)
        assert status.recheck_status == "ok", seen
        assert adapter.get_torrent_info(info_hash).save_path == CLIENT_ROOT
    finally:
        adapter.remove_torrent(info_hash, delete_files=True)


class _OneFile(http.server.BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/x-bittorrent")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("workspace", list(CLIENTS), indirect=True)
def test_a_url_stays_a_url(workspace):
    ws = workspace
    adapter = _adapter(ws.name)
    source = _payload_single(ws)
    torrent_path, torrent = _make_torrent(ws, source)
    with open(torrent_path, "rb") as f:
        handler = type("H", (_OneFile,), {"payload": f.read()})
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = os.environ.get("NAZGARR_IT_HTTP_HOST", "host.docker.internal")
    url = f"http://{host}:{server.server_address[1]}/download/{torrent.infohash}.torrent"
    try:
        info_hash = adapter.add_torrent(url, save_path=CLIENT_ROOT, expected_info_hash=torrent.infohash.upper())
        assert info_hash == torrent.infohash
        assert _settled(adapter, info_hash)[0].recheck_status == "ok"
        adapter.remove_torrent(info_hash, delete_files=True)
    finally:
        server.shutdown()
