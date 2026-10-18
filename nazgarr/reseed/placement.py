"""Dove vanno i file di un torrent ricreato con hardlink, rispetto alla
cartella dei nuovi hardlink, secondo il layout del contenuto scelto
dall'utente nel client (qBittorrent: Opzioni › Download › Layout del
contenuto; qui lo stesso). Una sola regola per chi li mette e per chi li
cerca dopo (audit 2026-10-18): l'esecutore (nazgarr/reseed/executor.py) la
applica col layout del client di quel momento; la registrazione del seed
appena creato (nazgarr/library/seed_refresh.py) e il controllo completo di
un'esecuzione (nazgarr/reseed/full_check.py) non sanno più quale fosse,
perché il seed_job non lo salva, e provano le disposizioni possibili
(possible_placements). Prima ricostruivano sempre la cartella del torrent,
e con "Subfolder" o "NoSubfolder" guardavano nel posto sbagliato."""

import os
from dataclasses import dataclass

from nazgarr.adapters.torrent_client.base import CONTENT_LAYOUTS


@dataclass(frozen=True)
class Placement:
    """save_dir è la cartella di save_path dentro la cartella dei nuovi
    torrent, folder la cartella radice dei file dentro save_dir, layout
    quello da mandare al client."""

    save_dir: str | None
    folder: str | None
    layout: str

    @property
    def prefix(self) -> str:
        """La cartella dei file del torrent dentro quella dei nuovi hardlink ("" = lì)."""
        return "/".join(p for p in (self.save_dir, self.folder) if p)

    def rel_path(self, torrent_path: str) -> str:
        return "/".join(p for p in (self.prefix, torrent_path) if p)


def placement_for(layout: str, folder: str | None, single_file_name: str | None) -> Placement:
    """"Crea sottocartella" su un torrent a file singolo: la cartella col
    nome del file senza estensione la crea Nazgarr, e il torrent arriva con
    save_path lì dentro e layout Original, così non serve indovinare come
    il client sceglie quel nome. "Non creare sottocartella" su un torrent
    con la cartella radice: gli hardlink senza quella cartella, e il client
    riceve lo stesso layout. Negli altri casi il layout non cambia niente.
    single_file_name: il nome del solo file del torrent, None se ne ha più
    d'uno."""
    if layout == "Subfolder" and not folder and single_file_name:
        stem = os.path.splitext(single_file_name)[0] or single_file_name
        return Placement(save_dir=stem, folder=None, layout="Original")
    if layout == "NoSubfolder" and folder:
        return Placement(save_dir=None, folder=None, layout="NoSubfolder")
    return Placement(save_dir=None, folder=folder, layout="Original")


def possible_placements(folder: str | None, single_file_name: str | None) -> list[Placement]:
    """Ogni posto in cui l'esecutore può aver messo i file, uno per
    cartella diversa, prima quello del torrent ("Original")."""
    out: list[Placement] = []
    for layout in CONTENT_LAYOUTS:
        placement = placement_for(layout, folder, single_file_name)
        if all(placement.prefix != seen.prefix for seen in out):
            out.append(placement)
    return out
