"""Il requisito di seed di un tracker (hit and run): seedtime minimo e ratio
minimo, entrambi facoltativi, sulla riga del tracker. Serve a dire se un
torrent ha già dato quello che deve e si può togliere senza rischi (vista
Not imported). Sola lettura: nessun torrent viene toccato.

Con entrambi impostati basta uno dei due (seed_rule "any", la regola più
comune: "72 ore oppure ratio 1.0"), o servono tutti e due ("all"). Il
tracker di un torrent si riconosce dall'host del suo announce, come in
app/tracker_scope.py."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Tracker
from app.tracker_scope import torrent_host

RULES = ("any", "all")


@dataclass
class Requirement:
    tracker_id: int
    tracker_label: str
    min_seed_time_seconds: int | None
    min_ratio: float | None
    rule: str

    @property
    def is_set(self) -> bool:
        return self.min_seed_time_seconds is not None or self.min_ratio is not None


def requirement(tracker: Tracker) -> Requirement:
    return Requirement(
        tracker_id=tracker.id, tracker_label=tracker.label, min_seed_time_seconds=tracker.min_seed_time_seconds,
        min_ratio=tracker.min_ratio, rule=tracker.seed_rule if tracker.seed_rule in RULES else "any",
    )


def by_host(session: Session) -> dict[str, Requirement]:
    """Host dell'announce o del sito -> requisito del tracker configurato."""
    out: dict[str, Requirement] = {}
    for tracker in session.query(Tracker).order_by(Tracker.id):
        for url in (tracker.announce_url, tracker.base_url):
            host = torrent_host(url)
            if host:
                out.setdefault(host, requirement(tracker))
    return out


def evaluate(req: Requirement | None, ratio: float | None, seeding_time_seconds: int | None) -> dict:
    """Lo stato di un torrent rispetto al requisito del suo tracker:

    - unknown_tracker: tracker non configurato (o announce sconosciuto);
    - no_rules: tracker configurato senza requisito;
    - met: requisito soddisfatto, si può togliere;
    - pending: non ancora, con quanto manca (seedtime e/o ratio);
    - unknown: il client non dà seedtime o ratio, non si può dire."""
    if req is None:
        return {"status": "unknown_tracker"}
    base = {
        "tracker_id": req.tracker_id, "tracker_label": req.tracker_label,
        "min_seed_time_seconds": req.min_seed_time_seconds, "min_ratio": req.min_ratio, "rule": req.rule,
    }
    if not req.is_set:
        return {**base, "status": "no_rules"}
    checks: dict[str, bool | None] = {}  # None = il client non lo dice
    if req.min_seed_time_seconds is not None:
        seeded = seeding_time_seconds
        checks["seed_time"] = None if seeded is None else seeded >= req.min_seed_time_seconds
    if req.min_ratio is not None:
        checks["ratio"] = None if ratio is None else ratio >= req.min_ratio
    values = list(checks.values())
    # "all": basta un no per dire no; "any": basta un sì per dire sì.
    decisive, other = (False, True) if req.rule == "all" else (True, False)
    met = decisive if decisive in values else (None if None in values else other)
    remaining = {}
    if checks.get("seed_time") is False:
        remaining["seed_time_seconds"] = req.min_seed_time_seconds - seeding_time_seconds
    if checks.get("ratio") is False:
        remaining["ratio"] = round(req.min_ratio - ratio, 3)
    status = "unknown" if met is None else ("met" if met else "pending")
    return {**base, "status": status, "remaining": remaining}
