from parser import normalize_date


def test_numeric_full_date():
    assert normalize_date(
        "01/13/2026",
        2026,
    ) == "2026-01-13"


def test_numeric_without_year():
    assert normalize_date(
        "01/13",
        2026,
    ) == "2026-01-13"


def test_full_month_with_suffix():
    assert normalize_date(
        "January 7th",
        2026,
    ) == "2026-01-07"


def test_abbreviated_month_with_period():
    assert normalize_date(
        "Jan. 10",
        2026,
    ) == "2026-01-10"


def test_abbreviated_month_without_period():
    assert normalize_date(
        "Feb 6",
        2026,
    ) == "2026-02-06"


def test_month_date_with_existing_year():
    assert normalize_date(
        "March 20, 2027",
        2026,
    ) == "2027-03-20"
