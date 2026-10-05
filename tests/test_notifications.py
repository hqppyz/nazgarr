"""Servizi di notifica (nazgarr/integrations/notifications.py, nazgarr/api/notifications.py)."""

import json

import pytest

import nazgarr.sdk as sdk
from nazgarr.core import events
from nazgarr.core.models import EventDelivery, NotificationService
from nazgarr.integrations import notifications, webhooks
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


def _service(session, topic, events_=("*",), enabled=True, name="ntfy"):
    service = NotificationService(name=name, adapter_type="ntfy", enabled=enabled,
                                  config_json=plugin_config.dumps({"topic": topic} if topic else {}),
                                  events_json=json.dumps(list(events_)))
    session.add(service)
    session.commit()
    return service


@pytest.fixture
def ntfy():
    SENT.clear()
    spec = sdk.register(sdk.AdapterSpec("notification", "ntfy", "ntfy", lambda ctx: _Ntfy(ctx.config),
                                        config_fields=(sdk.ConfigField("topic", "Topic", required=True),),
                                        plugin="nazgarr-ntfy"))
    yield spec
    REGISTRY.unregister("notification", "ntfy")


def test_an_unconfigured_or_unsubscribed_service_gets_nothing(db_session, ntfy):
    _service(db_session, None)  # manca il topic
    _service(db_session, "off", enabled=False)
    assert notifications.targets(db_session, "seed_job.finished") == []
    everything = _service(db_session, "nazgarr")
    uploads = _service(db_session, "uploads", events_=["upload.finished"])
    assert notifications.targets(db_session, "seed_job.finished") == [everything]
    assert notifications.targets(db_session, "upload.finished") == [everything, uploads]


def test_an_event_reaches_every_instance_through_the_queue(db_session, ntfy):
    _service(db_session, "bot")
    _service(db_session, "channel")
    events.store(db_session, "seed_job.finished", {"status": "failed", "torrent": "The.Matrix.1999",
                                                   "tracker": "ITT", "error": "Recheck failed"})
    db_session.commit()

    webhooks.deliver_due(db_session)

    assert sorted(topic for topic, _n in SENT) == ["bot", "channel"]
    notification = SENT[0][1]
    assert (notification.title, notification.level) == ("Reseed failed", "error")
    assert notification.body == "The.Matrix.1999 on ITT. Recheck failed"
    assert {d.status for d in db_session.query(EventDelivery)} == {"delivered"}


def test_a_failing_service_is_retried(db_session, ntfy):
    _service(db_session, "broken")
    events.store(db_session, "run.finished", {"items_scanned": 3})
    db_session.commit()

    webhooks.deliver_due(db_session)

    delivery = db_session.query(EventDelivery).one()
    assert (delivery.status, delivery.attempts) == ("pending", 1)
    assert "server said no" in delivery.last_error


def test_a_removed_plugin_leaves_its_services_unavailable(db_session, ntfy):
    _service(db_session, "nazgarr")
    REGISTRY.unregister("notification", "ntfy")
    assert notifications.targets(db_session, "run.finished") == []


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


def test_the_api_manages_several_instances_of_a_type(client, ntfy):
    bot = client.post("/api/notifications", json={"name": "Bot", "adapter_type": "ntfy",
                                                  "config": {"topic": "bot"}, "events": ["upload.finished"]})
    assert bot.status_code == 201, bot.text
    channel = client.post("/api/notifications", json={"name": "Channel", "adapter_type": "ntfy",
                                                      "config": {"topic": "channel"}})
    assert channel.json()["events"] == ["*"] and channel.json()["message_format"] == "standard"
    listed = client.get("/api/notifications").json()
    assert [(s["name"], s["values"], s["available"]) for s in listed] == [
        ("Bot", {"topic": "bot"}, True), ("Channel", {"topic": "channel"}, True)]

    assert client.post("/api/notifications", json={"name": "x", "adapter_type": "nope"}).status_code == 400
    assert client.post("/api/notifications", json={"name": " ", "adapter_type": "ntfy",
                                                   "config": {"topic": "t"}}).status_code == 400
    assert client.post("/api/notifications", json={"name": "x", "adapter_type": "ntfy"}).status_code == 400
    bot_id = bot.json()["id"]
    assert client.patch(f"/api/notifications/{bot_id}", json={"events": ["nope"]}).status_code == 400
    assert client.patch(f"/api/notifications/{bot_id}", json={"message_format": "nope"}).status_code == 400
    assert client.patch(f"/api/notifications/{bot_id}", json={"adapter_type": "discord"}).status_code == 400
    renamed = client.patch(f"/api/notifications/{bot_id}", json={"name": "Bot 2", "enabled": False})
    assert (renamed.json()["name"], renamed.json()["enabled"]) == ("Bot 2", False)

    tested = client.post(f"/api/notifications/{bot_id}/test").json()
    assert tested == {"status": "delivered", "error": None}
    assert SENT[-1] == ("bot", SENT[-1][1]) and SENT[-1][1].title == "Nazgarr test"
    assert client.get("/api/notifications").json()[0]["last_status"] == "delivered"
    assert [d["event"] for d in client.get(f"/api/notifications/{bot_id}/deliveries").json()] == ["test"]

    assert client.delete(f"/api/notifications/{bot_id}").status_code == 204
    assert [s["name"] for s in client.get("/api/notifications").json()] == ["Channel"]
    assert client.get(f"/api/notifications/{bot_id}/deliveries").status_code == 404


def test_secrets_never_come_back_and_an_unsaved_config_can_be_tried(client):
    created = client.post("/api/notifications", json={
        "name": "Chat", "adapter_type": "telegram", "config": {"bot_token": "1:secret", "chat_id": "42"},
    })
    assert created.status_code == 201, created.text
    assert created.json()["secrets_set"] == ["bot_token"]
    assert "1:secret" not in client.get("/api/notifications").text

    sent = []

    class _Fake(sdk.NotificationAdapter):
        def __init__(self, config):
            self.config = config

        def send(self, notification):
            sent.append((self.config, notification.title))

    sdk.register(sdk.AdapterSpec("notification", "fake", "Fake", lambda ctx: _Fake(ctx.config),
                                 config_fields=(sdk.ConfigField("token", "Token", type="secret", required=True),
                                                sdk.ConfigField("room", "Room", default="main")),
                                 plugin="nazgarr-fake"))
    try:
        assert client.post("/api/notifications/test", json={"adapter_type": "fake", "config": {}}).status_code == 400
        tried = client.post("/api/notifications/test", json={"adapter_type": "fake", "config": {"token": "t"}})
        assert tried.json() == {"status": "delivered", "error": None}
        assert sent == [({"token": "t", "room": "main"}, "Nazgarr test")]
        # Su un servizio salvato, un segreto non reinviato è quello di prima.
        saved = client.post("/api/notifications", json={"name": "F", "adapter_type": "fake",
                                                        "config": {"token": "stored"}}).json()
        client.post("/api/notifications/test", json={"adapter_type": "fake", "service_id": saved["id"],
                                                     "config": {"room": "other"}})
        assert sent[-1][0] == {"token": "stored", "room": "other"}
        assert client.get(f"/api/notifications/{saved['id']}/deliveries").json() == []  # nessuna traccia
    finally:
        REGISTRY.unregister("notification", "fake")


def test_a_plugin_icon_must_be_a_small_data_image():
    with pytest.raises(ValueError):
        sdk.register(sdk.AdapterSpec("notification", "x", "X", lambda ctx: None, icon="https://example.com/x.svg"))
    spec = sdk.register(sdk.AdapterSpec("notification", "x", "X", lambda ctx: None,
                                        icon="data:image/svg+xml;base64,PHN2Zy8+"))
    try:
        assert spec.icon.startswith("data:image/")
    finally:
        REGISTRY.unregister("notification", "x")


def test_watched_releases_have_their_own_messages():
    from nazgarr.integrations.notifications import render

    detected = render("upload.detected", {"upload_id": 3, "path": "releases/My.Movie.2024.mkv", "disk": "main"})
    ready = render("upload.ready", {"upload_id": 3, "title": "My Movie", "year": 2024, "trackers": ["ITT", "B"]})

    assert detected.title == "New release detected"
    assert detected.body == "releases/My.Movie.2024.mkv on main: upload started."
    assert (ready.title, ready.body) == ("Upload ready for your decision", "My Movie (2024) → ITT, B")
