import hashlib
import io

from syllasift.parsing import detect_course_metadata, extract_pdf_document
from syllasift.types import PendingSyllabus


def upload_identifier(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()[:16]


def analyze_uploaded_file(uploaded_file) -> PendingSyllabus:
    """Convert one Streamlit upload into a stable, session-safe record."""
    contents = uploaded_file.getvalue()
    upload_id = upload_identifier(contents)
    readable_file = io.BytesIO(contents)
    readable_file.name = uploaded_file.name

    try:
        document = extract_pdf_document(readable_file)
        if not document["text"].strip():
            raise ValueError(
                "No readable text was found. This may be a scanned PDF."
            )
        metadata = detect_course_metadata(document["text"], uploaded_file.name)
        return {
            "upload_id": upload_id,
            "filename": uploaded_file.name,
            "document": document,
            "metadata": metadata,
            "error": None,
        }
    except Exception as error:
        return {
            "upload_id": upload_id,
            "filename": uploaded_file.name,
            "document": None,
            "metadata": None,
            "error": str(error),
        }


def analyze_uploaded_files(uploaded_files) -> list[PendingSyllabus]:
    return [analyze_uploaded_file(uploaded_file) for uploaded_file in uploaded_files]
