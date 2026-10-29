# Claims ledger (for Patrick's approval)

Every number and statement in the README, demo and submission must trace to a run anyone can reproduce. Nothing below is approved for publication until Patrick says so; the status column is for him to fill in.

| # | Claim (as worded in README.md) | Source | Reproduce | Approved |
|---|---|---|---|---|
| 1 | Regex baseline: recall 54.0%, precision 100.0% on the 400-note test split | `results/regex-test-agnostic.json`, `docs/RESULTS.md` | `python -m deid.baselines.regex_baseline` then `python -m deid.eval.run --pred runs/regex.jsonl --name regex --split test --agnostic` | |
| 2 | Presidio (default settings): recall 94.7%, precision 74.3% on the same split | `results/presidio-test-agnostic.json` | `python -m deid.baselines.presidio_baseline`, same scoring command | |
| 3 | Philter through a compatibility shim: recall 100.0%, precision 86.4% | `results/philter-test-agnostic.json` | `python -m deid.baselines.philter_baseline`, same scoring command | |
| 4 | Adversarial set: Philter 96.3% / 0.78 false positives per note; Presidio 86.5% / 1.16; regex 14.4% / 0.00 | `results/adversarial/*.json` | `python -m deid.synth.adversarial`, each baseline with `--notes data/generated/adversarial/notes.jsonl`, then `python -m deid.eval.adversarial --pred ... --name ...` | |
| 5 | Detector smoke test: 83 of 83 identifiers found, no false positives, on 5 easy dev notes | `results/dev/meta-first5-dev.json` | `python -m deid.detect.run --live --limit 5` (billed; needs the key) | |
| 6 | Red-team smoke test: 0/5 control flagged, 5/5 planted flagged and quoted, 10/10 withheld found (15 probes) | `results/dev/redteam-first5-dev.json` | `python -m deid.redteam.run --live --limit 5` (billed) | |
| 6b | Agent run on 5 dev notes: all stages ran; verifier confirmed 2 spans; red-team rated all 5 notes low with no leftovers; 83 of 83 found; 12,481 fresh tokens (detection reused cached replies) | `results/dev/agent-first5-dev.json`, `-detector-dev.json`, `-final-dev.json` | `python -m deid.agent.run --live --limit 5` (billed unless cached) | |
| 7 | Replacement check on dev with true spans: 0 originals left, one shift per patient, no inconsistent name surrogates; 3 of 46 year-less dates one day off | `results/dev/replace-dev.json` | `python -m deid.replace.check` | |
| 8 | The dataset has 600 notes and 9,015 labeled spans, frozen with recorded hashes | `data/frozen.json`, `tests/test_frozen.py` | `python -m deid.synth.generate`, `python -m deid.eval.freeze` | |
| 9 | Every parts-status line in the "Status of each part" table | `docs/PLAN.md` progress log, `git log` | `python -m unittest discover -s tests` for the offline parts | |

## Wording rules this README follows

- Smoke-test results are labeled as such (5 notes, easy text) and are not presented as accuracy.
- No claim of beating any named product. The regex baseline's score is described as reflecting the synthetic formats.
- "Not measured yet" lists what has no number, so nothing is implied.
- "Self-hostable" and "runs locally" are not claimed; the code has not been tested that way.
- No cost, latency or per-token price is quoted: the price is unknown. Token counts exist in the result files but are not claimed as cost.

## Open items before publishing

- Choose a licence (none is set).
- Decide which planning and setup docs (for example `docs/PLAN.md`, `docs/RESOURCES.md`, `docs/PRE_KICKOFF_CHECKLIST.md`) should stay out of the public repository, and review them line by line before it goes public.
- Re-check every row above after the final runs; numbers from smoke tests will be replaced by full-run numbers.
