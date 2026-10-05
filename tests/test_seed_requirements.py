from nazgarr.torrents.seed_requirements import Requirement, evaluate

DAY = 86400


def _req(seed=None, ratio=None, rule="any"):
    return Requirement(tracker_id=1, tracker_label="T", min_seed_time_seconds=seed, min_ratio=ratio, rule=rule)


def test_an_unknown_tracker_or_one_without_rules_says_nothing():
    assert evaluate(None, 3.0, 10 * DAY)["status"] == "unknown_tracker"
    assert evaluate(_req(), 3.0, 10 * DAY)["status"] == "no_rules"


def test_a_single_requirement_is_met_or_says_what_is_missing():
    assert evaluate(_req(seed=7 * DAY), None, 8 * DAY)["status"] == "met"
    pending = evaluate(_req(seed=7 * DAY), 5.0, 5 * DAY)
    assert pending["status"] == "pending" and pending["remaining"] == {"seed_time_seconds": 2 * DAY}
    assert evaluate(_req(ratio=1.0), 0.4, None)["remaining"] == {"ratio": 0.6}


def test_with_both_set_either_is_enough_unless_the_tracker_wants_both():
    assert evaluate(_req(seed=3 * DAY, ratio=1.0), 1.2, DAY)["status"] == "met"
    both = evaluate(_req(seed=3 * DAY, ratio=1.0, rule="all"), 1.2, DAY)
    assert both["status"] == "pending" and both["remaining"] == {"seed_time_seconds": 2 * DAY}
    assert evaluate(_req(seed=3 * DAY, ratio=1.0, rule="all"), 1.2, 4 * DAY)["status"] == "met"


def test_when_the_client_does_not_report_it_the_answer_is_unknown():
    assert evaluate(_req(seed=DAY), 2.0, None)["status"] == "unknown"
    # Uno dei due basta: il ratio già raggiunto decide anche senza seedtime.
    assert evaluate(_req(seed=DAY, ratio=1.0), 2.0, None)["status"] == "met"
    # Servono entrambi: un no basta anche senza l'altro dato.
    assert evaluate(_req(seed=DAY, ratio=1.0, rule="all"), 0.5, None)["status"] == "pending"
