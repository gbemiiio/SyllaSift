import re
from datetime import datetime

from .dates import normalize_date


def get_lines(text):
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]


def append_deadline(
    deadlines,
    seen,
    item,
    raw_date,
    course_year,
):
    try:
        normalized_date = normalize_date(raw_date, course_year)
    except ValueError:
        return
    key = (item.lower(), normalized_date)
    if key in seen:
        return
    seen.add(key)
    deadlines.append({
        "Item": item,
        "Date": raw_date,
        "Normalized Date": normalized_date,
    })


def candidate_row(item, raw_date, course_year, confidence="High",
                  reason="Explicit due date", include=True):
    """Build a candidate row while safely ignoring impossible dates."""
    try:
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", raw_date):
            datetime.strptime(raw_date, "%Y-%m-%d")
            normalized_date = raw_date
        else:
            normalized_date = normalize_date(raw_date, course_year)
    except ValueError:
        return None
    return {
        "Item": item,
        "Date": raw_date,
        "Normalized Date": normalized_date,
        "_confidence": confidence,
        "_reason": reason,
        "_include": include,
    }
