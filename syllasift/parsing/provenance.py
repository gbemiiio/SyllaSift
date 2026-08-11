import re

from .classification import candidate_item_tokens
from .dates import normalize_date
from .patterns import DATE_PATTERN, DAY_FIRST_DATE_PATTERN


def _page_search_text(page):
    parts = [page.get("text", "")]
    for table in page.get("tables", []):
        for row in table or []:
            parts.extend(str(cell) for cell in row or [] if cell)
    parts.extend(
        str(word.get("text", "")) for word in page.get("ocr_words", [])
    )
    return "\n".join(parts)


def _normalized_page_dates(page_text, course_year):
    dates = set()
    for pattern in (DATE_PATTERN, DAY_FIRST_DATE_PATTERN):
        for match in re.finditer(pattern, page_text, re.IGNORECASE):
            try:
                dates.add(normalize_date(match.group(), course_year))
            except ValueError:
                continue
    return dates


def locate_candidate_source(row, pages, course_year):
    """Resolve a document-wide candidate back to its strongest source page."""
    target_date = row["Normalized Date"]
    item = str(row.get("Item", "")).strip().lower()
    item_tokens = {
        token for token in candidate_item_tokens(item) if len(token) >= 4
    }
    raw_date = str(row.get("Date", "")).strip().lower()
    matches = []

    for page in pages:
        search_text = _page_search_text(page)
        if target_date not in _normalized_page_dates(search_text, course_year):
            continue
        lowered = re.sub(r"\s+", " ", search_text).lower()
        score = sum(3 for token in item_tokens if token in lowered)
        if item and item in lowered:
            score += 8
        if raw_date and raw_date in lowered:
            score += 4
        matches.append((
            score,
            page.get("page"),
            page.get("source", "text").upper(),
        ))

    if not matches:
        return None, "TEXT"
    matches.sort(
        key=lambda value: (
            value[0],
            -(value[1] if isinstance(value[1], int) else 10_000),
        ),
        reverse=True,
    )
    return matches[0][1], matches[0][2]
