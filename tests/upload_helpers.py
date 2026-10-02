"""Fixture condivise dai test del flusso di upload v2."""

from nazgarr import upload_profiles
from nazgarr.models import Disk, TorrentClient, Tracker


class InlineExecutor:
    """Esegue subito quello che riceve: il worker nei test gira nel thread
    del test, senza attese né race."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def make_tracker(session, label="t", *, with_profile=True, announce_url="https://tracker.example/announce", **extra):
    tracker = Tracker(
        label=label, adapter_type="unit3d", base_url=f"https://{label}.example", api_token="x",
        announce_url=announce_url, **extra,
    )
    session.add(tracker)
    session.commit()
    if with_profile:
        upload_profiles.create_upload_profile(session, tracker, None)
    return tracker


def make_client(session, label="qbit", enabled=True):
    client = TorrentClient(
        label=label, adapter_type="qbittorrent", base_url="http://qbit", username="u", password="p", enabled=enabled
    )
    session.add(client)
    session.commit()
    return client


def make_disk(session, root_path):
    disk = Disk(label="d", root_path=str(root_path))
    session.add(disk)
    session.commit()
    return disk


def write_video(path, size=20000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class FakeTMDB:
    """Al posto di TMDBClient: risultati per (tipo, titolo), /find e dettagli."""

    def __init__(self, search=None, find=None, details=None):
        self.search = search or {}
        self.found = find or {}
        self.details = details or {}
        self.calls = []

    def search_many(self, content_type, query, year=None):
        self.calls.append(("search", content_type, query, year))
        return [dict(r) for r in self.search.get((content_type, query, year), [])]

    def find(self, source, external_id):
        self.calls.append(("find", source, external_id))
        return [dict(r) for r in self.found.get((source, external_id), [])]

    def full_details(self, content_type, tmdb_id):
        self.calls.append(("details", content_type, tmdb_id))
        return dict(self.details[(content_type, tmdb_id)])


def tmdb_result(tmdb_id, title, year, content_type="movie", poster_path=None):
    return {
        "tmdb_id": tmdb_id, "content_type": content_type, "title": title, "original_title": title,
        "year": year, "poster_path": poster_path, "overview": None,
    }
