# Spanish-language notes

Status: Day 8 (Oct 31). The generator and the replacement engine's Spanish support are built and tested offline, and the detector was run live once on the Spanish notes (result below). This is an assistant for human review, not a compliance certification.

## Why

A project that only ever shows English notes is untested on anything else. Many clinics write some notes in Spanish. This adds Spanish to the replacement step and a Spanish synthetic set, and a way to ask whether the hosted model finds identifiers in Spanish with an English prompt. It says nothing about other languages and nothing about real Spanish-language notes.

## What was added

- **Replacement engine, `language: es`** (`deid/replace/`): Spanish dates (`12 de abril de 2025`, `5 de marzo del 2024`, `03 de enero`) are parsed, shifted and written back in the same style with Spanish month names; slash and dash dates are read day-first (`04/05/2025` is 4 May), and when both numbers could be a month the change is flagged for review as a guess; stand-in names come from Spanish pools that do not overlap the generator's (a test enforces it); the titles Sr., Sra., Srta., Dr. and Dra. are kept (Don and Doña are not treated as titles, because Don is also an English first name); streets written `Calle Los Pinos 1423, Apto 2B, Town, TX 79316` are rewritten (street name, number, unit, town, ZIP). Agent: `--language es`. App: "Language of the notes" in the options.
- **Spanish synthetic set** (`python -m deid.synth.spanish`): 40 notes for 20 invented patients in the American Southwest, three kinds (follow-up visit, discharge summary, telephone encounter). Two surnames per person, `Apellido, Nombre` and `Nombre Apellido Apellido` forms, titles, five date styles plus two without a year, `Calle`/`Avenida`/`Camino`/`Paseo` addresses, the same phone/ID/email formats as the English set. 566 labeled identifiers (NAME 222, DATE 173, PHONE 99, ID 40, ADDRESS 26, EMAIL 6). Everything is invented; the clinical stories are generic.

## Measured offline (no model): `python -m deid.eval.spanish check`

The engine applied to the **true** labels: 566 of 566 replacements made, 0 fell back to a tag, 0 original names, IDs, phones, emails or addresses left in a cleaned note, and every one of the 20 patients' dates moved by a single shift (165 full dates compared). 42 of the dates were read day-first on a guess because both numbers could be a month; those are flagged in the audit. This shows the engine copes with these formats. Because the labels are given to it, it is not a detection result (`docs/REPLACEMENT.md` makes the same point for English).

## Detection in Spanish (Oct 31, 2026; Muse Spark `muse-spark-1.3`; English prompt; detector only; one run)

```powershell
python -m deid.eval.spanish detect --live --max-total-tokens 250000 --price-in 1.25 --price-out 4.25
python -m deid.eval.spanish score --pred runs/es-detector.jsonl --name es-detector
```

565 of 566 labeled identifiers found (99.8%, interval 99.5 to 100), precision 100% (0 false positives), 40 of 40 notes read without error, 0.10% of identifier characters left uncovered. By type: ADDRESS 26 of 26, DATE 173 of 173, EMAIL 6 of 6, ID 40 of 40, PHONE 99 of 99, NAME 221 of 222. The one miss is a bare first name repeated in a telephone note ("Patricia tuvo dudas..."), the same kind of miss the open-weights model made in English: a name repeated alone, later in a note. About $0.49 at list price (30,200 tokens in, 107,418 out).

What this shows: with the unchanged English prompt, the model handled these Spanish dates, two-surname names, `Calle` addresses and titles. What it does not show: anything about other languages, real Spanish-language notes, free-form (non-templated) writing, accents or typos beyond these 40 short templated notes written by this project, or the audio and scan paths in Spanish. One run. Files: `results/es/es-detector-all.json`, `results/es/es-detector-all-agnostic.json`, `results/es/es-detector.log.json`.

The offline rules engine (`python -m deid.app` with no key) is English-only and will miss most Spanish names and dates; use a hosted model for Spanish.
