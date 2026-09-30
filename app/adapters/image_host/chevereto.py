"""Helper condiviso per gli host "famiglia chevereto" (lensdump, ptscreens,
onlyimage, dalexni) — stessa piattaforma software (Chevereto) dietro host
diversi, con piccole differenze di annidamento della risposta reale non
tutte confermate byte-per-byte (ricerca su Upload-Assistant via un report
di sintesi, non il codice letto direttamente per ognuno). Il parser prova
più percorsi ragionevoli invece di assumerne uno solo che potrebbe rompersi
silenziosamente su un host con un annidamento leggermente diverso — mai
verificato contro un account reale per nessuno di questi (stessa categoria
di apertura già accettata per ptpimg/imgbb/pixhost)."""


def chevereto_image_url(data: dict) -> str | None:
    """L'immagine a risoluzione piena: la descrizione la mostra ridotta
    ([img=larghezza]) e al clic apre proprio questa. La versione media solo
    se la risposta non ha l'originale."""
    candidates = [
        lambda d: d["data"]["image"]["url"],
        lambda d: d["image"]["url"],
        lambda d: d["data"]["url"],
        lambda d: d["data"]["image"]["medium"]["url"],
        lambda d: d["image"]["medium"]["url"],
        lambda d: d["data"]["medium"]["url"],
    ]
    for get_url in candidates:
        try:
            url = get_url(data)
        except (KeyError, TypeError):
            continue
        if isinstance(url, str) and url:
            return url
    return None
