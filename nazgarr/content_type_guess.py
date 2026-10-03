"""Deduce movie vs tv da un dict guessit già calcolato — mai una scelta
manuale in configurazione (vedi nazgarr/models.py Disk, che non ha più un
content_type: le cartelle media non hanno un tipo, rilevato qui)."""


def guess_content_type_from_guessit(guess: dict) -> str:
    return "tv" if guess.get("type") == "episode" else "movie"
