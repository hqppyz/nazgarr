"""Il plugin di esempio (examples/nazgarr-ntfy) caricato come un plugin vero."""

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import nazgarr.sdk as sdk
from nazgarr.core import events
from nazgarr.core.models import NotificationService
from nazgarr.integrations import webhooks
from nazgarr.plugins import REGISTRY, loader
from nazgarr.plugins import config as plugin_config

EXAMPLE = Path(__file__).parent.parent / "examples" / "nazgarr-ntfy"


@pytest.fixture
def ntfy_module(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    import nazgarr_ntfy

    yield nazgarr_ntfy
    REGISTRY.unregister("notification", "ntfy")
    sys.modules.pop("nazgarr_ntfy", None)


def test_the_entry_point_in_pyproject_is_the_one_nazgarr_loads(ntfy_module):
    project = tomllib.loads((EXAMPLE / "pyproject.toml").read_text())
    assert project["project"]["entry-points"][loader.ENTRY_POINT_GROUP] == {"ntfy": "nazgarr_ntfy:setup"}

    ep = SimpleNamespace(name="ntfy", dist=SimpleNamespace(name="nazgarr-ntfy", version="0.1.0"),
                         load=lambda: ntfy_module.setup)
    [status] = loader.load_entry_points([ep])

    assert (status.status, status.adapters) == ("loaded", ["notification:ntfy"])
    assert REGISTRY.get("notification", "ntfy").plugin == "nazgarr-ntfy"


def test_it_sends_nazgarr_events_to_ntfy(db_session, ntfy_module):
    ntfy_module.setup()
    spec = REGISTRY.get("notification", "ntfy")
    db_session.add(NotificationService(
        name="ntfy", adapter_type=spec.adapter_type, events_json='["*"]',
        config_json=plugin_config.dumps(plugin_config.validate(spec, {"topic": "my-nazgarr", "token": "tk_1"})),
    ))
    db_session.commit()
    seen = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200))[1]))
    original = ntfy_module.NtfyNotifier.__init__
    ntfy_module.NtfyNotifier.__init__ = lambda self, *a, **k: original(self, *a, **{**k, "client": client})
    try:
        events.store(db_session, "seed_job.finished", {"status": "seeding", "torrent": "Dune", "tracker": "ITT"})
        db_session.commit()
        webhooks.deliver_due(db_session)
    finally:
        ntfy_module.NtfyNotifier.__init__ = original

    [request] = seen
    assert str(request.url) == "https://ntfy.sh/my-nazgarr"
    assert (request.headers["Title"], request.headers["Priority"]) == ("Reseed seeding", "3")
    assert request.headers["Authorization"] == "Bearer tk_1"
    assert request.content == b"Dune on ITT."


def test_a_refused_notification_is_an_error(ntfy_module):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="forbidden")))
    notifier = ntfy_module.NtfyNotifier("https://ntfy.example", "t", client=client)
    with pytest.raises(sdk.NotificationError, match="403"):
        notifier.send(sdk.Notification("test", "Hi", "there"))
