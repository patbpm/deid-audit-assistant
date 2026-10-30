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

## Measured: Muse Spark Open on Baseten (Oct 30)

Two detector runs on the 200 dev notes (the first with no retry, the second asking cut-off notes again once at 16,384 tokens) used 310,161 input and 1,187,479 output tokens together, about $5.43 at the list prices above, against the forecast of about $2.70 for one clean run (the model reasons at length and 82 notes needed a second attempt). The model id on this account's model list was `meta-models/muse-spark-open`. Whether the Baseten account was charged or credited was not checked.

## Measured: Muse Spark Open on Baseten, held-out notes (Oct 30)

340 of 400 test notes (detector only) used 452,045 input and 1,748,726 output tokens, about $8.00 at list price, against a forecast of about $7.80 for all 400 notes; the model used more output tokens per note than forecast, so the 2.2M-token cap stopped the run early. About 6,470 tokens per note, so all 400 notes would have needed about 2.6M tokens (about $9.4 at list price). Whether the Baseten account was charged or credited was not checked.

The last 60 held-out notes used 75,744 input and 274,237 output tokens, about $1.26 (forecast about $1.40). All 400 held-out notes together: 527,789 input and 2,022,963 output tokens, about $9.26 at list price, about 6,380 tokens per note.
