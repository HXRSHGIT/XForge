"""Findings rendered for humans (single-file HTML) and machines (JSON)."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from xforge.model import Design
from xforge.rules.base import Finding, Severity, registry

_CSS = """
:root{--bg:#f6f7f5;--panel:#fff;--ink:#1b2126;--muted:#5a656a;--line:#d4dad6;
--accent:#0a7a64;--code:#eef1ee;--head:#e7ece9;
--err:#b3261e;--warn:#9a6700;--adv:#0a5fa8;--info:#5a656a}
@media (prefers-color-scheme:dark){:root{--bg:#0f1314;--panel:#161b1d;--ink:#e4eae8;
--muted:#98a4a6;--line:#2c3437;--accent:#3ccba9;--code:#1d2326;--head:#1f272a;
--err:#ff6b5e;--warn:#e3b341;--adv:#6cb6ff;--info:#98a4a6}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);padding:0 16px;
font:15.5px/1.6 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 0 80px}
h1{font-size:28px;margin:0 0 6px}h2{font-size:21px;margin:40px 0 12px;
padding-top:14px;border-top:2px solid var(--line)}
.sub{color:var(--muted);margin:0 0 24px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:10px 16px;min-width:104px}
.card .n{font-size:24px;font-weight:600;line-height:1.2}
.card .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
table{border-collapse:collapse;font-size:14px;background:var(--panel);width:100%}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--head);font-weight:600}
.tbl{overflow-x:auto;margin:12px 0}
.f{background:var(--panel);border:1px solid var(--line);border-left-width:4px;
border-radius:8px;padding:12px 16px;margin:10px 0}
.f.ERROR{border-left-color:var(--err)}.f.WARNING{border-left-color:var(--warn)}
.f.ADVISORY{border-left-color:var(--adv)}.f.INFO{border-left-color:var(--info)}
.f h3{margin:0 0 4px;font-size:16px}
.pill{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;
padding:2px 7px;border-radius:4px;margin-right:8px;vertical-align:2px;color:#fff}
.pill.ERROR{background:var(--err)}.pill.WARNING{background:var(--warn)}
.pill.ADVISORY{background:var(--adv)}.pill.INFO{background:var(--info)}
.meta{font-size:12px;color:var(--muted);margin-top:6px}
.subj{font:12.5px/1.6 Consolas,ui-monospace,monospace;background:var(--code);
border-radius:6px;padding:8px 10px;margin-top:8px}
.subj div{white-space:pre-wrap}
code{font:13px Consolas,ui-monospace,monospace;background:var(--code);
padding:1px 5px;border-radius:4px}
.none{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:24px;text-align:center;color:var(--muted)}
"""


def to_json(design: Design, findings: Sequence[Finding], path: Path) -> None:
    """Machine-readable findings, for CI and for diffing between runs."""
    payload = {
        "schema": "xforge.findings/1",
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "design": {
            "name": design.name,
            "source": design.source,
            "tool": design.tool,
            "revision": design.revision,
            "company": design.company,
            "census": design.census(),
        },
        "findings": [
            {
                "rule": f.rule_id,
                "severity": f.severity.label,
                "summary": f.summary,
                "detail": f.detail,
                "subjects": f.subjects,
                "confidence": f.confidence,
            }
            for f in findings
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def to_html(design: Design, findings: Sequence[Finding], path: Path) -> None:
    """Single-file HTML report; opens identically anywhere, no assets."""
    e = html.escape
    rules = registry()
    counts = {s: sum(1 for f in findings if f.severity is s) for s in Severity}
    census = design.census()

    cards = "".join(
        f'<div class="card"><div class="n">{counts[s]}</div>'
        f'<div class="l">{s.label}</div></div>'
        for s in (Severity.ERROR, Severity.WARNING, Severity.ADVISORY, Severity.INFO)
    ) + "".join(
        f'<div class="card"><div class="n">{v}</div><div class="l">{k.replace("_", " ")}</div></div>'
        for k, v in (
            ("components", census["components"]),
            ("nets", census["nets"]),
            ("pins", census["pins"]),
        )
    )

    body = [
        f"<h1>{e(design.name)}</h1>",
        f'<p class="sub">{e(design.company or "")} &middot; rev {e(design.revision or "?")} '
        f'&middot; {e(design.tool or "")} &middot; '
        f'checked {datetime.now().strftime("%d %b %Y %H:%M")}</p>',
        f'<div class="cards">{cards}</div>',
    ]

    if not findings:
        body.append('<div class="none">No findings. Every enabled rule passed.</div>')
    for sev in (Severity.ERROR, Severity.WARNING, Severity.ADVISORY, Severity.INFO):
        group = [f for f in findings if f.severity is sev]
        if not group:
            continue
        body.append(f"<h2>{sev.label} &mdash; {len(group)}</h2>")
        for f in group:
            rule = rules.get(f.rule_id)
            subj = ""
            if f.subjects:
                subj = '<div class="subj">' + "".join(
                    f"<div>{e(s)}</div>" for s in f.subjects
                ) + "</div>"
            body.append(
                f'<div class="f {sev.name}">'
                f'<h3><span class="pill {sev.name}">{f.rule_id}</span>{e(f.summary)}</h3>'
                f"<div>{e(f.detail)}</div>{subj}"
                f'<div class="meta">{e(rule.title if rule else "")} &middot; '
                f'source: {e(rule.source if rule else "?")} &middot; '
                f"confidence: {e(f.confidence)}</div></div>"
            )

    body.append("<h2>Rules run</h2><div class='tbl'><table>")
    body.append("<tr><th>ID</th><th>Rule</th><th>Default</th><th>Source</th></tr>")
    for rid, r in sorted(rules.items()):
        body.append(
            f"<tr><td><code>{e(rid)}</code></td><td>{e(r.title)}</td>"
            f"<td>{e(r.default_severity.label)}</td><td>{e(r.source)}</td></tr>"
        )
    body.append("</table></div>")

    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>xforge check &mdash; {e(design.name)}</title>"
        f"<style>{_CSS}</style></head><body><main>"
        + "".join(body)
        + "</main></body></html>"
    )
    path.write_text(page, encoding="utf-8")
