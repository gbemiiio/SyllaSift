from collections.abc import MutableMapping
from typing import Any


def synchronize_deadline_widget_state(
    session_state: MutableMapping[str, Any],
    deadline_id: int,
    is_completed: bool,
) -> tuple[str, str]:
    widget_key = f"deadline_{deadline_id}"
    sync_key = f"{widget_key}_saved_value"
    if session_state.get(sync_key) != is_completed:
        session_state[widget_key] = is_completed
        session_state[sync_key] = is_completed
    return widget_key, sync_key


def reset_deadline_and_export_state(
    session_state: MutableMapping[str, Any],
) -> None:
    for key in list(session_state):
        if (
            key in {
                "calendar_export_courses",
                "calendar_export_selection_initialized",
                "calendar_export_completed",
            }
            or key.startswith("deadline_")
        ):
            del session_state[key]


def initialize_calendar_export_selection(
    session_state: MutableMapping[str, Any],
    course_labels,
) -> None:
    initialized_key = "calendar_export_selection_initialized"
    if not session_state.get(initialized_key, False):
        session_state["calendar_export_courses"] = list(course_labels)
        session_state[initialized_key] = True


def finish_calendar_export(session_state: MutableMapping[str, Any]) -> None:
    session_state["calendar_export_courses"] = []
    session_state["calendar_export_selection_initialized"] = True
    session_state["calendar_export_completed"] = True


def clear_saved_widget_state(session_state: MutableMapping[str, Any]) -> None:
    """Clear saved-data widgets while preserving unsaved PDF previews."""
    exact_keys = {
        "clear_saved_confirmation",
        "calendar_export_courses",
        "calendar_export_selection_initialized",
        "calendar_export_completed",
    }
    for key in list(session_state):
        if key in exact_keys or key.startswith("deadline_"):
            del session_state[key]
