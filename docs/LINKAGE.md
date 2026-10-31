# Reading a patient's notes together

Status: Day 8 (Oct 31). Built and tested offline, and the twelve-patient demonstration below was run live once. This is an assistant for human review, not a compliance certification.

## The problem

The re-identification reviewer (`docs/REDTEAM.md`) reads one cleaned note at a time. Details that are harmless in one note can single a person out in combination: a job in one note, a statewide award in another, a small town in a third. Research on re-identification of "de-identified" records (for example Sweeney and colleagues' linkage studies) turns on exactly this kind of combination.

## What it does

`--linkage` (agent) or the "read each patient's cleaned notes together" box (app) adds one reviewer call per patient with two or more cleaned notes (`deid/redteam/bundle.py`). The masked views of the patient's notes (each changed value shown as its type tag, as in the per-note review) go to the same reviewer prompt as one document headed "Notes about the same patient, to be read together as one record." If reading them together gives a higher risk level than the riskiest single note, or the reviewer quotes non-identifier clues at a level above low, a `linkage` item is added to the first note's review queue, naming the clues and which notes they come from. Nothing is edited: a job or a small town is for a person to judge. Only masked views are sent, never original text. A reply that cannot be read produces an item saying so, not silence. Notes that were not cleaned are left out.

The risk level is a model's judgment, a signal for a human reviewer and never a guarantee. Off by default; unavailable in replay mode.

## The demonstration: twelve invented patients

`python -m deid.synth.linkage` has six planted patients (each of three notes holds one mild detail; the three together describe one findable person) and six controls (ordinary jobs, places, conditions). Written without looking at any model's answer and not changed after a run. `python -m deid.eval.linkage` reads every note alone and then all three together, and reports per patient the single-note risks, the risk read together, and whether the pipeline would add an item.

Run once on Oct 31, 2026 (Muse Spark `muse-spark-1.3` as the reviewer; 48 calls; about $0.39):

```powershell
python -m deid.eval.linkage --live --max-total-tokens 150000 --price-in 1.25 --price-out 4.25
```

| Patient kind | Flagged by the linkage item | Read together rated medium or high | A single note already rated medium or high |
|---|---|---|---|
| Planted (6) | 6 of 6 | 6 of 6 | 6 of 6 |
| Control (6) | 0 of 6 | 0 of 6 | 0 of 6 |

The reviewer rated all six controls low alone and together, and all six planted patients high when read together. The item for each planted patient names the clues and which notes they come from (for example, for the teacher: the statewide teaching award in note 2 and the town of about 900 people in note 3).

**What this does not show.** In all six planted patients a single note was already rated medium or high on its own, so the notes were not "harmless one by one" as designed: the model found the single details identifying already. Reading them together raised the level in three of the six (athlete, council member and pastor went from medium to high); in the other three a single note was already high and the linkage item adds the combined picture and the note numbers, not a higher level. So the demonstration shows the check separates these planted patients from these controls and explains why, not that it finds risk no single note shows. Twelve invented patients; one run; the planted details were written by this project; the risk level is a model's judgment and never a guarantee. File: `results/linkage/linkage.json`.
