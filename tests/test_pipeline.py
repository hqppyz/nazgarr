

def test_every_error_of_a_run_is_kept_not_only_the_last():
    import json

    from nazgarr.core.models import RunLog
    from nazgarr.reseed.pipeline import _note_error

    run = RunLog(run_type="manual")
    _note_error(run, "tracker 'a': boom")
    _note_error(run, "TMDB resolution: timeout")

    assert json.loads(run.errors_json) == ["tracker 'a': boom", "TMDB resolution: timeout"]
    assert run.last_error == "TMDB resolution: timeout"
