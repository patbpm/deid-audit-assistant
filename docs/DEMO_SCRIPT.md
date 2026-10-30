# Demo video script (3:00)

Status: draft for Patrick's approval. Nothing here has been recorded. Every number spoken or shown must match a row in `docs/CLAIMS.md`; if a run changes, change the line here. Synthetic data only on screen. This is an assistant for human review, not a compliance certification, and the video says so.

Judges score Demo at 25%, and the video is the main thing they watch, so the order is: the problem in one picture, the tool working live, the evidence behind one change, the hard case that makes it more than pattern matching, the measured result with its limits, the agents around it, and an honest close.

## Before recording (checklist)

- [ ] Meta Model API key set in the environment (never typed or shown on screen). Check Billing shows the credit; a rehearsal and a take together cost about 0.2 USD at list price (`results/dev/app-live-check.json`: about 0.17 USD for both samples). **Each live run needs Patrick's yes.**
- [ ] Start the front page with the hosted models: `python -m deid.app --live --open`. Browser at 125% zoom, dark theme as is, one tab, bookmarks bar hidden, notifications off.
- [ ] Start the review page on the saved set B run in a second tab: `python -m deid.review.server --audit runs/agent-meta-advb-rtfix.audit.json --open` (the file is git-ignored; if it is missing, rebuild it from the cached replies with the command in `docs/ADVERSARIAL.md`, which costs nothing). Open note B0001.
- [ ] Prepare the watch-mode terminal (offline rules, no key needed): `python -m deid.watch.feed --out runs/demo-feed --count 8 --interval 4` in one terminal and `python -m deid.watch --source folder:runs/demo-feed --state runs/watch/demo` in another; `runs/watch/demo/status.html` open in a tab. Delete `runs/demo-feed` and `runs/watch/demo` first so it starts empty.
- [ ] Results slide (one still image, made from `results/adversarial-b/*.json`): the four numbers in segment 4, the caption "one run, 200 synthetic notes written by the project", and one line for the held-out run: "400 held-out easy template notes: 5,992 of 5,992 found, 0 false positives".
- [ ] A first take of the live run is recorded as a fallback in case the hosted model is slow on the day.
- [ ] Title and closing cards carry the repository URL and the line "Assistant for human review. Not a compliance certification. Synthetic data only."

## Timeline

| Time | On screen | What the viewer should get |
|---|---|---|
| 0:00 - 0:20 | Note B0001 original text, the words "Sage Fair", "Fair skin", "Sage tea", "Ms. Fair" highlighted | The problem: a name can also be an ordinary word, so find-and-replace tools make mistakes in both directions |
| 0:20 - 0:55 | Front page, live: sample notes, the synthetic tick, start, the four steps filling in, result card with the "See the change" before-and-after panel | It runs end to end on a hosted Meta model, and tells you what it is unsure about |
| 0:55 - 1:30 | Review page: side by side, click a replacement, evidence row, reject one | Every change has evidence you can check; a person decides |
| 1:30 - 2:05 | Back to B0001 in the review page; then the results slide | The hard case, handled, and the number that goes with it, with its limits |
| 2:05 - 2:30 | Red-team result, then the watch-mode terminals and status page | Agents that check each other, and notes cleaned as they arrive |
| 2:30 - 3:00 | Closing card | What Meta tooling did what, what is not claimed, built during the hackathon, repository |

## Narration (about 430 words, read at a calm pace)

**0:00 - 0:20 (problem).** "Clinical notes can't be shared for research until the identifiers are out. Here is a synthetic note. 'Sage Fair' is the patient. But 'Fair skin' and 'Sage tea' are ordinary words. A tool that replaces every match scrubs the medicine along with the name, and a tool that skips common words can leave a real name behind. I built an assistant that gets this right where it can, and tells a person where it can't."

**0:20 - 0:55 (live run).** "This is the front page, running on Meta's Muse Spark through the Meta Model API. I load the sample notes, confirm they are synthetic, and start. The agent works in four steps: detect identifiers, verify the ones it is unsure about with a second call, replace them consistently, and finally a red-team agent reads the cleaned note and tries to work out who it is about. [Sped up, say so on screen.] Sixty-four replacements, two items left for a person, risk rated low. That rating is a model's opinion, not a guarantee."

**0:55 - 1:30 (evidence and review).** "Each change keeps its evidence. I click a replacement: here are the original's character offsets, the detector that found it and its confidence, the verifier's verdict, and the rule that rewrote it. Dates shift by one amount per patient, so intervals survive; one fake name per real name across a patient's notes. I disagree with this one, so I reject it, and the original comes back. Anything I leave undecided stays replaced. The tool is built so doing nothing never exposes a name."

**1:30 - 2:05 (hard case and result).** "Back to the hard case. The detector flags 'Fair' as possibly an ordinary word, and a separate narrow check reads each doubtful occurrence in context. 'Ms. Fair' is replaced. 'Fair skin' is left as written, and it shows up in the review list with a button, 'Replace it after all', so a person can overrule it. If that check fails or is unsure, the name is replaced. On a second adversarial set of 200 short synthetic notes, written by me, one run: all 609 identifiers covered, including 21 real surnames written bare, and one false positive per two hundred notes at detection. Philter makes 0.83 false positives per note on the same set, Presidio 1.55. One run, a set I wrote, so treat it as evidence, not proof. On 400 held-out notes of easy template text, all 5,992 identifiers found, no false positives."

**2:05 - 2:30 (agents and watch mode).** "The red-team agent isn't decoration: identifiers it finds go back to the detector for another pass, and clues like a rare condition or a small town go to the reviewer. And notes don't have to arrive in a batch. In watch mode, notes dropped into a folder or a database table are cleaned as they arrive, and when an original is edited, its cleaned copy is withdrawn and cleaned again. This clip uses the offline rules engine; I have not run watch mode with a hosted model."

**2:30 - 3:00 (close).** "Meta's Muse Spark does the detecting, the verifying, the name check and the red-team reading, and Muse Voice Transcribe and the vision model let it take dictated and scanned notes. Everything on screen was built during the hackathon, and everything it saw was synthetic. It is an assistant for human review, not a compliance certification, and I have not tested it on real notes. I also ran Meta's open-weights Muse Spark Open as the detector on the dev notes: 99.2 percent found, no false positives, against 100 for Muse Spark, detector only. The code, the test sets and the commands to reproduce every number are in the repository."

## Notes on what to show and what not to say

- Say "false positives per note", not "accuracy". Do not say "beats Philter" or "better than"; say the numbers and the conditions.
- Do not say "runs locally", "on-premises", "HIPAA compliant", "safe for patient data" or "production ready".
- Do not claim watch mode or the two-model cross-check work with a hosted model; they are built and tested with scripted models only. The cross-check is not shown in the video.
- The 400-note test split was run once, with the pass criteria written first (`docs/TEST_RUN.md`): 5,992 of 5,992, 0 false positives. Say "easy template text" next to it every time; it is not a real-notes result, and the adversarial set is the harder test.
- If the live run is slow, cut to the recorded fallback and keep the on-screen label "sped up" or "recorded".
- Keep the key, job folders and `*.key.json` files off screen even though the data is synthetic: they hold what reverses the cleaning.

## If time is short on the day

Cut order, from the bottom: the watch-mode clip (2:05 - 2:30 becomes red-team only), then the reject action, then the live run (use the recorded one). Never cut the hard case or the closing limits.
