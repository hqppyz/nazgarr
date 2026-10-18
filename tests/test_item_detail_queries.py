"""La scheda di dettaglio di una serie (GET /api/library/items/...): le
query non crescono con gli episodi in revisione e le loro esecuzioni (audit
2026-10-18). Prima ogni review ricostruiva il suo contesto (seeding_on con
due GROUP BY su tutta la libreria, i client, le esecuzioni)."""

from nazgarr.api import library as api
from nazgarr.core.models import SeedJob
from tests.test_review_queue import _counting, _Library

TMDB_ID = 1399


def _detail_statements(session, library: _Library, start: int, count: int, executions: bool = False) -> int:
    for episode in range(start, start + count):
        review = library.review(tmdb_id=TMDB_ID, season=1, episode=episode, seeding=episode % 2 == 0)
        if executions and episode % 3 == 0:  # un'esecuzione già partita: la sua review esce dalla coda
            session.add(SeedJob(candidate_id=review.candidate_id, source_media_file_id=review.media_file_id,
                                final_status="failed", error_message="x"))
    session.commit()
    session.expire_all()
    with _counting(session) as statements:
        detail = api.get_item_detail("tv", TMDB_ID, session)
    assert len(detail["files"]) == start + count - 1
    assert detail["reviews"] and detail["seed_jobs"]
    return len(statements)


def test_the_detail_of_a_series_costs_the_same_queries_with_more_episodes(db_session):
    library = _Library(db_session)
    # Le esecuzioni restano quelle del primo giro: ognuna legge ancora il suo
    # candidato (nazgarr/library/detail.py), una query piccola per esecuzione.
    few = _detail_statements(db_session, library, 1, 3, executions=True)
    many = _detail_statements(db_session, library, 4, 30)
    assert many <= few + 2, (few, many)
