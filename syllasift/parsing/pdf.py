import io
import re

from pypdf import PdfReader

from .metadata import detect_platform_notices

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    np = None
    pdfium = None
    RapidOCR = None


_OCR_ENGINE = None


def _extract_headerless_schedule_table(page, page_text, tables):
    """Recover the first row of a schedule continued across a page break.

    Word-generated PDFs may omit the top border of the first continuation row.
    The default line-based table extractor then starts at row two. A text-based
    horizontal pass retains that first row and the five columns needed for
    deadline extraction.
    """
    if not tables or max((len(row or []) for row in tables[0]), default=0) < 6:
        return None
    first_row = tables[0][0] if tables[0] else []
    if any(str(cell or "").strip().lower() == "date" for cell in first_row or []):
        return None
    schedule_rows = re.findall(
        r"(?m)^\s*(?:\d+\s+)?\d{1,2}/\d{1,2}\s+"
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b",
        page_text,
        re.IGNORECASE,
    )
    if len(schedule_rows) < 3:
        return None
    fallback_tables = page.extract_tables({
        "vertical_strategy": "lines",
        "horizontal_strategy": "text",
        "min_words_horizontal": 1,
    }) or []
    fallback = next(
        (
            table for table in fallback_tables
            if max((len(row or []) for row in table), default=0) == 5
        ),
        None,
    )
    if not fallback:
        return None
    default_first_date = next(
        (
            match.group()
            for row in tables[0]
            for cell in row or []
            if cell
            for match in [re.search(r"\b\d{1,2}/\d{1,2}\b", str(cell))]
            if match
        ),
        "",
    )
    if not default_first_date:
        return None
    cutoff = next(
        (
            index for index, row in enumerate(fallback)
            if any(default_first_date in str(cell or "") for cell in row or [])
        ),
        len(fallback),
    )
    fallback = fallback[:cutoff]
    if not fallback:
        return None
    return [[
        "Date", "Day", "Lesson prep", "In-Class Topic",
        "Homework (HW), In class (IC), (PMIP) or (AC) reports due",
    ]] + fallback


def get_ocr_engine():
    global _OCR_ENGINE

    if RapidOCR is None:
        return None

    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()

    return _OCR_ENGINE


def page_needs_ocr(page, page_text):
    if not page.images:
        return False

    page_area = float(page.width * page.height)
    image_area = sum(
        max(0, image["x1"] - image["x0"])
        * max(0, image["y1"] - image["y0"])
        for image in page.images
    )

    return page_area > 0 and image_area / page_area >= 0.25


def extract_ocr_page(pdf_bytes, page_index):
    engine = get_ocr_engine()

    if engine is None or pdfium is None or np is None:
        return "", []

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        image = pdf[page_index].render(scale=2.5).to_pil()
    finally:
        pdf.close()
    result, _ = engine(np.array(image))
    words = []

    for box, text, score in result or []:
        x_values = [point[0] for point in box]
        y_values = [point[1] for point in box]
        words.append(
            {
                "text": text.strip(),
                "score": float(score),
                "x0": min(x_values),
                "x1": max(x_values),
                "top": min(y_values),
                "bottom": max(y_values),
            }
        )

    words.sort(key=lambda word: (word["top"], word["x0"]))
    return "\n".join(word["text"] for word in words), words


def extract_pdf_document(uploaded_file):
    """Extract page text and tables while keeping a pypdf fallback."""
    pages = []
    uploaded_file.seek(0)
    pdf_bytes = uploaded_file.read()

    plumber_error = None
    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    native_text = page.extract_text() or ""
                    page_text = native_text
                    tables = page.extract_tables() or []
                    continuation_table = _extract_headerless_schedule_table(
                        page, native_text, tables,
                    )
                    if continuation_table:
                        tables.append(continuation_table)
                    source = "text"
                    ocr_words = []

                    if page_needs_ocr(page, native_text):
                        ocr_text, ocr_words = extract_ocr_page(
                            pdf_bytes,
                            page_number - 1,
                        )
                        if ocr_text.strip():
                            if native_text.strip():
                                native_lines = {
                                    line.strip().casefold()
                                    for line in native_text.splitlines()
                                    if line.strip()
                                }
                                additions = [
                                    line for line in ocr_text.splitlines()
                                    if line.strip().casefold() not in native_lines
                                ]
                                if additions:
                                    page_text = (
                                        native_text + "\n" + "\n".join(additions)
                                    )
                                    source = "mixed"
                            else:
                                page_text = ocr_text
                                source = "ocr"

                    pages.append({
                        "page": page_number,
                        "text": page_text,
                        "tables": tables,
                        "source": source,
                        "ocr_words": ocr_words,
                    })
        except Exception as error:
            pages = []
            plumber_error = error

    if not pages:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                pages.append({
                    "page": page_number,
                    "text": page_text,
                    "tables": [],
                    "source": "text",
                    "ocr_words": [],
                })
        except Exception as error:
            detail = str(error or plumber_error or "unknown PDF error")
            raise ValueError(f"Unable to read this PDF: {detail}") from error

    combined_text = "\n".join(page["text"] for page in pages)
    notices = detect_platform_notices(combined_text)

    return {
        "text": combined_text,
        "pages": pages,
        "notices": notices,
    }


def extract_pdf_text(uploaded_file):
    """Backward-compatible text-only PDF extraction helper."""
    return extract_pdf_document(uploaded_file)["text"]
