from fastapi import FastAPI
from fastapi.testclient import TestClient

from nazgarr.frontend import mount_frontend


def _build_fake_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa shell</body></html>")
    (dist / "favicon.svg").write_text("<svg></svg>")
    (dist / "assets" / "index-abc123.js").write_text("console.log('hi')")
    return dist


def test_mount_frontend_returns_false_when_dist_missing(tmp_path):
    app = FastAPI()

    mounted = mount_frontend(app, str(tmp_path / "does-not-exist"))

    assert mounted is False
    client = TestClient(app)
    assert client.get("/").status_code == 404


def test_mount_frontend_serves_index_for_root(tmp_path):
    dist = _build_fake_dist(tmp_path)
    app = FastAPI()
    mount_frontend(app, str(dist))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "spa shell" in response.text


def test_mount_frontend_serves_root_level_static_file(tmp_path):
    dist = _build_fake_dist(tmp_path)
    app = FastAPI()
    mount_frontend(app, str(dist))
    client = TestClient(app)

    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert "svg" in response.text


def test_mount_frontend_serves_asset_via_static_mount(tmp_path):
    dist = _build_fake_dist(tmp_path)
    app = FastAPI()
    mount_frontend(app, str(dist))
    client = TestClient(app)

    response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_mount_frontend_falls_back_to_index_for_client_side_route(tmp_path):
    dist = _build_fake_dist(tmp_path)
    app = FastAPI()
    mount_frontend(app, str(dist))
    client = TestClient(app)

    response = client.get("/reseeding/dashboard")

    assert response.status_code == 200
    assert "spa shell" in response.text


def test_mount_frontend_never_shadows_api_routes(tmp_path):
    dist = _build_fake_dist(tmp_path)
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    mount_frontend(app, str(dist))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mount_frontend_never_serves_files_outside_dist(tmp_path):
    dist = _build_fake_dist(tmp_path)
    (tmp_path / "secret.txt").write_text("SECRET")
    app = FastAPI()
    mount_frontend(app, str(dist))
    client = TestClient(app)

    for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"):
        response = client.get(path)
        assert "SECRET" not in response.text, path
