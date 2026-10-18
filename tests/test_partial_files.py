"""I file che un client rinomina mentre sono incompleti (Transmission,
rename-partial-files: "<nome>.part"), rimessi al loro nome dopo un recheck
fallito (decisione dell'utente, 2026-10-19; nazgarr/torrents/partial_files.py)."""

import os

from nazgarr.torrents import partial_files


def _identity(path):
    st = os.lstat(path)
    return st.st_dev, st.st_ino


def _seeding(tmp_path):
    folder = tmp_path / "disk" / "torrents"
    folder.mkdir(parents=True)
    return os.path.realpath(folder)


def test_a_tracked_file_renamed_by_the_client_gets_its_name_back(tmp_path):
    folder = _seeding(tmp_path)
    path = os.path.join(folder, "Movie", "Movie.mkv")
    os.makedirs(os.path.dirname(path))
    with open(path + ".part", "wb") as f:
        f.write(b"x")

    restored = partial_files.restore_names([path], {_identity(path + ".part")}, ".part", [folder])

    assert restored == [path] and os.path.isfile(path) and not os.path.exists(path + ".part")


def test_only_files_with_the_recorded_identity_inside_the_folders(tmp_path):
    folder = _seeding(tmp_path)
    mine = os.path.join(folder, "mine.mkv")
    other = os.path.join(folder, "other.mkv")
    outside = str(tmp_path / "elsewhere.mkv")
    for path in (mine, other, outside):
        with open(path + ".part", "wb") as f:
            f.write(b"x")
    known = {_identity(mine + ".part"), _identity(outside + ".part")}

    restored = partial_files.restore_names([mine, other, outside], known, ".part", [folder])

    assert restored == [mine]
    assert os.path.exists(other + ".part") and os.path.exists(outside + ".part")


def test_never_over_another_file_never_through_a_symlink(tmp_path):
    folder = _seeding(tmp_path)
    taken = os.path.join(folder, "taken.mkv")
    for path in (taken, taken + ".part"):
        with open(path, "wb") as f:
            f.write(b"x")
    # Un link simbolico al posto del file rinominato: mai seguito.
    target = tmp_path / "library.mkv"
    target.write_bytes(b"y")
    linked = os.path.join(folder, "linked.mkv")
    os.symlink(target, linked + ".part")
    # Una cartella che è un link simbolico verso fuori.
    real = tmp_path / "outside"
    real.mkdir()
    (real / "ep.mkv.part").write_bytes(b"z")
    os.symlink(real, os.path.join(folder, "jump"))
    through = os.path.join(folder, "jump", "ep.mkv")
    known = {_identity(taken + ".part"), _identity(str(target)), _identity(str(real / "ep.mkv.part"))}

    restored = partial_files.restore_names([taken, linked, through], known, ".part", [folder])

    assert restored == []
    assert os.path.islink(linked + ".part") and (real / "ep.mkv.part").exists()


def test_the_suffix_comes_from_the_client_only_when_it_says_so():
    class Renames:
        def partial_file_suffix(self):
            return ".part"

    class Down:
        def partial_file_suffix(self):
            raise RuntimeError("down")

    class Odd:
        def partial_file_suffix(self):
            return "/x"

    assert partial_files.suffix_of(Renames()) == ".part"
    assert partial_files.suffix_of(Down()) is None and partial_files.suffix_of(Odd()) is None
    assert partial_files.suffix_of(object()) is None  # un plugin senza la classe base
