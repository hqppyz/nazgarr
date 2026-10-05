"""imageride: host di immagini Chevereto, plugin incluso (decisione dell'utente, 2026-10-05)."""

from nazgarr.bundled._chevereto import REQUIRES_SDK, register_chevereto

PLUGIN_NAME = "nazgarr-imageride"
DESCRIPTION = "Screenshots on imageride (https://www.imageride.net), with your API key."
__all__ = ["DESCRIPTION", "PLUGIN_NAME", "REQUIRES_SDK", "setup"]


def setup() -> None:
    register_chevereto("imageride", "imageride", "https://www.imageride.net")
