"""Contratto per l'upload degli screenshot verso un host immagini
(docs/SPEC.md §9/§17). Più implementazioni concrete (ptpimg/imgbb/imgbox)
sono combinate in ordine di priorità da ImageHostChain (chain.py) — se una
fallisce si prova la successiva, mai un errore secco al primo host che ha
un problema temporaneo."""

from abc import ABC, abstractmethod


class ImageHostError(Exception):
    """Upload fallito verso un singolo host — usato da ImageHostChain per
    decidere se provare il prossimo in ordine di priorità."""


class ImageHostAdapter(ABC):
    @abstractmethod
    def upload(self, image_path: str) -> str:
        """Ritorna l'URL pubblico diretto (embeddabile) dell'immagine
        caricata. Solleva ImageHostError se l'upload fallisce — mai
        un'eccezione generica non gestita, altrimenti ImageHostChain non
        può decidere di provare il prossimo host."""
