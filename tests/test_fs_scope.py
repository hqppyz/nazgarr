import pytest

from nazgarr.core.fs_scope import ScopeViolation, resolve_scoped


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


def test_a_symlinked_directory_inside_the_root_cannot_lead_outside(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(root), "link/x")


def test_a_symlinked_directory_that_stays_inside_is_fine(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    assert resolve_scoped(str(tmp_path), "alias/x") == str((tmp_path / "real" / "x").resolve())


def test_a_sibling_folder_with_the_same_prefix_is_outside(tmp_path):
    # disk1 e disk10: un controllo con startswith(root) senza separatore li confonderebbe.
    (tmp_path / "disk1").mkdir()
    (tmp_path / "disk10").mkdir()
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(tmp_path / "disk1"), "../disk10/x")


def test_a_root_given_through_a_symlink_still_scopes_correctly(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "mount").symlink_to(tmp_path / "real", target_is_directory=True)
    assert resolve_scoped(str(tmp_path / "mount"), "a") == str((tmp_path / "real" / "a").resolve())
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(tmp_path / "mount"), "../x")


def test_a_null_byte_is_a_scope_violation_not_a_crash(tmp_path):
    with pytest.raises(ScopeViolation):
        resolve_scoped(str(tmp_path), "a\x00b")
