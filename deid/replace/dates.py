"""Parse a date string, shift it, and write it back in the same style.

Every date of one patient moves by the same number of days, so intervals
between dates (and ages at each event) are unchanged. Slash and dash dates are
read month-first (US) unless the first number cannot be a month; dotted dates
(30.04.2025) are read day-first, the usual convention for dots. Two-digit
years below 27 are read as 20xx, others as 19xx. A guess about the order is
recorded so the change can be flagged.
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
    ("iso", re.compile(r"(?P<y>\d{4})-(?P<a>\d{1,2})-(?P<b>\d{1,2})")),
    ("ymd_slash", re.compile(r"(?P<y>\d{4})/(?P<a>\d{1,2})/(?P<b>\d{1,2})")),
    ("ymd_dot", re.compile(r"(?P<y>\d{4})\.(?P<a>\d{1,2})\.(?P<b>\d{1,2})")),
    ("dmy_dash", re.compile(rf"(?P<d>\d{{1,2}})-{MONTH}-(?P<y>\d{{2}}|\d{{4}})")),
    ("dmy_tight", re.compile(r"(?P<d>\d{1,2})(?P<mon>[A-Za-z]{3,9})(?P<y>\d{4})")),
    ("ordinal_of", re.compile(rf"(?P<d>\d{{1,2}})(?:st|nd|rd|th)\s+of\s+{MONTH}(?:\s+(?P<y>\d{{4}}))?")),
    ("long", re.compile(rf"{MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?P<comma>,)?\s+(?P<y>\d{{4}})")),
    ("dmy", re.compile(rf"(?P<d>\d{{1,2}})\s+{MONTH}(?P<comma>,)?\s+(?P<y>\d{{4}})")),
    ("mon_day", re.compile(rf"{MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?")),
    ("slash", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})")),
    ("slash2", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{2})")),
    ("dash", re.compile(r"(?P<a>\d{1,2})-(?P<b>\d{1,2})-(?P<y>\d{4})")),
    ("dot", re.compile(r"(?P<a>\d{1,2})\.(?P<b>\d{1,2})\.(?P<y>\d{4})")),
    ("slash_md", re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})")),
    ("dash_md", re.compile(r"(?P<a>\d{1,2})-(?P<b>\d{1,2})")),
]

NAMED_MONTH_STYLES = ("long", "dmy", "mon_day", "dmy_dash", "dmy_tight", "ordinal_of")


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
    assumed_day_first: bool = False  # dotted date with both numbers possible as a month
    short_year: bool = False  # two-digit year as written

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
            parsed = Parsed(style, year, month, day, pad=g["d"].startswith("0"), abbr=abbr,
                            comma=bool(g.get("comma")), short_year=bool(g.get("y")) and len(g["y"]) == 2)
        elif style in ("iso", "ymd_dot"):
            parsed = Parsed(style, year, int(g["a"]), int(g["b"]), pad=len(g["a"]) == 2 and len(g["b"]) == 2)
        else:
            a, b = int(g["a"]), int(g["b"])
            dotted = style == "dot"
            day_first = (a > 12 and b <= 12) or dotted
            month, day = (b, a) if day_first else (a, b)
            pad = g["a"].startswith("0") or g["b"].startswith("0") or (a >= 10 and b >= 10)
            if style == "ymd_slash":
                month, day, day_first = a, b, False
            ambiguous = a <= 12 and b <= 12 and a != b
            parsed = Parsed(style, year, month, day, pad=pad, day_first=day_first,
                            assumed_month_first=(not day_first and ambiguous),
                            assumed_day_first=(dotted and ambiguous))
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


def ordinal(day):
    return f"{day}{'th' if 10 <= day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')}"


def render(p):
    mm, dd = (f"{p.month:02d}", f"{p.day:02d}") if p.pad else (str(p.month), str(p.day))
    if p.style == "iso":
        return f"{p.year:04d}-{mm}-{dd}"
    if p.style == "ymd_dot":
        return f"{p.year:04d}.{mm}.{dd}"
    if p.style in NAMED_MONTH_STYLES:
        name = ABBR[p.month - 1] if p.abbr else MONTHS[p.month - 1]
        comma = "," if p.comma else ""
        if p.style == "long":
            return f"{name} {p.day}{comma} {p.year}"
        if p.style == "dmy":
            return f"{p.day} {name}{comma} {p.year}"
        if p.style == "dmy_dash":
            year = f"{p.year % 100:02d}" if p.short_year else f"{p.year:04d}"
            return f"{dd if p.pad else p.day}-{name}-{year}"
        if p.style == "dmy_tight":
            return f"{p.day}{name}{p.year:04d}"
        if p.style == "ordinal_of":
            return f"{ordinal(p.day)} of {name}" + (f" {p.year}" if p.has_year else "")
        return f"{name} {p.day}"
    if p.style == "ymd_slash":
        return f"{p.year}/{mm}/{dd}"
    first, second = (dd, mm) if p.day_first else (mm, dd)
    if p.style == "slash_md":
        return f"{first}/{second}"
    if p.style == "dash_md":
        return f"{first}-{second}"
    sep = {"dash": "-", "dot": "."}.get(p.style, "/")
    year = f"{p.year % 100:02d}" if p.style == "slash2" else f"{p.year:04d}"
    return f"{first}{sep}{second}{sep}{year}"
