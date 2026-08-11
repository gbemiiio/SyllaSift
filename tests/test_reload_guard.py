from syllasift.state.reload_guard import build_reload_guard_html


def test_dirty_reload_guard_installs_beforeunload_handler():
    html = build_reload_guard_html(True)
    assert "if (true)" in html
    assert 'addEventListener("beforeunload", handler)' in html
    assert "event.preventDefault()" in html


def test_clean_reload_guard_removes_existing_handler_without_installing_one():
    html = build_reload_guard_html(False)
    assert "if (false)" in html
    assert 'removeEventListener("beforeunload", existing)' in html
