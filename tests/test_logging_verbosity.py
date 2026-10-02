import logging

from nazgarr.logging_config import VerbosityFilter


def _record(name, message, level=logging.INFO):
    return logging.LogRecord(name, level, __file__, 1, message, None, None)


def test_library_chatter_goes_to_verbose():
    request = _record("httpx", "HTTP Request: GET https://api.themoviedb.org/3 \"HTTP/1.1 200 OK\"")
    started = _record("apscheduler.scheduler", "Scheduler started")

    assert VerbosityFilter().filter(request) and request.levelname == "DEBUG"
    assert VerbosityFilter().filter(started) and started.levelno == logging.DEBUG


def test_the_scheduler_heartbeat_is_dropped_unless_debugging():
    running = 'Running job "_deliver_events (trigger: interval[0:00:15])" (scheduled at 2026-10-02 10:42:52)'
    done = 'Job "_deliver_events (trigger: interval[0:00:15])" executed successfully'

    assert not VerbosityFilter().filter(_record("apscheduler.executors.default", running))
    assert not VerbosityFilter().filter(_record("apscheduler.executors.default", done))
    kept = _record("apscheduler.executors.default", done)
    assert VerbosityFilter(keep_heartbeat=True).filter(kept) and kept.levelname == "DEBUG"


def test_our_messages_and_library_problems_are_untouched():
    ours = _record("nazgarr.pipeline", "Run #3 completata")
    failure = _record("apscheduler.executors.default", "Job raised an exception", logging.ERROR)

    assert VerbosityFilter().filter(ours) and ours.levelname == "INFO"
    assert VerbosityFilter().filter(failure) and failure.levelname == "ERROR"
