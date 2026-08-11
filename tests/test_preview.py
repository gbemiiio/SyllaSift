import pandas as pd

from syllasift.ui.imports import _preview_frame


def test_preview_uses_nullable_page_numbers_instead_of_literal_none():
    frame = _preview_frame([{
        "Include": True,
        "Item": "Manually added assignment",
        "Normalized Date": "2026-09-01",
        "Page": None,
    }])

    assert str(frame["Page"].dtype) == "Int64"
    assert pd.isna(frame.loc[0, "Page"])
