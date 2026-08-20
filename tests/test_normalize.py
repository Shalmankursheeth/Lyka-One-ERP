import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.normalize import (
    NormalizationError, normalize_date_to_dubai, normalize_deal_value,
    normalize_name, normalize_phone, normalize_status,
)


@pytest.mark.parametrize("raw,expected", [
    ("+971 50 111 2222", "+971501112222"),
    ("0501112222", "+971501112222"),
    ("00971509876543", "+971509876543"),
    ("971561112233", "+971561112233"),
])
def test_phone_ok(raw, expected):
    assert normalize_phone(raw) == expected


def test_phone_1012_reason_mentions_digit_count():
    with pytest.raises(NormalizationError) as ei:
        normalize_phone("+971 50 333")
    assert "5 digits" in ei.value.reason
    assert "expected 9" in ei.value.reason


def test_nbsp_name():
    assert normalize_name("Muhammed\u00A0Shanil") == "Muhammed Shanil"


def test_deal_fils():
    assert normalize_deal_value("AED 1,200,000") == 120000000
    assert normalize_deal_value("1200000") == 120000000
    assert normalize_deal_value("") is None


def test_status_rejects_empty_and_meeting_done():
    with pytest.raises(NormalizationError):
        normalize_status("")
    with pytest.raises(NormalizationError):
        normalize_status("Meeting Done")


def test_dates():
    assert (normalize_date_to_dubai("19/07/2026").year,
            normalize_date_to_dubai("19/07/2026").month,
            normalize_date_to_dubai("19/07/2026").day) == (2026, 7, 19)
    dt = normalize_date_to_dubai("01-02-2026")
    assert (dt.year, dt.month, dt.day) == (2026, 2, 1)
