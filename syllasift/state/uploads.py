from collections.abc import Iterable, MutableMapping
from typing import Any

from syllasift.types import PendingSyllabus


PENDING_SYLLABI_KEY = "pending_syllabi"
PENDING_ORDER_KEY = "pending_syllabus_order"
UPLOADER_GENERATION_KEY = "pdf_uploader_generation"
UPLOAD_WIDGET_PREFIXES = (
    "course_name_",
    "course_code_",
    "semester_",
    "year_",
    "include_",
    "deadline_editor_",
    "remove_",
)


def initialize_upload_state(state: MutableMapping[str, Any]) -> None:
    """Create the session containers used by temporary PDF imports."""
    state.setdefault(PENDING_SYLLABI_KEY, {})
    state.setdefault(PENDING_ORDER_KEY, [])
    state.setdefault(UPLOADER_GENERATION_KEY, 0)


def uploader_widget_key(state: MutableMapping[str, Any]) -> str:
    initialize_upload_state(state)
    return f"syllabus_uploader_{state[UPLOADER_GENERATION_KEY]}"


def prune_stale_uploader_widgets(state: MutableMapping[str, Any]) -> None:
    """Release file objects held by upload-widget generations no longer shown."""
    current_key = uploader_widget_key(state)
    for key in list(state):
        if key.startswith("syllabus_uploader_") and key != current_key:
            del state[key]


def register_pending_syllabi(
    state: MutableMapping[str, Any],
    syllabi: Iterable[PendingSyllabus],
) -> None:
    """Merge newly analyzed PDFs into the queue without duplicating content."""
    initialize_upload_state(state)
    pending = state[PENDING_SYLLABI_KEY]
    order = state[PENDING_ORDER_KEY]

    for syllabus in syllabi:
        upload_id = syllabus["upload_id"]
        if upload_id not in pending:
            order.append(upload_id)
        pending[upload_id] = syllabus


def get_pending_syllabi(
    state: MutableMapping[str, Any],
) -> list[PendingSyllabus]:
    initialize_upload_state(state)
    pending = state[PENDING_SYLLABI_KEY]
    return [
        pending[upload_id]
        for upload_id in state[PENDING_ORDER_KEY]
        if upload_id in pending
    ]


def _clear_widget_state(
    state: MutableMapping[str, Any],
    upload_ids: Iterable[str],
) -> None:
    identifiers = tuple(upload_ids)
    for key in list(state):
        if key.startswith(UPLOAD_WIDGET_PREFIXES) and any(
            key.endswith(upload_id) for upload_id in identifiers
        ):
            del state[key]


def remove_pending_syllabus(
    state: MutableMapping[str, Any],
    upload_id: str,
) -> None:
    """Discard one unsaved syllabus and only its associated widget state."""
    initialize_upload_state(state)
    state[PENDING_SYLLABI_KEY].pop(upload_id, None)
    state[PENDING_ORDER_KEY] = [
        item for item in state[PENDING_ORDER_KEY] if item != upload_id
    ]
    _clear_widget_state(state, [upload_id])


def clear_pending_syllabi(state: MutableMapping[str, Any]) -> None:
    """Discard every unsaved PDF and reset the native upload widget."""
    initialize_upload_state(state)
    upload_ids = list(state[PENDING_SYLLABI_KEY])
    _clear_widget_state(state, upload_ids)
    state[PENDING_SYLLABI_KEY] = {}
    state[PENDING_ORDER_KEY] = []
    state[UPLOADER_GENERATION_KEY] += 1


def advance_uploader_generation(state: MutableMapping[str, Any]) -> None:
    """Clear the native chooser after its files have entered the queue."""
    initialize_upload_state(state)
    state[UPLOADER_GENERATION_KEY] += 1


def has_unsaved_work(
    state: MutableMapping[str, Any],
    has_selected_files: bool = False,
) -> bool:
    """Return whether a browser reload would discard user work."""
    initialize_upload_state(state)
    manual_values = (
        state.get("manual_course_name", ""),
        state.get("manual_course_code", ""),
        state.get("manual_syllabus_text", ""),
    )
    return bool(
        has_selected_files
        or state[PENDING_ORDER_KEY]
        or state.get("manual_import_draft")
        or any(str(value).strip() for value in manual_values)
    )
