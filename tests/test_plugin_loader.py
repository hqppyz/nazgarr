"""Caricamento dei plugin (nazgarr/plugins/loader.py)."""

import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from nazgarr.plugins import REGISTRY, loader


def _ep(name, obj, dist="nazgarr-test", version="0.1.0"):
    def load():
        if isinstance(obj, Exception):
            raise obj
        return obj
    return SimpleNamespace(name=name, dist=SimpleNamespace(name=dist, version=version), load=load)


def _setup(adapter_type, requires=">=1.0,<2", then_fail=False):
    import nazgarr_sdk as sdk

    def setup():
        sdk.register(sdk.AdapterSpec("tracker", adapter_type, adapter_type, lambda ctx: None))
        if then_fail:
            raise RuntimeError("boom")
    setup.REQUIRES_SDK = requires
    return setup


@pytest.fixture(autouse=True)
def _clean():
    yield
    for spec in [s for s in REGISTRY.all() if s.plugin]:
        REGISTRY.unregister(spec.kind, spec.adapter_type)


def test_the_list_comes_from_the_env_var_or_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv(loader.ENV_VAR, raising=False)
    assert loader.requested_plugins(str(tmp_path)) == (None, [])
    (tmp_path / "plugins.txt").write_text("nazgarr-deluge==1.2  # client\n\n# spento\nnazgarr-ntfy\n")
    assert loader.requested_plugins(str(tmp_path)) == ("file", ["nazgarr-deluge==1.2", "nazgarr-ntfy"])
    monkeypatch.setenv(loader.ENV_VAR, "a, b  c")
    assert loader.requested_plugins(str(tmp_path)) == ("env", ["a", "b", "c"])


def test_a_plugin_registers_its_adapters_under_its_name():
    [status] = loader.load_entry_points([_ep("gazelle", _setup("gazelle"))])

    assert (status.status, status.adapters) == ("loaded", ["tracker:gazelle"])
    assert REGISTRY.get("tracker", "gazelle").plugin == "nazgarr-test"


def test_a_broken_or_incompatible_plugin_is_disabled_and_the_others_load():
    statuses = loader.load_entry_points([
        _ep("half", _setup("half", then_fail=True), dist="nazgarr-half"),
        _ep("old", _setup("old", requires=">=2"), dist="nazgarr-old"),
        _ep("unknown", _setup("unknown", requires=None), dist="nazgarr-unknown"),
        _ep("missing", ImportError("No module named nazgarr_missing"), dist="nazgarr-missing"),
        _ep("good", _setup("good"), dist="nazgarr-good"),
    ])

    assert [(s.name, s.status) for s in statuses] == [
        ("half", "failed"), ("old", "incompatible"), ("unknown", "incompatible"), ("missing", "failed"),
        ("good", "loaded"),
    ]
    # Quello che il plugin rotto aveva già registrato si annulla.
    assert REGISTRY.get("tracker", "half") is None and REGISTRY.get("tracker", "good") is not None
    assert "richiede l'SDK >=2" in statuses[1].error and "REQUIRES_SDK" in statuses[2].error


def test_an_installed_plugin_is_found_through_its_entry_point(tmp_path, monkeypatch):
    """Un pacchetto come lo lascia pip in data_dir/plugins/site."""
    site = tmp_path / "plugins" / "site"
    (site / "nazgarr_demo").mkdir(parents=True)
    (site / "nazgarr_demo" / "__init__.py").write_text(textwrap.dedent('''
        import nazgarr_sdk as sdk
        REQUIRES_SDK = ">=1.0,<2"

        def setup():
            sdk.register(sdk.AdapterSpec("torrent_client", "demo", "Demo", lambda ctx: None))
    '''))
    dist_info = site / "nazgarr_demo-0.3.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: nazgarr-demo\nVersion: 0.3.0\n")
    (dist_info / "entry_points.txt").write_text("[nazgarr.plugins]\ndemo = nazgarr_demo:setup\n")
    monkeypatch.setenv(loader.ENV_VAR, "nazgarr-demo")
    monkeypatch.setattr(loader, "install", lambda data_dir, requested: None)  # niente pip né rete
    monkeypatch.setattr(sys, "path", list(sys.path))

    state = loader.load(str(tmp_path))

    demo = next(p for p in state.plugins if p.name == "demo")
    assert (demo.distribution, demo.version, demo.status) == ("nazgarr-demo", "0.3.0", "loaded")
    assert REGISTRY.get("torrent_client", "demo").plugin == "nazgarr-demo"
    sys.modules.pop("nazgarr_demo", None)


def _fake_pip(calls):
    def fake_run(command, **kwargs):
        calls.append(command)
        target = command[command.index("--target") + 1]
        for package in command[command.index("--target") + 2:]:
            os.makedirs(os.path.join(target, os.path.basename(package.rstrip("/"))), exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return fake_run


def test_pip_runs_only_when_the_list_changes_and_starts_from_scratch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(loader.subprocess, "run", _fake_pip(calls))
    site = loader.site_dir(str(tmp_path))

    assert loader.install(str(tmp_path), ["nazgarr-a"]) is None
    assert loader.install(str(tmp_path), ["nazgarr-a"]) is None
    assert len(calls) == 1 and calls[0][-3:] == ["--target", f"{site}.new", "nazgarr-a"]
    assert sorted(os.listdir(site)) == ["nazgarr-a"]
    # Tolto dalla lista: la nuova installazione non lo contiene più.
    loader.install(str(tmp_path), ["nazgarr-b"])
    assert len(calls) == 2 and sorted(os.listdir(site)) == ["nazgarr-b"]


def test_pip_options_are_never_accepted_from_the_list(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(loader.subprocess, "run", _fake_pip(calls))
    error = loader.install(str(tmp_path), ["--index-url", "https://evil.example/simple", "nazgarr-a"])
    assert "options are not allowed" in error and calls == []


def test_only_plugins_installed_by_nazgarr_are_loaded(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    ours = SimpleNamespace(name="ours", dist=SimpleNamespace(locate_file=lambda _p: site))
    stray = SimpleNamespace(name="stray", dist=SimpleNamespace(locate_file=lambda _p: tmp_path / "elsewhere"))
    monkeypatch.setattr(loader.importlib.metadata, "entry_points", lambda group: [ours, stray])
    assert [ep.name for ep in loader.installed_entry_points(str(site))] == ["ours"]


def test_a_pip_failure_is_reported(tmp_path, monkeypatch):
    failed = SimpleNamespace(returncode=1, stdout="", stderr="No matching distribution")
    monkeypatch.setattr(loader.subprocess, "run", lambda command, **kw: failed)
    assert "No matching distribution" in loader.install(str(tmp_path), ["nazgarr-nope"])


def test_the_api_lists_plugins_and_adapters(client):
    body = client.get("/api/plugins").json()

    assert body["sdk_version"] and body["env_var"] == "NAZGARR_PLUGINS"
    ptpimg = next(a for a in body["adapters"] if a["adapter_type"] == "ptpimg")
    assert ptpimg["plugin"] is None and ptpimg["config_fields"][0]["type"] == "secret"


def test_a_local_plugin_folder_is_reinstalled_when_its_code_changes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(loader.subprocess, "run", _fake_pip(calls))
    plugin = tmp_path / "nazgarr-dev"
    (plugin / "nazgarr_dev").mkdir(parents=True)
    code = plugin / "nazgarr_dev" / "__init__.py"
    code.write_text("v = 1\n")
    data = tmp_path / "data"
    data.mkdir()

    loader.install(str(data), [str(plugin)])
    loader.install(str(data), [str(plugin)])
    assert len(calls) == 1  # niente di cambiato: pip non riparte
    # I file che pip stesso lascia nella cartella non contano.
    (plugin / "build").mkdir()
    (plugin / "build" / "x.py").write_text("x")
    loader.install(str(data), [str(plugin)])
    assert len(calls) == 1

    code.write_text("v = 2  # una modifica\n")
    loader.install(str(data), [str(plugin)])
    assert len(calls) == 2
