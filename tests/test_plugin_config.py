"""Configurazione degli adapter dei plugin (nazgarr/plugins/config.py)."""

import pytest

import nazgarr_sdk as sdk
from nazgarr import adapter_factory
from nazgarr.adapters.media_resolver.base import ResolvedMedia
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
    spec = sdk.register(sdk.AdapterSpec("torrent_client", "deluge", "Deluge", lambda ctx: _Client(ctx.config),
                                        config_fields=FIELDS, plugin="nazgarr-deluge"))
    yield spec
    REGISTRY.unregister("torrent_client", "deluge")


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
    kept = plugin_config.validate(deluge, {"url": "http://e", "password": None}, config)
    assert kept["password"] == "pw" and kept["url"] == "http://e"
    with pytest.raises(plugin_config.AdapterConfigError):
        plugin_config.validate(deluge, {"password": ""}, config)


def test_a_plugin_client_is_configured_through_the_api_and_its_secret_never_comes_back(client, deluge):
    body = {"label": "Deluge", "adapter_type": "deluge", "base_url": "http://d:8112"}
    assert client.post("/api/torrent-clients", json=body).status_code == 400  # campi obbligatori mancanti

    created = client.post("/api/torrent-clients", json={**body, "config": {"url": "http://d:8112", "password": "pw"}})
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["config"] == {"values": {"url": "http://d:8112", "port": None, "ssl": None, "mode": None},
                              "secrets_set": ["password"]}
    assert "pw" not in created.text

    updated = client.patch(f"/api/torrent-clients/{data['id']}", json={"config": {"port": 1234}}).json()
    assert updated["config"]["values"]["port"] == 1234 and updated["config"]["secrets_set"] == ["password"]

    from nazgarr.models import TorrentClient
    with client.app.state.session_factory() as session:
        adapter = adapter_factory.build_torrent_client_adapter(session.get(TorrentClient, data["id"]))
    assert adapter.config == {"url": "http://d:8112", "password": "pw", "port": 1234, "ssl": False, "mode": None}


def test_a_builtin_client_takes_no_plugin_config(client):
    response = client.post("/api/torrent-clients", json={
        "label": "q", "adapter_type": "qbittorrent", "base_url": "http://q", "config": {"x": 1},
    })
    assert response.status_code == 400


def test_a_global_adapter_is_configured_from_the_plugins_api(client):
    sdk.register(sdk.AdapterSpec("notification", "ntfy", "ntfy", lambda ctx: None, plugin="nazgarr-ntfy",
                                 config_fields=(sdk.ConfigField("topic", "Topic", required=True),
                                                sdk.ConfigField("token", "Token", type="secret"))))
    try:
        saved = client.put("/api/plugins/config/notification/ntfy",
                           json={"config": {"topic": "nazgarr", "token": "s3cret"}, "enabled": False})
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"kind": "notification", "adapter_type": "ntfy", "enabled": False,
                                "values": {"topic": "nazgarr"}, "secrets_set": ["token"],
                                "events": ["*"], "last_delivery": None}
        assert "s3cret" not in client.get("/api/plugins/config/notification/ntfy").text
        # Integrati e sconosciuti non si configurano da qui.
        assert client.get("/api/plugins/config/image_host/ptpimg").status_code == 404
        assert client.get("/api/plugins/config/notification/nope").status_code == 404
    finally:
        REGISTRY.unregister("notification", "ntfy")


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
