# Site profile: teach it your clinic

Status: Day 8 (Oct 31). Built and tested offline with scripted models. **No live model result exists yet**; this page says so until one does. This is an assistant for human review, not a compliance certification.

## Why

A generic "find identifiers" prompt does not know that `Birch Pavilion` is a building at one hospital, that `HRH-48213` is that hospital's research ID, or that `MICU-3` is a ward. A 2026 study of LLM de-identification found that naming the institution's own categories in the prompt recovered most of the identifiers that a purpose-built tool and the reference annotations had missed (hospital abbreviations, building names, internal codes): https://arxiv.org/abs/2608.17051 . This implements that idea in a form a person can use in a minute.

## What you give it

In the app (notes jobs): a box of **local names to remove**, one per line, and an optional one-line hint ("wings here are named after trees"). On the command line (`python -m deid.agent.run --site-profile data/site/hartwell.json`): a JSON file:

```json
{"name": "Hartwell Regional (invented)",
 "facilities": ["Hartwell Regional Hospital", "HRH", "Birch Pavilion", "MICU-3"],
 "id_patterns": [{"label": "Research ID", "regex": "HRH-\\d{5}", "example": "HRH-12345"}],
 "notes": "Buildings and units here are named after trees. List any such name."}
```

## What it does

Two parts (`deid/detect/site.py`):

1. **Rules, no model.** Every listed facility name (whole words, any capitalization) and every match of an `id_patterns` regex becomes a span with source `site profile` (confidence 1.0, shown in the audit as the detector). Facility names are replaced by `Facility 1`, `Facility 2`... (the same stand-in for the same name); codes by a same-shaped code. The model's own spans win where they overlap, and a model `ADDRESS` span that is exactly a listed name is retyped so it gets the same stand-in. These rules also run with the offline engine, so the box works without any key.
2. **Prompt.** The detection prompt gets a short "local rules" section that names the same things and asks the model to list other hospital, clinic, building, ward or unit names of the organization too. This is what can catch names the file does not list (the hint says how to recognize them). The verifier, name check and reviewer prompts are unchanged. The profile's digest is part of every cached request, so saved replies for different profiles never mix.

Limits: a profile holds at most 300 names and 20 patterns; a pattern may not match the empty string. Patterns are the person's own, run with Python's `re`, which has no time limit: do not paste a pattern you do not understand. Replay mode uses saved replies made without a profile, so there only the rules apply.

## The test: an invented hospital

`python -m deid.synth.site` appends a short local-details block to 60 ordinary synthetic notes (own seed, 20261031): where the patient was seen, sometimes a transfer, sometimes a research ID. The site, "Hartwell Regional", is invented. Its places are named for trees. 181 labeled site identifiers: 111 the profile lists and 70 it does not list (five tree-named places and one code format the profile never describes). The base notes' own labels are untouched.

What is claimed is only what a run shows; the offline tests show these properties (`tests/test_site.py`): the rules find every listed name and code and none of the unlisted ones, so the rules alone cannot generalize; the profile reaches only the detection prompt; two different profiles never share a cache entry.

The live experiment compares the detector without and with the profile on the same 60 notes, scoring recall on the base notes, on the listed site identifiers, on the unlisted ones, and false positives:

```powershell
python -m deid.synth.site
python -m deid.eval.site detect --arm generic            # dry run first
python -m deid.eval.site detect --arm generic --live --max-total-tokens 400000 --price-in 1.25 --price-out 4.25
python -m deid.eval.site detect --arm profile --live --max-total-tokens 400000 --price-in 1.25 --price-out 4.25
python -m deid.eval.site score --pred runs/site-generic.jsonl --name generic
python -m deid.eval.site score --pred runs/site-profile.jsonl --name profile --profile data/site/hartwell.json
```

Not run yet. Caveats to state with any result: the site, the profile and the hint were written together by the project, and the hint was written knowing the unlisted names are tree-named (the point is the mechanism, not a measured gain on a real clinic); 60 short synthetic notes; one run per arm; no real hospital was used.
