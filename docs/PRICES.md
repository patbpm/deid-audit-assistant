# Per-token prices and cost estimates

Retrieved Oct 29, 2026 from the vendors' own pages. Prices change; re-check before quoting any dollar figure. Nothing here is a claim about accuracy.

## List prices (USD per million tokens, standard mode)

| Model | Host | Input | Cached input | Output | Source |
|---|---|---|---|---|---|
| `muse-spark-1.3` | Meta Model API | 1.25 | 0.15 | 4.25 | [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits) |
| Muse Spark Open (`meta-models/muse-spark-open`) | Baseten Model APIs | 1.25 | 0.15 | 4.25 | [Baseten library page](https://www.baseten.co/library/muse-spark-open/) |

Third-party trackers list the same $1.25 / $4.25 for Muse Spark Open on Modal, Together, Nebius, Fireworks and Baseten, but those are not primary sources; confirm on each host's own page before using one.

**Not used:** Meta also lists `muse-spark-1.3-contributor` at $0.10 input / $0.20 output, but that mode requires permission to train future Meta models on the prompts and responses. This project does not use it.

Rate limits (muse-spark-1.3, per team): 3,000 requests and 4,000,000 tokens per minute; far above what these runs need.

## What is not settled

- **Reasoning tokens.** Meta's page does not say whether reasoning tokens are billed as output tokens. The API's `completion_tokens` figure (which the run logs record) is large because Muse Spark reasons, and the estimates below bill all of it at the output rate. If Meta bills differently the invoice is the authority.
- **Cached input.** The estimates bill every input token at the full input rate, which can only overstate cost. The response cache in this repo is separate from the host's prompt caching and is not counted at all (a cache hit costs nothing).
- **Baseten model id.** The library page shows `meta-models/muse-spark-open`; the hackathon notes in `docs/RESOURCES.md` say to use `meta-models/muse-spark-open-1026`. Confirm with `baseten model-api list` once a key exists.
- **Credits.** Baseten's docs do not say how credits show up on an invoice; their cost subtotals exclude credits. These are list-price estimates, not what any account will be charged.

## Cost of the runs so far, at list price

Computed from the token counts in `results/dev/*.json`; every one was covered by the $150 credit.

| Run | Input tokens | Output tokens | Estimated cost |
|---|---|---|---|
| Detector smoke test, 5 notes | 3,640 | 14,862 | $0.068 |
| Red-team smoke test, 15 probes | 12,803 | 21,037 | $0.105 |
| Agent run, 5 notes (fresh calls only; detection came from cache) | 4,798 | 7,683 | $0.039 |
| **Total** | | | **$0.21** |

## Rough forecasts (extrapolated from those runs; not measurements)

Per detection call about 728 input and 2,972 output tokens, about $0.0135 per note. Each red-team call about 854 input and 1,402 output tokens.

| Run | Notes | Tokens | Estimated cost |
|---|---|---|---|
| Detector only, dev split | 200 | about 0.74M | about $2.70 |
| Detector only, test split | 400 | about 1.5M | about $5.40 |
| Whole agent, dev split, 1 red-team call per note | 200 | about 1.2M (plus the verifier) | about $4.10 |
| Whole agent, dev split, 2 red-team calls per note | 200 | about 1.6M | about $5.50 |

The whole-agent dev run exceeds a 1,000,000-token cap, so it would need a higher cap (your approval) even though the dollar cost is small against the $150 credit and the $100 paid-usage ceiling. Muse Spark Open's token use may differ from `muse-spark-1.3`'s.

## Using the prices

```powershell
python -m deid.eval.compare --split dev --name meta-vs-open `
    --system meta=runs/meta-dev.jsonl --log meta=runs/meta-dev.log.json `
    --system open=runs/open-dev.jsonl --log open=runs/open-dev.log.json `
    --price meta=1.25,4.25 --price open=1.25,4.25
python -m deid.detect.run --live --price-in 1.25 --price-out 4.25 ...      # prints cost_usd in the run summary
```

The code never assumes a price; these flags are how the numbers get in.

## Running Muse Spark Open on Baseten

Needs a Baseten account and API key, which only you can create or claim (credits are by request form and email). Then:

```powershell
$env:DETECT_BASE_URL = "https://inference.baseten.co/v1"
$env:DETECT_MODEL    = "meta-models/muse-spark-open"      # or the -1026 id if the list command shows it
$env:DETECT_API_KEY  = "<your Baseten key>"               # set in your user environment, never in a file
python -m deid.detect.run --provider custom --limit 5             # dry run first
```

Check before a real run: the base URL and bearer-token auth match what Baseten documents; the output-token limit (`--max-output-tokens`, default 4096) leaves room for reasoning, since a truncated reply is counted as a failure; and a first run on 5 dev notes confirms the replies parse.
