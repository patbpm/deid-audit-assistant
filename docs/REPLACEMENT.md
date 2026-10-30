# Replacement engine

Status: Day 5, working on the dev split with **true** spans. It has not been run on any detector's output beyond one 5-note smoke run, and not on the test split. This is an assistant for human review, not a compliance certification.

`deid/replace/` takes a note and a list of spans (start, end, type) and returns the de-identified text plus a change record for every replacement. It reads only start, end and type: the true entity ids and ISO dates in the dataset are used by the checker afterwards, never by the engine (a test enforces this).

```powershell
python -m deid.replace.run --pred runs/<predictions>.jsonl --out runs/deid-dev   # or --pred gold
python -m deid.replace.check                                                      # dev split, true spans
```

## What it does

| Type | Rule |
|---|---|
| DATE | Shifted by one fixed number of days per patient (30-365 days, either direction, chosen from a hash of the patient key and the seed). Intervals between a patient's dates are unchanged. The written style is kept (`2025-04-11`, `2025-4-11`, `Apr 11`, `4/11/25`, `11 Apr 2025`, `11-Apr-25`, `11Apr2025`, `11th of April 2025`, `2025.04.11`, `11.04.2025`...). Dotted dates are read day-first; slash and dash dates month-first. |
| NAME | Replaced token by token. A real first name always maps to the same surrogate first name, a real surname to the same surrogate surname, wherever and however it is written. "Murphy, Patrick R", "Patrick Murphy" and "Murphy" stay linked; relatives who share a surname still share one. Titles (Dr., Mrs.) and credentials (MD, PA-C) are kept. Which tokens are first names or surnames is read from the full names in the batch; a name seen only on its own gets a name that works as either. |
| ID | Same shape, different characters. A leading letter run that looks like a label (4+ letters, or followed by a separator) is kept, so `ACCT` and `RAD-` survive. Nine-digit dashed numbers stay in the 900 range, which is never issued as a real SSN. Different originals never share a surrogate. |
| PHONE | Punctuation kept; digits become a fictional `555-01xx` number. The same digits give the same surrogate in any format. |
| EMAIL | `firstname.lastnameNN@example.com` or `.org`. |
| ADDRESS | Street number, street name, unit number, town and ZIP replaced; street type and state kept (two-letter or spelled out). Also handles `PO Box` and a unit written first. A town on its own maps to the same surrogate town as inside a full address. An address with no commas is flagged, not guessed. |

Surrogate names, streets and towns come from pools that do not overlap the generator's (tested), and a surrogate that equals a real value in the batch is never used.

Anything the engine cannot rewrite safely is replaced with a tag such as `[DATE]` or `[ADDRESS]` and marked `flagged` in the change record. It is never left in the text and never guessed at. These flagged items are what the review step (Day 7) will show a person.

## Check on the dev split (true spans, 200 notes, 3,023 spans)

From `results/dev/replace-dev.json`, produced by `python -m deid.replace.check` (seed 0):

- 0 flagged replacements; 0 original names, IDs, phones, emails or addresses left in a note.
- Dates: 804 full dates across 50 patients; every patient has exactly one shift, and it equals the engine's recorded offset (shifts range from -355 to +356 days).
- Names: 103 distinct real name tokens; none maps to more than one surrogate, no two share one, none maps to a value that is a real name in the batch; all 161 people keep consistent tokens across their notes.
- 0 phone, ID or email shapes changed; 0 notes with text changed outside the replaced spans.

Because the engine is given the true spans, the zero-leak result is partly by construction. It shows the replacement step is sound, not that the pipeline is. End-to-end leakage depends on what the detector misses, and was not measured with detector output on the test split (not run).

## Hard formats (adversarial set, true spans)

Run on the 180 adversarial notes (`docs/ADVERSARIAL.md`, checked by `tests/test_adversarial.py`): no crash and no replacement equal to its original. Before the fixes below, 128 of 540 replacements fell back to a tag; now 31 do, all of them either a mistyped date with a doubled slash (`7/7//2025`) or an address with no commas. Fixes: a 7-digit phone that was already in the fictional block was returned unchanged and is now always changed; more date styles (unpadded ISO, dotted, `11-Apr-25`, `11Apr2025`, `11th of April`, `11-10`); PO boxes, spelled-out states and a unit written first. The dev-split check above is unchanged by these edits.

## Known limits (read before quoting anything)

- **Year-less dates.** `Apr 21` has no year, so the engine assumes the most common year among the note's other dates. Where a shift crosses 29 February and that guess is wrong, the result is one day off: 3 of the 46 year-less dates on dev. Their `rule` ends in `-no-year` so they can be listed.
- **Month-first assumption.** `04/05/2025` is read as 5 April. When both numbers could be a month the `rule` says `-assumed-month-first`; 162 of the dev dates were of that kind.
- **Shifts are blunt.** Season and day of the week are not preserved. Ages of 90 or more are not aggregated, which Safe Harbor requires; the synthetic set has none. The shift is applied to every date type, including birth dates, with the same offset.
- **Names.** Surrogate first names do not match sex, so "Mrs." can precede a male-sounding name. Gender words and pronouns in the note are untouched. The first-name/surname split depends on the other names in the batch.
- **Labels kept.** A 4+ letter ID prefix is kept as a label. An insurance ID with four or more leading letters would keep them.
- **Not covered.** Identifying detail in unlabeled text (rare conditions, occupation, a small town named in prose). That is the re-identification check planned for Day 6.
- **The key re-identifies.** `<out>.key.json` and `<out>.changes.jsonl` hold the originals. Never share them with the de-identified notes. Both are git-ignored under `runs/`.
