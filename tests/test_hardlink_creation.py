"""L'unico modo di creare hardlink (nazgarr/library/hardlinks.py), per l'esecuzione
delle review e per l'upload."""

import os

import pytest

from nazgarr.core.fs_scope import ScopeViolation
from nazgarr.library import hardlinks


@pytest.fixture
def area(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "seed").mkdir()
    source = tmp_path / "media" / "Movie.mkv"
    source.write_bytes(b"x" * 100)
    return tmp_path, str(source), str(tmp_path / "seed")


def test_check_link_accepts_a_free_target_and_reuses_the_same_file(area):
    tmp_path, source, root = area
    target = os.path.join(root, "Release", "Movie.mkv")
    assert hardlinks.check_link(source, target, root) == os.path.realpath(target)
    os.makedirs(os.path.dirname(target))
    os.link(source, target)
    assert hardlinks.check_link(source, target, root) is None  # già lo stesso file: si riusa


def test_check_link_refuses_symlinks_other_files_and_paths_outside(area):
    tmp_path, source, root = area
    link = tmp_path / "media" / "link.mkv"
    link.symlink_to(source)
    with pytest.raises(hardlinks.LinkProblem) as problem:
        hardlinks.check_link(str(link), os.path.join(root, "x.mkv"), root)
    assert problem.value.code == "source_not_a_file"
    other = os.path.join(root, "Other.mkv")
    with open(other, "wb") as f:
        f.write(b"y")
    with pytest.raises(hardlinks.LinkProblem) as problem:
        hardlinks.check_link(source, other, root)
    assert problem.value.code == "target_exists"
    with pytest.raises(ScopeViolation):
        hardlinks.check_link(source, os.path.join(root, "..", "media", "escape.mkv"), root)


def test_create_links_removes_what_it_created_if_one_fails(area, monkeypatch):
    tmp_path, source, root = area
    first, second = os.path.join(root, "a", "1.mkv"), os.path.join(root, "b", "2.mkv")
    real = os.link
    monkeypatch.setattr(os, "link", lambda s, t, **kw: (_ for _ in ()).throw(OSError("full"))
                        if t == second else real(s, t, **kw))
    with pytest.raises(OSError):
        hardlinks.create_links([(source, first), (source, second)])
    assert not os.path.lexists(first) and os.path.isfile(source)


@pytest.fixture
def strict_umask():
    previous = os.umask(0o077)  # come la umask di prima, per tutto il processo
    try:
        yield
    finally:
        os.umask(previous)


def test_new_folders_copy_the_permissions_of_the_folder_above(area, strict_umask):
    # Con la umask 077 le cartelle di seed nascevano 0700: un client torrent con
    # un altro utente dello stesso gruppo non ci entrava (audit 2026-10-18).
    tmp_path, source, root = area
    os.chmod(root, 0o2775)
    os.chmod(source, 0o664)
    target = os.path.join(root, "Movie.2020.1080p", "Sub", "Movie.mkv")
    resolved = hardlinks.check_link(source, target, root)
    assert hardlinks.create_links([(source, resolved)]) == [resolved]
    for folder in (os.path.join(root, "Movie.2020.1080p"), os.path.join(root, "Movie.2020.1080p", "Sub")):
        assert os.stat(folder).st_mode & 0o7777 == 0o2775, folder
        assert os.stat(folder).st_gid == os.stat(root).st_gid
    assert os.stat(resolved).st_mode & 0o777 == 0o664  # un hardlink: lo stesso file


def test_make_dirs_leaves_existing_folders_alone(tmp_path, strict_umask):
    existing = tmp_path / "seed"
    existing.mkdir(mode=0o750)
    os.chmod(existing, 0o750)
    hardlinks.make_dirs(str(existing))
    assert os.stat(existing).st_mode & 0o777 == 0o750
    (tmp_path / "file").write_text("x")
    with pytest.raises(FileExistsError):
        hardlinks.make_dirs(str(tmp_path / "file"))


def test_new_folders_never_lose_permissions_they_were_created_with(tmp_path):
    # Copiare il modo tale e quale toglieva bit: sotto una cartella 0750 una
    # nuova perdeva r-x per gli altri, e con una cartella sopra senza rwx per
    # il proprietario Nazgarr si chiudeva fuori da solo.
    previous = os.umask(0o022)
    try:
        parent = tmp_path / "seed"
        parent.mkdir()
        os.chmod(parent, 0o750)
        hardlinks.make_dirs(str(parent / "a"))
        assert os.stat(parent / "a").st_mode & 0o7777 == 0o755
        os.chmod(parent, 0o2370)  # il proprietario può creare, ma non leggere
        hardlinks.make_dirs(str(parent / "b"))
        assert os.stat(parent / "b").st_mode & 0o7777 == 0o2775
    finally:
        os.chmod(tmp_path / "seed", 0o755)
        os.umask(previous)


def test_under_an_acl_managed_folder_the_mode_is_left_to_the_acl(tmp_path, strict_umask, monkeypatch):
    # Synology (d---------+) o un dataset NFSv4 di TrueNAS: i bit della
    # cartella sopra valgono 0, si scrive grazie all'ACL. Prima la cartella
    # nuova finiva a 0000 e l'hardlink dopo falliva con EACCES (audit 2026-10-18).
    import stat

    acl_root = tmp_path / "share"
    acl_root.mkdir()
    real_stat = os.stat

    def acl_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fspath(path) == str(acl_root):
            fields = list(result)
            fields[0] = stat.S_IFDIR  # nessun bit di permesso
            return os.stat_result(fields)
        return result

    chmods = []
    real_chmod = os.chmod
    monkeypatch.setattr(os, "stat", acl_stat)
    monkeypatch.setattr(os, "chmod", lambda path, mode, **kw: (chmods.append(mode), real_chmod(path, mode, **kw)))
    hardlinks.make_dirs(str(acl_root / "Movie.2020.1080p"))
    monkeypatch.undo()
    assert chmods == []
    assert os.stat(acl_root / "Movie.2020.1080p").st_mode & 0o700 == 0o700
