import pytest

from nazgarr.adapters.tracker.base import TorrentCandidate
from nazgarr.upload.dupes import SourceSummary, check, classify

GB = 1024**3


def _candidate(name, size=5 * GB, file_sizes=None, tid="1"):
    return TorrentCandidate(
        torrent_id_remote=tid, info_hash=None, name=name, size_bytes=size, file_list=None,
        mediainfo_unique_id=None, download_link=f"https://t/{tid}", file_sizes=file_sizes,
    )


MOVIE = SourceSummary(
    name="Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC-GRP", total_size_bytes=60 * GB,
    video_sizes=(60 * GB - 1000,), kind="movie", seasons=frozenset(), episode=None,
)


def test_identical_by_total_size():
    result = classify(_candidate("Dune Part Two 2024 2160p REMUX", size=60 * GB), MOVIE)
    assert result["verdict"] == "identical"


def test_identical_by_video_sizes_even_with_different_extras():
    result = classify(
        _candidate("Dune.Part.Two.2024.2160p.BluRay.REMUX-GRP", size=61 * GB,
                   file_sizes={"Dune.mkv": 60 * GB - 1000, "Dune.nfo": 2000}),
        MOVIE,
    )
    assert result["verdict"] == "identical"


@pytest.mark.parametrize(("name", "verdict", "reasons"), [
    ("Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC-OTHER", "same_slot", []),
    ("Dune.Part.Two.2024.1080p.BluRay.REMUX.AVC-OTHER", "different", ["resolution", "hdr"]),
    ("Dune.Part.Two.2024.2160p.UHD.BluRay.x265.DV.HDR-OTHER", "different", ["remux"]),
    ("Dune.Part.Two.2024.2160p.WEB-DL.DV.HDR.H265-OTHER", "different", ["source", "remux"]),
])
def test_movie_slots(name, verdict, reasons):
    result = classify(_candidate(name), MOVIE)
    assert (result["verdict"], result["reasons"]) == (verdict, reasons)


EPISODE = SourceSummary(
    name="Severance.S02E03.1080p.ATVP.WEB-DL.DDP5.1.H.264-GRP.mkv", total_size_bytes=3 * GB,
    video_sizes=(3 * GB,), kind="episode", seasons=frozenset({2}), episode=3,
)


def test_episode_is_covered_by_a_season_pack_of_the_same_slot():
    result = classify(_candidate("Severance.S02.1080p.ATVP.WEB-DL.DDP5.1.H.264-NTb", size=30 * GB), EPISODE)
    assert (result["verdict"], result["reasons"]) == ("same_slot", ["covered_by_pack"])


def test_other_episode_or_season_is_not_a_dupe():
    assert classify(_candidate("Severance.S02E04.1080p.WEB-DL-GRP"), EPISODE)["reasons"] == ["episode"]
    assert classify(_candidate("Severance.S01.1080p.WEB-DL-GRP"), EPISODE)["reasons"] == ["season"]


def test_season_pack_against_a_single_episode():
    pack = SourceSummary(
        name="Severance.S02.1080p.ATVP.WEB-DL-GRP", total_size_bytes=30 * GB, video_sizes=(3 * GB,) * 10,
        kind="season_pack", seasons=frozenset({2}), episode=None,
    )
    assert classify(_candidate("Severance.S02E03.1080p.WEB-DL-X"), pack)["reasons"] == ["single_episode"]
    assert classify(_candidate("Severance.S02.1080p.WEB-DL-X"), pack)["verdict"] == "same_slot"


def test_repack_of_the_same_group_replaces_the_release():
    repack = SourceSummary(
        name="Severance.S02E03.REPACK.1080p.WEB-DL-GRP.mkv", total_size_bytes=3 * GB, video_sizes=(3 * GB,),
        kind="episode", seasons=frozenset({2}), episode=3,
    )
    result = classify(_candidate("Severance.S02E03.1080p.WEB-DL-GRP", size=3 * GB - 5), repack)
    assert (result["verdict"], result["reasons"]) == ("different", ["repack_of_same_group"])


def test_check_orders_results_and_suggests_an_action():
    results, suggested = check([
        _candidate("Dune.Part.Two.2024.1080p.BluRay.REMUX-X", tid="a"),
        _candidate("Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC-X", tid="b"),
    ], MOVIE)
    assert [r["torrent_id_remote"] for r in results] == ["b", "a"]
    assert suggested == "skip"

    assert check([_candidate("x", size=60 * GB)], MOVIE)[1] == "reseed"
    assert check([], MOVIE) == ([], "upload")


def test_a_library_name_without_resolution_uses_the_mediainfo_one():
    """Un nome rinominato da Plex/Radarr non dice la risoluzione: senza
    quella di MediaInfo un 1080p sul tracker sembrava lo stesso posto."""
    plex = SourceSummary(name="Dune Part Two (2024)", total_size_bytes=60 * GB, video_sizes=(60 * GB - 1000,),
                         kind="movie", seasons=frozenset(), episode=None, resolution="2160p")
    assert classify(_candidate("Dune.Part.Two.2024.1080p.WEB-DL.H264-OTHER"), plex)["reasons"] == ["resolution"]
    unknown = SourceSummary(name="Dune Part Two (2024)", total_size_bytes=60 * GB, video_sizes=(60 * GB - 1000,),
                            kind="movie", seasons=frozenset(), episode=None)
    assert classify(_candidate("Dune.Part.Two.2024.1080p.WEB-DL.H264-OTHER"), unknown)["verdict"] == "same_slot"


def test_summary_of_reads_the_release_name_and_the_mediainfo_resolution(tmp_path):
    from types import SimpleNamespace

    from nazgarr.upload.analysis import summary_of

    job = SimpleNamespace(kind="movie", seasons_json="[]", episode=None, source_path=str(tmp_path / "Dune (2024)"),
                          is_dir=True, pack_json=None)
    analysis = {"name_source": {"name": "Dune.Part.Two.2024.2160p.BluRay.REMUX-GRP", "origin": "torrent"},
                "mediainfo": {"video": {"width": 3840, "height": 1608}}}
    summary = summary_of(job, [(str(tmp_path / "Dune (2024)" / "Dune.mkv"), 10)], analysis)
    assert summary.name == "Dune.Part.Two.2024.2160p.BluRay.REMUX-GRP" and summary.resolution == "2160p"
