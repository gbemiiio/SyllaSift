from app import NO_DATED_ASSIGNMENTS_MESSAGE, PREVIEW_COLUMNS


def test_preview_only_shows_user_facing_columns():
    assert PREVIEW_COLUMNS == ["Include", "Item", "Due Date", "Page"]
    assert "Confidence" not in PREVIEW_COLUMNS
    assert "Reason" not in PREVIEW_COLUMNS
    assert "Source" not in PREVIEW_COLUMNS


def test_zero_deadline_message_is_direct_and_actionable():
    assert NO_DATED_ASSIGNMENTS_MESSAGE == (
        "No dated assignments are listed in this PDF. "
        "You can add rows or import the course without deadlines."
    )
