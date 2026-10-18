"""Configurazione degli adapter dei plugin (nazgarr/plugins/config.py)."""

import pytest

import nazgarr.sdk as sdk
from nazgarr.adapters.media_resolver.base import ResolvedMedia
from nazgarr.integrations import adapter_factory
from nazgarr.plugins import REGISTRY
from nazgarr.plugins import config as plugin_config

FIELDS = (
    sdk.ConfigField("url", "URL", type="url", required=True),
    sdk.ConfigField("password", "Password", type="secret", required=True),
    sdk.ConfigField("port", "Port", type="number", default=58846),
    sdk.ConfigField("ssl", "SSL", type="boolean", default=False),
    sdk.ConfigField("mode", "Mode", type="choice", choices=("a", "b")),
)


class _Client(sdk.TorrentClientAdapter):
    def __init__(self, config):
        self.config = config

    def add_torrent(self, *args, **kwargs):
        raise NotImplementedError

    def get_torrent_status(self, info_hash):
        raise NotImplementedError

    def list_torrents(self):
        return []


@pytest.fixture
def deluge():
    # Un client che Nazgarr non ha già integrato (Deluge ora lo è).
    spec = sdk.register(sdk.AdapterSpec("torrent_client", "flood", "Flood", lambda ctx: _Client(ctx.config),
                                        config_fields=FIELDS, plugin="nazgarr-flood"))
    yield spec
    REGISTRY.unregister("torrent_client", "flood")


def test_values_are_checked_against_the_declared_fields(deluge):
    config = plugin_config.validate(deluge, {"url": "http://d:8112", "password": "pw", "port": "58846", "ssl": "true"})
    assert config == {"url": "http://d:8112", "password": "pw", "port": 58846, "ssl": True}

    for bad, code in (({"url": "http://d", "password": "p", "nope": 1}, "adapter_config_unknown_field"),
                      ({"url": "http://d"}, "adapter_config_missing_field"),
                      ({"url": "ftp://d", "password": "p"}, "adapter_config_invalid"),
                      ({"url": "http://d", "password": "p", "mode": "c"}, "adapter_config_invalid"),
                      ({"url": "http://d", "password": "p", "port": "x"}, "adapter_config_invalid")):
        with pytest.raises(plugin_config.AdapterConfigError) as err:
            plugin_config.validate(deluge, bad)
        assert err.value.code == code

    # Un segreto non inviato resta, uno vuoto si cancella (e qui è obbligatorio).
    kept = plugin_config.validate(deluge, {"url": "http://d:8112", "port": 1, "password": None}, config)
    assert kept["password"] == "pw" and kept["port"] == 1
    with pytest.raises(plugin_config.AdapterConfigError):
        plugin_config.validate(deluge, {"password": ""}, config)


def test_a_new_host_needs_the_secrets_again(deluge):
    """Un campo url puntato altrove si teneva il segreto salvato: una API key
    di scrittura se lo faceva mandare (audit 2026-10-18)."""
    stored = {"url": "https://d:8112", "password": "pw"}
    for incoming, code in (({"url": "https://attacker.example"}, "secret_required_for_new_host"),
                           ({"url": "https://attacker.example", "password": None}, "secret_required_for_new_host"),
                           ({"url": "http://d:8112"}, "secret_required_for_insecure_scheme")):
        with pytest.raises(plugin_config.AdapterConfigError) as err:
            plugin_config.validate(deluge, incoming, stored)
        assert err.value.code == code and err.value.params == {"fields": "password"}
    moved = plugin_config.validate(deluge, {"url": "https://e", "password": "new"}, stored)
    assert moved == {"url": "https://e", "password": "new"}
    # Lo stesso indirizzo (anche riscritto uguale) o https su un host http: nessun segreto da reinviare.
    assert plugin_config.validate(deluge, {"url": "https://d:8112"}, stored)["password"] == "pw"
    upgraded = plugin_config.validate(deluge, {"url": "https://d"}, {"url": "http://d", "password": "pw"})
    assert upgraded["password"] == "pw"


def test_a_new_host_over_the_default_counts_too():
    spec = sdk.AdapterSpec("image_host", "selfhost", "Self host", lambda ctx: None, plugin="nazgarr-selfhost",
                           config_fields=(sdk.ConfigField("endpoint", "Endpoint", type="url",
                                                          default="https://img.example"),
                                          sdk.ConfigField("api_key", "API key", type="secret", required=True)))
    with pytest.raises(plugin_config.AdapterConfigError) as err:
        plugin_config.validate(spec, {"endpoint": "https://attacker.example"}, {"api_key": "k"})
    assert err.value.code == "secret_required_for_new_host"
    # Tolto l'indirizzo salvato si torna al default: un altro host anche quello.
    with pytest.raises(plugin_config.AdapterConfigError):
        plugin_config.validate(spec, {"endpoint": ""}, {"endpoint": "https://other.example", "api_key": "k"})
    # Alla creazione non c'è niente di salvato da proteggere.
    assert plugin_config.validate(spec, {"endpoint": "https://mine.example", "api_key": "k"})["api_key"] == "k"


def test_a_plugin_client_is_configured_through_the_api_and_its_secret_never_comes_back(client, deluge):
    body = {"label": "Flood", "adapter_type": "flood", "base_url": "http://d:8112"}
    assert client.post("/api/torrent-clients", json=body).status_code == 400  # campi obbligatori mancanti

    created = client.post("/api/torrent-clients", json={**body, "config": {"url": "http://d:8112", "password": "pw"}})
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["config"] == {"values": {"url": "http://d:8112", "port": None, "ssl": None, "mode": None},
                              "secrets_set": ["password"]}
    assert "pw" not in created.text

    updated = client.patch(f"/api/torrent-clients/{data['id']}", json={"config": {"port": 1234}}).json()
    assert updated["config"]["values"]["port"] == 1234 and updated["config"]["secrets_set"] == ["password"]

    from nazgarr.core.models import TorrentClient
    with client.app.state.session_factory() as session:
        adapter = adapter_factory.build_torrent_client_adapter(session.get(TorrentClient, data["id"]))
    assert adapter.config == {"url": "http://d:8112", "password": "pw", "port": 1234, "ssl": False, "mode": None}

    # Il campo url del plugin su un altro host, con base_url uguale: prima
    # passava, col segreto salvato (audit 2026-10-18).
    moved = client.patch(f"/api/torrent-clients/{data['id']}", json={"config": {"url": "http://attacker:8112"}})
    assert moved.status_code == 400 and moved.json()["detail"]["code"] == "secret_required_for_new_host"


def test_a_builtin_client_takes_no_plugin_config(client):
    response = client.post("/api/torrent-clients", json={
        "label": "q", "adapter_type": "qbittorrent", "base_url": "http://q", "config": {"x": 1},
    })
    assert response.status_code == 400


def test_a_global_adapter_is_configured_from_the_plugins_api(client):
    sdk.register(sdk.AdapterSpec("media_resolver", "anidb", "AniDB", lambda ctx: None, plugin="nazgarr-anidb",
                                 config_fields=(sdk.ConfigField("user", "User", required=True),
                                                sdk.ConfigField("token", "Token", type="secret"))))
    try:
        saved = client.put("/api/plugins/config/media_resolver/anidb",
                           json={"config": {"user": "me", "token": "s3cret"}, "enabled": False})
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"kind": "media_resolver", "adapter_type": "anidb", "enabled": False,
                                "values": {"user": "me"}, "secrets_set": ["token"]}
        assert "s3cret" not in client.get("/api/plugins/config/media_resolver/anidb").text
        # Image host integrati, adapter sconosciuti e notifiche (/api/notifications) non si configurano da qui.
        assert client.get("/api/plugins/config/image_host/ptpimg").status_code == 404
        assert client.get("/api/plugins/config/media_resolver/nope").status_code == 404
        assert client.get("/api/plugins/config/notification/discord").status_code == 404
    finally:
        REGISTRY.unregister("media_resolver", "anidb")


def test_plugin_resolvers_come_before_the_builtin_ones_even_without_tmdb(db_session):
    class AniDB(sdk.MediaResolverAdapter):
        SOURCE = "anidb"

        def resolve(self, file_path):
            if "Anime" not in file_path:
                return None
            return ResolvedMedia(content_type="tv", tmdb_id=1, title="Anime", year=2020, source="anidb")

    spec = sdk.register(sdk.AdapterSpec("media_resolver", "anidb", "AniDB", lambda ctx: AniDB(),
                                        plugin="nazgarr-anidb"))
    try:
        # Nessun campo obbligatorio: acceso anche senza una configurazione salvata.
        resolver = adapter_factory.build_media_resolver(db_session)  # senza chiave TMDB
        assert resolver.resolve("/media/Anime.S01E01.mkv").source == "anidb"
        assert resolver.resolve("/media/Movie.2020.mkv") is None
        plugin_config.save_global(db_session, spec, None, enabled=False)
        with pytest.raises(adapter_factory.TmdbApiKeyMissingError):
            adapter_factory.build_media_resolver(db_session)
    finally:
        REGISTRY.unregister("media_resolver", "anidb")
