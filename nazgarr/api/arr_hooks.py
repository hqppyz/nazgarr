"""Dove Radarr e Sonarr mandano i loro webhook (nazgarr/integrations/arr_webhooks.py).

Fuori dal login di Nazgarr (Radarr non ha un token di Nazgarr): ogni istanza
ha la sua password del webhook, che Radarr/Sonarr mandano come password della
connessione (HTTP Basic, il nome utente non conta) o, per altri strumenti,
come ?token=. Senza la password giusta: 401, e niente si salva. La risposta
arriva subito, il lavoro lo fa lo scheduler.

L'endpoint è async solo per leggere il corpo dopo la password (chi non la sa
non fa leggere niente); le query e la scrittura vanno nel threadpool. Sul
loop, un commit che aspettava il lock di SQLite (una scansione che scrive)
fermava ogni altra richiesta del processo (audit 2026-10-18).
"""

import base64
import binascii
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from nazgarr.core.errors import coded_detail
from nazgarr.integrations import arr_webhooks
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/arr-hooks", tags=["arr-hooks"])

MAX_BODY = 1024 * 1024  # un evento di Radarr/Sonarr è di pochi KB


class ArrHookResponse(BaseModel):
    status: str  # "accepted" | "ignored"


def _password(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        return decoded.partition(":")[2] or None
    return request.query_params.get("token")


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail=coded_detail("arr_hook_too_large"))


async def _payload(request: Request) -> dict:
    """Il JSON dell'evento, letto al massimo fino a MAX_BODY: un Content-Length
    più grande si rifiuta senza leggere niente."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise _too_large()
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=coded_detail("arr_hook_invalid")) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=coded_detail("arr_hook_invalid"))
    return payload


@router.post("/{source}/{instance_id}", response_model=ArrHookResponse)
async def receive(source: str, instance_id: int, request: Request, session: Session = Depends(get_session)):
    instance = await run_in_threadpool(arr_webhooks.instance_for_token, session, source, instance_id,
                                       _password(request))
    if instance is None:
        raise HTTPException(status_code=401, detail=coded_detail("arr_hook_unauthorized"))
    payload = await _payload(request)
    # Lo stato si legge nel threadpool: dopo il commit la riga è scaduta, e
    # leggerla qui sarebbe un'altra SELECT sul loop.
    status = await run_in_threadpool(lambda: arr_webhooks.receive(session, source, instance, payload).status)
    return ArrHookResponse(status="accepted" if status == "pending" else "ignored")
