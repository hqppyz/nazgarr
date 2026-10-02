"""Contratto dei servizi di notifica (docs/ROADMAP.md Fase 10): Discord,
Telegram, ntfy, Apprise... arrivano dai plugin. Nazgarr trasforma ogni
evento (nazgarr/events.py) in una Notification già leggibile; l'adapter la
manda. Un errore (NotificationError, o qualunque eccezione) fa ritentare la
consegna come per i webhook (nazgarr/webhooks.py)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


class NotificationError(Exception):
    pass


@dataclass(frozen=True)
class Notification:
    event: str  # nome dell'evento, es. "seed_job.finished"
    title: str
    body: str
    level: Literal["info", "success", "warning", "error"] = "info"
    data: dict = field(default_factory=dict)  # il payload dell'evento, com'è nei webhook


class NotificationAdapter(ABC):
    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Manda la notifica; solleva un'eccezione se non ci riesce."""
        raise NotImplementedError
