"""La forma delle regole di naming (nazgarr/upload/naming.py): quelle di un
profilo di upload e quelle dei nomi dei file (nazgarr/upload/file_names.py).

Arrivano come JSON libero dall'API (il CLI con `tracker profile naming
--set`, un config import, uno script) e prima si salvavano senza controllo:
un "templates": 5, un "separator": 3 o un "audio_languages": "all" facevano
fallire con un TypeError ogni upload in analisi (le regole dei nomi dei
file) o ogni upload verso quel tracker (quelle del profilo), lontano dalla
modifica che li aveva causati (audit 2026-10-18). L'editor della UI non
produce queste forme.

Si controllano i tipi delle chiavi note; le altre passano, come i campi
"version" e "force" dei profili bundlati o una chiave di una versione più
nuova.
"""

from nazgarr.core.errors import CodedError

# Testi liberi (None vale il default).
_TEXT = (
    "separator", "group_separator", "subs_format", "subs_multi_format", "subs_style", "sdr_label",
    "title_language", "language", "subs_label", "audio",
)
# Mappe testo -> testo: i template per tipo e le etichette.
_MAPS = ("templates", "audio_codecs", "type_labels", "hybrid_type_labels", "format_labels")
_LANGUAGES = ("audio_languages", "subs_languages")
TITLE_CHOICES = ("original", "local", "local_original")
LANGUAGE_STYLES = ("none", "all", "primary_first")


class NamingRulesError(CodedError):
    """Regole che non hanno la forma attesa; field dice quale chiave."""

    def __init__(self, field: str):
        super().__init__("upload_invalid_naming_rules", field=field)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate(rules) -> dict:
    """Le regole come sono, se hanno la forma attesa; NamingRulesError se no."""
    if not isinstance(rules, dict):
        raise NamingRulesError("rules")
    for key in _TEXT:
        if rules.get(key) is not None and not isinstance(rules[key], str):
            raise NamingRulesError(key)
    for key in _MAPS:
        value = rules.get(key)
        if value is None:
            continue
        if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
            raise NamingRulesError(key)
    if rules.get("title") is not None and rules["title"] not in TITLE_CHOICES:
        raise NamingRulesError("title")
    for key in _LANGUAGES:
        value = rules.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise NamingRulesError(key)
        if value.get("style") is not None and value["style"] not in LANGUAGE_STYLES:
            raise NamingRulesError(f"{key}.style")
        if value.get("primary") is not None and not isinstance(value["primary"], str):
            raise NamingRulesError(f"{key}.primary")
        multi_from = value.get("multi_from")
        if multi_from is not None and (not _is_int(multi_from) or multi_from < 0):
            raise NamingRulesError(f"{key}.multi_from")
    if rules.get("version") is not None and not _is_int(rules["version"]):
        raise NamingRulesError("version")
    return rules
