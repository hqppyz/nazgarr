import json

import pytest
from sqlalchemy import text

from nazgarr.adapters.image_host.chevereto import CheveretoImageHost
from nazgarr.bundled.image_hosts import ImgbbAdapter
from nazgarr.core import settings_repo
from nazgarr.core.db import migrate_image_hosts_to_plugins
from nazgarr.core.models import AdapterConfig, AppSetting
from nazgarr.integrations import adapter_factory
from nazgarr.plugins import REGISTRY
from nazgarr.plugins import config as plugin_config


def _key(session, host, value="key", enabled=None):
    plugin_config.save_global(session, REGISTRY.get("image_host", host), {"api_key": value}, enabled)


def test_the_included_hosts_are_a_bundled_plugin_with_an_api_key():
    hosts = {spec.adapter_type: spec for spec in REGISTRY.of_kind("image_host")}
    assert set(hosts) == {"ptscreens", "passtheima", "imageride", "imgbb"}
    assert {spec.plugin for spec in hosts.values()} == {"nazgarr-image-hosts"}
    assert all(spec.required_fields for spec in hosts.values())  # nessun host anonimo


def test_without_any_key_there_is_no_chain(db_session):
    with pytest.raises(adapter_factory.ImageHostConfigError):
        adapter_factory.build_image_host_chain(db_session)
    assert adapter_factory.image_host_status(db_session)["usable"] == []


def test_the_chain_follows_the_saved_order_and_skips_disabled_hosts(db_session):
    _key(db_session, "imgbb")
    _key(db_session, "passtheima")
    _key(db_session, "ptscreens", enabled=False)
    settings_repo.set_setting(db_session, "image_host_priority", "imgbb,gone,ptscreens")

    chain = adapter_factory.build_image_host_chain(db_session)

    # imgbb per primo come salvato, un host che non esiste più saltato, gli altri in coda.
    assert adapter_factory.image_host_priority(db_session) == ["imgbb", "ptscreens", "passtheima", "imageride"]
    assert [type(a) for a in chain._adapters] == [ImgbbAdapter, CheveretoImageHost]
    assert chain._adapters[1].name == "Passtheima"
    status = adapter_factory.image_host_status(db_session)
    assert status["usable"] == ["imgbb", "passtheima"]
    assert status["order"] == ["imgbb", "ptscreens", "passtheima", "imageride"]


def _old_setting(session, key, value):
    session.add(AppSetting(key=key, value=settings_repo.encode(key, value)))
    session.commit()


def test_the_migration_moves_the_kept_keys_and_reports_the_removed_hosts_in_use(db_session):
    _old_setting(db_session, "image_host_priority", "ptpimg,imgbb,lensdump")
    _old_setting(db_session, "image_host_ptpimg_api_key", "ptp")
    _old_setting(db_session, "image_host_imgbb_api_key", "bb")
    _old_setting(db_session, "image_host_ptscreens_api_key", "pts")  # spento: non era nella priorità
    _old_setting(db_session, "image_host_lensdump_api_key", "ld")

    engine = db_session.get_bind()
    assert migrate_image_hosts_to_plugins(engine) == 3
    assert migrate_image_hosts_to_plugins(engine) == 0  # idempotente
    db_session.expire_all()

    rows = {r.adapter_type: r for r in db_session.query(AdapterConfig).filter_by(kind="image_host")}
    assert {k: (json.loads(r.config_json)["api_key"], r.enabled) for k, r in rows.items()} == {
        "imgbb": ("bb", True), "ptscreens": ("pts", False), "lensdump": ("ld", True)}
    assert settings_repo.get_setting(db_session, "image_host_priority") == "imgbb,lensdump"
    assert settings_repo.get_setting(db_session, "image_hosts_removed") == "ptpimg"
    left = db_session.execute(text("SELECT key FROM app_settings WHERE key LIKE 'image_host_%_api_key'")).all()
    assert left == []
    assert adapter_factory.image_host_status(db_session)["usable"] == ["imgbb"]
    # La chiave nel DB è cifrata, come quella di ogni plugin.
    raw = db_session.execute(text("SELECT config_json FROM adapter_config WHERE adapter_type = 'imgbb'")).scalar()
    assert "bb" not in raw


def test_the_anonymous_hosts_are_reported_only_to_who_uploaded_with_them(db_session):
    engine = db_session.get_bind()
    # Il DB dei test ha già fatto le migrazioni, da nuovo: nessun avviso.
    assert settings_repo.get_setting(db_session, "image_hosts_removed") is None
    db_session.execute(text(
        "INSERT INTO upload_job (relative_path, source_path, status) VALUES ('x.mkv', '/x.mkv', 'done')"))
    db_session.commit()

    migrate_image_hosts_to_plugins(engine)  # default di sempre, nessuna chiave: si usavano imgbox e pixhost

    assert settings_repo.get_setting(db_session, "image_hosts_removed") == "imgbox,pixhost"
