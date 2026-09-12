"""The corruption detector matches Flet's desynced-tree signature and
nothing else - background loops key their terminate-vs-retry decision on it."""

from app.components.frontend.core.session_health import is_tree_corruption


def test_matches_flet_tree_desync_signature() -> None:
    exc = AssertionError("_process_remove_command: control with ID 'None' not found.")
    assert is_tree_corruption(exc) is True


def test_ignores_other_errors() -> None:
    assert is_tree_corruption(AssertionError("something else")) is False
    assert is_tree_corruption(RuntimeError("_process_remove_command")) is False
    assert is_tree_corruption(ValueError("boom")) is False
