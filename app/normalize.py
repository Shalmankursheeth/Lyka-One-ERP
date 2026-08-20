"""R1 — normalise or raise NormalizationError with an operator-readable reason."""
import re
from datetime import datetime, timezone, timedelta

DUBAI_TZ = timezone(timedelta(hours=4))
STATUS_ENUM = {"New", "Qualified", "Booked", "Closed Won", "Lost"}
COUNTRY_RULES = {
    "971": 9,
    "91": 10,
    "977": 10,
}


class NormalizationError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def normalize_name(raw: str) -> str:
    if raw is None:
        raise NormalizationError("name is null")
    collapsed = re.sub(r"[\s\u00A0\u2000-\u200B\u202F\u205F\u3000]+", " ", raw).strip()
    if not collapsed:
        raise NormalizationError("name is empty after trimming whitespace")
    return collapsed


def normalize_phone(raw: str) -> str:
    if raw is None:
        raise NormalizationError("phone is null")

    s = raw.strip()
    if s == "":
        raise NormalizationError("phone is empty")

    had_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)

    if digits == "":
        raise NormalizationError(f"phone '{raw}' contains no digits")

    if not had_plus and digits.startswith("00"):
        digits = digits[2:]
        had_plus = True

    if not had_plus and digits.startswith("0") and not digits.startswith("00"):
        national = digits[1:]
        expected = COUNTRY_RULES["971"]
        if len(national) != expected:
            raise NormalizationError(
                f"phone '{raw}' looks like a local UAE number (leading 0) with "
                f"{len(national)} digits after the trunk prefix, expected {expected}"
            )
        return f"+971{national}"

    for cc, expected in COUNTRY_RULES.items():
        if digits.startswith(cc):
            national = digits[len(cc):]
            if len(national) == expected:
                return f"+{cc}{national}"
            raise NormalizationError(
                f"phone '{raw}' has {len(national)} digits after country code "
                f"+{cc}, expected {expected}"
            )

    raise NormalizationError(
        f"phone '{raw}' does not match a recognised country code (+971, +91, +977) "
        f"and is not a valid local UAE number"
    )


def normalize_deal_value(raw: str):
    if raw is None:
        return None
    s = raw.strip()
    if s == "":
        return None
    cleaned = re.sub(r"(?i)aed", "", s)
    cleaned = cleaned.replace(",", "").strip()
    if not re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
        raise NormalizationError(f"deal_value '{raw}' is not a recognisable amount")
    return round(float(cleaned) * 100)


def normalize_date_to_dubai(raw: str) -> datetime:
    """
    ISO timestamps with Z are UTC. Date-only values are Asia/Dubai midnight.

    Slash dates are DD/MM/YYYY (19/07/2026 cannot be month-first).
    Hyphen dates like 01-02-2026 are ambiguous; we apply the same DD-MM locale
    as the slash format and as Dubai convention. That is a documented locale
    rule, not a per-row coin flip. See NOTES.md Q1-adjacent assumptions.
    """
    if raw is None or raw.strip() == "":
        raise NormalizationError("date is null/empty")
    s = raw.strip()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone(DUBAI_TZ)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        y, m, d = (int(x) for x in s.split("-"))
        return _dubai_midnight(y, m, d, raw)

    m_slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m_slash:
        d, m, y = (int(x) for x in m_slash.groups())
        return _dubai_midnight(y, m, d, raw)

    m_hyphen = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", s)
    if m_hyphen:
        d, m, y = (int(x) for x in m_hyphen.groups())
        return _dubai_midnight(y, m, d, raw)

    raise NormalizationError(f"date '{raw}' does not match any known source format")


def _dubai_midnight(y, m, d, raw):
    try:
        return datetime(y, m, d, 0, 0, 0, tzinfo=DUBAI_TZ)
    except ValueError:
        raise NormalizationError(
            f"date '{raw}' parsed to invalid calendar date {y}-{m:02d}-{d:02d}"
        )


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_status(raw: str) -> str:
    if raw is None:
        raise NormalizationError("status is null")
    s = raw.strip()
    if s == "":
        raise NormalizationError(
            "status is empty; permitted values are exactly "
            "New | Qualified | Booked | Closed Won | Lost — no default is allowed"
        )
    if s not in STATUS_ENUM:
        raise NormalizationError(
            f"status '{raw}' is not a permitted value; enum is exactly "
            f"New|Qualified|Booked|Closed Won|Lost"
        )
    return s
