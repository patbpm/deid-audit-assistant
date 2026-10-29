"""Hard synthetic cases with ground-truth labels, kept apart from the frozen dataset.

    python -m deid.synth.adversarial [--seed N] [--per-family N] [--out DIR]

Short notes in nine families, each aimed at a known weakness of identifier
detectors: names that are also common words, unusual date formats, abbreviated
names, typos, non-English names, lookalikes that are not identifiers, identifier
and phone variants, address variants, and eponyms. Same record format and
labeling conventions as the main dataset (docs/DATASET.md), plus a `family` field.
Everything is invented; phones use 555-01xx, SSNs start with 9, emails use
example.com and example.org.

This set is not part of data/frozen.json and does not change it. Treat it as a
test set: do not tune prompts or rules on it. See docs/ADVERSARIAL.md.

Two vocabularies. Set A (the default) was scored once on Oct 29 and its errors were read,
so it can no longer judge a fix. Set B (`--vocab b`, seed 20261030) uses different common
words, eponyms, lookalike sentences, names and date phrasings, plus a tenth family of notes
full of relative and year-only dates. B was written after A's errors were known, to judge the
fixes made because of them; its words are disjoint from A's and from the examples written
into the prompts (a test checks that).
"""

import argparse
import hashlib
import json
import platform
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from . import GENERATOR_VERSION, formats, pools
from .builder import validate_spans

DEFAULT_SEED = 20261029
DEFAULT_SEED_B = 20261030
DEFAULT_PER_FAMILY = 20
VERSION = "0.1"
VERSION_B = "0.2"
NOTES_FILE = "notes.jsonl"
MANIFEST_FILE = "manifest.json"

FAMILIES = ("common_word_names", "odd_date_formats", "abbreviated_names", "typos_and_noise",
            "non_english_names", "lookalikes", "identifier_variants", "address_variants",
            "eponym_names")
FAMILIES_B = FAMILIES + ("relative_dates",)


def L(text, kind, subtype=""):
    """A labeled piece of a note."""
    return (text, kind, subtype)


def assemble(parts):
    """parts: strings and labeled pieces -> (text, spans)."""
    out, spans, length = [], [], 0
    for part in parts:
        if isinstance(part, str):
            out.append(part)
            length += len(part)
            continue
        text, kind, subtype = part
        spans.append({"start": length, "end": length + len(text), "type": kind, "subtype": subtype,
                      "entity": "", "text": text})
        out.append(text)
        length += len(text)
    return "".join(out), spans


# --- common words that are also names -------------------------------------------------
FIRST_WORDS = {
    "Hope": "She expressed hope for a full recovery.", "Grace": "Grace period for the follow-up visit was explained.",
    "Joy": "Joy in daily activities has returned.", "Faith": "Faith in the treatment plan was noted.",
    "Will": "He will return in two weeks.", "Mark": "Mark the site before the procedure.",
    "Frank": "Frank blood was seen in the stool.", "Rose": "Rose-colored rash on the trunk.",
    "May": "May resume normal activity as tolerated.", "Dawn": "Symptoms are worst at dawn.",
    "Rich": "Rich diet reported, high in saturated fat.", "Bill": "Bill sent to the insurer on discharge.",
}
LAST_WORDS = {
    "White": "White blood cell count 7.2.", "Brown": "Brown discharge from the wound.",
    "Black": "Black stools for two days.", "Stone": "Stone seen in the left ureter.",
    "Young": "Young adult with no prior history.", "Page": "Page the on-call resident if pain worsens.",
    "Baker": "Baker cyst behind the right knee.", "Early": "Early satiety noted.",
    "Short": "Short of breath on exertion.", "Long": "Long-standing hypertension.",
    "Strong": "Strong family history of colon cancer.", "Bishop": "Bishop score was reviewed.",
}


def bare_surname(rng, name):
    """Set B only: the patient's surname alone, no title or label before it, as clinicians often write it.
    This is the case a wrong "ordinary word" answer would leak, so the set has to contain it."""
    tail = rng.choice([" reports the pain is better and asks about driving.", " was cooperative throughout the visit.",
                       " denies fever or chills."])
    return [L(name, "NAME", "patient_surname_bare"), tail, " Follow up in clinic.\n"]


def make_common_word_names(rng, i, v):
    first, last = rng.choice(sorted(v["first_words"])), rng.choice(sorted(v["last_words"]))
    return [
        "Patient: ", L(f"{first} {last}", "NAME", "patient_full"), "\n",
        v["last_words"][last], " ", v["first_words"][first], "\n",
    ] + (bare_surname(rng, last) if v["bare_names"] and rng.random() < 0.5 else [
        "Spoke with Mr. " if rng.random() < 0.5 else "Spoke with Ms. ", L(last, "NAME", "patient_surname"),
        " by phone. Follow up in clinic.\n",
    ])


# --- unusual date formats ----------------------------------------------------------------
ORD = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}


def ordinal(day):
    return f"{day}{ORD.get(day, 'th')}"


DATE_FORMATS = (
    ("ordinal_of_month", lambda d: f"{ordinal(d.day)} of {formats.MONTHS[d.month - 1]} {d.year}"),
    ("month_ordinal", lambda d: f"{formats.MONTHS[d.month - 1]} {ordinal(d.day)}, {d.year}"),
    ("dash_mon_yy", lambda d: f"{d.day}-{formats.MONTHS_SHORT[d.month - 1]}-{d.year % 100:02d}"),
    ("dotted_ymd", lambda d: f"{d.year}.{d.month:02d}.{d.day:02d}"),
    ("dotted_dmy", lambda d: f"{d.day:02d}.{d.month:02d}.{d.year}"),
    ("run_together", lambda d: f"{d.day}{formats.MONTHS_SHORT[d.month - 1]}{d.year}"),
    ("abbrev_period", lambda d: f"{formats.MONTHS_SHORT[d.month - 1]}. {d.day}, {d.year}"),
    ("unpadded_iso", lambda d: f"{d.year}-{d.month}-{d.day}"),
    ("ordinal_no_year", lambda d: f"{ordinal(d.day)} of {formats.MONTHS[d.month - 1]}"),
    ("mon_ordinal_no_year", lambda d: f"{formats.MONTHS_SHORT[d.month - 1]} {ordinal(d.day)}"),
    ("dash_md", lambda d: f"{d.month:02d}-{d.day:02d}"),
)


def make_odd_date_formats(rng, i, v):
    base = date(2024, 1, 1) + timedelta(days=rng.randrange(0, 700))
    parts = ["Visit note.\n"]
    for k, (name, fn) in enumerate(rng.sample(DATE_FORMATS, 3)):
        when = base + timedelta(days=rng.randrange(0, 40))
        parts += [["Admitted on ", "Seen again on ", "Follow-up scheduled for "][k], L(fn(when), "DATE", name), ". "]
    tail = v["date_tails"]
    parts += [rng.choice(tail) if tail else "\nPain 7/10, BP 118/76. Symptoms began last Tuesday and she has felt better since 2019.\n"]
    return parts


# --- abbreviated and unusual-case names -----------------------------------------------------
FIRSTS = ["John", "Maria", "David", "Susan", "Robert", "Linda", "James", "Karen"]
LASTS = ["Smith", "Garcia", "Miller", "Davis", "Wilson", "Moore", "Taylor", "Clark"]
ABBREV_FORMS = (
    ("initial_last", lambda f, l, m: f"{f[0]}. {l}"),
    ("last_initial", lambda f, l, m: f"{l}, {f[0]}."),
    ("two_initials_last", lambda f, l, m: f"{f[0]}.{m}. {l}"),
    ("last_two_initials", lambda f, l, m: f"{l}, {f[0]} {m}"),
    ("all_caps", lambda f, l, m: f"{l.upper()}, {f.upper()}"),
    ("all_lower", lambda f, l, m: f"{l.lower()}, {f.lower()}"),
    ("no_period_initials", lambda f, l, m: f"{f[0]}{m} {l}"),
)


def make_abbreviated_names(rng, i, v):
    parts = ["Chart review.\n"]
    for k, (name, fn) in enumerate(rng.sample(ABBREV_FORMS, 3)):
        f, l, m = rng.choice(v["firsts"]), rng.choice(v["lasts"]), rng.choice("ABCDEFGHJKLMNPRST")
        parts += [["Patient: ", "Referred by Dr. ", "Seen with nurse "][k], L(fn(f, l, m), "NAME", name), ". "]
    parts += ["\nPlan reviewed with the family.\n"]
    return parts


# --- typos and noise -----------------------------------------------------------------------------
def swap(word, rng):
    if len(word) < 4:
        return word
    k = rng.randrange(1, len(word) - 2)
    return word[:k] + word[k + 1] + word[k] + word[k + 2:]


def drop(word, rng):
    k = rng.randrange(1, len(word) - 1)
    return word[:k] + word[k + 1:]


def make_typos_and_noise(rng, i, v):
    f, l = rng.choice(v["firsts"]), rng.choice(v["lasts"])
    typo = f"{swap(f, rng)} {drop(l, rng)}"
    mrn = digits(rng, 7)
    mrn_ocr = mrn[:3] + rng.choice("OlI") + mrn[4:]
    d = date(2025, 1, 1) + timedelta(days=rng.randrange(0, 300))
    return ["Patient :  ", L(typo, "NAME", "misspelled"), "\n",
            "MRN:   ", L(mrn_ocr, "ID", "ocr_letter"), "\n",
            "Seen on ", L(f"{d.month}/{d.day}//{d.year}", "DATE", "double_slash"), " and again ",
            L(f"{d.year}-{d.month}-{d.day + 1 if d.day < 28 else d.day}", "DATE", "unpadded_iso"), ".\n",
            "Call back at ", L(f"555 01{rng.randrange(0, 100):02d}", "PHONE", "no_area_code"), " if worse.\n"]


# --- non-English and hyphenated names --------------------------------------------------------------
INTERNATIONAL = [
    "José García-López", "Nguyen Thi Lan", "Mohammed Al-Farsi", "Oluwaseun Adeyemi",
    "Siobhan O'Reilly", "Zhang Wei", "Priya Raghunathan", "Dmitri Volkov", "Fatima Zahra Benali",
    "Yuki Tanaka", "Łukasz Wiśniewski", "Søren Lindqvist", "Ngozi Eze", "Amara de la Cruz",
    "Willem van der Meer", "Hye-jin Park", "Tariq Mahmood", "Ingrid Østergaard", "Mei-Ling Chen",
    "Andrés Fernández Ruiz", "Aroha Te Rangi", "Kwame Mensah", "Anastasia Petrova", "Rahul Chaudhry",
]


def make_non_english_names(rng, i, v):
    patient, relative, clinician = rng.sample(v["international"], 3)
    return ["Patient: ", L(patient, "NAME", "patient_full"), "\n",
            "Interpreter used for the visit. Daughter ", L(relative, "NAME", "relative"),
            " was present.\n", "Seen by Dr. ", L(clinician, "NAME", "clinician"), ".\n"]


# --- lookalikes that are not identifiers ----------------------------------------------------------------
LOOKALIKES = [
    "Troponin 0.04 ng/mL, creatinine 1.1, pH 7.35.", "ICD-10 E11.9 and CPT 99213 were billed.",
    "Tenderness at L4/5 and T12/L1, with C5-6 disc bulge.", "Takes 5/325 mg tablets every 6 hours as needed.",
    "Grade 4/5 strength in the right arm; pain 7/10.", "BP 132/84, HR 72, RR 16, SpO2 96%.",
    "Sleeps on 2/3 pillows. Stage 3/4 disease per the oncology note.", "Arrived at 07:30; room 4/12 assigned.",
    "Reference range 4.5-11.0 x10^9/L; FEV1 2.15 L.", "Software version 2.3.1 was used for the scan.",
    "Symptoms since 2019; seen last Tuesday; tomorrow at noon.", "Ratio 1/2 dilution; 1:1000 epinephrine.",
]


def make_lookalikes(rng, i, v):
    f, l = rng.choice(v["firsts"]), rng.choice(v["lasts"])
    chosen = rng.sample(v["lookalikes"], 4)
    return ["Patient: ", L(f"{f} {l}", "NAME", "patient_full"), "\n", "\n".join(chosen), "\nCall ",
            L(f"({rng.randint(200, 989)}) 555-01{rng.randrange(0, 100):02d}", "PHONE", "paren"), " with questions.\n"]


# --- identifier and contact variants --------------------------------------------------------------------
def digits(rng, n):
    return "".join(rng.choice("0123456789") for _ in range(n))


def make_identifier_variants(rng, i, v):
    area = lambda: rng.randint(200, 989)
    line = lambda: f"01{rng.randrange(0, 100):02d}"
    options = [
        lambda: ["MRN#", L(digits(rng, 7), "ID", "mrn_hash_no_space")],
        lambda: ["MR# ", L(digits(rng, 7), "ID", "mr_hash")],
        lambda: ["Acct No. ", L(digits(rng, 10), "ID", "acct_no")],
        lambda: ["Policy ID: ", L(f"ABC-{digits(rng, 9)}", "ID", "dashed_policy")],
        lambda: ["SSN ", L("9" + digits(rng, 8), "ID", "ssn_no_dashes")],
        lambda: ["SSN: ", L(f"9{digits(rng, 2)}-{digits(rng, 2)}-{digits(rng, 4)}", "ID", "ssn_dashed")],
        lambda: ["Fax ", L(f"{area()}-555-{line()}", "PHONE", "fax_dash")],
        lambda: ["Phone ", L(f"{area()}.555.{line()} x{rng.randint(100, 999)}", "PHONE", "dots_extension")],
        lambda: ["Phone ", L(f"+1 ({area()}) 555-{line()}", "PHONE", "intl_paren")],
        lambda: ["Phone ", L(f"{area()} 555 {line()}", "PHONE", "spaces")],
        lambda: ["Phone ", L(f"1-{area()}-555-{line()}", "PHONE", "leading_one")],
        lambda: ["Email ", L(f"John.Smith+clinic{rng.randint(1, 99)}@Example.COM", "EMAIL", "plus_mixed_case")],
        lambda: ["Email ", L(f"j_smith{rng.randint(1, 99)}@mail.example.org", "EMAIL", "underscore_subdomain")],
    ]
    parts = ["Registration details.\n"]
    for build in rng.sample(options, 4):
        parts += build() + ["\n"]
    return parts


# --- address variants ------------------------------------------------------------------------------------------
STATE_NAMES = {"IA": "Iowa", "WI": "Wisconsin", "MN": "Minnesota", "IL": "Illinois", "MO": "Missouri",
               "NE": "Nebraska", "SD": "South Dakota", "KS": "Kansas"}


def make_address_variants(rng, i, v):
    town, state = rng.choice(pools.TOWNS)
    street = rng.choice(pools.STREET_NAMES)
    zipcode = f"{rng.randint(10000, 99999)}"
    number = rng.randint(10, 999)
    variants = [
        ("Mailing address: ", L(f"PO Box {rng.randint(100, 9999)}, {town}, {state} {zipcode}", "ADDRESS", "po_box")),
        ("Lives at ", L(f"{number} {street} St Apt {rng.randint(1, 9)}B {town} {state} {zipcode}", "ADDRESS", "no_commas")),
        ("Home: ", L(f"{number} {street} Street, {town}, {STATE_NAMES[state]} {zipcode}", "ADDRESS", "state_spelled_out")),
        ("Address on file: ", L(f"Unit {rng.randint(1, 40)}, {number} {street} Ave, {town}, {state} {zipcode}", "ADDRESS", "unit_first")),
        ("She is staying with her sister in ", L(f"{town}, {state}", "ADDRESS", "town")),
    ]
    parts = ["Social history.\n"]
    for prefix, piece in rng.sample(variants, 3):
        parts += [prefix, piece, ".\n"]
    return parts


# --- eponyms: surnames that are also diseases or devices -----------------------------------------------------
EPONYMS = {
    "Foley": "Foley catheter", "Parkinson": "Parkinson disease", "Graves": "Graves disease",
    "Wilson": "Wilson disease", "Crohn": "Crohn disease", "Hodgkin": "Hodgkin lymphoma",
    "Bell": "Bell palsy", "Addison": "Addison disease", "Cushing": "Cushing syndrome",
    "Raynaud": "Raynaud phenomenon", "Wernicke": "Wernicke encephalopathy", "Down": "Down syndrome",
}


def make_eponym_names(rng, i, v):
    eponyms = v["eponyms"]
    doctor, other = rng.sample(sorted(eponyms), 2)
    first = rng.choice(v["firsts"])
    if v["eponym_layouts"] > 1 and rng.random() < 0.5:   # set B: a second layout, the patient first
        return ["Patient: ", L(f"{first} {other}", "NAME", "patient_eponym"), "\n",
                "Discussed the ", eponyms[doctor], " with the family. Referred by Dr. ",
                L(doctor, "NAME", "clinician_eponym"), ".\n",
                "Past history includes ", eponyms[other], ". ", *bare_surname(rng, other)]
    return ["Seen by Dr. ", L(doctor, "NAME", "clinician_eponym"), " today.\n",
            "History of ", eponyms[other], ". ",
            "The ", eponyms[doctor], " was discussed in the plan.\n",
            "Patient: ", L(f"{other}, {first}", "NAME", "patient_eponym"), "\n"]


# --- set B only: notes dense in relative and year-only dates ------------------------------------------
def make_relative_dates(rng, i, v):
    first, second = rng.sample(DATE_FORMATS, 2)
    base = date(2024, 1, 1) + timedelta(days=rng.randrange(0, 700))
    other = base + timedelta(days=rng.randrange(5, 60))
    f, l = rng.choice(v["firsts"]), rng.choice(v["lasts"])
    rel = rng.sample(v["relative_phrases"], 3)
    years = rng.sample(v["year_phrases"], 2)
    return ["Patient: ", L(f"{f} {l}", "NAME", "patient_full"), "\n",
            "Visit on ", L(first[1](base), "DATE", first[0]), ". Cough began ", rel[0], ". A similar episode was reported ", rel[1],
            ". Smoked ", years[0], "; quit ", years[1], ". Recheck ", rel[2], ", booked for ",
            L(second[1](other), "DATE", second[0]), ".\n"]


VOCAB_A = {
    "first_words": FIRST_WORDS, "last_words": LAST_WORDS, "firsts": FIRSTS, "lasts": LASTS,
    "international": INTERNATIONAL, "lookalikes": LOOKALIKES, "eponyms": EPONYMS,
    "date_tails": None, "eponym_layouts": 1, "bare_names": False,
}

VOCAB_B = {
    "first_words": {
        "Pearl": "Pearl-white plaques were seen on the tongue.", "Ivy": "Ivy exposure was reported after gardening.",
        "Sage": "Sage tea was used as a home remedy.", "Lance": "Lance the abscess if it does not drain.",
        "Grant": "Grant of leave from work was discussed with the employer.",
        "Chase": "Chase the pending lab result before discharge.", "Drew": "Drew blood from the left arm without difficulty.",
        "Art": "Art therapy was offered twice weekly.", "Pat": "Pat dry the incision after showering.",
        "Summer": "Summer heat worsened the symptoms.",
    },
    "last_words": {
        "Hall": "Hall ambulation twice daily was encouraged.", "Rice": "Rice and bananas were advised for the diarrhea.",
        "Wood": "Wood chip exposure at work was denied.", "Cross": "Cross-sectional imaging showed no mass.",
        "Bond": "Bond with the newborn appears strong.", "Frost": "Frost damage to the fingertips was noted.",
        "Swift": "Swift improvement followed the antibiotics.", "Sharp": "Sharp pain in the left flank since morning.",
        "Fair": "Fair skin with multiple freckles.", "Little": "Little change in the rash since the last visit.",
        "Chambers": "Chambers of the heart were normal on echo.", "Gray": "Gray matter lesions were seen on MRI.",
    },
    "firsts": ["Helen", "Peter", "Nora", "Victor", "Alice", "Edgar", "Tina", "Oscar"],
    "lasts": ["Nakamura", "Patel", "Kowalski", "Romero", "Hughes", "Barnes", "Fleming", "Owens"],
    "international": [
        "Chidi Okafor", "Aiko Matsumoto", "Bogdan Popescu", "Leila Haddad", "Thiago Barbosa Lima",
        "Ngoc Anh Tran", "Sven Johansson", "Ximena Torres-Vega", "Emeka Nwosu", "Katarzyna Zielińska",
        "Rashid Al-Mansoori", "Mariam Diallo", "Jae-won Seo", "Çağla Yıldız", "Henrik Nygård",
        "Anahit Grigoryan", "Tomás Ibáñez", "Wanjiru Kamau", "Dariusz Kaczmarek", "Sakura Ito",
    ],
    "lookalikes": [
        "Hgb 13.2 g/dL, platelets 245, INR 1.0.", "Codes J45.909 and I10 were billed; CPT 99214.",
        "Disc bulge at L3/4 and narrowing at L5-S1.", "Takes 10/325 mg tablets every 4 hours as needed.",
        "Strength 5/5 bilaterally; pain 3/10.", "BP 124/78, HR 64, RR 14, SpO2 98%.",
        "Firmware 4.1.2 was installed on the monitor.", "Seen at 14:45; bed 12/3 assigned.",
        "Reference 135-145 mmol/L; eGFR 82.", "Dilution 1:500; ratio 2/3.",
        "Symptoms for 3 weeks; seen two weeks ago; follow-up next Friday.",
        "Surgery in 2017 with no complications since 2018.",
    ],
    "eponyms": {
        "Marfan": "Marfan syndrome", "Huntington": "Huntington disease", "Paget": "Paget disease",
        "Barrett": "Barrett esophagus", "Kaposi": "Kaposi sarcoma", "Hashimoto": "Hashimoto thyroiditis",
        "Meniere": "Meniere disease", "Tourette": "Tourette syndrome", "Achilles": "Achilles tendon",
        "Apgar": "Apgar score", "Glasgow": "Glasgow coma scale", "Babinski": "Babinski sign",
    },
    "date_tails": [
        "\nPain 4/10, BP 122/80. Symptoms began two weeks ago and have eased since last month. Prior surgery in 2017.\n",
        "\nPain 6/10, BP 130/84. She felt well in 2018 and again until yesterday. Review next Monday.\n",
        "\nPain 2/10, BP 116/72. Onset a few weeks back; worse this morning; similar episode in 2021.\n",
        "\nPain 5/10, BP 126/82. Started in the spring, with a milder bout five years back.\n",
    ],
    "eponym_layouts": 2, "bare_names": True,
    "relative_phrases": ["two weeks ago", "yesterday", "last month", "next Friday", "in three days", "this morning",
                         "a few weeks back", "over the weekend", "at the start of the year", "in the spring",
                         "the week before admission", "earlier this year"],
    "year_phrases": ["in 2009", "until 2014", "since 2016", "in 1998", "from 2003", "in 2021"],
}
VOCABS = {"a": VOCAB_A, "b": VOCAB_B}

BUILDERS = {
    "common_word_names": make_common_word_names, "odd_date_formats": make_odd_date_formats,
    "abbreviated_names": make_abbreviated_names, "typos_and_noise": make_typos_and_noise,
    "non_english_names": make_non_english_names, "lookalikes": make_lookalikes,
    "identifier_variants": make_identifier_variants, "address_variants": make_address_variants,
    "eponym_names": make_eponym_names, "relative_dates": make_relative_dates,
}


def generate_notes(seed=DEFAULT_SEED, per_family=DEFAULT_PER_FAMILY, vocab="a"):
    rng = random.Random(seed)
    families = FAMILIES if vocab == "a" else FAMILIES_B
    prefix = "A" if vocab == "a" else "B"
    patient_base = 9000 if vocab == "a" else 8000
    notes = []
    for family in families:
        for i in range(per_family):
            text, spans = assemble(BUILDERS[family](rng, i, VOCABS[vocab]))
            validate_spans(text, spans)
            number = len(notes) + 1
            for span in spans:
                span["entity"] = f"{prefix}{number:04d}"
            notes.append({"note_id": f"{prefix}{number:04d}", "patient_id": f"P{patient_base + number}",
                          "family": family, "note_type": "adversarial", "note_date": "2026-01-01",
                          "text": text, "spans": spans})
    return notes


def build_manifest(notes, notes_path, seed, per_family, vocab="a"):
    by_family, by_type = Counter(), Counter()
    for note in notes:
        by_family[note["family"]] += len(note["spans"])
        for span in note["spans"]:
            by_type[span["type"]] += 1
    extra = {} if vocab == "a" else {"vocab": vocab}
    return {
        **extra,
        "adversarial_version": VERSION if vocab == "a" else VERSION_B, "generator_version": GENERATOR_VERSION,
        "python_version": platform.python_version(), "seed": seed, "per_family": per_family,
        "notes": len(notes), "spans": sum(by_type.values()),
        "spans_by_family": dict(sorted(by_family.items())), "spans_by_type": dict(sorted(by_type.items())),
        "notes_sha256": hashlib.sha256(Path(notes_path).read_bytes()).hexdigest(),
    }


def write_notes(notes, out_dir, seed, per_family, vocab="a"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes_path = out_dir / NOTES_FILE
    with open(notes_path, "w", encoding="utf-8", newline="\n") as handle:
        for note in notes:
            handle.write(json.dumps(note, sort_keys=True, ensure_ascii=False) + "\n")
    manifest = build_manifest(notes, notes_path, seed, per_family, vocab)
    with open(out_dir / MANIFEST_FILE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vocab", choices=("a", "b"), default="a",
                        help="a: the first set (scored once, now a tuned set); b: the second set, for judging fixes")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--per-family", type=int, default=DEFAULT_PER_FAMILY)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    seed = args.seed if args.seed is not None else (DEFAULT_SEED if args.vocab == "a" else DEFAULT_SEED_B)
    out = args.out or ("data/generated/adversarial" if args.vocab == "a" else "data/generated/adversarial-b")
    manifest = write_notes(generate_notes(seed, args.per_family, args.vocab), out, seed, args.per_family, args.vocab)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
