"""An invented site, to test a site profile: notes that name one made-up hospital's own places and codes.

    python -m deid.synth.site --out data/generated/site

Takes ordinary synthetic notes (the project's generator, its own seed) and appends a short local-details
block to each: where the patient was seen, sometimes a transfer, sometimes a research ID. The site is
"Hartwell Regional" (invented; any resemblance to a real place is chance). Its places are named for trees,
which is what lets a profile's one-line hint generalize to names the profile does not list.

Each appended identifier is labeled (ADDRESS for a place, ID for a code) with a subtype and a "site"
field: "listed" if data/site/hartwell.json names it or its format, "unlisted" if only the hint covers it.
The base notes' own labels are untouched (the block is appended, so no offset moves).
"""

import argparse
import json
import random
from pathlib import Path

from . import generate

SEED = 20261031
FAMILY = "site"
PROFILE = "data/site/hartwell.json"

LISTED_PLACES = ["Hartwell Regional Hospital", "HRH", "Birch Pavilion", "MICU-3", "Hartwell Heart Clinic"]
UNLISTED_PLACES = ["Linden Annex", "East Oak Unit", "Cedar Outpatient Clinic", "Maple Wing", "Willow Day Hospital"]
LISTED_CODES = [("HRH-{:05d}", "research ID", 5), ("HRH-ST-{:04d}", "study code", 4)]
UNLISTED_CODES = [("HW{:07d}", "bed-tracking code", 7)]  # a format the profile does not describe: nobody asked for it

SEEN = ["Seen at {a}.", "Admitted to {a}, {b}.", "Location of care: {a} ({b}).", "Evaluated in {a}."]
TRANSFER = ["Transferred from {a} to {b}.", "Follow-up arranged at {a}.", "Referred to {a} for review."]
CODE = ["Research ID {c}.", "Enrolled under {c}.", "Tracking code {c}."]


def piece(text, label, subtype, site):
    return {"text": text, "type": label, "subtype": subtype, "site": site}


def append_block(note, rng, index):
    """Append the local-details block; return the note with its new spans."""
    text, spans = note["text"], list(note["spans"])
    sentences = []

    def place():
        listed = rng.random() < 0.6
        name = rng.choice(LISTED_PLACES if listed else UNLISTED_PLACES)
        return piece(name, "ADDRESS", "FACILITY", "listed" if listed else "unlisted")

    def code():
        if rng.random() < 0.8:
            fmt, kind, digits = rng.choice(LISTED_CODES)
            return piece(fmt.format(rng.randrange(10 ** (digits - 1), 10 ** digits)), "ID", "SITE-CODE", "listed")
        fmt, kind, digits = rng.choice(UNLISTED_CODES)
        return piece(fmt.format(rng.randrange(10 ** (digits - 1), 10 ** digits)), "ID", "SITE-CODE", "unlisted")

    sentences.append((rng.choice(SEEN), {"a": place(), "b": place()}))
    if index % 2 == 0:
        sentences.append((rng.choice(TRANSFER), {"a": place(), "b": place()}))
    if index % 3 != 0:
        sentences.append((rng.choice(CODE), {"c": code()}))
    out = text.rstrip("\n") + "\n\n"
    for template, pieces in sentences:
        cursor = 0
        for token in sorted((t for t in "abc" if "{" + t + "}" in template), key=template.index):
            before = template[cursor:template.index("{" + token + "}")]
            out += before
            p = pieces[token]
            start = len(out)
            out += p["text"]
            spans.append({"start": start, "end": len(out), "type": p["type"], "subtype": p["subtype"], "entity": "",
                          "text": p["text"], "site": p["site"]})
            cursor = template.index("{" + token + "}") + len(token) + 2
        out += template[cursor:] + " "
    out = out.rstrip() + "\n"
    for s in spans:
        assert out[s["start"]:s["end"]] == s["text"], s
    return {**note, "text": out, "spans": spans, "family": FAMILY}


def build(count=60, seed=SEED):
    rng = random.Random(seed)
    base = generate.generate_notes(seed, max(1, (count + 3) // 4))[:count]
    return [append_block(n, rng, i) for i, n in enumerate(base, 1)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/generated/site")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    notes = build(args.count, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "notes.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for n in notes:
            handle.write(json.dumps(n, sort_keys=True) + "\n")
    site = [s for n in notes for s in n["spans"] if "site" in s]
    print(f"{len(notes)} notes, {len(site)} site identifiers "
          f"({sum(s['site'] == 'listed' for s in site)} listed in the profile, {sum(s['site'] == 'unlisted' for s in site)} unlisted) -> {out}")


if __name__ == "__main__":
    main()
