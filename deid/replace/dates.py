"""Parse a date string, shift it, and write it back in the same style.

Every date of one patient moves by the same number of days, so intervals
between dates (and ages at each event) are unchanged. Dates are read
month-first (US) unless the first number cannot be a month. Two-digit years
below 27 are read as 20xx, others as 19xx.
"""

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
ABBR = [m[:3] for m in MONTHS]
MONTH_LOOKUP = {m.lower(): i + 1 for i, m in enumerate(MONTHS)}
MONTH_LOOKUP.update({a.lower(): i + 1 for i, a in enumerate(ABBR)})
MONTH_LOOKUP["sept"] = 9
MONTH = r"(?P<mon>[A-Za-z]{3,9})\.?"

# (style, regex) tried in order; the regex must match the whole string.
PATTERNS = [
    ("iso", re.compile(r"(?P<y>\d{4})-(?P<a>\d{2})-(?P<b>\d{2})")),
    ("ymd_slash", re.compile(r"(?P<y>\d{4})/(?P<a>\d{1,2})/(?P<b>\d{1,2})")),
    ("long", re.compile(rf"{MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?P<comma>,)?\s+(?P<y>\d{{4}})")),
    ("dmy", re.compile(rf"(?P<d>\d{{1,2}})\s+{MONTH}(?P<comma>,)?\s+(?P<y>\d{{4}})")),
    ("mon_day", re.compile(rf"{MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?")),
    ("slash", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})")),
    ("slash2", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{2})")),
    ("dash", re.compile(r"(?P<a>\d{1,2})-(?P<b>\d{1,2})-(?P<y>\d{4})")),
    ("slash_md", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})")),
]


class DateError(ValueError):
    pass


@dataclass(frozen=True)
class Parsed:
    style: str
    year: int | None  # None when the text has no year
    month: int
    day: int
    pad: bool = True  # zero-padded numbers
    abbr: bool = True  # "Apr" rather than "April"
    comma: bool = False
    day_first: bool = False  # numeric styles written day/month
    assumed_month_first: bool = False  # both numbers could be a month

    @property
    def has_year(self):
        return self.year is not None


def _year(text):
    n = int(text)
    if len(text) == 2:
        return 2000 + n if n <= 26 else 1900 + n
    return n


def parse_date(text):
    """-> Parsed. Raises DateError if the text is not a recognizable date."""
    text = text.strip()
    for style, pattern in PATTERNS:
        m = pattern.fullmatch(text)
        if not m:
            continue
        g = m.groupdict()
        year = _year(g["y"]) if g.get("y") else None
        if "mon" in g:
            mon = g["mon"].lower()
            if mon not in MONTH_LOOKUP:
                continue  # a word that is not a month: try the next pattern
            month, day = MONTH_LOOKUP[mon], int(g["d"])
            abbr = len(g["mon"]) <= 3 or g["mon"].lower() == "sept"
            parsed = Parsed(style, year, month, day, abbr=abbr, comma=bool(g.get("comma")))
        elif style == "iso":
            parsed = Parsed(style, year, int(g["a"]), int(g["b"]))
        else:
            a, b = int(g["a"]), int(g["b"])
            day_first = a > 12 and b <= 12
            month, day = (b, a) if day_first else (a, b)
            pad = g["a"].startswith("0") or g["b"].startswith("0") or (a >= 10 and b >= 10)
            if style == "ymd_slash":
                month, day, day_first = a, b, False
            parsed = Parsed(style, year, month, day, pad=pad, day_first=day_first,
                            assumed_month_first=(not day_first and a <= 12 and b <= 12 and a != b))
        _validate(parsed, year or 2000)
        return parsed
    raise DateError(f"not a recognized date: {text!r}")


def _validate(parsed, year):
    try:
        date(year, parsed.month, parsed.day)
    except ValueError as err:
        raise DateError(str(err)) from None


def to_date(parsed, ref_year):
    year = parsed.year if parsed.has_year else ref_year
    _validate(parsed, year)
    return date(year, parsed.month, parsed.day)


def shift(parsed, days, ref_year):
    """The same date moved by `days`, keeping the text style. A date with no year
    is moved using `ref_year` and written without a year."""
    moved = to_date(parsed, ref_year) + timedelta(days=days)
    return replace(parsed, year=moved.year if parsed.has_year else None,
                   month=moved.month, day=moved.day)


def render(p):
    mm, dd = (f"{p.month:02d}", f"{p.day:02d}") if p.pad else (str(p.month), str(p.day))
    if p.style == "iso":
        return f"{p.year:04d}-{p.month:02d}-{p.day:02d}"
    if p.style in ("long", "dmy", "mon_day"):
        name = ABBR[p.month - 1] if p.abbr else MONTHS[p.month - 1]
        comma = "," if p.comma else ""
        if p.style == "long":
            return f"{name} {p.day}{comma} {p.year}"
        if p.style == "dmy":
            return f"{p.day} {name}{comma} {p.year}"
        return f"{name} {p.day}"
    if p.style == "ymd_slash":
        return f"{p.year}/{mm}/{dd}"
    first, second = (dd, mm) if p.day_first else (mm, dd)
    if p.style == "slash_md":
        return f"{first}/{second}"
    sep = "-" if p.style == "dash" else "/"
    year = f"{p.year % 100:02d}" if p.style == "slash2" else f"{p.year:04d}"
    return f"{first}{sep}{second}{sep}{year}"
