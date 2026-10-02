"""Catena di host immagini in ordine di priorità (docs/SPEC.md §9/§17,
decisione utente in Fase 6: PTPImg/ImgBB/Imgbox tutti disponibili, provati
in un ordine configurabile — se il primo fallisce si prova il successivo).
Mai un errore silenzioso: se TUTTI gli host falliscono, propaga l'errore
dell'ultimo tentativo."""

import logging

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError

logger = logging.getLogger(__name__)


class ImageHostChain:
    def __init__(self, adapters: list[ImageHostAdapter]):
        if not adapters:
            raise ValueError("ImageHostChain richiede almeno un adapter configurato")
        self._adapters = adapters

    def upload(self, image_path: str) -> str:
        last_error: ImageHostError | None = None
        for adapter in self._adapters:
            try:
                return adapter.upload(image_path)
            except ImageHostError as exc:
                logger.warning(
                    "Upload fallito su %s, provo il prossimo host della catena: %s", type(adapter).__name__, exc
                )
                last_error = exc
        assert last_error is not None
        raise last_error
