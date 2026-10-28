"""Build probe notes to test the red-team reviewer against known answers.

The frozen dataset holds almost no identifying prose, so the reviewer is tested
on variants of its dev notes. All three variants end with an ADDITIONAL HISTORY
line, so the line's presence gives nothing away:

  control  a benign line; every true span is replaced. Should come out low risk.
  planted  a fictional line that makes the person easier to find. Should be flagged.
  leak     a benign line, and a few true spans are withheld from the replacement
           step, as a detector's misses would be. The leftovers should be found.

The sentences are invented, describe no real person, and are not part of the
frozen dataset (the notes file and its hashes are untouched).
"""

import hashlib

VARIANTS = ("control", "planted", "leak")

BENIGN = [
    "Lives with family and denies tobacco use.",
    "Independent in daily activities and walks without assistance.",
    "Drinks alcohol rarely and has no recent travel.",
    "Follows the usual diet advice and takes medications as prescribed.",
    "Has no known drug allergies and no recent hospital stays.",
    "Sleeps about seven hours a night and reports no new stressors.",
]

# category -> sentences that would narrow a person to a handful of people
CLUES = {
    "RARE_CONDITION": [
        "Followed at a national referral center for Erdheim-Chester disease, one of fewer than 1,000 known cases worldwide.",
        "Born with a chromosomal deletion so rare that the case was written up in a journal.",
        "Has a genetic disorder carried by only one other family in the state.",
    ],
    "OCCUPATION": [
        "Works as the only large-animal veterinarian serving the whole county.",
        "Is the elected mayor of a town of about nine hundred people.",
        "Is the sole lighthouse keeper on the island ferry route.",
    ],
    "PUBLIC_EVENT": [
        "Was the driver injured in last month's bridge collapse, which led the evening news for a week.",
        "Won the state lottery jackpot last spring and was named in the local paper.",
        "Was one of two survivors of the grain elevator fire that the whole region still talks about.",
    ],
    "SMALL_PLACE": [
        "Lives on a small island with a year-round population of about forty people.",
        "Is one of the few residents of a mountain village reached by a single unpaved road.",
        "Grew up in the only house on a lake that has no other year-round neighbors.",
    ],
}


def _pick(options, *parts):
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def add_history_line(note, sentence):
    """The note with an ADDITIONAL HISTORY line appended, and the sentence's
    character range. Appending leaves every true span's offsets valid."""
    prefix = note["text"].rstrip("\n") + "\n\nADDITIONAL HISTORY: "
    return prefix + sentence + "\n", (len(prefix), len(prefix) + len(sentence))


def make_probe(note, variant, seed=0, leak_count=2):
    """One probe from a dev note: {"text", "spans" (given to the replacement
    step), "planted" ((start, end) or None), "category", "withheld" (true spans left out)}."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    benign = _pick(BENIGN, seed, note["note_id"], "benign")
    spans, planted, category, withheld = list(note["spans"]), None, "", []
    if variant == "planted":
        category = _pick(sorted(CLUES), seed, note["note_id"], "category")
        sentence = _pick(CLUES[category], seed, note["note_id"], "clue")
    else:
        sentence = benign
    text, line = add_history_line(note, sentence)
    if variant == "planted":
        planted = line
    if variant == "leak":
        order = sorted(spans, key=lambda s: hashlib.sha256(
            f"{seed}|{note['note_id']}|{s['start']}".encode()).hexdigest())
        withheld = [s for s in order if s["type"] in ("NAME", "DATE", "ID", "PHONE", "EMAIL", "ADDRESS")][:leak_count]
        gone = {id(s) for s in withheld}
        spans = [s for s in spans if id(s) not in gone]
    return {"text": text, "spans": spans, "planted": planted, "category": category,
            "withheld": [dict(s) for s in withheld]}
