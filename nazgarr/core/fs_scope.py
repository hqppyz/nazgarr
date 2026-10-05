"""Funzione di scoping condivisa per ogni endpoint che tocca il filesystem.

Vedi docs/SPEC.md sezione 5 (ereditata da ratio-guardian) e CLAUDE.md: non
va mai duplicata, va sempre riusata (browse, mkdir, e in futuro la
creazione degli hardlink).
"""

import os

from nazgarr.core.errors import CodedError


class ScopeViolation(CodedError):
    def __init__(self, candidate: str):
        self.candidate = candidate
        super().__init__("path_outside_scope", path=candidate)


def resolve_scoped(root_path: str, relative: str) -> str:
    try:
        candidate = os.path.realpath(os.path.join(root_path, relative))
        root_real = os.path.realpath(root_path)
    except ValueError as exc:  # un byte nullo nel percorso
        raise ScopeViolation(repr(relative)) from exc
    if not (candidate == root_real or candidate.startswith(root_real + os.sep)):
        raise ScopeViolation(candidate)
    return candidate
