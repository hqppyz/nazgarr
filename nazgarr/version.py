"""Versione dell'app, mostrata in fondo alla sidebar e usata dal controllo
aggiornamenti (Configuration > Application).

La versione vera la decide la CI (.github/workflows/docker-publish.yml): a
ogni push su main incrementa la patch dell'ultimo tag vX.Y.Z (0.2.1,
0.2.2, …), crea tag e GitHub Release e la inietta nell'immagine Docker
(NAZGARR_VERSION / NAZGARR_COMMIT) — nessun commit automatico
sul repo. Qui resta solo la base major.minor: per passare a 0.3.x basta
alzare BASE_VERSION a "0.3.0", la CI parte da lì al push successivo.
1.0.0 è riservata a un rilascio pubblico vero, testato end-to-end.

Canali: ogni push su main è una build di test (GitHub prerelease, immagine
:nightly). Una versione già pubblicata diventa stable solo a mano, col
workflow "Promote to stable" (.github/workflows/promote-stable.yml):
immagini :stable e :latest, tag git "stable", release non più prerelease.

Fuori da un'immagine pubblicata (sviluppo locale) la versione è
BASE_VERSION + "-dev": a colpo d'occhio non si confonde con una release."""

import os

BASE_VERSION = "0.7.0"

# Il pacchetto Python (pipx, scripts/build_package.sh) porta con sé la sua
# versione in nazgarr/_build_info.py, scritto al momento della build.
try:
    from nazgarr._build_info import COMMIT as _BUILT_COMMIT
    from nazgarr._build_info import VERSION as _BUILT_VERSION
except ImportError:
    _BUILT_VERSION = _BUILT_COMMIT = None

__version__ = os.environ.get("NAZGARR_VERSION") or _BUILT_VERSION or f"{BASE_VERSION}-dev"
# Commit breve da cui è stata costruita l'immagine, None in sviluppo locale.
__commit__ = os.environ.get("NAZGARR_COMMIT") or _BUILT_COMMIT or None
