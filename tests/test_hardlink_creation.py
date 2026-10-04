"""L'unico modo di creare hardlink (nazgarr/hardlinks.py), per l'esecuzione
delle review e per l'upload."""

import os

import pytest

from nazgarr import hardlinks
from nazgarr.fs_scope import ScopeViolation


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
