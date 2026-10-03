import pytest

from nazgarr.guess import clean_name, guess
from nazgarr.upload_source import scan_source


@pytest.mark.parametrize("name, cleaned", [
    ("The Matrix_t00.mkv", "The Matrix.mkv"),
    ("The Matrix (1999)_t01.mkv", "The Matrix (1999).mkv"),
    ("Inception t02.mkv", "Inception.mkv"),
    ("/data/rips/Show S01E01_t03.mkv", "/data/rips/Show S01E01.mkv"),
    ("Movie.2024_t100", "Movie.2024"),
    # Non è il suffisso di MakeMKV: resta.
    ("Matt00.mkv", "Matt00.mkv"),
    ("t00.mkv", "t00.mkv"),
    ("Show.S01E01.1080p.WEB-DL-GRP.mkv", "Show.S01E01.1080p.WEB-DL-GRP.mkv"),
])
def test_the_makemkv_title_suffix_goes(name, cleaned):
    assert clean_name(name) == cleaned


def test_the_title_is_read_without_it(tmp_path):
    assert guess("The Matrix_t00.mkv")["title"] == "The Matrix"
    assert "episode_title" not in guess("Show S01E01_t03.mkv")
    video = tmp_path / "Arrival (2016)_t00.mkv"
    video.write_bytes(b"x" * 1000)
    layout = scan_source(str(video))
    assert (layout.title, layout.year) == ("Arrival", 2016)
