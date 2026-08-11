import io

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


def get_ocr_engine():
    global _OCR_ENGINE

    if RapidOCR is None:
        return None

    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()

    return _OCR_ENGINE


def page_needs_ocr(page, page_text):
    if len(page_text.strip()) >= 80 or not page.images:
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
    image = pdf[page_index].render(scale=2.5).to_pil()
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

    if pdfplumber is not None:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                tables = page.extract_tables() or []
                source = "text"
                ocr_words = []

                if page_needs_ocr(page, page_text):
                    ocr_text, ocr_words = extract_ocr_page(
                        pdf_bytes,
                        page_number - 1,
                    )
                    if ocr_text.strip():
                        page_text = ocr_text
                        source = "ocr"

                pages.append(
                    {
                        "page": page_number,
                        "text": page_text,
                        "tables": tables,
                        "source": source,
                        "ocr_words": ocr_words,
                    }
                )

    if not pages:
        reader = PdfReader(io.BytesIO(pdf_bytes))

        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            pages.append(
                {
                    "page": page_number,
                    "text": page_text,
                    "tables": [],
                    "source": "text",
                    "ocr_words": [],
                }
            )

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
