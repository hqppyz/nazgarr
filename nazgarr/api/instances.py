"""Le altre istanze (nazgarr/instances.py): /api/instances per registrarle e
vederne lo stato, /api/remote/{id}/… per parlarci attraverso questa.

Solo con il login, mai con una API key (main.py: require_login): una chiave
di questa istanza non deve poter usare le chiavi delle altre."""

import concurrent.futures

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr import instances
from nazgarr.api_errors import coded_detail, from_coded_error
from nazgarr.deps import get_session
from nazgarr.models import RemoteInstance
from nazgarr.version import __version__

router = APIRouter(prefix="/api/instances", tags=["instances"])
remote_router = APIRouter(prefix="/api/remote", tags=["instances"])

MAX_RESPONSE_BYTES = 200 * 1024 * 1024
_FORWARDED_REQUEST = ("content-type", "accept", "if-none-match")
_FORWARDED_RESPONSE = ("content-type", "etag", "cache-control", "content-disposition", "last-modified")


class InstanceCreateRequest(BaseModel):
    label: str
    base_url: str
    api_key: str


class InstanceUpdateRequest(BaseModel):
    label: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class InstanceStatus(BaseModel):
    status: str  # ok | unreachable | bad_key
    error: str | None = None
    version: str | None = None
    level: str | None = None  # read | write
    compatibility: str = "unknown"  # ok | warn | block_major | block_newer | unknown


class InstanceResponse(BaseModel):
    id: int
    label: str
    base_url: str
    status: InstanceStatus | None = None


class InstancesResponse(BaseModel):
    local_version: str
    instances: list[InstanceResponse]


def _get(session: Session, instance_id: int) -> RemoteInstance:
    row = session.get(RemoteInstance, instance_id)
    if row is None:
        raise HTTPException(status_code=404, detail=coded_detail("instance_not_found", id=instance_id))
    return row


def _url(value: str) -> str:
    try:
        return instances.normalize_url(value)
    except instances.InstanceError as exc:
        raise HTTPException(status_code=400, detail=from_coded_error(exc)) from exc


def _response(row: RemoteInstance, status: dict | None) -> InstanceResponse:
    return InstanceResponse(id=row.id, label=row.label, base_url=row.base_url,
                            status=InstanceStatus(**status) if status else None)


@router.get("", response_model=InstancesResponse)
def list_instances(probe: bool = False, session: Session = Depends(get_session)):
    """Le istanze registrate; con probe=true anche il loro stato (in parallelo)."""
    rows = session.query(RemoteInstance).order_by(RemoteInstance.id).all()
    statuses: dict[int, dict] = {}
    if probe and rows:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
            futures = {pool.submit(instances.cached_probe, r.id, r.base_url, r.api_key): r.id for r in rows}
            statuses = {futures[f]: f.result() for f in futures}
    return InstancesResponse(local_version=__version__,
                             instances=[_response(r, statuses.get(r.id)) for r in rows])


@router.post("", response_model=InstanceResponse, status_code=201)
def create_instance(body: InstanceCreateRequest, session: Session = Depends(get_session)):
    if not body.label.strip() or not body.api_key.strip():
        raise HTTPException(status_code=400, detail=coded_detail("instance_fields_required"))
    row = RemoteInstance(label=body.label.strip(), base_url=_url(body.base_url), api_key=body.api_key.strip())
    session.add(row)
    session.commit()
    return _response(row, instances.cached_probe(row.id, row.base_url, row.api_key, fresh=True))


@router.patch("/{instance_id}", response_model=InstanceResponse)
def update_instance(instance_id: int, body: InstanceUpdateRequest, session: Session = Depends(get_session)):
    row = _get(session, instance_id)
    if body.label is not None and body.label.strip():
        row.label = body.label.strip()
    if body.base_url is not None:
        row.base_url = _url(body.base_url)
    if body.api_key:
        row.api_key = body.api_key.strip()
    session.commit()
    instances.forget(row.id)
    return _response(row, instances.cached_probe(row.id, row.base_url, row.api_key, fresh=True))


@router.delete("/{instance_id}", status_code=204)
def delete_instance(instance_id: int, session: Session = Depends(get_session)):
    row = _get(session, instance_id)
    session.delete(row)
    session.commit()
    instances.forget(instance_id)


@router.post("/{instance_id}/test", response_model=InstanceResponse)
def test_instance(instance_id: int, session: Session = Depends(get_session)):
    row = _get(session, instance_id)
    return _response(row, instances.cached_probe(row.id, row.base_url, row.api_key, fresh=True))


# --- proxy --------------------------------------------------------------------


async def _body(request: Request) -> bytes:
    return await request.body()


@remote_router.api_route("/{instance_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(instance_id: int, path: str, request: Request, body: bytes = Depends(_body),
          session: Session = Depends(get_session)):
    """Inoltra una chiamata alle API dell'istanza, con la sua API key. Solo
    /api/…, mai login e chiavi; un'istanza con una versione incompatibile è
    rifiutata (instance_incompatible)."""
    row = _get(session, instance_id)
    try:
        target = instances.proxied_path(path)
    except instances.InstanceError as exc:
        raise HTTPException(status_code=403, detail=from_coded_error(exc)) from exc
    status = instances.cached_probe(row.id, row.base_url, row.api_key)
    if instances.blocked(status["compatibility"]):
        raise HTTPException(status_code=409, detail=coded_detail(
            "instance_incompatible", label=row.label, version=status.get("version") or "?", local=__version__))
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARDED_REQUEST}
    try:
        with instances.CLIENT_FACTORY(row.base_url, row.api_key) as client:
            upstream = client.request(request.method, target, params=list(request.query_params.multi_items()),
                                      content=body or None, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=coded_detail(
            "instance_unreachable", label=row.label, error=str(exc))) from exc
    if len(upstream.content) > MAX_RESPONSE_BYTES:
        raise HTTPException(status_code=502, detail=coded_detail("instance_response_too_large", label=row.label))
    out = {k: v for k, v in upstream.headers.items() if k.lower() in _FORWARDED_RESPONSE}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=out)
