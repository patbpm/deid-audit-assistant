# Cerebral Valley submission form: draft answers

Draft for Patrick's approval. Nothing here has been submitted. Every number traces to a row in `docs/CLAIMS.md`. Questions about opinions and ratings are Patrick's to answer; the notes under them list what actually happened so the answer can be honest.

## Form fields

**Team Name:** Patrick to choose. Suggestion: the project name, "Clinical text de-identification and audit assistant".

**Team Members:** filled in by the form from the Cerebral Valley account (it shows "Patrick Bope"). Solo, so no one else is added. Check this against the full name in `docs/SUBMISSION.md`.

**Which track:** Indie developer.

**Which problem statement:** Build for Your World.

**Most Viral Track X post link:** leave empty (no X post was made).

**Public GitHub Repository:** https://github.com/patbpm/deid-audit-assistant

**3-Minute Demo Video:** the YouTube link (Unlisted), once the video is uploaded.

### Project Description (short version, about 120 words)

Clinical notes cannot be shared for research until names, dates, IDs and contact details are removed, and tools make mistakes in both directions: they miss names that look like ordinary words and over-scrub medical terms. This is an open-source assistant for human-reviewed de-identification. Muse Spark finds identifiers, a second call checks the doubtful ones, and a replacement step shifts dates by one amount per patient and gives each real name one fake name. A red-team agent then reads the cleaned note and tries to work out who it is about. Every change links to its evidence (offsets, detector, confidence, verifier verdict), and anything left undecided stays replaced. It is an assistant for human review, not a compliance certification. All data is synthetic.

### Describe your use of Meta products to build the submitted project

- **Muse Spark (`muse-spark-1.3`) through the Meta Model API** in four separate roles, each with its own prompt and fail-closed behavior: detector, verifier, name-use check (is "Fair" a name or a word here?) and re-identification red-team. It also reads scanned pages (vision).
- **Muse Voice Transcribe** turns dictated notes into text that goes through the same pipeline (30% word error on 5 synthetic recordings; the cleaning step is what matters).
- **Muse Spark Open (open weights) on Baseten** was run as the detector on the 200 dev notes and on all 400 held-out synthetic notes with the same prompt: 98.9% of 5,992 identifiers found with 0 false positives, against 100% for Muse Spark on the same notes. One run each; the open model was run as detector only, not inside the full agent.
- Muse Spark results on synthetic notes: 5,992 of 5,992 identifiers found on 400 held-out easy template notes; on a 200-note adversarial set written by me, all 609 covered with 1 false positive at detection. One run each, synthetic data only, no real notes tested.
- Several later additions were also run once on Muse Spark: a site profile for local place names, a prompt-injection test, a note-to-note linkage check and Spanish notes. See `docs/EVIDENCE.md` and the README.

### Why are Meta's models important to your solution?

- The hard part of de-identification is reading context: whether "Sage" is a patient, a herb or a hospital ward. A model that reads the sentence can decide that, where pattern tools cannot. Muse Spark did this well on my test sets, and the separate name-use check cut false positives on the hard set from 30 to 1 (stage ablation, `docs/ABLATION.md`).
- Having both a hosted model and an open-weights model from the same family let me check that the pipeline does not depend on one host: the open-weights model came within 1.1 points of recall on 400 held-out notes. The code uses an OpenAI-style endpoint, so the model can be swapped.
- One family also covers dictation (Muse Voice Transcribe) and scanned pages (Muse Spark vision), so the same cleaning pipeline takes text, audio and images.
- Limits I am not claiming: no comparison with non-Meta language models was made, and no cost or speed comparison between the hosted and open-weights models was measured the same way.

## Partner technology feedback (Fireworks, Modal, Baseten)

Only Baseten was used. Facts from the run, to edit into your own words:

- Baseten's model list on my account showed `meta-models/muse-spark-open`, not the `-1026` id in the hackathon notes, so I had to look the id up.
- The open model reasons at length. With a 4,096-token output limit and no retry, 82 of 200 replies were cut off; raising the limit to 16,384 for a retry fixed it. Output limits matter for this model.
- Median first-attempt latency was 10.6 s (13.5 s p90) on the 200 dev notes. No cut-off replies and no parse errors on the 400 held-out notes at the higher limit.
- Fireworks and Modal were not used.

## Rating questions: Patrick's choice

I cannot answer these for you. Notes on what happened, if useful:

- **How likely to build with Meta Model API / overall opinion / recommend Meta Model API / recommend Muse Code:** your own experience. Muse Code was not used in this project (if that is wrong, say so). The Meta Model API did what the project needed: 4 roles, vision and voice all ran live.
- **Biggest obstacle:** options that are true: (a) the models reason at length, so long runs hit token caps and cost more than a first estimate (two held-out runs stopped at their caps and were resumed); (b) false positives on names that are ordinary words, which needed a separate name-use check; (c) a first adversarial set exposed two failure causes that had to be fixed and then judged on a second set.
- **Compared with other AI models you have used:** this project compared only Muse Spark with Muse Spark Open and with Presidio and Philter (not language models). If you have used other models for similar work, say that from your own experience and do not cite this project's numbers for it.
- **What matters most when choosing / hardest to switch / what would stop you using Meta's models in production:** your own view. One fact: the code is model-agnostic, so switching cost for this project is low; the real production blockers are that nothing was tested on real clinical text and that any hosted model would see patient text, which needs the organization's own approval.
