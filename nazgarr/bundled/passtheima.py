"""Passtheima: host di immagini Chevereto, plugin incluso (decisione dell'utente, 2026-10-05)."""

from nazgarr.bundled._chevereto import REQUIRES_SDK, register_chevereto

PLUGIN_NAME = "nazgarr-passtheima"
DESCRIPTION = "Screenshots on Passtheima (https://passtheima.ge), with your API key."
__all__ = ["DESCRIPTION", "PLUGIN_NAME", "REQUIRES_SDK", "setup"]


def setup() -> None:
    register_chevereto("passtheima", "Passtheima", "https://passtheima.ge")
