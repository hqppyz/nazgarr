import pytest

from nazgarr.upload_source import scan_source
from tests.upload_helpers import write_video


def test_single_movie_file(tmp_path):
    video = write_video(tmp_path / "Movie.Name.2024.1080p.BluRay.x264-GRP.mkv")

    layout = scan_source(str(video))

    assert layout.kind == "movie"
    assert layout.content_type == "movie"
    assert layout.title == "Movie Name"
    assert layout.year == 2024
    assert layout.main_video == str(video)
    assert layout.release_group == "GRP"


def test_single_episode_file(tmp_path):
    video = write_video(tmp_path / "Show.Name.S02E03.1080p.WEB-DL-GRP.mkv")

    layout = scan_source(str(video))

    assert layout.kind == "episode"
    assert layout.seasons == [2]
    assert layout.episodes_by_season == {2: [3]}


def test_movie_folder_ignores_sample_and_extras(tmp_path):
    folder = tmp_path / "Movie.Name.2024.1080p.BluRay.x264-GRP"
    write_video(folder / "Movie.Name.2024.1080p.BluRay.x264-GRP.mkv", 50000)
    write_video(folder / "Sample" / "sample.mkv", 1000)
    (folder / "movie.nfo").write_text("nfo")

    layout = scan_source(str(folder))

    assert layout.kind == "movie"
    assert [v.relative_path for v in layout.videos] == ["Movie.Name.2024.1080p.BluRay.x264-GRP.mkv"]
    assert layout.other_files == 2  # nfo + il sample
    assert layout.main_video.endswith("Movie.Name.2024.1080p.BluRay.x264-GRP.mkv")


def test_season_pack_folder(tmp_path):
    folder = tmp_path / "Show.Name.S02.1080p.WEB-DL-GRP"
    for ep in (1, 2, 4):
        write_video(folder / f"Show.Name.S02E0{ep}.1080p.WEB-DL-GRP.mkv")

    layout = scan_source(str(folder))

    assert layout.kind == "season_pack"
    assert layout.content_type == "tv"
    assert layout.seasons == [2]
    assert layout.episodes_by_season == {2: [1, 2, 4]}


def test_complete_pack_with_season_subfolders_and_bare_episode_names(tmp_path):
    folder = tmp_path / "Show Name (2019) Complete"
    write_video(folder / "Season 1" / "Show Name - 01.mkv")
    write_video(folder / "Season 1" / "Show Name - 02.mkv")
    write_video(folder / "Season 2" / "Show Name - 01.mkv")

    layout = scan_source(str(folder))

    assert layout.kind == "complete_pack"
    assert layout.seasons == [1, 2]
    assert layout.episodes_by_season == {1: [1, 2], 2: [1]}


def test_folder_without_videos_raises(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "readme.txt").write_text("x")

    with pytest.raises(ValueError, match="no_video_files"):
        scan_source(str(folder))


def test_a_movie_folder_reads_the_file_name_first_and_the_folder_for_what_is_missing(tmp_path):
    # La cartella dice poco ("New release"), il file dice tutto.
    write_video(tmp_path / "New release" / "Movie.Name.2024.1080p.WEB-DL.H.264-GRP.mkv")
    layout = scan_source(str(tmp_path / "New release"))
    assert (layout.title, layout.year, layout.release_group) == ("Movie Name", 2024, "GRP")

    # Il file non ha l'anno: lo dà la cartella.
    write_video(tmp_path / "Other Movie (2019)" / "Other.Movie.1080p.BluRay.x264-GRP.mkv")
    layout = scan_source(str(tmp_path / "Other Movie (2019)"))
    assert (layout.title, layout.year) == ("Other Movie", 2019)
