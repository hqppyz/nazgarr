"""Creazione del .torrent per un nuovo upload (docs/SPEC.md §9) — torf,
puro Python, coerente con l'assenza di binari esterni pesanti del progetto
(a differenza di mkbrr usato da Upload-Assistant)."""

import torf


def create_torrent(source_path: str, announce_url: str, output_path: str, *, private: bool = True) -> tuple[str, str]:
    """Crea il .torrent, lo scrive su output_path e ritorna (output_path, info_hash)."""
    torrent = torf.Torrent(path=source_path, trackers=[announce_url], private=private)
    torrent.generate()
    torrent.write(output_path, overwrite=True)
    return output_path, torrent.infohash
