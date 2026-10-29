"""How well did speech or page reading preserve the identifiers, and does anything
survive cleaning? String-level checks against a known truth; no offsets needed.

    python -m deid.ingest.fidelity --truth data/generated/ingest/truth.jsonl \
        --ingested runs/ingest-x.notes.jsonl [--cleaned runs/agent-x.notes.jsonl] --name x

For each note the truth holds the written text, the dictation script, and every
identifier in written and spoken form. Reported per source (audio or scan):
  - word error rate (audio: against the script) and character error rate (scans:
    against the page text), as total edits over total reference length;
  - identifier recovery: how many true identifiers can still be found in the
    transcribed text, by type (a speech or reading error is a recovery miss, not
    a de-identification miss);
  - with --cleaned: how many of the recovered identifiers survive in the cleaned
    text. Dates are not checked there (their spoken and written forms differ, and
    the replacement check covers the shift).
A match is a string check. A name or address word also matches a one-letter
variant of itself (Larsen/Larson), since speech recognition respells names; so a
surname that is also a common word, or a near-miss word, can show as a false leak.
Leakage is an upper bound for names and addresses; for IDs, phones and emails an
identifier respelled by the recognizer is not found (recovery is a lower bound).
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from deid.replace import dates

CHECKED = ("NAME", "ID", "PHONE", "EMAIL", "ADDRESS")
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def alnum(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def has_token(token, have):
    """The word is there, or a one-letter variant of it is (speech recognition often
    respells names: Larsen -> Larson). Only for words of 5 or more letters."""
    if token in have:
        return True
    return len(token) >= 5 and any(abs(len(h) - len(token)) <= 1 and edit_distance(token, h) <= 1 for h in have)


def error_rates(reference, hypothesis):
    """(word edits, reference words, char edits, reference chars), on lowercase alphanumerics."""
    ref_w, hyp_w = words(reference), words(hypothesis)
    ref_c, hyp_c = " ".join(ref_w), " ".join(hyp_w)
    return edit_distance(ref_w, hyp_w), len(ref_w), edit_distance(ref_c, hyp_c), len(ref_c)


def present(kind, written, text, any_token=False):
    """Is this identifier still readable in `text`?"""
    have = set(words(text))
    if kind == "NAME":
        tokens = [w for w in words(written) if len(w) >= 3]
        return bool(tokens) and (any if any_token else all)(has_token(t, have) for t in tokens)
    if kind in ("ID", "PHONE"):
        return alnum(written) in alnum(text)
    if kind == "EMAIL":
        return alnum(written) in alnum(re.sub(r"\b(dot|at)\b", " ", text.lower()))
    if kind == "ADDRESS":
        tokens = [w for w in words(written) if len(w) >= 3 or w.isdigit()]
        return bool(tokens) and all(has_token(t, have) for t in tokens)
    if kind == "DATE":
        if alnum(written) in alnum(text):
            return True
        try:
            p = dates.parse_date(written)
        except dates.DateError:
            return False
        month = MONTHS[p.month - 1]
        days = {re.sub(r"(st|nd|rd|th)$", "", w) for w in have}
        return ((month in have or month[:3] in have) and str(p.day) in days
                and (not p.has_year or str(p.year) in have))
    return False


def reference_of(truth, source):
    return truth["script"] if source == "audio" else truth["text"]


def check(truths, ingested, cleaned=None):
    by_id = {t["note_id"]: t for t in truths}
    acc = {}
    for note in ingested:
        truth, source = by_id.get(note.get("source_note_id", note["note_id"])), note.get("source")
        if truth is None or source not in ("audio", "scan"):
            continue
        s = acc.setdefault(source, {"notes": 0, "word_edits": 0, "words": 0, "char_edits": 0, "chars": 0,
                                    "identifiers": Counter(), "recovered": Counter(),
                                    "checked": Counter(), "leaked": Counter()})
        we, wn, ce, cn = error_rates(reference_of(truth, source), note["text"])
        s["notes"] += 1
        s["word_edits"] += we
        s["words"] += wn
        s["char_edits"] += ce
        s["chars"] += cn
        clean_text = cleaned.get(note["note_id"]) if cleaned else None
        for g in truth["gold"]:
            s["identifiers"][g["type"]] += 1
            if present(g["type"], g["written"], note["text"]):
                s["recovered"][g["type"]] += 1
                if clean_text is not None and g["type"] in CHECKED:
                    s["checked"][g["type"]] += 1
                    s["leaked"][g["type"]] += present(g["type"], g["written"], clean_text, any_token=True)
    result = {}
    for source, s in acc.items():
        total, rec = sum(s["identifiers"].values()), sum(s["recovered"].values())
        result[source] = {
            "notes": s["notes"],
            "word_error_rate": s["word_edits"] / s["words"] if s["words"] else None,
            "char_error_rate": s["char_edits"] / s["chars"] if s["chars"] else None,
            "identifiers": total, "recovered": rec,
            "recovery_rate": rec / total if total else None,
            "recovered_by_type": {t: {"of": s["identifiers"][t], "found": s["recovered"][t]}
                                  for t in sorted(s["identifiers"])},
        }
        if cleaned is not None:
            chk, leak = sum(s["checked"].values()), sum(s["leaked"].values())
            result[source]["after_cleaning"] = {
                "checked_identifiers": chk, "still_present": leak,
                "leak_rate": leak / chk if chk else None,
                "by_type": {t: {"checked": s["checked"][t], "still_present": s["leaked"][t]}
                            for t in sorted(s["checked"])},
            }
    return result


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--truth", required=True)
    parser.add_argument("--ingested", required=True, help="notes JSONL from deid.ingest.run")
    parser.add_argument("--cleaned", help="cleaned notes JSONL from deid.agent.run (<name>.notes.jsonl)")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", default="results/dev")
    args = parser.parse_args(argv)
    cleaned = {r["note_id"]: r["text"] for r in read_jsonl(args.cleaned)} if args.cleaned else None
    result = {"name": args.name, "sources": check(read_jsonl(args.truth), read_jsonl(args.ingested), cleaned)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"ingest-{args.name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                                  encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
