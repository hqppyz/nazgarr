"""Servizi di streaming e la loro abbreviazione nei nomi delle release: una
lista sola per tutti i tracker (la sorgente di un WEB-DL/WEBRip/WEBMux/DLMux
è il servizio, nazgarr/upload/naming.py {service} e {source_full}).

La lista è quella della wiki di ItaTorrents, che segue la convenzione scene
comune. guessit riconosce da solo buona parte di questi servizi ma li chiama
per nome (es. "Amazon Prime"): per tornare all'abbreviazione si usano i suoi
stessi pattern, scegliendo quello che compare qui. Quelli che guessit non
conosce (es. TIMV) si cercano fra le parole del nome dopo il titolo.
"""

import json
import os
import re
from functools import cache

import guessit

# (piattaforma, abbreviazione)
SERVICES: tuple[tuple[str, str], ...] = (
    ("9Now", "9NOW"), ("A&E", "AE"), ("ABC (AU) iView", "AUBC"), ("ABC (US)", "AMBC"), ("Adult Swim", "AS"),
    ("Al Jazeera English", "AJAZ"), ("All4 (Channel 4, ex-4oD)", "ALL4"), ("Amazon, Prime Video", "AMZN"),
    ("AMC", "AMC"), ("America's Test Kitchen", "ATK"), ("Animal Planet", "ANPL"), ("AnimeLab", "ANLB"),
    ("AOL", "AOL"), ("Apple TV+", "ATVP"), ("ARD", "ARD"), ("BBC iPlayer", "iP"), ("Binge", "BNGE"),
    ("Blackpills", "BKPL"), ("Boomerang", "BOOM"), ("BravoTV", "BRAV"), ("C More", "CMOR"), ("Canal+", "CNLP"),
    ("Cartoon Network", "CN"), ("CBC", "CBC"), ("CBS", "CBS"), ("CHRGD", "CHGD"), ("Cinemax", "CMAX"),
    ("Club illico", "CLBI"), ("CNBC", "CNBC"), ("Comedians in Cars Getting Coffee", "CCGC"),
    ("Comedy Central", "CC"), ("Cooking Channel", "COOK"), ("Country Music Television", "CMT"),
    ("Crackle", "CRKL"), ("Crave", "CRAV"), ("Criterion Channel", "CRIT"), ("Crunchy Roll", "CR"),
    ("CSpan", "CSPN"), ("CTV", "CTV"), ("CuriosityStream", "CUR"), ("The CW", "CW"), ("CWSeed", "CWS"),
    ("Daisuki", "DSKI"), ("DC Universe", "DCU"), ("Deadhouse Films", "DHF"), ("Destination America", "DEST"),
    ("Digiturk Dilediğin Yerde", "DDY"), ("DirecTV Now", "DTV"), ("Discovery Channel", "DISC"),
    ("Discovery+", "DSCP"), ("Disney", "DSNY"), ("Disney+", "DSNP"), ("DIY Network", "DIY"),
    ("Doc Club", "DOCC"), ("DPlay (Rebranded as Discovery+)", "DPLY"), ("DramaFever", "DF"),
    ("Dropout", "DRPO"), ("DRTV", "DRTV"), ("E!", "ETV"), ("El Trece", "ETTV"), ("EPIX", "EPIX"),
    ("ESPN", "ESPN"), ("Esquire", "ESQ"), ("Family", "FAM"), ("Family Jr", "FJR"), ("Food Network", "FOOD"),
    ("Fox", "FOX"), ("Foxtel Now", "FXTL"), ("FPT Play", "FPT"), ("France.tv", "FTV"), ("Freeform", "FREE"),
    ("Funimation", "FUNI"), ("FYI Network", "FYI"), ("Global", "GLBL"), ("GloboSat Play", "GLOB"),
    ("go90", "GO90"), ("Google Play", "PLAY"), ("Hallmark", "HLMK"), ("HBO", "HBO"), ("HBO Max", "HMAX"),
    ("HGTV", "HGTV"), ("HIDIVE", "HIDI"), ("History Channel", "HIST"), ("Hotstar", "HTSR"), ("Hulu", "HULU"),
    ("Ici TOU.TV", "TOU"), ("IFC", "IFC"), ("Investigation Discovery", "ID"), ("iTunes", "iT"), ("ITV", "ITV"),
    ("Kanopy", "KNPY"), ("Kayo Sports", "KAYO"), ("Knowledge Network", "KNOW"), ("Lifetime", "LIFE"),
    ("Loving Nature", "LN"), ("Max", "MAX"), ("MBC", "MBC"), ("Motor Trend OnDemand", "MTOD"),
    ("MSNBC", "MNBC"), ("MTV", "MTV"), ("National Geographic", "NATG"), ("NBA League Pass", "NBA"),
    ("NBC", "NBC"), ("Netflix", "NF"), ("NFL Network", "NFL"), ("NFL Now", "NFLN"), ("NHL GameCenter", "GC"),
    ("Nickelodeon", "NICK"), ("Norsk Rikskringkasting", "NRK"), ("Now (Sky)", "NOW"), ("OnDemandKorea", "ODK"),
    ("Oxygen", "OXGN"), ("Paramount Network", "PMNT"), ("Paramount+", "PMTP"), ("PBS", "PBS"),
    ("PBS Kids", "PBSK"), ("Peacock", "PCOK"), ("Playstation Network", "PSN"), ("Pluzz", "PLUZ"),
    ("PokerGo", "POGO"), ("Project Alpha", "PA"), ("puhutv", "PUHU"), ("Quibi", "QIBI"), ("Rakuten TV", "RKTN"),
    ("The Roku Channel", "ROKU"), ("Rooster Teeth", "RSTR"), ("RTÉ", "RTE"), ("SBS (AU)", "SBS"),
    ("Seeso", "SESO"), ("Shomi", "SHMI"), ("Showtime", "SHO"), ("Shudder", "SHDR"), ("SkyShowtime", "SKST"),
    ("Spike", "SPIK"), ("Sportsnet", "SNET"), ("Sprout", "SPRT"), ("Stan", "STAN"), ("Star+", "STRP"),
    ("Starz", "STZ"), ("Sveriges Television", "SVT"), ("SwearNet", "SWER"), ("SyFy", "SYFY"), ("TBS", "TBS"),
    ("TenPlay", "TEN"), ("TFOU", "TFOU"), ("TIMvision", "TIMV"), ("TLC", "TLC"), ("Travel Channel", "TRVL"),
    ("TubiTV", "TUBI"), ("TV3 (IE)", "TV3"), ("TV4 (SE)", "TV4"), ("TVING", "TVING"), ("TVLand", "TVL"),
    ("UFC", "UFC"), ("UKTV", "UKTV"), ("Univision", "UNIV"), ("USA Network", "USAN"), ("Velocity", "VLCT"),
    ("VET Tv", "VTRN"), ("VH1", "VH1"), ("Viaplay", "VIAP"), ("Viceland", "VICE"), ("Viki", "VIKI"),
    ("Vimeo", "VMEO"), ("VRV", "VRV"), ("W Network", "WNET"), ("WatchMe", "WME"), ("WWE Network", "WWEN"),
    ("Xbox Video", "XBOX"), ("Yahoo", "YHOO"), ("YouTube Movies", "YT"), ("YouTube Red", "RED"), ("ZDF", "ZDF"),
)
ABBREVIATIONS = frozenset(abbr for _name, abbr in SERVICES)

# Dove finisce il titolo: anno, stagione/episodio o risoluzione. Solo dopo si
# cercano le abbreviazioni, così una parola del titolo (es. "Max") non conta.
_TITLE_END = re.compile(r"^((19|20)\d\d|S\d{1,2}(E\d{1,3})*|\d{3,4}[pi])$", re.IGNORECASE)
_WORDS = re.compile(r"[ ._\-\[\]()]+")


@cache
def _guessit_patterns() -> dict[str, list[str]]:
    path = os.path.join(os.path.dirname(guessit.__file__), "config", "options.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)["advanced_config"]["streaming_service"]
    def plain(pattern) -> str:  # {"pattern": "iT", "ignore_case": false} -> "iT"
        return pattern["pattern"] if isinstance(pattern, dict) else pattern

    return {name: [plain(p) for p in (patterns if isinstance(patterns, list) else [patterns])]
            for name, patterns in raw.items()}


def abbreviation(guessit_name: str | None, release_name: str | None = None) -> str | None:
    """L'abbreviazione del servizio: dal nome che dà guessit, se no dalle
    parole del nome della release dopo il titolo."""
    if guessit_name:
        patterns = _guessit_patterns().get(str(guessit_name), [])
        found = next((p for p in patterns if p in ABBREVIATIONS), None)
        if found:
            return found
        plain = next((p for p in patterns if not p.startswith("re:")), None)
        return plain or str(guessit_name)
    if not release_name:
        return None
    words = [w for w in _WORDS.split(release_name) if w]
    start = next((i + 1 for i, w in enumerate(words) if _TITLE_END.match(w)), None)
    if start is None:
        return None
    return next((w for w in words[start:] if w in ABBREVIATIONS), None)
