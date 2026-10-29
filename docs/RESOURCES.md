# Resources and how to use them

Partner credits are not guaranteed and are distributed at each partner's discretion.

## Models (from the Participant Guide)
- Via Meta Model API: Muse Spark series, Muse Wonder, Muse Image, Muse Voice Transcribe, SAM 3.1
- Open weights: Muse Glimmer, Muse Spark Open (run on your own hardware or through partner inference)
- Coding agent: Muse Code
- Baseten: use model id `meta-models/muse-spark-open-1026` for the hackathon (the docs show `meta-models/muse-spark-open`; use the -1026 version)

## Credits
| Resource | Amount | How to get it | Use it for |
|---|---|---|---|
| Meta Model API | $150 | Create account at dev.meta.ai, add a card, submit the credit form by Nov 4 9 PM ET; shows under Billing > "free credits" (up to 2 business days) | Primary model: Muse Spark detection and hard cases; comparison against open weights |
| Baseten | $100 + 2M TPM limit | Request form; up to 2,000 participants; reviewed by use case, notified by email | Running Muse Spark Open at volume for full evaluation runs |
| Modal | $100 | Request form; first 1,000 participants (request early) | Serverless GPUs for batch evaluation; Endpoints for open-weights models |
| Fireworks | $25 | Request for your team; shortlist of select teams; email with redemption details | Cheap inference with Muse open models; attend the Oct 30 workshop |

## Billing rules for Meta Model API
- A credit card is required before the first API call. A temporary pre-authorization appears and is released within a few business days.
- Until the credit is applied, calls are charged to the card. Do not call the API (including `scripts/hello.py api`) until "free credits" shows the $150.
- The "Spend Limit" on the Billing page is a notification, not a hard cap. Set it at or below $150 and check usage often.
- Each participant claims their own credits; they cannot be claimed on someone else's behalf.

## Community
- Discord channels: #intros, #questions (ask Cerebral Valley), #office-hours (Meta team, text, 10-11 AM ET weekdays), #announcements, plus the Baseten channel.
- Docs: Meta Model API overview, quickstart, model list, API cookbook, OSS model cookbook, Muse Code recipes (links are in the Participant Guide).

## Rules for using cloud resources
- Only synthetic or public data goes to any cloud service.
- Do not claim the system runs locally. Say "self-hostable" only if tested.
- Track credit spend. Paid usage beyond credits is capped at $100 total across all providers (Patrick's current budget). Stop before the cap and ask him before raising it.

## Inference decisions
- Primary: Meta Model API (Muse Spark). Open weights: Muse Spark Open (816B parameters, hosted only) on Baseten, Fireworks, Modal, or another host; model id on Baseten: meta-models/muse-spark-open-1026.
- Muse Glimmer 30B is the only open model small enough to self-host (about 24 GB GPU memory); Patrick chose not to run models on his computer, so it is optional.
- If partner credits do not arrive, Patrick will pay for Muse Spark Open inference. The budget cap is $100. Use short synthetic notes and count tokens.
- List prices and the Baseten endpoint details (retrieved Oct 29, 2026) are in docs/PRICES.md.
