from collections.abc import MutableMapping
from typing import Any


CALENDAR_EXPORT_SELECTION_KEY = "calendar_export_course_ids"
_LEGACY_CALENDAR_EXPORT_KEYS = {
    "calendar_export_courses",
    "calendar_export_selection_initialized",
    "calendar_export_completed",
}


def synchronize_deadline_widget_state(
    session_state: MutableMapping[str, Any],
    deadline_id: int,
    is_completed: bool,
) -> tuple[str, str]:
    widget_key = f"deadline_{deadline_id}"
    sync_key = f"{widget_key}_saved_value"
    if (
        widget_key not in session_state
        or session_state.get(sync_key) != is_completed
    ):
        session_state[widget_key] = is_completed
        session_state[sync_key] = is_completed
    return widget_key, sync_key


def reset_deadline_and_export_state(
    session_state: MutableMapping[str, Any],
) -> None:
    for key in list(session_state):
        if (
            key == CALENDAR_EXPORT_SELECTION_KEY
            or key in _LEGACY_CALENDAR_EXPORT_KEYS
            or key.startswith("deadline_")
        ):
            del session_state[key]


def initialize_calendar_export_selection(
    session_state: MutableMapping[str, Any],
    course_ids,
) -> None:
    """Initialize or reconcile the ID-based calendar export selection."""
    available_ids = [int(course_id) for course_id in course_ids]
    available_set = set(available_ids)

    for key in _LEGACY_CALENDAR_EXPORT_KEYS:
        session_state.pop(key, None)

    if CALENDAR_EXPORT_SELECTION_KEY not in session_state:
        session_state[CALENDAR_EXPORT_SELECTION_KEY] = available_ids
        return

    selected_ids = session_state.get(CALENDAR_EXPORT_SELECTION_KEY, [])
    session_state[CALENDAR_EXPORT_SELECTION_KEY] = [
        course_id
        for course_id in selected_ids
        if isinstance(course_id, int) and course_id in available_set
    ]


def finish_calendar_export(session_state: MutableMapping[str, Any]) -> None:
    """Retain the current selection after a calendar download."""


def clear_saved_widget_state(session_state: MutableMapping[str, Any]) -> None:
    """Clear saved-data widgets while preserving unsaved PDF previews."""
    exact_keys = {
        "clear_saved_confirmation",
        CALENDAR_EXPORT_SELECTION_KEY,
        *_LEGACY_CALENDAR_EXPORT_KEYS,
    }
    for key in list(session_state):
        if key in exact_keys or key.startswith("deadline_"):
            del session_state[key]
