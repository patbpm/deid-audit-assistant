# Comparing systems (Meta Model API and Muse Spark Open)

Status: Day 7 (Oct 30), **one open-weights run exists** (detector only, dev split; result below). List prices for both models are recorded in `docs/PRICES.md`. This is an assistant for human review, not a compliance certification.

```powershell
# 1. run each system on the same notes (dev first; the test split only for the final run)
python -m deid.detect.run --live --limit 0 --name meta-dev --max-total-tokens 1000000
python -m deid.detect.run --live --limit 0 --provider custom --name open-dev      # DETECT_BASE_URL, DETECT_MODEL, DETECT_API_KEY set

# 2. compare
python -m deid.eval.compare --split dev --name meta-vs-open `
    --system meta=runs/meta-dev.jsonl --log meta=runs/meta-dev.log.json `
    --system open=runs/open-dev.jsonl --log open=runs/open-dev.log.json `
    --price meta=PRICE_IN,PRICE_OUT --price open=PRICE_IN,PRICE_OUT
```

The first `--system` is the reference. `--gold` takes another notes file (for example the adversarial set, with `--split all`). The result is written to `results/compare/<name>.json` and printed as two tables.

## What it reports

- **Accuracy**, type-agnostic (a hit is any overlap): recall, precision, leaked characters and false positives, each with a 95% bootstrap interval over notes.
- **The paired recall difference** between each system and the reference, with an interval from resampling the same notes for both. A difference whose interval includes zero is not evidence that one system is better.
- **Cost and speed**: tokens per live note, median and p90 latency, and cost per 1,000 notes, from the `.log.json` each detector run writes.

## Rules it keeps

- Only notes every system predicted are scored, so all systems face identical text.
- Prices are never assumed. Without `--price` the cost shows as n/a; the script does not guess a rate.
- Tokens served from the response cache are not counted, so a rerun looks cheaper than the first call did. The table shows how many notes came from the cache.
- Latency depends on the host, the time of day and the output limit; treat it as indicative, not a benchmark.
- Parse errors, truncated replies and unmatched strings are shown beside accuracy, since a system that returns unreadable replies should not look cheap.

## Limits

- The same prompt (`v2`) is used for both models. A prompt tuned for one model would be a different comparison and should be reported as such.
- Muse Spark always reasons, so its output tokens include reasoning; an open-weights host may bill or count tokens differently. Compare cost only with each provider's own price list.
- It compares detection only. The verifier, red-team and the whole agent run through `deid.agent.run`, which writes detector and final spans separately and can be compared the same way.

## Result (Oct 30, 2026, dev split, detector only)

Muse Spark Open (`meta-models/muse-spark-open`, Baseten Model APIs), detector only, prompt v2, the 200 dev notes, scored against the saved Muse Spark (`muse-spark-1.3`) detector output on the same notes: **99.2% recall (98.8-99.5), 100.0% precision, 0 false positives, -0.8 points of recall against Muse Spark (paired interval -1.2 to -0.5).** All 25 misses of 3,023 identifiers are names, and all are bare repeat mentions of a name (for example "Mrs. Kim" or "Karen reports") that the model did not list as a separate string; whether the replacement step would catch them anyway was not measured for this model.

Cost and speed of the open model (estimated at list price, $1.25 in / $4.25 out per million tokens): the first run used a 4,096-token output limit with no retry and 82 of 200 replies were cut off (recall 51.8% at that setting: a setting problem, not a measure of the model). The rerun, which asked the cut-off notes again once at 16,384 tokens, finished all 200. Both runs together used 310,161 input and 1,187,479 output tokens, about $5.43; first-attempt latency was 10.6 s median (13.5 s p90); the 82 retried notes took 20.1 s median counting both attempts. The model reasons at length, so output limit and retry matter.

Caveats: one run each; easy template notes; the dev notes are the split the prompts were tuned on, with Muse Spark, so the open model used a prompt that was not tuned for it; only the detector was run, not the verifier, name check or red-team, and not the adversarial sets (the held-out set is the next result); Muse Spark's own cost and latency were not measured with the same command, so no cost or latency comparison between the two models is claimed.

Files: `results/compare/meta-vs-open.json` (final comparison), `results/compare/meta-vs-open-4096.json` and `results/compare/open-dev-4096.log.json` (first run, no retry), `results/compare/open-dev-retry.log.json` and `results/dev/open-dev-retry-dev.json` (rerun, per-type scores).

Reproduce (needs a Baseten key; billed):

```powershell
$env:DETECT_BASE_URL = "https://inference.baseten.co/v1"; $env:DETECT_MODEL = "meta-models/muse-spark-open"   # DETECT_API_KEY set in the environment
python -m deid.detect.run --live --provider custom --split dev --name open-dev --limit 0 --max-total-tokens 1000000 --price-in 1.25 --price-out 4.25
python -m deid.detect.run --live --provider custom --split dev --name open-dev-retry --limit 0 --retry-output-tokens 16384 --max-total-tokens 1500000 --price-in 1.25 --price-out 4.25
python -m deid.eval.compare --split dev --name meta-vs-open --system meta=runs/agent-meta-dev-v2.detector.jsonl --system open=runs/open-dev-retry.jsonl
```

Baseten's model list on this account showed `meta-models/muse-spark-open`, not the `-1026` id in the hackathon notes.

## Result (Oct 30, 2026, held-out test split, all 400 notes)

Muse Spark Open, detector only, prompt v2, all 400 held-out test notes, scored against the saved Muse Spark detector output on the same notes: **98.9% recall (98.6-99.1) of 5,992 labeled identifiers, 100.0% precision, 0 false positives, -1.1 points of recall against Muse Spark (paired interval -1.4 to -0.9).** All 67 misses are names (name recall 97.4%); dates, IDs, phones, emails and addresses were all found. Cost about $9.26 at list price ($1.25 in / $4.25 out per million tokens; 527,789 in / 2,022,963 out tokens in total); no cut-off replies and no parse errors. The run was done in two parts: the first hit its 2.2M-token cap after 340 notes (99.0% recall on those 340, about $8.00) and the last 60 were run afterwards with the first 340 replies reused from the saved copy (about $1.26). Latency: median 12.3 s per note on the first 340 and 16.3 s on the last 60 (not pooled). Caveats: one run; easy template text; detector only; the test split has now been used for this run, so it is no longer untouched for tuning.

Files: `results/compare/meta-vs-open-test-full.json` (comparison on all 400), `results/test/open-test-full-test.json` (per-type scores), `results/compare/open-test.log.json` (first 340 notes) and `results/compare/open-test-rest.log.json` (last 60 live, 340 from cache), `results/compare/meta-vs-open-test.json` and `results/test/open-test-test.json` (the 340-note partial score).

Reproduce (billed; needs a Baseten key and Patrick's yes; the first command stops at 2.2M tokens, so the second is needed to finish):

```powershell
python -m deid.detect.run --live --provider custom --split test --allow-test --name open-test --limit 0 --retry-output-tokens 16384 --max-total-tokens 2200000 --price-in 1.25 --price-out 4.25
python -m deid.detect.run --live --provider custom --split test --allow-test --name open-test-rest --limit 0 --retry-output-tokens 16384 --max-total-tokens 500000 --price-in 1.25 --price-out 4.25
python -m deid.eval.compare --split test --allow-test --name meta-vs-open-test-full --system meta=runs/agent-meta-test.detector.jsonl --system open=runs/open-test-rest.jsonl
python -m deid.eval.run --pred runs/open-test-rest.jsonl --name open-test-full --split test --out results/test
```
