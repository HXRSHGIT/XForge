"""The evidence pack: what was verified, by what authority, and what was not.

A certification reviewer asks three questions about any automated check: what
did it examine, where do its numbers come from, and what did it *not* cover.
Most tools answer the first and leave the other two to a meeting.

This module produces one self-contained HTML file answering all three. The
third is the one that makes it worth reading - a pack that implies completeness
it does not have is worse than no pack, because it moves a gap from "known
open" to "believed closed". So every rule that could not be evaluated, every
number below the gating trust tier, and every accepted deviation is stated as
prominently as the passes.

Composes what exists today: the rule register with citations, the findings, the
accepted-deviation baseline, the formula provenance table, and conductor
sizing. It does not claim the isolation table, the derating report or the
FMEDA that E3 eventually needs; those appear in the coverage boundary as not
covered, by name.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from xforge import __version__
from xforge.config import Config
from xforge.model import Design
from xforge.physics import formula as formulamod
from xforge.rules.base import Finding, Severity, Status, registry

# Work this pack makes no statement about. Naming these is the point: a
# reviewer must not have to infer the boundary from what happens to be absent.
OUT_OF_SCOPE = [
    (
        "Insulation coordination",
        "Creepage and clearance are not computed. XF008 checks only that no "
        "component bridges a declared barrier. IEC 60664-1 has not been "
        "obtained, and secondary sources disagree by up to 25%.",
    ),
    (
        "Thermal performance",
        "No thermal simulation. Conductor sizing assumes the stated ambient "
        "and temperature rise; it does not verify that either is achieved.",
    ),
    (
        "EMC and immunity",
        "Not modelled. No statement about emissions, surge, ESD or transients.",
    ),
    (
        "Board layout",
        "No physical verification. Copper geometry, spacing, stackup "
        "realisation and DRC are the PCB tool's responsibility, not this one's.",
    ),
    (
        "Firmware behaviour",
        "Communication artefacts are generated from a declared spec; the pack "
        "does not establish that firmware implements the safety logic.",
    ),
    (
        "Component qualification",
        "No statement about supplier certificates, AEC-Q grading, derating "
        "policy or end-of-life status.",
    ),
    (
        "Requirement traceability",
        "No requirement-to-test matrix. Nothing here links a finding to a "
        "product requirement or a test case.",
    ),
]


@dataclass
class Coverage:
    """One line of the boundary: a subject and how far the pack goes on it."""

    subject: str
    state: str  # verified | partial | not covered
    detail: str


@dataclass
class Pack:
    """Everything the report needs, assembled before any HTML is written."""

    design: Design
    findings: list[Finding]
    config: Config
    netlist: Path
    digest: str = ""
    baseline: object | None = None  # xforge.baseline.Baseline
    power: object | None = None  # xforge.power.PowerReport
    generated: str = ""
    gating: set[str] = field(default_factory=set)

    @property
    def violations(self) -> list[Finding]:
        return [f for f in self.findings if f.status is Status.VIOLATION]

    @property
    def passed(self) -> list[Finding]:
        return [f for f in self.findings if f.status is Status.PASS]

    @property
    def blocked(self) -> list[Finding]:
        return [f for f in self.findings if f.status is Status.BLOCKED]

    @property
    def unaccepted(self) -> list[Finding]:
        """Gating violations this design has not signed off."""
        gating = [f for f in self.violations if f.rule_id in self.gating]
        gating = [f for f in gating if f.severity >= Severity.ERROR]
        if self.baseline is None:
            return gating
        return [f for f in gating if not self.baseline.accepts(f)]

    @property
    def verdict(self) -> tuple[str, str]:
        """(state, sentence) for the headline."""
        if self.unaccepted:
            return (
                "FAIL",
                f"{len(self.unaccepted)} finding(s) from gating rules are "
                "neither fixed nor accepted.",
            )
        if not self.gating:
            return (
                "ADVISORY",
                "No rule is gating on this project, so this pack reports "
                "findings but establishes no pass criterion.",
            )
        accepted = len(self.baseline) if self.baseline else 0
        tail = f" {accepted} known deviation(s) are accepted and listed below." if accepted else ""
        return (
            "PASS",
            f"No unaccepted findings from gating rules {sorted(self.gating)}."
            + tail,
        )

    def coverage(self) -> list[Coverage]:
        """The boundary, derived where possible rather than asserted."""
        out: list[Coverage] = []

        reg = registry()
        fired = {f.rule_id for f in self.violations}
        passed = {f.rule_id for f in self.passed}
        for rid in sorted(reg):
            rule = reg[rid]
            blocked = [f for f in self.blocked if f.rule_id == rid]
            if blocked:
                out.append(
                    Coverage(
                        f"{rid} {rule.title}",
                        "not covered",
                        "; ".join(f.summary for f in blocked),
                    )
                )
            elif rid in fired:
                n = sum(1 for f in self.violations if f.rule_id == rid)
                out.append(
                    Coverage(f"{rid} {rule.title}", "verified", f"{n} finding(s)")
                )
            elif rid in passed:
                out.append(
                    Coverage(f"{rid} {rule.title}", "verified", "checked, no finding")
                )
            else:
                out.append(
                    Coverage(
                        f"{rid} {rule.title}",
                        "partial",
                        "ran without producing a finding; the design may "
                        "contain nothing this rule applies to",
                    )
                )

        # Numbers the engine holds but is not allowed to fail a build on.
        weak = [f for f in formulamod.registry().values() if not f.tier.may_gate]
        if weak:
            out.append(
                Coverage(
                    "Calculations below gating trust",
                    "partial",
                    f"{len(weak)} formula(e) are tier C or D and may inform a "
                    "review but may not gate: "
                    + ", ".join(sorted(f.id for f in weak)),
                )
            )

        for subject, detail in OUT_OF_SCOPE:
            out.append(Coverage(subject, "not covered", detail))
        return out


def digest_of(path: Path) -> str:
    """SHA-256 of the netlist, so the pack names exactly what it read."""
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def assemble(
    design: Design,
    findings: Sequence[Finding],
    config: Config,
    netlist: Path,
    baseline=None,
    power=None,
) -> Pack:
    gating = set(config.gating_rules)
    return Pack(
        design=design,
        findings=list(findings),
        config=config,
        netlist=Path(netlist),
        digest=digest_of(netlist),
        baseline=baseline,
        power=power,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        gating=gating,
    )


# ── rendering ─────────────────────────────────────────────────────────

_EXTRA_CSS = """
.verdict{border:1px solid var(--line);border-left-width:6px;border-radius:10px;
padding:16px 20px;margin:20px 0;background:var(--panel)}
.verdict.PASS{border-left-color:var(--accent)}
.verdict.FAIL{border-left-color:var(--err)}
.verdict.ADVISORY{border-left-color:var(--adv)}
.verdict .s{font-size:22px;font-weight:700;letter-spacing:.04em}
.verdict.PASS .s{color:var(--accent)}
.verdict.FAIL .s{color:var(--err)}
.verdict.ADVISORY .s{color:var(--adv)}
.state{font-size:11px;font-weight:700;letter-spacing:.06em;padding:2px 7px;
border-radius:4px;color:#fff;white-space:nowrap}
.state.verified{background:var(--accent)}
.state.partial{background:var(--warn)}
.state.notcovered{background:var(--err)}
.tier{font:12px Consolas,ui-monospace,monospace;font-weight:700;
padding:1px 6px;border-radius:4px;background:var(--code)}
.tier.A,.tier.B{color:var(--accent)}
.tier.C,.tier.D{color:var(--warn)}
.note{background:var(--code);border-left:3px solid var(--muted);
padding:10px 14px;margin:12px 0;font-size:14px}
.kv{font:13px Consolas,ui-monospace,monospace}
.wrap{word-break:break-all}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:13px}
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<div class="none">nothing to report</div>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _identity(p: Pack) -> str:
    rows = [
        ["Design", _e(p.design.name)],
        ["Company", _e(p.design.company or "-")],
        ["Revision", _e(p.design.revision or "-")],
        ["Source schematic", f'<span class="wrap">{_e(p.design.source or "-")}</span>'],
        ["Authoring tool", _e(p.design.tool or "-")],
        ["Netlist", f'<span class="wrap">{_e(p.netlist.name)}</span>'],
        ["Netlist SHA-256", f'<span class="kv wrap">{_e(p.digest)}</span>'],
        ["Components", _e(len(p.design.components))],
        ["Nets", _e(len(p.design.nets))],
        ["Sheets", _e(len(p.design.sheets))],
        ["Checked by", f"XForge {_e(__version__)}"],
        ["Generated", _e(p.generated)],
    ]
    return _table(["Field", "Value"], rows)


def _rule_register(p: Pack) -> str:
    reg = registry()
    counts: dict[str, int] = {}
    for f in p.violations:
        counts[f.rule_id] = counts.get(f.rule_id, 0) + 1
    rows = []
    for rid in sorted(reg):
        r = reg[rid]
        if rid in p.gating:
            status = '<span class="state verified">GATING</span>'
        elif r.blocking:
            status = '<span class="state partial">capable</span>'
        else:
            status = "advisory"
        rows.append(
            [
                f"<strong>{_e(rid)}</strong>",
                _e(r.title),
                _e(r.default_severity.label),
                status,
                _e(counts.get(rid, 0)),
                _e(r.source),
            ]
        )
    return _table(
        ["Rule", "Checks", "Severity", "Enforcement", "Findings", "Authority"], rows
    )


def _findings(p: Pack) -> str:
    out = []
    for f in sorted(p.findings, key=lambda x: x.sort_key()):
        cls = f.severity.name if f.status is Status.VIOLATION else f.status.name
        accepted = (
            ' <span class="state partial">ACCEPTED</span>'
            if p.baseline is not None and p.baseline.accepts(f)
            else ""
        )
        src = registry().get(f.rule_id)
        out.append(
            f'<div class="f {cls}">'
            f'<h3><span class="pill {cls}">{_e(f.severity.label if f.status is Status.VIOLATION else f.status.name)}</span>'
            f"{_e(f.rule_id)} &mdash; {_e(f.summary)}{accepted}</h3>"
            + (f'<div class="meta">key: <code>{_e(f.key)}</code></div>' if f.key else "")
            + (
                f'<div class="meta">authority: {_e(src.source)}</div>'
                if src
                else ""
            )
            + (
                '<div class="subj">'
                + "".join(f"<div>{_e(s)}</div>" for s in f.subjects)
                + "</div>"
                if f.subjects
                else ""
            )
            + "</div>"
        )
    return "".join(out) or '<div class="none">no findings</div>'


def _deviations(p: Pack) -> str:
    if p.baseline is None or not len(p.baseline):
        return (
            '<div class="none">No accepted deviations. Every finding in this '
            "pack is either open or does not gate.</div>"
        )
    note = (
        f'<div class="note"><strong>Stated reason for acceptance.</strong><br>'
        f"{_e(p.baseline.note)}</div>"
        if p.baseline.note
        else ""
    )
    rows = [
        [f"<strong>{_e(e.rule)}</strong>", f"<code>{_e(e.key)}</code>",
         _e(e.severity or "-"), _e(e.summary or "-")]
        for e in p.baseline.entries
    ]
    meta = (
        f'<p class="sub">Recorded {_e(p.baseline.created)} from '
        f"<span class='kv'>{_e(p.baseline.source)}</span>.</p>"
    )
    return (
        "<p>These findings are <strong>known and open</strong>. They are "
        "accepted for now so that verification can gate on new defects; they "
        "are not resolved, and nothing in this pack should be read as "
        "clearing them.</p>"
        + meta
        + note
        + _table(["Rule", "Subject", "Severity", "Finding"], rows)
    )


def _formulas(p: Pack) -> str:
    rows = []
    for f in sorted(formulamod.registry().values(), key=lambda x: x.id):
        may = (
            '<span class="state verified">may gate</span>'
            if f.tier.may_gate
            else '<span class="state partial">advisory only</span>'
        )
        rows.append(
            [
                f"<code>{_e(f.id)}</code>",
                _e(f.name),
                f"<code>{_e(f.equation)}</code>",
                f'<span class="tier {_e(f.tier.value)}">{_e(f.tier.value)}</span> '
                f"{_e(f.tier.label)}",
                may,
                _e(f.source) + (f"<br><em>{_e(f.validity)}</em>" if f.validity else ""),
            ]
        )
    return (
        "<p>Every number this engine computes, the expression it computes it "
        "with, and where that expression comes from. Tier A and B may fail a "
        "build; tier C and D may not, and that restriction is enforced in "
        "code rather than by convention.</p>" + _table(
            ["ID", "Quantity", "Expression", "Trust", "Enforcement", "Source"], rows
        )
    )


def _power(p: Pack) -> str:
    if p.power is None or not getattr(p.power, "nets", None):
        return (
            '<div class="none">No currents declared, so no conductor '
            "requirement was computed. A netlist cannot state what a net "
            "carries; declare currents in the project config to populate "
            "this section.</div>"
        )
    rows = []
    for n in p.power.nets:
        rows.append(
            [
                f"<code>{_e(n.net)}</code>",
                _e(f"{n.continuous_a:g}")
                + (f" / {n.peak_a:g} pk" if n.peak_a else ""),
                _e(f"{n.outer.width_mm:.2f}"),
                _e(f"{n.inner.width_mm:.2f}"),
                _e(n.netclass),
                (
                    f'<span class="state partial">busbar '
                    f"{n.busbar_mm2:.1f} mm&sup2;</span>"
                    if n.exceeds_trace_limit
                    else "trace"
                ),
                _e(n.note),
            ]
        )
    stack = p.power.stackup
    intro = (
        f'<p class="sub">{_e(stack.outer_copper_oz)} oz outer, {_e(stack.inner_copper_oz)} oz '
        f"inner, {_e(stack.max_temp_rise_c)} &deg;C rise at {_e(stack.ambient_c)} &deg;C "
        f"ambient. Widths are the IPC-2221 "
        "requirement (tier B), not a layout result.</p>"
    )
    unmatched = ""
    if p.power.unmatched_specs:
        unmatched = (
            '<div class="note"><strong>Declared but not found in this '
            "netlist:</strong> "
            + ", ".join(
                _e(s.role or ", ".join(s.nets) or "unnamed")
                for s in p.power.unmatched_specs
            )
            + ". A current declared against a net that does not exist verifies "
            "nothing.</div>"
        )
    return (
        intro
        + _table(
            [
                "Net",
                "Current (A)",
                "Outer (mm)",
                "Inner (mm)",
                "Net class",
                "Conductor",
                "Basis",
            ],
            rows,
        )
        + unmatched
    )


def _coverage(p: Pack) -> str:
    rows = []
    for c in p.coverage():
        cls = c.state.replace(" ", "")
        rows.append(
            [
                _e(c.subject),
                f'<span class="state {cls}">{_e(c.state)}</span>',
                _e(c.detail),
            ]
        )
    return (
        "<p>What this pack does and does not establish. A subject marked "
        "<em>not covered</em> has not been examined at all &mdash; it is not a "
        "pass. A subject marked <em>partial</em> was examined within stated "
        "limits.</p>" + _table(["Subject", "State", "Basis"], rows)
    )


_SECTIONS = [
    ("Design under verification", _identity),
    ("Rule register and authority", _rule_register),
    ("Accepted deviations", _deviations),
    ("Findings", _findings),
    ("Calculation provenance", _formulas),
    ("Conductor requirements", _power),
    ("Coverage boundary", _coverage),
]


def to_html(pack: Pack, path: Path) -> None:
    """Write the pack as one self-contained file."""
    from xforge.report import _CSS

    state, sentence = pack.verdict
    counts = {
        s: sum(1 for f in pack.violations if f.severity is s) for s in Severity
    }
    cards = "".join(
        f'<div class="card"><div class="n">{n}</div><div class="l">{lbl}</div></div>'
        for lbl, n in [
            ("errors", counts[Severity.ERROR]),
            ("warnings", counts[Severity.WARNING]),
            ("advisory", counts[Severity.ADVISORY]),
            ("passed", len(pack.passed)),
            ("not evaluable", len(pack.blocked)),
            ("accepted", len(pack.baseline) if pack.baseline else 0),
        ]
    )

    toc = "".join(
        f'<li><a href="#s{i}">{_e(title)}</a></li>'
        for i, (title, _) in enumerate(_SECTIONS)
    )
    body = "".join(
        f'<h2 id="s{i}">{_e(title)}</h2>{fn(pack)}'
        for i, (title, fn) in enumerate(_SECTIONS)
    )

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verification evidence &mdash; {_e(pack.design.name)}</title>
<style>{_CSS}{_EXTRA_CSS}</style></head>
<body><main>
<h1>Verification evidence</h1>
<p class="sub">{_e(pack.design.name)}
{(" &middot; rev " + _e(pack.design.revision)) if pack.design.revision else ""}
&middot; {_e(pack.generated)}</p>

<div class="verdict {state}"><div class="s">{state}</div><p>{_e(sentence)}</p></div>

<div class="cards">{cards}</div>

<div class="note">This pack is generated from the netlist named below and from
the rules registered in XForge {_e(__version__)}. It is evidence of what was
checked automatically. It is not a certificate, and the
<a href="#s{len(_SECTIONS) - 1}">coverage boundary</a> lists what it does not
establish.</div>

<ol>{toc}</ol>
{body}

<footer>XForge {_e(__version__)} &middot; generated {_e(pack.generated)} &middot;
netlist SHA-256 <span class="kv wrap">{_e(pack.digest)}</span></footer>
</main></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
