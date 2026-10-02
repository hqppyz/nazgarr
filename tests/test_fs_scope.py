import pytest

from nazgarr.fs_scope import ScopeViolation, resolve_scoped


def test_resolves_within_root(tmp_path):
    (tmp_path / "sub").mkdir()
    assert resolve_scoped(str(tmp_path), "sub") == str(tmp_path / "sub")


def test_resolves_root_itself(tmp_path):
    assert resolve_scoped(str(tmp_path), "") == str(tmp_path.resolve())


def test_rejects_parent_traversal(tmp_path):
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(tmp_path), "../outside")


def test_rejects_absolute_escape(tmp_path):
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(tmp_path), "/etc/passwd")
