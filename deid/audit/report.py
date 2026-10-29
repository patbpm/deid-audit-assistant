"""Render audit records as one self-contained HTML page (no external files).

The page contains the original text and every original identifier, so it is as
sensitive as the notes themselves. Synthetic data only.
"""

from html import escape

CSS = """
:root{--bg:#fff;--fg:#1c1f23;--muted:#5b6470;--line:#d8dce1;--card:#f6f7f9;--accept:#d7efe0;--review:#fde3b5;--clue:#e5d9f6;--active:#9fc5ff;--warn:#fff4d6}
@media (prefers-color-scheme:dark){:root{--bg:#15181c;--fg:#e6e8eb;--muted:#9aa3ad;--line:#2d333a;--card:#1d2228;--accept:#1f4a33;--review:#6b4a12;--clue:#46316b;--active:#2f5d9e;--warn:#3a3014}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:1180px;padding:16px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.1rem;margin:1.6rem 0 .4rem}
.banner{background:var(--warn);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0}
.muted{color:var(--muted)}table{border-collapse:collapse;width:100%;margin:.5rem 0}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top;font-size:.9rem}
.panes{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media (max-width:800px){.panes{grid-template-columns:1fr}}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap;word-break:break-word;font:13px/1.5 ui-monospace,monospace;margin:0}
mark{border-radius:3px;padding:0 1px;color:inherit;cursor:pointer}mark.accept{background:var(--accept)}mark.review{background:var(--review)}mark.clue{background:var(--clue)}
.active{background:var(--active)!important;outline:2px solid var(--active)}
.badge{display:inline-block;border-radius:10px;padding:0 8px;font-size:.8rem;background:var(--card);border:1px solid var(--line)}
.hide{display:none}
"""

JS = """
const all=(sel)=>[...document.querySelectorAll(sel)];
document.addEventListener('click',e=>{const t=e.target.closest('[data-id]');if(!t)return;
 const on=!t.classList.contains('active');all('.active').forEach(x=>x.classList.remove('active'));
 if(on){all('[data-id="'+t.dataset.id+'"]').forEach(x=>x.classList.add('active'));}});
document.getElementById('only').addEventListener('change',e=>{
 all('tr.accept').forEach(r=>r.classList.toggle('hide',e.target.checked));
 all('section.note.clean').forEach(s=>s.classList.toggle('hide',e.target.checked));});
"""


def marked(text, ranges):
    """HTML for text with <mark> around ranges [(start, end, id, css_class, title)];
    overlapping ranges are skipped (the earlier one wins)."""
    out, cursor = [], 0
    for start, end, ident, css, title in sorted(ranges):
        if start < cursor or end > len(text):
            continue
        out.append(escape(text[cursor:start]))
        out.append(f'<mark class="{css}" data-id="{escape(ident)}" title="{escape(title)}">{escape(text[start:end])}</mark>')
        cursor = end
    out.append(escape(text[cursor:]))
    return "".join(out)


def cleaned_text(audit):
    out, cursor = [], 0
    for e in audit["entries"]:
        out.append(audit["text"][cursor:e["start"]])
        out.append(e["replacement"])
        cursor = e["end"]
    out.append(audit["text"][cursor:])
    return "".join(out)


def note_html(audit):
    entries = audit["entries"]
    covered = [(e["start"], e["end"]) for e in entries]
    left = [(e["start"], e["end"], e["id"], e["status"], f'{e["type"]} -> {e["rule"]}') for e in entries]
    for n, item in enumerate(i for i in audit["review"] if i["kind"] == "clue"):
        for a, b in item["ranges"]:
            if not any(a < ce and cs < b for cs, ce in covered):
                left.append((a, b, f'{audit["note_id"]}:clue{n}', "clue", f'{item["category"]}: {item["text"]}'))
    cleaned = cleaned_text(audit)
    right = [(e["new_start"], e["new_end"], e["id"], e["status"], e["type"]) for e in entries]
    rows = "".join(
        f'<tr class="{e["status"]}" data-id="{escape(e["id"])}"><td>{e["type"]}</td>'
        f'<td>{escape(e["original"])}</td><td>{escape(e["replacement"])}</td>'
        f'<td>{e["start"]}&ndash;{e["end"]}</td><td>{escape(e["detector"])}'
        f'{"" if e["confidence"] is None else f" ({e["confidence"]:.2f})"}'
        f'{"<br>also: " + escape(", ".join(e["also_found_by"])) if e["also_found_by"] else ""}'
        f'{"<br>verifier: " + escape(e["verifier"]["decision"]) if e.get("verifier") else ""}</td>'
        f'<td>{escape(e["rule"])}</td>'
        f'<td>{e["status"]}{"<br>" + escape("; ".join(e["checks"]["reasons"])) if e["checks"]["reasons"] else ""}</td></tr>'
        for e in entries)
    queue = "".join(
        f'<li><b>{escape(i["kind"])}</b>'
        f'{"" if not i.get("text") else " &ldquo;" + escape(i["text"]) + "&rdquo;"}: {escape("; ".join(i["reasons"]))}</li>'
        for i in audit["review"])
    risk = audit["risk"] or "not assessed"
    clean = "" if audit["review"] else " clean"
    failed = "".join(f'<div class="banner"><b>NOT CLEANED</b>: {escape(r)}. This note was not de-identified; '
                     f'its original text is shown on both sides.</div>' for r in audit.get("failed", []))
    return (
        f'<section class="note{clean}">{failed}<h2>{escape(audit["note_id"])} '
        f'<span class="badge">re-identification risk: {escape(risk)}</span> '
        f'<span class="badge">{len(entries)} changes, {len(audit["review"])} to review</span></h2>'
        f'{"<ul>" + queue + "</ul>" if queue else ""}'
        f'<div class="panes"><div><div class="muted">Original</div><pre>{marked(audit["text"], left)}</pre></div>'
        f'<div><div class="muted">De-identified</div><pre>{marked(cleaned, right)}</pre></div></div>'
        f'<table><tr><th>Type</th><th>Original</th><th>Replacement</th><th>Offsets</th>'
        f'<th>Detector (confidence)</th><th>Rule</th><th>Checks</th></tr>{rows}</table></section>')


def render(audits, summary, title="De-identification audit report"):
    counts = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in [
        ("Notes", summary["notes"]), ("Changes", summary["changes"]),
        ("Changes needing review", summary["changes_needing_review"]),
        ("Review items (all kinds)", summary["review_items"]),
        ("By type", ", ".join(f"{k} {v}" for k, v in summary["by_type"].items())),
        ("Risk levels", ", ".join(f"{k} {v}" for k, v in summary["risk_levels"].items()))])
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>'
        f'<style>{CSS}</style></head><body><h1>{escape(title)}</h1>'
        f'<div class="banner"><b>Contains original identifiers.</b> This page shows the original text next to the '
        f'cleaned text, so it is as sensitive as the notes. Synthetic data only. This is an assistant for human review, '
        f'not a compliance certification: a person should check every flagged item. Re-identification risk levels are a '
        f'model&rsquo;s judgment, not a guarantee.</div>'
        f'<table>{counts}</table>'
        f'<label><input type="checkbox" id="only"> Show only what needs review</label>'
        f'<p class="muted">Click a highlighted span or a table row to link the original, the cleaned text and the trace. '
        f'Orange = a check asked for review; green = no check objected; purple = red-team clue.</p>'
        f'{"".join(note_html(a) for a in audits)}<script>{JS}</script></body></html>')
