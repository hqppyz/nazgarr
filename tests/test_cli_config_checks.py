"""Il CLI e i controlli della configurazione (audit 2026-10-18): una
pianificazione salvata che non si legge, un indirizzo in chiaro verso un host
pubblico, cosa se ne va eliminando un tracker o un disco."""

from tests.test_cli_client import _login, cli_env, run  # noqa: F401 (cli_env è un fixture)


def test_schedule_show_says_a_stored_cron_cannot_be_read(cli_env, client, capsys):
    from nazgarr.core import settings_repo

    _login(capsys)
    with client.app.state.session_factory() as session:
        settings_repo.set_setting(session, "schedule_cron", "every night please")

    code, out, err = run(capsys, "schedule", "show")

    assert code == 0, err
    assert "cannot be read" in err and "every night please" in err
    assert "run on their own" not in out
