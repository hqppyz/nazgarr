"""Categoria e tag dei torrent che Nazgarr aggiunge a un client: i default
del client (torrent_client.category_* / tags_*), per tipo di contenuto e per
azione. Solo etichette: la gestione automatica dei torrent resta spenta, una
categoria non sposta mai i file (app/adapters/torrent_client/base.py).

Anime: genere Animation su TMDB e lingua originale giapponese (decisione
dell'utente, 2026-09-30), correggibile nel job.
"""

from app.models import TorrentClient


def is_anime(details: dict | None) -> bool:
    details = details or {}
    return "Animation" in (details.get("genres") or []) and details.get("original_language") == "ja"


def split_tags(raw: str | None) -> list[str]:
    return [tag.strip() for tag in (raw or "").split(",") if tag.strip()]


def default_category(client: TorrentClient | None, content_type: str | None, anime: bool = False) -> str | None:
    if client is None:
        return None
    if anime and client.category_anime:
        return client.category_anime
    return client.category_tv if content_type == "tv" else client.category_movie


def default_tags(client: TorrentClient | None, action: str | None) -> str | None:
    """"upload" o "reseed"; un'altra azione non ne ha."""
    if client is None:
        return None
    return {"upload": client.tags_upload, "reseed": client.tags_reseed}.get(action or "") or None


def add_kwargs(category: str | None, tags: str | None) -> dict:
    """Gli argomenti di add_torrent, solo se ce ne sono."""
    out: dict = {}
    if category:
        out["category"] = category
    if split_tags(tags):
        out["tags"] = split_tags(tags)
    return out
