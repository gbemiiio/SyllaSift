from typing import Any, Optional, TypedDict


class ExtractedPage(TypedDict, total=False):
    page: int
    text: str
    tables: list[list[list[Optional[str]]]]
    source: str
    ocr_words: list[dict[str, Any]]


class ExtractedDocument(TypedDict, total=False):
    text: str
    pages: list[ExtractedPage]
    notices: list[str]


DeadlineCandidate = TypedDict(
    "DeadlineCandidate",
    {
        "Item": str,
        "Date": str,
        "Normalized Date": str,
        "Confidence": str,
        "Reason": str,
        "Page": Optional[int],
        "Source": str,
        "Include": bool,
    },
    total=False,
)


class CourseMetadata(TypedDict, total=False):
    course_name: str
    course_code: str
    semester: str
    year: int


class PendingSyllabus(TypedDict, total=False):
    upload_id: str
    filename: str
    document: Optional[ExtractedDocument]
    metadata: Optional[CourseMetadata]
    error: Optional[str]
