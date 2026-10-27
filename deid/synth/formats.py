"""Formatting helpers: dates, phones, addresses, and identifier strings.

Safe-by-construction fake values: phones use the 555-01xx block reserved for
fiction, SSNs use area numbers 900-999 (never issued), emails use example.com
and example.org.
"""

from dataclasses import dataclass

from . import pools

MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
]
MONTHS_SHORT = [m[:3] for m in MONTHS]

# Styles that carry the full date (year included).
FULL_DATE_STYLES = ("slash", "slash_nopad", "slash2", "iso", "long", "dmy")
# Styles that drop the year; they still identify a day, so they are labeled.
PARTIAL_DATE_STYLES = ("mon_day", "slash_md")
PHONE_STYLES = ("paren", "dash", "dot", "intl")


def fmt_date(d, style):
    if style == "slash":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "slash_nopad":
        return f"{d.month}/{d.day}/{d.year}"
    if style == "slash2":
        return f"{d.month:02d}/{d.day:02d}/{d.year % 100:02d}"
    if style == "iso":
        return d.isoformat()
    if style == "long":
        return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"
    if style == "dmy":
        return f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year}"
    if style == "mon_day":
        return f"{MONTHS_SHORT[d.month - 1]} {d.day}"
    if style == "slash_md":
        return f"{d.month}/{d.day}"
    raise ValueError(f"unknown date style: {style}")


@dataclass(frozen=True)
class Phone:
    area: int
    line: int  # last two digits pair after the reserved 555-01 prefix, 0-99


def make_phone(rng):
    return Phone(area=rng.randint(200, 989), line=rng.randint(0, 99))


def fmt_phone(p, style):
    local = f"555-01{p.line:02d}"
    if style == "paren":
        return f"({p.area}) {local}"
    if style == "dash":
        return f"{p.area}-{local}"
    if style == "dot":
        return f"{p.area}.555.01{p.line:02d}"
    if style == "intl":
        return f"+1 {p.area}-{local}"
    raise ValueError(f"unknown phone style: {style}")


@dataclass(frozen=True)
class Address:
    number: int
    street: str
    street_type: str
    unit: str  # empty when there is no unit
    town: str
    state: str
    zip_code: str


def make_address(rng):
    unit = ""
    if rng.random() < 0.3:
        unit = f"{rng.choice(pools.UNIT_TYPES)} {rng.randint(1, 40)}{rng.choice('ABCD')}"
    town, state = rng.choice(pools.TOWNS)
    return Address(
        number=rng.randint(10, 9899),
        street=rng.choice(pools.STREET_NAMES),
        street_type=rng.choice(pools.STREET_TYPES),
        unit=unit,
        town=town,
        state=state,
        zip_code=f"{rng.randint(50000, 56999):05d}",
    )


def fmt_address(a):
    street = f"{a.number} {a.street} {a.street_type}"
    if a.unit:
        street += f", {a.unit}"
    return f"{street}, {a.town}, {a.state} {a.zip_code}"


def fmt_town(a):
    return f"{a.town}, {a.state}"


def make_mrn(rng):
    return str(rng.randint(1000000, 9999999))


def make_account(rng):
    return f"ACCT{rng.randint(10**9, 10**10 - 1)}"


def make_ssn(rng):
    return f"{rng.randint(900, 999)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"


def make_insurance_id(rng):
    letters = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(3))
    return f"{letters}{rng.randint(10**8, 10**9 - 1)}"


def make_accession(rng, d):
    return f"RAD-{d.year % 100:02d}-{rng.randint(1, 999999):06d}"


def make_email(rng, first, last):
    local = rng.choice([f"{first}.{last}", f"{first[0]}{last}", f"{first}{rng.randint(1, 99)}"])
    local = "".join(c for c in local.lower() if c.isalnum() or c in "._")
    return f"{local}@{rng.choice(pools.EMAIL_DOMAINS)}"
