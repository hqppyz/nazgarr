"""Servizi di notifica dei plugin (nazgarr/notifications.py)."""

import pytest

import nazgarr_sdk as sdk
from nazgarr import events, notifications, webhooks
from nazgarr.models import EventDelivery
from nazgarr.plugins import REGISTRY
from nazgarr.plugins import config as plugin_config

SENT = []


class _Ntfy(sdk.NotificationAdapter):
    def __init__(self, config):
        self.config = config

    def send(self, notification):
        if self.config.get("topic") == "broken":
            raise sdk.NotificationError("server said no")
        SENT.append((self.config["topic"], notification))


@pytest.fixture
def ntfy():
    SENT.clear()
    spec = sdk.register(sdk.AdapterSpec("notification", "ntfy", "ntfy", lambda ctx: _Ntfy(ctx.config),
                                        config_fields=(sdk.ConfigField("topic", "Topic", required=True),),
                                        plugin="nazgarr-ntfy"))
    yield spec
    REGISTRY.unregister("notification", "ntfy")


def test_an_unconfigured_or_unsubscribed_service_gets_nothing(db_session, ntfy):
    assert notifications.targets(db_session, "seed_job.finished") == []  # manca il topic
    row = plugin_config.save_global(db_session, ntfy, {"topic": "nazgarr"}, enabled=True)
    assert notifications.targets(db_session, "seed_job.finished") == ["ntfy"]  # di default tutti gli eventi
    row.events_json = '["upload.finished"]'
    db_session.commit()
    assert notifications.targets(db_session, "seed_job.finished") == []
    assert notifications.targets(db_session, "upload.finished") == ["ntfy"]


def test_an_event_reaches_the_service_through_the_queue(db_session, ntfy):
    plugin_config.save_global(db_session, ntfy, {"topic": "nazgarr"}, enabled=True)
    events.store(db_session, "seed_job.finished", {"status": "failed", "torrent": "The.Matrix.1999",
                                                   "tracker": "ITT", "error": "Recheck failed"})
    db_session.commit()

    webhooks.deliver_due(db_session)

    [(topic, notification)] = SENT
    assert (topic, notification.title, notification.level) == ("nazgarr", "Reseed failed", "error")
    assert notification.body == "The.Matrix.1999 on ITT. Recheck failed"
    assert db_session.query(EventDelivery).one().status == "delivered"


def test_a_failing_service_is_retried(db_session, ntfy):
    plugin_config.save_global(db_session, ntfy, {"topic": "broken"}, enabled=True)
    events.store(db_session, "run.finished", {"items_scanned": 3})
    db_session.commit()

    webhooks.deliver_due(db_session)

    delivery = db_session.query(EventDelivery).one()
    assert (delivery.status, delivery.attempts) == ("pending", 1)
    assert "server said no" in delivery.last_error


def test_every_event_has_a_readable_message():
    upload = notifications.render("upload.finished", {"status": "partial", "title": "Dune", "targets": [
        {"tracker": "ITT", "action": "upload", "status": "done", "error": None},
        {"tracker": "BLU", "action": "reseed", "status": "failed", "error": "upload_reseed_missing_video"},
        {"tracker": "X", "action": "skip", "status": "skipped", "error": None},
    ]})
    assert (upload.title, upload.level) == ("Upload partial: Dune", "warning")
    assert upload.body == "ITT: upload done\nBLU: reseed failed (upload_reseed_missing_video)"
    for name in events.CATALOG:
        assert notifications.render(name, {}).title


def test_the_plugins_api_sets_events_and_sends_a_test(client, ntfy):
    saved = client.put("/api/plugins/config/notification/ntfy",
                       json={"config": {"topic": "nazgarr"}, "events": ["upload.finished", "run.finished"]})
    assert saved.json()["events"] == ["run.finished", "upload.finished"]
    assert client.put("/api/plugins/config/notification/ntfy", json={"events": ["nope"]}).status_code == 400

    tested = client.post("/api/plugins/config/notification/ntfy/test").json()
    assert tested == {"status": "delivered", "error": None}
    assert SENT[-1][1].title == "Nazgarr test"
    assert client.get("/api/plugins/config/notification/ntfy").json()["last_delivery"]["status"] == "delivered"
