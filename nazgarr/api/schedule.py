"""Configurazione dello scheduler in-process (docs/SPEC.md §8, Fase 5).

Endpoint dedicato invece di riusare l'API generica app_settings
(nazgarr/api/settings.py): scrivere schedule_cron deve anche riconfigurare a
runtime il job APScheduler live (nazgarr/scheduler.py), un effetto
collaterale che l'API key/value generica non ha motivo di conoscere.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nazgarr import scheduler as scheduler_module
from nazgarr.core import settings_repo
from nazgarr.core.errors import coded_detail
from nazgarr.web.deps import get_session

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class ScheduleResponse(BaseModel):
    cron: str | None
    enabled: bool  # c'è un cron valido: le scansioni partono da sole
    # Il motivo, se il cron salvato non si legge (scritto a mano nel DB, o da
    # una versione di prima che lo lasciava passare dall'API generica):
    # all'avvio lo scheduler lo scarta e nessuna scansione parte, e prima
    # questa risposta lo dava per attivo (audit 2026-10-18).
    error: str | None = None


class ScheduleUpdateRequest(BaseModel):
    cron: str | None = None  # None o stringa vuota disabilita lo scheduling


def _cron_error(cron: str) -> str | None:
    """Perché APScheduler non legge il cron, o None se lo legge."""
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(cron)
    except ValueError as exc:
        return str(exc)
    return None


@router.get("", response_model=ScheduleResponse)
def get_schedule(session: Session = Depends(get_session)):
    cron = settings_repo.get_setting(session, scheduler_module.SETTING_KEY) or None
    error = _cron_error(cron) if cron else None
    return ScheduleResponse(cron=cron, enabled=bool(cron) and error is None, error=error)


@router.put("", response_model=ScheduleResponse)
def set_schedule(body: ScheduleUpdateRequest, request: Request, session: Session = Depends(get_session)):
    cron = body.cron or None
    error = _cron_error(cron) if cron else None
    if error is not None:
        raise HTTPException(status_code=422, detail=coded_detail("invalid_cron_expression", message=error))

    settings_repo.set_setting(session, scheduler_module.SETTING_KEY, cron or "")
    scheduler_module.reschedule(
        request.app.state.scheduler, cron, request.app.state.session_factory, request.app.state.settings.data_dir
    )
    return ScheduleResponse(cron=cron, enabled=bool(cron))
