# Review interface

Status: Day 6, built and tried by hand on the 5-note smoke-test audit (reject, select-and-redact, export all worked in the browser). Tested offline (`tests/test_review.py`). It has not been used on a live agent run, and no reviewer other than the developer has tried it. This is an assistant for human review, not a compliance certification.

```powershell
python -m deid.agent.run --live --limit 5                      # produces runs/<name>.audit.json
python -m deid.review.server --audit runs/<name>.audit.json --open
python -m deid.review.server --audit runs/<name>.audit.json --export   # write the outputs without the page
```

A local page on `127.0.0.1` (no framework, no external files). The left list shows each note and how many items are still open. For the chosen note, the original and the current result sit side by side, with a card for everything the agent flagged.

## What a reviewer can do

| Item | Actions |
|---|---|
| A flagged replacement | **Accept** (keep it replaced) or **Reject** (put the original text back). Every replacement, flagged or not, can also be restored from the table. |
| A red-team clue | **Redact it** (replace every location with `[REDACTED]`) or **Dismiss** (acknowledge, change nothing). |
| An unmatched model string | **Dismiss**. |
| Something the agent missed | Select text in the original and choose a type: it is replaced with a tag such as `[NAME]`, or `[REDACTED]` for OTHER. |

Keys: `j`/`k` move between items, `a` accept, `r` reject, `d` dismiss. Every action can be undone.

## Rules that keep it safe

- **Undecided stays replaced.** Leaving work unfinished never un-redacts anything; only an explicit reject restores original text.
- **Reviewer-added redactions use tags, not surrogates.** The replacement engine is not rerun, so these will not match the consistent fake names or shifted dates elsewhere in the note.
- Edits that overlap another edit are refused.
- Decisions are saved beside the audit file (`<name>.audit.decisions.json`) after every click, with who and when. The audit file is never changed, and decisions saved for a different audit file are refused.
- **Export** writes `<name>.reviewed.notes.jsonl` (the final notes) and `<name>.review-log.json` (every decision, and counts of accepted, rejected, dismissed, redacted, added and still undecided items). The log and the page contain original identifiers: synthetic data only, never shared.

## Local-only safeguards

The server binds to 127.0.0.1, rejects requests whose Host header is not the local address, requires a custom header on every change (so another website cannot post to it), sends a restrictive Content-Security-Policy, and the page builds its content with `textContent`, never markup from note text (a test checks this). There is no login: anyone who can reach this computer's localhost port can use it, so run it on a machine you control.

## Limits

- One reviewer at a time; no merging of two reviewers' decisions.
- Rejecting a replacement restores the original text exactly; it does not offer a different surrogate.
- The page is not tuned for very long notes or for phones.
- It shows what the agent flagged. A span nobody flagged can only be found by the reviewer reading the original.
