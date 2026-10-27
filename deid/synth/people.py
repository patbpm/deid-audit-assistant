"""People and patient records. All values are drawn from the seeded RNG."""

from dataclasses import dataclass
from datetime import date, timedelta

from . import formats, pools


@dataclass(frozen=True)
class Person:
    entity: str
    first: str
    middle: str  # single initial or empty
    last: str
    sex: str  # "F" or "M"


@dataclass(frozen=True)
class Provider:
    person: Person
    credential: str
    specialty: str


@dataclass(frozen=True)
class Patient:
    pid: str
    person: Person
    dob: date
    age: int
    admit: date
    discharge: date
    prior: date
    followup: date
    mrn: str
    account: str
    ssn: str
    insurance_id: str
    address: formats.Address
    phone_home: formats.Phone
    phone_cell: formats.Phone
    email: str
    spouse: "Person | None"
    kin: Person
    kin_phone: formats.Phone
    clinic_address: formats.Address
    clinic_phone: formats.Phone
    clinic_fax: formats.Phone
    scenario: int
    attending: Provider
    pcp: Provider
    consultant: Provider
    resident: Provider
    radiologist: Provider


def make_person(rng, entity, sex=None, last=None):
    sex = sex or rng.choice("FM")
    first = rng.choice(pools.FEMALE_FIRST if sex == "F" else pools.MALE_FIRST)
    middle = rng.choice("ABCDEJKLMRST") if rng.random() < 0.6 else ""
    if last is None:
        last = rng.choice(pools.LAST_NAMES)
        if rng.random() < 0.08:
            last = f"{last}-{rng.choice(pools.LAST_NAMES)}"
    return Person(entity, first, middle, last, sex)


def make_providers(rng, count=24, radiologists=4):
    providers = []
    for i in range(count):
        radiology = i < radiologists
        credential = "MD" if radiology else rng.choice(pools.PROVIDER_CREDENTIALS)
        non_radiology = [s for s in pools.PROVIDER_SPECIALTIES if s != "radiology"]
        specialty = "radiology" if radiology else rng.choice(non_radiology)
        person = make_person(rng, f"D{i + 1:02d}")
        providers.append(Provider(person, credential, specialty))
    return providers


def make_patient(rng, index, providers):
    pid = f"P{index:04d}"
    sex = rng.choice("FM")
    person = make_person(rng, pid, sex)

    admit = date(2019, 1, 1) + timedelta(days=rng.randint(0, 365 * 7 - 1))
    age = rng.randint(22, 88)
    dob = admit - timedelta(days=age * 365 + rng.randint(0, 364))
    los = rng.randint(3, 9)
    discharge = admit + timedelta(days=los)

    spouse = None
    if rng.random() < 0.6:
        spouse = make_person(
            rng, f"{pid}:spouse", "M" if sex == "F" else "F", last=person.last
        )
    kin = make_person(rng, f"{pid}:kin", None, last=person.last if rng.random() < 0.7 else None)

    clinicians = providers[4:]
    return Patient(
        pid=pid,
        person=person,
        dob=dob,
        age=age,
        admit=admit,
        discharge=discharge,
        prior=admit - timedelta(days=rng.randint(30, 700)),
        followup=discharge + timedelta(days=rng.randint(7, 21)),
        mrn=formats.make_mrn(rng),
        account=formats.make_account(rng),
        ssn=formats.make_ssn(rng),
        insurance_id=formats.make_insurance_id(rng),
        address=formats.make_address(rng),
        phone_home=formats.make_phone(rng),
        phone_cell=formats.make_phone(rng),
        email=formats.make_email(rng, person.first, person.last),
        spouse=spouse,
        kin=kin,
        kin_phone=formats.make_phone(rng),
        clinic_address=formats.make_address(rng),
        clinic_phone=formats.make_phone(rng),
        clinic_fax=formats.make_phone(rng),
        scenario=index,  # reduced modulo the scenario count by the caller
        attending=rng.choice(clinicians),
        pcp=rng.choice(clinicians),
        consultant=rng.choice(clinicians),
        resident=rng.choice(clinicians),
        radiologist=rng.choice(providers[:4]),
    )
