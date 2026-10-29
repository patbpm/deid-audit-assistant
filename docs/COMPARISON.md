# Comparing systems (Meta Model API and Muse Spark Open)

Status: Day 6, the comparison script is built and tested offline. **No open-weights run exists**: there is no partner endpoint or key yet, and no per-token price for any provider. This is an assistant for human review, not a compliance certification.

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

- The same prompt (`v1`) is used for both models. A prompt tuned for one model would be a different comparison and should be reported as such.
- Muse Spark always reasons, so its output tokens include reasoning; an open-weights host may bill or count tokens differently. Compare cost only with each provider's own price list.
- It compares detection only. The verifier, red-team and the whole agent run through `deid.agent.run`, which writes detector and final spans separately and can be compared the same way.
