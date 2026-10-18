"""Un'istruzione SQL che fallisce a metà di una migrazione, come un avvio
interrotto: lo stato salvato dopo il fallimento è quello che troverebbe
il riavvio (le istruzioni già committate restano, il resto no)."""

import sqlite3


def fail_once(monkeypatch, engine, action: int, table: str) -> None:
    """La prima istruzione `action` (sqlite3.SQLITE_INSERT, SQLITE_ALTER_TABLE...)
    su `table` fallisce con "not authorized"; tutte le altre passano."""
    fired = []

    def authorizer(code, arg1, arg2, _db, _source):
        target = arg2 if code == sqlite3.SQLITE_ALTER_TABLE else arg1
        if not fired and code == action and target == table:
            fired.append(True)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    real = engine.raw_connection

    def raw_connection():
        conn = real()
        conn.driver_connection.set_authorizer(authorizer)
        return conn

    monkeypatch.setattr(engine, "raw_connection", raw_connection)
