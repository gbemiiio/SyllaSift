from .dates import normalize_date
from .metadata import detect_course_metadata, detect_platform_notices
from .pdf import extract_pdf_document, extract_pdf_text, page_needs_ocr
from .pipeline import extract_deadline_candidates
from .strategies.ocr import extract_ocr_column_deadlines
from .strategies.text import extract_deadlines

__all__ = [
    "detect_course_metadata",
    "detect_platform_notices",
    "extract_deadline_candidates",
    "extract_deadlines",
    "extract_ocr_column_deadlines",
    "extract_pdf_document",
    "extract_pdf_text",
    "normalize_date",
    "page_needs_ocr",
]
