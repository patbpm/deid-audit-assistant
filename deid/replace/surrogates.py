"""Consistent surrogate values. The same input always gets the same surrogate
within a run (and across runs with the same seed and the same inputs), and two
different inputs never share one.

Names are replaced token by token: a real first name maps to one surrogate first
name wherever it appears, a real surname to one surrogate surname. So "Murphy,
Patrick R", "Patrick Murphy" and "Murphy" stay linked, and relatives who share a
surname still share one. The tables are a re-identification key: keep them out of
shared output.
"""

import hashlib
import re

from . import pools

TITLES = {"dr", "mr", "mrs", "ms", "miss", "mx", "prof", "rev", "sr", "jr", "ii", "iii", "iv"}
CREDENTIALS = {"md", "do", "np", "pa", "pa-c", "rn", "phd", "dds", "pharmd", "mph", "msn", "lpn"}
SYLLABLES = ("ba", "dro", "ke", "li", "mor", "ne", "po", "ra", "sen", "tal", "vi", "wen", "zu")


def digest(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()


def number(*parts):
    return int.from_bytes(digest(*parts), "big")


def match_case(original, fake):
    if len(original) > 1 and original.isupper():
        return fake.upper()
    if original.islower():
        return fake.lower()
    return fake


class Registry:
    """Injective map original -> surrogate, picked from a pool by hash with
    probing, so no two originals share a surrogate and no surrogate equals a
    forbidden (real) value. Falls back to invented syllable names if the pool
    runs out."""

    def __init__(self, seed, label, pool, forbidden=()):
        self.seed, self.label, self.pool = seed, label, list(pool)
        self.forbidden = {f.lower() for f in forbidden}
        self.table, self.used = {}, set()

    def get(self, original):
        key = original.lower()
        if key in self.table:
            return self.table[key]
        start = number(self.seed, self.label, key)
        for step in range(len(self.pool)):
            candidate = self.pool[(start + step) % len(self.pool)]
            if candidate.lower() not in self.used | self.forbidden | {key}:
                break
        else:
            candidate = self._invent(start)
        self.used.add(candidate.lower())
        self.table[key] = candidate
        return candidate

    def _invent(self, start):
        n = 0
        while True:
            h = number(self.seed, self.label, "invent", start, n)
            word = "".join(SYLLABLES[(h >> (4 * i)) % len(SYLLABLES)] for i in range(3)).capitalize()
            if word.lower() not in self.used and word.lower() not in self.forbidden:
                return word
            n += 1


def scramble_digits(text, *parts):
    """Replace every digit with a hashed digit (a different one when possible)."""
    stream = digest(*parts, text)
    out, i = [], 0
    for ch in text:
        if ch.isdigit():
            d = stream[i % len(stream)] % 10
            if i == 0 and len(text) > 1 and d == 0:
                d = 1  # no leading zero on numbers
            out.append(str((d if str(d) != ch else (d + 1) % 10)))
            i += 1
        else:
            out.append(ch)
    return "".join(out)


class Surrogates:
    def __init__(self, seed, forbidden_names=()):
        self.seed = seed
        self.first = Registry(seed, "first", pools.FIRST, forbidden_names)
        self.last = Registry(seed, "last", pools.LAST, forbidden_names)
        self.either = Registry(seed, "either", pools.EITHER, forbidden_names)
        self.street = Registry(seed, "street", pools.STREETS, forbidden_names)
        self.town = Registry(seed, "town", pools.TOWNS, forbidden_names)
        self.ids = {}
        self.ids_used = set()

    # --- names -------------------------------------------------------------
    def name_token(self, token, kind):
        registry = {"first": self.first, "last": self.last}.get(kind, self.either)
        return match_case(token, registry.get(token))

    def initial(self, letter):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        new = alphabet[number(self.seed, "initial", letter.upper()) % 26]
        if new == letter.upper():
            new = alphabet[(alphabet.index(new) + 1) % 26]
        return new if letter.isupper() else new.lower()

    # --- identifiers ---------------------------------------------------------
    def identifier(self, original):
        """Same shape, different characters. A leading letter run is kept when it
        looks like a label (four or more letters, or followed by a separator), so
        'ACCT' and 'MRN:' survive; shorter runs followed directly by digits are
        scrambled. Nine-digit dashed numbers (SSN shape) stay in the 900 range
        that is never issued."""
        if original in self.ids:
            return self.ids[original]
        for attempt in range(1000):
            new = self._scramble_id(original, attempt)
            if new != original and new not in self.ids_used:
                break
        self.ids[original] = new
        self.ids_used.add(new)
        return new

    def _scramble_id(self, original, attempt):
        keep = re.match(r"[A-Za-z]{4,}|[A-Za-z]+(?=[\s:#_-])", original)
        prefix = keep.group(0) if keep else ""
        stream = digest(self.seed, "id", original, attempt)
        out = []
        for i, ch in enumerate(original[len(prefix):]):
            b = stream[i % len(stream)]
            if ch.isdigit():
                out.append(str(b % 10))
            elif ch.isalpha():
                letter = "ABCDEFGHJKLMNPQRSTUVWXYZ"[b % 24]
                out.append(letter if ch.isupper() else letter.lower())
            else:
                out.append(ch)
        body = "".join(out)
        if re.fullmatch(r"\d{3}-\d{2}-\d{4}", original):
            body = "9" + body[1:]
        return prefix + body

    def phone(self, original):
        """Keeps the punctuation; digits become a fictional 555-01xx number."""
        digits = re.sub(r"\D", "", original)
        h = number(self.seed, "phone", digits)
        if len(digits) >= 10:
            tail = f"{200 + h % 790}55501{(h >> 20) % 100:02d}"
            new_digits = digits[:-10] + tail
        elif len(digits) == 7:
            new_digits = f"55501{(h >> 20) % 100:02d}"
        else:
            return scramble_digits(original, self.seed, "phone")
        if new_digits == digits:  # an already-fictional number must still change
            new_digits = new_digits[:-2] + f"{(int(new_digits[-2:]) + 37) % 100:02d}"
        it = iter(new_digits)
        return re.sub(r"\d", lambda _: next(it), original)

    def email(self, original):
        h = number(self.seed, "email", original.lower())
        first = pools.FIRST[h % len(pools.FIRST)].lower()
        last = pools.LAST[(h >> 16) % len(pools.LAST)].lower()
        domain = pools.EMAIL_DOMAINS[(h >> 32) % len(pools.EMAIL_DOMAINS)]
        return f"{first}.{last}{(h >> 40) % 90 + 10}@{domain}"

    # --- addresses -----------------------------------------------------------
    def town_name(self, original):
        return self.town.get(original)

    def street_name(self, original):
        return self.street.get(original)

    def digits(self, text, label):
        return scramble_digits(text, self.seed, label)
