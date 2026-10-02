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
from nazgarr import settings_repo
from nazgarr.api_errors import coded_detail
from nazgarr.deps import get_session

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class ScheduleResponse(BaseModel):
    cron: str | None
    enabled: bool


class ScheduleUpdateRequest(BaseModel):
    cron: str | None = None  # None o stringa vuota disabilita lo scheduling


@router.get("", response_model=ScheduleResponse)
def get_schedule(session: Session = Depends(get_session)):
    cron = settings_repo.get_setting(session, scheduler_module.SETTING_KEY) or None
    return ScheduleResponse(cron=cron, enabled=bool(cron))


@router.put("", response_model=ScheduleResponse)
def set_schedule(body: ScheduleUpdateRequest, request: Request, session: Session = Depends(get_session)):
    cron = body.cron or None
    if cron is not None:
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(cron)
        except ValueError as exc:
            detail = coded_detail("invalid_cron_expression", message=str(exc))
            raise HTTPException(status_code=422, detail=detail) from exc

    settings_repo.set_setting(session, scheduler_module.SETTING_KEY, cron or "")
    scheduler_module.reschedule(
        request.app.state.scheduler, cron, request.app.state.session_factory, request.app.state.settings.data_dir
    )
    return ScheduleResponse(cron=cron, enabled=bool(cron))
