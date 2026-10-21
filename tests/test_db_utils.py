from datetime import UTC, datetime, timedelta, timezone

from nazgarr.core.db_utils import as_utc


def test_as_utc_reads_a_date_without_zone_as_utc_and_keeps_one_with_its_zone():
    """SQLite restituisce senza fuso anche le date salvate con: sono UTC.
    Un solo helper per tutti (audit 2026-10-18, finding 126)."""
    naive = datetime(2026, 10, 21, 12, 0, tzinfo=UTC).replace(tzinfo=None)  # come la rende SQLite
    rome = datetime(2026, 10, 21, 14, 0, tzinfo=timezone(timedelta(hours=2)))

    assert as_utc(None) is None
    assert as_utc(naive) == datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    assert as_utc(rome) is rome
