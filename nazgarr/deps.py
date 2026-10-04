from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from nazgarr.api_errors import coded_detail
from nazgarr.config import Settings


def get_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_or_404[T](session: Session, model: type[T], row_id: int, code: str, **params) -> T:
    """La riga, o un 404 con il codice d'errore tradotto (code, params; di
    default id=row_id)."""
    row = session.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=coded_detail(code, **(params or {"id": row_id})))
    return row
