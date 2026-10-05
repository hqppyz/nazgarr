"""Quanto è sicuro un candidato TMDB per un upload (0-1), per il match
automatico dei file della cartella osservata (nazgarr/upload/watch.py) e per
mostrarlo nella schermata di match.

- ID forzati: 1; Radarr/Sonarr (sanno cos'è quel file): 0.97;
- ricerca per nome: somiglianza del titolo (anche con quello originale) per
  l'anno (esatto, uno di scarto come succede tra uscita e nome, o assente)
  per il tipo (film/serie come dice il nome del file);
- due candidati quasi pari: il primo vale meno, il match è ambiguo."""

import re
import unicodedata
from difflib import SequenceMatcher

FORCED = 1.0
ARR = 0.97
AMBIGUOUS_MARGIN = 0.05
AMBIGUOUS_FACTOR = 0.9


def _norm(text: str | None) -> str:
    value = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    value = value.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _best_title(guess: str | None, candidate: dict) -> tuple[float, str | None]:
    """(somiglianza, il titolo di TMDB che somiglia di più al nome del file).
    Anche il titolo originale e quelli nella lingua dei tracker."""
    wanted = _norm(guess)
    if not wanted:
        return 0.0, None
    names = [candidate.get("title"), candidate.get("original_title"), *(candidate.get("titles") or [])]
    best = (0.0, None)
    for name in names:
        if _norm(name):
            ratio = SequenceMatcher(None, wanted, _norm(name)).ratio()
            if ratio > best[0]:
                best = (ratio, name)
    return best


def title_similarity(guess: str | None, candidate: dict) -> float:
    return _best_title(guess, candidate)[0]


def _year_factor(guess_year: int | None, year: int | None) -> float:
    if guess_year is None or year is None:
        return 0.85  # non si può confermare
    if guess_year == year:
        return 1.0
    if abs(guess_year - year) == 1:
        return 0.85
    return 0.5


def parts(candidate: dict, title: str | None, year: int | None, content_type: str) -> dict:
    """Da cosa viene la confidence, per la schermata di match: aiuta a capire
    a che soglia mettere il match automatico."""
    source = candidate.get("source") or ""
    if source.startswith("forced"):
        return {"basis": "forced"}
    if source in ("radarr", "sonarr", "arr"):
        return {"basis": "arr"}
    similarity, matched = _best_title(title, candidate)
    # Oltre ai fattori, cosa è stato confrontato: per spiegare la percentuale.
    return {
        "basis": "name",
        "title": round(similarity, 3),
        "title_guess": title,
        "title_matched": matched,
        "year": _year_factor(year, candidate.get("year")),
        "year_guess": year,
        "year_candidate": candidate.get("year"),
        "type": 1.0 if candidate.get("content_type") == content_type else 0.6,
        "type_guess": content_type,
        "type_candidate": candidate.get("content_type"),
    }


def score(candidate: dict, title: str | None, year: int | None, content_type: str) -> float:
    explained = parts(candidate, title, year, content_type)
    if explained["basis"] == "forced":
        return FORCED
    if explained["basis"] == "arr":
        return ARR
    return explained["title"] * explained["year"] * explained["type"]


def scored(candidates: list[dict], title: str | None, year: int | None, content_type: str) -> list[dict]:
    """I candidati con la loro "confidence" e da cosa viene ("confidence_parts"),
    dal più sicuro (a pari merito l'ordine di prima: forzati, resolver, ricerca)."""
    out = [
        {**c, "confidence": round(score(c, title, year, content_type), 3),
         "confidence_parts": parts(c, title, year, content_type)}
        for c in candidates
    ]
    out.sort(key=lambda c: -c["confidence"])
    # Più candidati quasi pari al primo (es. due film con lo stesso titolo e
    # lo stesso anno): il match è ambiguo, valgono tutti meno e nessuno
    # passa una soglia alta da solo. Gli id forzati restano sicuri.
    if out and not str(out[0].get("source") or "").startswith("forced"):
        top = out[0]["confidence"]
        rivals = [c for c in out if top - c["confidence"] < AMBIGUOUS_MARGIN]
        if len(rivals) > 1:
            for candidate in rivals:
                candidate["confidence"] = round(candidate["confidence"] * AMBIGUOUS_FACTOR, 3)
                candidate["ambiguous"] = True  # mai un match automatico (nazgarr/upload/identify.py)
                candidate["confidence_parts"]["ambiguous"] = AMBIGUOUS_FACTOR
    return out


def explained(candidates: list[dict], layout: dict | None) -> list[dict]:
    """I candidati di un job, ciascuno con la spiegazione della sua
    confidence: quelli salvati prima che ci fosse ("confidence_parts" senza
    dettagli) la ricalcolano dal nome della sorgente (layout)."""
    if not layout:
        return candidates
    out = []
    for candidate in candidates:
        current = candidate.get("confidence_parts") or {}
        if candidate.get("confidence") is not None and current.get("basis") == "name" and "title_guess" in current:
            out.append(candidate)
            continue
        parts_now = parts(candidate, layout.get("title"), layout.get("year"), layout.get("content_type") or "movie")
        if candidate.get("ambiguous"):
            parts_now["ambiguous"] = AMBIGUOUS_FACTOR
        out.append({**candidate, "confidence_parts": parts_now})
    return out
