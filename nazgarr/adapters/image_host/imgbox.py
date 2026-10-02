"""Imgbox (docs/SPEC.md §9/§17) — nessuna api_key richiesta (upload
anonimi, a differenza di PTPImg/ImgBB). Imgbox non pubblica un'API HTTP
documentata: usiamo la libreria di terze parti `pyimgbox`, che
reimplementa il flusso del form web — stesso tipo di rischio di
fragilità già accettato consapevolmente per lo storico UNIT3D
(docs/SPEC.md §17), non un blocco. Wrapper sync via asyncio.run() perché
il resto del progetto (adapter, pipeline) è sincrono/httpx — nessuna
plumbing asincrona da propagare al resto della codebase per un solo
adapter."""

import asyncio

import pyimgbox

from nazgarr.adapters.image_host.base import ImageHostAdapter, ImageHostError


class ImgboxAdapter(ImageHostAdapter):
    def upload(self, image_path: str) -> str:
        try:
            return asyncio.run(_upload_async(image_path))
        except ImageHostError:
            raise
        except Exception as exc:
            raise ImageHostError(f"Upload Imgbox fallito: {exc}") from exc


async def _upload_async(image_path: str) -> str:
    async with pyimgbox.Gallery(thumb_width=350, square_thumbs=False) as gallery:
        async for submission in gallery.add([image_path]):
            if not submission["success"]:
                raise ImageHostError(f"Upload Imgbox fallito: {submission['error']}")
            if not submission["image_url"]:
                raise ImageHostError("Risposta Imgbox senza image_url")
            return submission["image_url"]
    raise ImageHostError("Imgbox: nessuna submission ricevuta")
