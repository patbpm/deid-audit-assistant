# Submission text (draft for Patrick's approval)

Nothing here is submitted or published. Every number traces to a row in `docs/CLAIMS.md`; Patrick approves each claim before it goes on the Cerebral Valley form. Square brackets are for Patrick to fill in or delete.

## Fields

**Project name:** [Patrick to choose. Working title: Clinical text de-identification and audit assistant.]

**Track:** Indie developer (solo). **Problem statement:** Build for Your World.

**Representative / team:** Patrick [full name as on the CV account]. No other contributors.

**Repository:** [public URL, set before submitting]  **Demo video (3 min):** [link, accessible without login]

**One line (under 140 characters):** An open-source assistant that de-identifies clinical notes with Meta's Muse Spark, shows evidence for every change, and leaves the hard calls to a person.

**Short description (about 60 words):** Clinical notes cannot be shared for research until names, dates, IDs and contact details are removed, and tools make mistakes in both directions. This assistant uses Muse Spark to find identifiers, check the doubtful ones, replace them consistently, and have a second agent try to re-identify the result. Every change comes with its evidence, and a person reviews what the agent is unsure about.

## Description

### The problem

De-identifying free-text clinical notes is slow, and it fails in two ways. Pattern tools miss identifiers that do not look like identifiers: a name that is also a word ("Fair", "Wood", "Swift"), an odd date format, a typo, a surname written without a title. Or they over-scrub and damage the clinical content, so a note stops being usable: "Fair skin" becomes a person, "Wilson disease" loses its name, "last Tuesday" becomes a date. In both cases the person who has to sign off gets no evidence about what was changed or why.

[Patrick, in your own words, one or two sentences on why you know this problem firsthand. Do not name your employer's projects or data.]

### What it does

Each note goes through a small pipeline of Muse Spark agents:

1. **Detect** names, dates, IDs, phone numbers, emails and addresses.
2. **Verify** the spans the detector was unsure about, with a second call. The verifier can raise doubt but never removes a span.
3. **Check name uses.** When a name is also an ordinary word ("Sage tea" next to "Patient: Sage Fair"), a narrow call reads each doubtful occurrence in context. Only a clear "ordinary word" answer leaves text as written; a failed, cut-off or unsure answer keeps the name replaced.
4. **Replace consistently.** One date shift per patient (intervals survive), one fake name per real name across a patient's notes, same-shape IDs, fictional phones and emails. What cannot be rewritten safely becomes a tag and is flagged.
5. **Red-team.** A second agent reads the cleaned note and tries to work out who it is about: leftover identifiers go back to the detector; clues such as a rare condition or a small town go to a person. It reports a risk level, which is a signal, not a guarantee.
6. **Audit and review.** Every change links to its character offsets, the detector, its confidence, the verifier's verdict and the rule that rewrote it. A local review page puts original and cleaned text side by side; a person accepts, rejects, redacts or adds. Anything left undecided stays replaced, so doing nothing never exposes a name.

Around the pipeline: a front page where a person drops or pastes notes (plus CSV tables, dictated audio and scanned pages); a **watch mode** that cleans notes as they arrive in a folder or SQLite table and re-cleans a note when its original changes; and a **two-model cross-check** that flags any span two detectors disagree on.

### How it uses Meta's models

- **Muse Spark (`muse-spark-1.3`, Meta Model API)** runs four separate roles: detector, verifier, name-use check and the re-identification red-team, each with its own prompt and failure behavior (fail closed). The same model reads scanned pages.
- **Muse Voice Transcribe** turns dictation into notes that go through the same pipeline.
- The client speaks an OpenAI-style endpoint, so the model is swappable (`--provider custom`), and a second model can be added for the cross-check. **Muse Spark Open on partner inference was planned for a comparison and was not run; no open-weights result is claimed.**

### What was measured

All results are on synthetic notes, are reproducible from the repository, and come from one run unless said otherwise. Full tables, intervals and caveats are in `docs/EVIDENCE.md`.

- **Hard cases (adversarial set B, 200 short notes, 609 labeled identifiers, written by the project):** all 609 covered, including 21 real surnames written bare, with 1 false positive at the detection stage (0.005 per note) and 1 in the final output. Philter makes 0.83 false positives per note on the same set and Presidio 1.55. The success test was stated before the run, and it passed. Estimated cost 2.74 USD at list price.
- **A failure found and fixed in public:** the first adversarial set (180 notes) exposed two causes of false positives (every occurrence of a listed name replaced; relative and year-only dates listed): 108 false positives, 0.60 per note. I fixed both, built set B from a new seed and different vocabulary to judge the fixes, and a stage disagreement that the date fix created (the red-team re-adding year-only dates, 7 false positives at the end) was found and corrected (1). Set A is now a tuned set and set B has been read for that last fix; both are disclosed as such.
- **Easy template notes (200 dev notes):** 3,023 of 3,023 identifiers found with no false positives and nothing left word for word. This is the split the prompts were tuned on, so it shows no regression, not accuracy.
- **Baselines on 400 held-out synthetic notes:** regex 54.0% recall, Presidio 94.7% / 74.3% precision, Philter 100.0% / 86.4% (recall / precision).
- **Review burden:** on the first adversarial set, ranking flags by confidence reached 90% of the gain after 6 reviews against 52 in random order, with a perfect reviewer assumed.

### What was not measured, and limits

- The model-based system was **not run** on the 400-note held-out test split (a decision made on Oct 29), so there is no held-out result for it; the model results are on the dev split and two adversarial sets the project wrote.
- The open-weights comparison, the two-model cross-check with a real second model, and watch mode with a hosted model were **not run**. They are built and pass their tests with scripted models only.
- The synthetic notes are template-based and short; scores will not predict performance on real clinical text. **Nothing was tested on real notes, and it must not be used on real patient data.**
- The adversarial sets were written by the project, with 20 notes or fewer per family, so intervals are wide.
- This is an assistant for human review, **not a compliance certification**. It does not guarantee removal of every identifier and gives no medical advice. The replacement key and audit files contain original identifiers and must never be shared with the cleaned notes.
- "Self-hostable" and "runs locally" are not claimed: the code has not been tested that way. Hosted services only ever see synthetic data.

### Built during the hackathon

Setup files and a smoke-test script were created on Oct 26, 2026. All project code, the synthetic data generator and test sets, the evaluation harness, the pipeline, the review and front pages, table, dictation and scan input, the cross-check and watch mode were written between Oct 27 and Nov 4. The commit history shows what was added when; no earlier code was imported. No real patient data and no data from any employer or research project was used.

### What I would do next

Run the held-out test split once on the final system (not run for this submission); run the same pipeline on Muse Spark Open through a partner endpoint to compare accuracy, cost and latency; run the cross-check with two real models and measure whether disagreement is a better review signal than confidence; and have someone other than the developer use the review page.

## Anti-project check (for my own use, not for the form)

Not medical advice, not a RAG app, not an image analyzer, not a generic chatbot: it is a multi-agent tool that finds, changes and audits identifiers in text. The organizers' "Best Agentic Use-Case" fits the red-team loop and watch mode; "Best Build on Meta Open Weight Models" does not apply because no open-weights run was made.
