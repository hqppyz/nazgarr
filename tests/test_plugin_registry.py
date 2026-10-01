"""Registro degli adapter (app/plugins/registry.py): gli integrati iscritti
come un plugin, e un adapter di un plugin costruito dalle stesse factory."""

import pytest

import nazgarr_sdk as sdk
from app import adapter_factory
from app.models import TorrentClient
from app.plugins import REGISTRY
from app.plugins import config as plugin_config
from app.plugins.registry import AdapterAlreadyRegisteredError


def test_the_builtin_adapters_are_registered():
    assert REGISTRY.types("torrent_client") >= {"qbittorrent", "qui"}
    assert REGISTRY.types("tracker") >= {"unit3d"}
    assert {"ptpimg", "imgbox", "pixhost"} <= REGISTRY.types("image_host")
    assert all(spec.plugin is None for spec in REGISTRY.of_kind("tracker"))
    # Imgbox e Pixhost non chiedono chiavi.
    assert set(adapter_factory.keyed_image_hosts()).isdisjoint({"imgbox", "pixhost"})


def test_a_plugin_cannot_replace_a_builtin_adapter():
    with pytest.raises(AdapterAlreadyRegisteredError, match="Nazgarr"):
        sdk.register(sdk.AdapterSpec("torrent_client", "qbittorrent", "Fake", lambda ctx: None, plugin="evil"))
    with pytest.raises(ValueError, match="kind"):
        sdk.register(sdk.AdapterSpec("printer", "x", "X", lambda ctx: None))


@pytest.fixture
def fake_client_type():
    class FakeClient(sdk.TorrentClientAdapter):
        def __init__(self, row):
            self.row = row

        def add_torrent(self, *args, **kwargs):
            raise NotImplementedError

        def get_torrent_status(self, info_hash):
            raise NotImplementedError

        def list_torrents(self):
            return []

    sdk.register(sdk.AdapterSpec("torrent_client", "fakeclient", "Fake client", lambda ctx: FakeClient(ctx.row),
                                 plugin="nazgarr-fake"))
    yield FakeClient
    REGISTRY.unregister("torrent_client", "fakeclient")


def test_a_plugin_adapter_is_built_by_the_same_factory(db_session, fake_client_type):
    row = TorrentClient(label="fake", adapter_type="fakeclient", base_url="http://fake")

    adapter = adapter_factory.build_torrent_client_adapter(row)

    assert isinstance(adapter, fake_client_type) and adapter.row is row


def test_a_plugin_client_type_is_accepted_by_the_api(client, fake_client_type):
    created = client.post("/api/torrent-clients", json={
        "label": "fake", "adapter_type": "fakeclient", "base_url": "http://fake",
    })
    assert created.status_code == 201, created.text
    assert client.post("/api/torrent-clients", json={
        "label": "x", "adapter_type": "nope", "base_url": "http://x",
    }).status_code == 400


def test_a_plugin_image_host_takes_its_fields_from_its_config(db_session):
    class FakeHost(sdk.ImageHostAdapter):
        def __init__(self, token, album):
            self.token, self.album = token, album

        def upload(self, image_path):
            return f"https://img.example/{self.album}/{image_path}"

    sdk.register(sdk.AdapterSpec(
        "image_host", "fakehost", "Fake host", lambda ctx: FakeHost(ctx.config["token"], ctx.config["album"]),
        config_fields=(sdk.ConfigField("token", "Token", type="secret", required=True),
                       sdk.ConfigField("album", "Album", default="nazgarr")),
        plugin="nazgarr-fakehost",
    ))
    try:
        # Senza il campo obbligatorio: host saltato, come un integrato senza chiave.
        assert adapter_factory._build_image_host_adapter(db_session, "fakehost") is None
        spec = REGISTRY.get("image_host", "fakehost")
        plugin_config.save_global(db_session, spec, {"token": "t0k"}, enabled=True)
        host = adapter_factory._build_image_host_adapter(db_session, "fakehost")
        assert (host.token, host.album) == ("t0k", "nazgarr")
        assert "fakehost" in adapter_factory.keyed_image_hosts()
        # In coda alla priorità, senza doverla salvare di nuovo.
        assert adapter_factory.image_host_priority(db_session)[-1] == "fakehost"
        assert adapter_factory.image_host_status(db_session)["with_api_key"] == ["fakehost"]
        # Spento: si salta.
        plugin_config.save_global(db_session, spec, None, enabled=False)
        assert adapter_factory._build_image_host_adapter(db_session, "fakehost") is None
    finally:
        REGISTRY.unregister("image_host", "fakehost")
