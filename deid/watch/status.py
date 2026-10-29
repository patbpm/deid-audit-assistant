"""status.html: one line per note, no note text. Safe to open or show; it holds ids and states only."""

import time
from html import escape

LABELS = {"released": "released", "pending": "held for review", "failed": "NOT CLEANED", "error": "error, will retry",
          "queued": "waiting"}


def render_status(state, paused, engine, now):
    notes = state["notes"]
    counts = {k: sum(n["status"] == k for n in notes.values()) for k in LABELS}
    rows = []
    for note_id in sorted(notes):
        n = notes[note_id]
        rows.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            escape(n["status"]), escape(note_id), escape(n["patient_id"]), escape(LABELS.get(n["status"], n["status"])),
            n["version"], escape(str(n.get("undecided", ""))), escape(n.get("error", ""))))
    summary = ", ".join(f"{counts[k]} {LABELS[k]}" for k in LABELS if counts[k]) or "no notes yet"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="3">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Watch status</title>
<style>:root{{--bg:#fff;--fg:#1d2330;--mut:#667;--line:#d9dee7;--ok:#e3f4e6;--hold:#fff3d6;--bad:#fde1e1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14181f;--fg:#e8ebf0;--mut:#9aa3b2;--line:#2b3340;--ok:#1d3524;--hold:#3a3014;--bad:#42191a}}}}
body{{font:15px system-ui,sans-serif;margin:24px 16px;background:var(--bg);color:var(--fg)}}h1{{font-size:20px;margin:0 0 4px}}
.mut{{color:var(--mut)}}table{{border-collapse:collapse;width:100%;max-width:900px;margin-top:16px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}}tr.released td:nth-child(3){{background:var(--ok)}}
tr.pending td:nth-child(3),tr.queued td:nth-child(3){{background:var(--hold)}}tr.failed td:nth-child(3),tr.error td:nth-child(3){{background:var(--bad)}}</style>
</head><body><h1>Watching for notes</h1>
<p class="mut">{escape(summary)}. Engine: {escape(engine)}. {'PAUSED: the token cap was reached. ' if paused else ''}Updated {escape(time.strftime('%H:%M:%S', time.localtime(now)))}. This page lists ids and states only, never note text.</p>
<table><tr><th>Note</th><th>Patient</th><th>State</th><th>Version</th><th>Left to review</th><th>Problem</th></tr>{''.join(rows)}</table>
<p class="mut">Held notes are not released until every review item is decided. An assistant for human review, not a compliance certification.</p></body></html>"""
