import pytest

from nazgarr.core import net_guard


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/", "http://0.0.0.0:8080/",
    "http://[fd00:ec2::254]/", "http://[::ffff:169.254.169.254]/",
])
def test_metadata_and_link_local_are_forbidden(url):
    with pytest.raises(net_guard.ForbiddenDestination):
        net_guard.check_url(url)


@pytest.mark.parametrize("url", ["http://192.168.1.10:8080/", "http://10.0.0.5/", "http://127.0.0.1:7878/"])
def test_the_lan_stays_reachable(url):
    net_guard.check_url(url)  # client torrent, Radarr e Sonarr vivono qui
