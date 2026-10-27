"""Turns template tokens into labeled Pieces for one note.

Token families:
  d_<key>    dates (dob, admit, dc, note, prior, followup, sign)
  pt_*       patient name forms; spouse_*/kin_* family; <role>_* providers
  mrn, acct, ssn, ins_id, accession      identifiers
  phone_*, pt_email, addr, clinic_addr, town   contact details
Labels cover only the identifier value (never "Dr." or "MRN:").
"""

from . import formats
from .builder import Piece, plain
from .formats import FULL_DATE_STYLES, PARTIAL_DATE_STYLES, PHONE_STYLES

PROVIDER_ROLES = ("attending", "pcp", "consultant", "resident", "radiologist")


class Resolver:
    def __init__(self, rng, patient, dates, accession=""):
        self.rng = rng
        self.p = patient
        self.dates = dates
        self.accession = accession
        self.date_style = rng.choice(FULL_DATE_STYLES)
        self.phone_style = rng.choice(PHONE_STYLES)

    def __call__(self, token):
        if token.startswith("d_"):
            return self._date(token[2:])
        for role in PROVIDER_ROLES:
            if token.startswith(role + "_"):
                provider = getattr(self.p, role)
                return self._provider(provider, token[len(role) + 1:])
        for who, person, subtype in (
            ("pt", self.p.person, "PATIENT"),
            ("spouse", self.p.spouse, "FAMILY"),
            ("kin", self.p.kin, "FAMILY"),
        ):
            if token.startswith(who + "_") and token[len(who) + 1:] in NAME_FORMS:
                return self._person(person, token[len(who) + 1:], subtype)
        return getattr(self, "t_" + token)()

    # --- dates -----------------------------------------------------------
    def _date(self, key):
        d = self.dates[key]
        style = self.date_style
        roll = self.rng.random()
        if roll < 0.2:
            style = self.rng.choice(FULL_DATE_STYLES)
        elif roll < 0.3 and key not in ("dob", "sign"):
            style = self.rng.choice(PARTIAL_DATE_STYLES)
        return [Piece(formats.fmt_date(d, style), "DATE", key.upper(), "", d.isoformat())]

    # --- people ----------------------------------------------------------
    def _name_piece(self, text, person, subtype):
        return Piece(text, "NAME", subtype, person.entity)

    def _person(self, person, form, subtype):
        if person is None:
            raise KeyError(f"no such family member for form {form}")
        middle = f" {person.middle}" if person.middle and self.rng.random() < 0.5 else ""
        if form == "full":
            return [self._name_piece(f"{person.first}{middle} {person.last}", person, subtype)]
        if form == "lf":
            return [self._name_piece(f"{person.last}, {person.first}{middle}", person, subtype)]
        if form == "first":
            return [self._name_piece(person.first, person, subtype)]
        if form == "last":
            return [self._name_piece(person.last, person, subtype)]
        if form == "title":
            title = "Mr." if person.sex == "M" else self.rng.choice(["Ms.", "Mrs."])
            return [plain(title + " "), self._name_piece(person.last, person, subtype)]
        raise KeyError(form)

    def _provider(self, provider, form):
        person = provider.person
        if form == "title":
            return [plain("Dr. "), self._name_piece(person.last, person, "PROVIDER")]
        if form == "sig":
            return [
                self._name_piece(f"{person.first} {person.last}", person, "PROVIDER"),
                plain(f", {provider.credential}"),
            ]
        if form == "lf":
            return [self._name_piece(f"{person.last}, {person.first}", person, "PROVIDER")]
        if form == "specialty":
            return [plain(provider.specialty)]
        raise KeyError(form)

    # --- identifiers -----------------------------------------------------
    def t_mrn(self):
        return [Piece(self.p.mrn, "ID", "MRN", self.p.pid)]

    def t_acct(self):
        return [Piece(self.p.account, "ID", "ACCOUNT", self.p.pid)]

    def t_ssn(self):
        return [Piece(self.p.ssn, "ID", "SSN", self.p.pid)]

    def t_ins_id(self):
        return [Piece(self.p.insurance_id, "ID", "INSURANCE", self.p.pid)]

    def t_accession(self):
        return [Piece(self.accession, "ID", "ACCESSION", "")]

    # --- contact ---------------------------------------------------------
    def _phone(self, phone, subtype, entity):
        return [Piece(formats.fmt_phone(phone, self.phone_style), "PHONE", subtype, entity)]

    def t_phone_home(self):
        return self._phone(self.p.phone_home, "HOME", self.p.pid)

    def t_phone_cell(self):
        return self._phone(self.p.phone_cell, "CELL", self.p.pid)

    def t_phone_kin(self):
        return self._phone(self.p.kin_phone, "FAMILY", self.p.kin.entity)

    def t_phone_clinic(self):
        return self._phone(self.p.clinic_phone, "CLINIC", "")

    def t_phone_fax(self):
        return self._phone(self.p.clinic_fax, "FAX", "")

    def t_pt_email(self):
        return [Piece(self.p.email, "EMAIL", "PATIENT", self.p.pid)]

    def t_addr(self):
        return [Piece(formats.fmt_address(self.p.address), "ADDRESS", "HOME", self.p.pid)]

    def t_clinic_addr(self):
        return [Piece(formats.fmt_address(self.p.clinic_address), "ADDRESS", "CLINIC", "")]

    def t_town(self):
        return [Piece(formats.fmt_town(self.p.address), "ADDRESS", "TOWN", self.p.pid)]


NAME_FORMS = ("full", "lf", "first", "last", "title")
