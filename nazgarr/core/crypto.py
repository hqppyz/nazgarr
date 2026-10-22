"""Cifratura a riposo dei segreti salvati nel DB.

docs/schema.sql marca `tracker.api_token` e `torrent_client.password` come
"cifrato a riposo". Usato dal TypeDecorator EncryptedString in nazgarr/core/models.py.
"""

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class SecretKeyMissingError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET_KEY")
    if not key:
        raise SecretKeyMissingError(
            "APP_SECRET_KEY non impostata: necessaria per cifrare/decifrare "
            "credenziali tracker/torrent_client. Vedi .env.example."
        )
    return Fernet(key.encode())


def check_key() -> None:
    """APP_SECRET_KEY c'è ed è una chiave Fernet. All'avvio, prima del backup
    e dell'aggiornamento del database (nazgarr/core/db_startup.py): una
    chiave che manca è un errore di configurazione, non un aggiornamento
    fallito da ripristinare con un backup (che butterebbe via dati)."""
    try:
        _fernet()
    except ValueError as exc:  # Fernet: non 32 byte in base64 url-safe
        raise SecretKeyMissingError(
            "APP_SECRET_KEY non è una chiave valida (32 byte in base64 url-safe, come la genera "
            "`nazgarr init` o Fernet.generate_key()). Vedi .env.example."
        ) from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Impossibile decifrare il valore: chiave errata o dato corrotto") from exc
