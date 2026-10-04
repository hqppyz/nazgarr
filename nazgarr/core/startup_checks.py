"""Controlli che devono fallire in modo rumoroso all'avvio, invece di
emergere come un errore confuso dentro un endpoint qualunque molto più
tardi (mai un fallimento silenzioso — stesso principio già applicato al
recheck forzato e alla validazione st_dev, vedi docs/SPEC.md).
"""

import logging

from sqlalchemy.orm import Session

from nazgarr.core import crypto
from nazgarr.core.models import AppSetting

logger = logging.getLogger(__name__)

_CANARY_KEY = "app_secret_key_canary"
_CANARY_PLAINTEXT = "nazgarr-secret-key-check"
# Prima del rename del progetto: ancora valido, e riscritto col testo nuovo.
_LEGACY_CANARY_PLAINTEXT = "gauntletarr-secret-key-check"


class SecretKeyMismatchError(RuntimeError):
    pass


def verify_secret_key(session: Session) -> None:
    """Rileva un APP_SECRET_KEY cambiato rispetto a quello usato la prima
    volta per cifrare i dati (tracker.api_token/torrent_client.password,
    docs/schema.sql). Senza questo controllo, una chiave cambiata non
    fallisce finché qualcosa non prova a decifrare una riga reale — un
    errore confuso, lontano dalla causa reale, e non è detto che accada
    subito all'avvio. Qui fallisce prima, con un messaggio esplicito."""
    row = session.get(AppSetting, _CANARY_KEY)
    if row is None:
        # Primo avvio (o DB nuovo): non c'è ancora nulla con cui confrontare,
        # scriviamo il valore di riferimento cifrato con la chiave corrente.
        row = AppSetting(key=_CANARY_KEY, value=crypto.encrypt(_CANARY_PLAINTEXT))
        session.add(row)
        session.commit()
        return

    try:
        decrypted = crypto.decrypt(row.value)
    except ValueError as exc:
        raise SecretKeyMismatchError(
            "APP_SECRET_KEY non corrisponde più alla chiave usata per cifrare i dati "
            "già presenti nel database: ogni token tracker e password client torrent "
            "salvati finora sono ora illeggibili. Ripristina la APP_SECRET_KEY "
            "precedente se la conservi ancora, oppure riparti con quella nuova "
            "reinserendo da capo quelle credenziali."
        ) from exc
    if decrypted == _LEGACY_CANARY_PLAINTEXT:
        row.value = crypto.encrypt(_CANARY_PLAINTEXT)
        session.commit()
        return
    if decrypted != _CANARY_PLAINTEXT:
        # Non dovrebbe accadere in pratica (Fernet solleverebbe già InvalidToken
        # su qualunque manomissione/chiave sbagliata prima di arrivare qui), ma
        # mai fidarsi in silenzio.
        raise SecretKeyMismatchError("Verifica di APP_SECRET_KEY fallita in modo inatteso.")
