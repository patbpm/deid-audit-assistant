"""Two models, one note: where they disagree, a person looks.

A second detector (for example Muse Spark Open on partner inference next to Muse Spark on the
Meta Model API) reads the same note independently. The primary model decides what is replaced;
the second can only add. Then:

- a span both models found (their spans overlap) is "agree";
- a span only the primary found is kept replaced and marked "only primary";
- a span only the second found is added, replaced, and marked "only second", because a missed
  identifier costs more than an extra replacement.

Every disagreement goes to the review queue with the models named, and to the verifier for a third
opinion that the reviewer can read. A model's own confidence number says how sure it is; two models
disagreeing says that they would not both have gone the same way, which is a different signal. Whether
it is a better one is measured, not assumed (deid.eval.burden --cross, docs/CROSSCHECK.md).
"""

AGREE, ONLY_PRIMARY, ONLY_SECOND = "agree", "only primary", "only second"


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def cross_check(primary, second):
    """primary, second: span lists. Returns the merged span list; each span carries "cross" and, where the
    two models gave different types, "second_type". Input spans are not changed."""
    merged = []
    for s in primary:
        match = [t for t in second if overlaps(s, t)]
        span = {**s, "cross": AGREE if match else ONLY_PRIMARY}
        if match and all(t["type"] != s["type"] for t in match):
            span["second_type"] = match[0]["type"]
        merged.append(span)
    for t in second:
        if not any(overlaps(t, s) for s in primary):
            merged.append({**t, "cross": ONLY_SECOND})
    # a span only the second found can overlap another one only it found: keep the longer
    merged.sort(key=lambda s: (-(s["end"] - s["start"]), s["start"]))
    kept = []
    for s in merged:
        if not any(overlaps(s, k) for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: (s["start"], s["end"]))


def disagreements(spans):
    return [s for s in spans if s.get("cross") in (ONLY_PRIMARY, ONLY_SECOND) or s.get("second_type")]


def reason(span, primary_name, second_name):
    """The sentence the audit shows for a span the models disagree about, or None."""
    if span.get("cross") == ONLY_PRIMARY:
        return f"only {primary_name} found this; {second_name} did not"
    if span.get("cross") == ONLY_SECOND:
        return f"only {second_name} found this; {primary_name} did not"
    if span.get("second_type"):
        return f"the models disagree on the type: {primary_name} says {span['type']}, {second_name} says {span['second_type']}"
    return None
