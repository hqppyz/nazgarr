from nazgarr.adapters.torrent_client.base import seeders
from nazgarr.adapters.torrent_client.transmission import TransmissionAdapter


def test_seeder_counts_below_one_mean_unknown():
    assert [seeders(v) for v in (3, "1", 0, -1, None, "x")] == [3, 1, None, None, None, None]


def test_transmission_takes_the_highest_count_among_its_trackers():
    torrent = {"hashString": "h", "trackerStats": [{"seederCount": -1}, {"seederCount": 4}, {"seederCount": 1}]}
    assert TransmissionAdapter._info(torrent).swarm_seeders == 4
    assert TransmissionAdapter._info({"hashString": "h", "trackerStats": [{"seederCount": -1}]}).swarm_seeders is None
    assert TransmissionAdapter._info({"hashString": "h"}).swarm_seeders is None
