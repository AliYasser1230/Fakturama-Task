from __future__ import annotations

import re
from datetime import date, datetime
from html import escape
from typing import Any

OUTCOMES = {
    "completed": ("Completed", "good", "All stages passed: the Order and the linked Invoice are saved in Fakturama."),
    "needs review": ("Needs review", "bad", "The run stopped for a person. Nothing after the stopped stage was done."),
    "partial": ("Partial", "warn", "The run ended early: the remaining stages are not built yet."),
}

STYLE = """
* { box-sizing: border-box; }
body { margin: 0; background: #f4f6f9; color: #1b2430; font: 15px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 32px 24px 48px; }
h1 { font-size: 26px; margin: 0; }
h2 { font-size: 18px; margin: 32px 0 12px; }
.muted { color: #56657a; }
.card { background: #fff; border: 1px solid #dde3ea; border-radius: 10px; padding: 20px 24px; margin-bottom: 12px; }
.head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.badge { font-weight: 600; font-size: 14px; padding: 4px 14px; border-radius: 999px; }
.good { color: #146c43; background: #e3f4ea; }
.bad { color: #b42318; background: #fdecea; }
.warn { color: #9a4a00; background: #fff1de; }
.facts { display: grid; grid-template-columns: 190px 1fr; gap: 6px 16px; margin: 18px 0 0; }
.facts dt { color: #56657a; }
.facts dd { margin: 0; }
.alert { border-left: 5px solid #b42318; }
.alert h2 { margin: 0 0 8px; color: #b42318; }
details.stage { padding: 0; }
details.stage > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 12px; padding: 14px 20px; }
details.stage > summary::-webkit-details-marker { display: none; }
details.stage[open] > summary { border-bottom: 1px solid #dde3ea; }
.mark { width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex: none; }
.title { font-weight: 600; flex: 1; }
.body { padding: 12px 20px 16px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: #56657a; font-weight: 600; border-bottom: 2px solid #dde3ea; padding: 6px 8px; }
td { border-bottom: 1px solid #eef1f5; padding: 6px 8px; vertical-align: top; overflow-wrap: anywhere; }
td.ok { width: 34px; text-align: center; font-weight: 700; }
tr.failed td { background: #fdecea; }
ul.notes { margin: 12px 0 0; padding-left: 20px; color: #3a4a5e; }
.notbuilt { color: #56657a; }
.shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.shots figure { margin: 0; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; overflow: hidden; }
.shots img { display: block; width: 100%; aspect-ratio: 16 / 10; object-fit: cover; object-position: top; }
.shots figcaption { padding: 8px 12px; font-size: 13px; }
pre { background: #1b2430; color: #e8edf3; padding: 14px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
@media print { body { background: #fff; } details.stage { break-inside: avoid; } }
"""


def render_html(report: dict[str, Any], title: str, next_step: str | None = None) -> str:
    label, tone, meaning = OUTCOMES.get(report["outcome"], (report["outcome"], "warn", ""))
    order = report["order"]
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><main>",
        '<section class="card">',
        f'<div class="head"><h1>Order {escape(order["external_reference"])}</h1>'
        f'<span class="badge {tone}">{escape(label)}</span></div>',
        f'<p class="muted">{escape(meaning)}</p>',
        '<dl class="facts">',
        *(f"<dt>{escape(name)}</dt><dd>{value}</dd>" for name, value in facts(report)),
        "</dl></section>",
    ]
    if report.get("stopped"):
        parts += stopped_box(report["stopped"], next_step)
    parts += ["<h2>Stages</h2>",
              '<p class="muted">Every check compares the value the order expects with the value read back from '
              "Fakturama. Lists are read with OCR, so lookalike characters (0 and O, 1 and I, $ and S) and text "
              "cut off with ... are accepted there; any other difference fails the check.</p>"]
    parts += [stage_card(stage) for stage in report["stages"]]
    parts += [f'<div class="card notbuilt">{escape(name)}: not built yet</div>' for name in report.get("not_built", [])]
    if report.get("screenshots"):
        parts += ["<h2>Screenshots</h2>", '<div class="shots">', *map(screenshot, report["screenshots"]), "</div>"]
    if report.get("trace"):
        parts += ["<h2>Error details</h2>", f"<pre>{escape(report['trace'].rstrip())}</pre>"]
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def facts(report: dict[str, Any]) -> list[tuple[str, str]]:
    order = report["order"]
    totals = order["totals"]
    payment = order["payment"]
    paid = f" on {nice_date(payment['date'])}" if payment.get("date") else ""
    rows = [
        ("Customer", escape(order["company"])),
        ("Order date", escape(nice_date(order["order_date"]))),
        ("Items", "<br>".join(f"{escape(i['quantity'])} &times; {escape(i['sku'])} at {escape(i['unit_net_price'])}"
                              for i in order["items"])),
        ("Totals", f"Net {escape(totals['net'])} &middot; VAT {escape(totals['vat'])} &middot; "
                   f"<b>Gross {escape(totals['gross'])} {escape(order['currency'])}</b>"),
        ("Payment", escape(f"{payment['method']}, {payment['status']}{paid}")),
    ]
    documents = report.get("documents") or {}
    saved = [f"{kind.capitalize()} {number}" for kind, number in documents.items() if number]
    if saved:
        rows.append(("Saved in Fakturama", f"<b>{escape(' · '.join(saved))}</b>"))
    rows.append(("Order data from", escape(source_text(report.get("extraction") or {}))))
    checks = [c for stage in report["stages"] for c in stage["checks"]]
    passed = sum(1 for c in checks if c["ok"])
    rows.append(("Checks", escape(f"{passed} of {len(checks)} passed")))
    rows.append(("Run", escape(run_time(report["started"], report["finished"]))))
    if report.get("open_editors"):
        rows.append(("Left open in Fakturama", escape(", ".join(report["open_editors"]))))
    warnings = (report.get("extraction") or {}).get("issues") or []
    if warnings:
        rows.append(("Extraction warnings", "<br>".join(escape(f"{w['field']}: {w['message']}") for w in warnings)))
    return rows


def stopped_box(stopped: dict[str, Any], next_step: str | None) -> list[str]:
    parts = ['<section class="card alert">',
             f"<h2>Stopped at stage {escape(stopped['stage'])} &middot; {escape(stopped['title'])} "
             f"({escape(stopped['kind'])})</h2>",
             f"<p>{escape(stopped['reason'] or '')}</p>"]
    if next_step:
        parts.append(f"<p><b>What to do next:</b> {escape(next_step)}</p>")
    parts.append("</section>")
    return parts


def stage_card(stage: dict[str, Any]) -> str:
    checks = stage["checks"]
    failed = [c for c in checks if not c["ok"]]
    passed = stage["status"] == "passed"
    tone = "good" if passed else "bad"
    if passed:
        count = f"{len(checks)} checks passed"
    elif failed:
        count = f"{len(failed)} of {len(checks)} checks failed"
    else:
        count = stage["status"]
    rows = "".join(
        f'<tr class="{"" if c["ok"] else "failed"}"><td>{escape(c["what"])}</td><td>{escape(c["expected"])}</td>'
        f'<td>{escape(c["shown"])}</td><td class="ok {"good" if c["ok"] else "bad"}">'
        f'{"&#10003;" if c["ok"] else "&#10007;"}</td></tr>'
        for c in checks)
    table = (f"<table><thead><tr><th>Check</th><th>Expected</th><th>Fakturama shows</th><th></th></tr></thead>"
             f"<tbody>{rows}</tbody></table>") if checks else ""
    notes = "".join(f"<li>{escape(n)}</li>" for n in stage["notes"])
    return (f'<details class="card stage"{"" if passed else " open"}><summary>'
            f'<span class="mark {tone}">{"&#10003;" if passed else "&#10007;"}</span>'
            f'<span class="title">Stage {escape(stage["stage"])} &middot; {escape(stage["title"])}</span>'
            f'<span class="badge {tone}">{escape(count)}</span></summary><div class="body">'
            f'{table}'
            f'{f"<ul class=notes>{notes}</ul>" if notes else ""}</div></details>')


def screenshot(shot: dict[str, str]) -> str:
    caption = escape(shot_label(shot["label"]))
    if "error" in shot:
        return f'<figure><figcaption>{caption}: not taken ({escape(shot["error"])})</figcaption></figure>'
    src = escape(shot["file"], quote=True)
    return (f'<figure><a href="{src}" target="_blank"><img src="{src}" alt="{caption}" loading="lazy"></a>'
            f"<figcaption>{caption}</figcaption></figure>")


def shot_label(label: str) -> str:
    if label == "start":
        return "Before the run"
    match = re.fullmatch(r"stage(\d+)_(.+)", label)
    if match:
        return f"After stage {match.group(1)} ({match.group(2).replace('_', ' ')})"
    return label.replace("_", " ")


def source_text(extraction: dict[str, Any]) -> str:
    source = extraction.get("source") or "unknown"
    if source.startswith("claude:"):
        text = f"Claude ({source.split(':', 1)[1]}) read the image"
    elif source == "raw-json":
        text = "Saved transcription (--raw)"
    else:
        return source
    if extraction.get("ocr_engine"):
        text += f", every value cross-checked with {extraction['ocr_engine'].capitalize()} OCR"
    return text


def nice_date(value: str) -> str:
    day = date.fromisoformat(value)
    return f"{day:%b} {day.day}, {day:%Y}"


def run_time(started: str, finished: str) -> str:
    start, end = datetime.fromisoformat(started), datetime.fromisoformat(finished)
    seconds = int((end - start).total_seconds())
    length = f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"
    return f"{nice_date(start.date().isoformat())}, {start:%H:%M:%S} to {end:%H:%M:%S} ({length})"
