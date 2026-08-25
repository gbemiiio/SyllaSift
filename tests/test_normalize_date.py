import pytest

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


def test_september_four_letter_abbreviation_is_supported():
    assert normalize_date("Sept 5", 2026) == "2026-09-05"


@pytest.mark.parametrize("date_text", ["13/45/2026", "February 30"])
def test_invalid_dates_raise_sanitized_error(date_text):
    with pytest.raises(
        ValueError,
        match=rf"^Invalid or unsupported date: {date_text}$",
    ):
        normalize_date(date_text, 2026)
