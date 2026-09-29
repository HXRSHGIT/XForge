"""`xforge` command line.

Deliberately dependency-free (argparse, not click/typer) so the checker runs
on a bare Python install and on a CI runner we do not control.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from xforge import __version__
from xforge.config import Config
from xforge.model import Design
from xforge import readers
from xforge.rules import Severity, Status, registry, run

EXIT_OK = 0
EXIT_FINDINGS = 1  # gating rules fired
EXIT_ERROR = 2  # could not run


def _read(path: Path) -> Design:
    return readers.read(path)


def _cmd_inspect(args) -> int:
    design = _read(args.netlist)
    print(f"{design.name}")
    print(f"  company  : {design.company or '-'}")
    print(f"  revision : {design.revision or '-'}")
    print(f"  tool     : {design.tool or '-'}")
    print(f"  source   : {design.source or '-'}")
    for key, val in design.census().items():
        print(f"  {key:16s}: {val}")
    return EXIT_OK


def _cmd_rules(args) -> int:
    for rid, rule in sorted(registry().items()):
        gate = " [gating-capable]" if rule.blocking else ""
        print(f"{rid}  {rule.default_severity.label:8s}  {rule.title}{gate}")
        print(f"        source: {rule.source}")
    return EXIT_OK


def _cmd_check(args) -> int:
    design = _read(args.netlist)
    config = Config.load(args.config)
    findings = run(design, config)

    violations = [f for f in findings if f.status is Status.VIOLATION]
    blocked = [f for f in findings if f.status is Status.BLOCKED]
    passed = [f for f in findings if f.status is Status.PASS]
    counts = {s: sum(1 for f in violations if f.severity is s) for s in Severity}

    _MARK = {Status.VIOLATION: "", Status.BLOCKED: "?", Status.PASS: "+"}
    for f in findings:
        if args.quiet and f.status is not Status.VIOLATION:
            continue
        if args.quiet and f.severity < Severity.WARNING:
            continue
        print(f"{_MARK[f.status]:1s}[{f.severity.label:8s}] {f.rule_id}  {f.summary}")
        if args.verbose:
            # A subject may be a multi-line formula explanation; indent every
            # line of it, not just the first.
            for s in f.subjects:
                for line in str(s).splitlines() or [""]:
                    print(f"                {line}")

    print()
    print(
        f"{design.name}: {counts[Severity.ERROR]} error, "
        f"{counts[Severity.WARNING]} warning, "
        f"{counts[Severity.ADVISORY]} advisory, {counts[Severity.INFO]} info"
    )
    if passed or blocked:
        print(f"  {len(passed)} check(s) passed, {len(blocked)} not evaluable")

    if args.html:
        from xforge.report import to_html

        to_html(design, findings, args.html)
        print(f"report : {args.html}")
    if args.json:
        from xforge.report import to_json

        to_json(design, findings, args.json)
        print(f"json   : {args.json}")

    # Advisory by default: only rules the project has explicitly opted into
    # gating can fail the run. See docs/enforcement.md.
    gating = config.gating_rules
    if args.gate:
        gating = gating | {r for r, v in registry().items() if v.blocking}
    fired = [
        f
        for f in findings
        if f.rule_id in gating
        and f.status is Status.VIOLATION
        and f.severity >= Severity.ERROR
    ]
    if not gating:
        return EXIT_OK

    # A baseline holds the violations already known and accepted, so switching
    # gating on does not fail the build over a defect that was there yesterday.
    baseline = None
    if args.baseline:
        from xforge.baseline import Baseline, BaselineError

        try:
            baseline = Baseline.load(args.baseline)
        except BaselineError as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            return EXIT_ERROR

        accepted = [f for f in fired if baseline.accepts(f)]
        fired = [f for f in fired if not baseline.accepts(f)]
        if accepted:
            print(
                f"\nbaseline: {len(accepted)} known violation(s) accepted "
                f"from {args.baseline.name}"
            )
        stale = baseline.stale(findings)
        if stale:
            # Fixed defects, or a rule that went quiet. Either way the file is
            # now broader than the truth.
            print(f"  {len(stale)} baseline entr(ies) no longer fire:")
            for e in stale:
                print(f"    {e.rule}  {e.key}")
            print("  run `xforge baseline ... --prune` to tighten it")

    if fired:
        print(f"\nFAIL: {len(fired)} finding(s) from gating rules {sorted(gating)}")
        for f in fired:
            print(f"  {f.rule_id}  {f.key or f.summary}")
        if baseline is not None:
            print(
                "\nIf these are accepted rather than fixed, add them with "
                "`xforge baseline`."
            )
        return EXIT_FINDINGS

    print(f"\nPASS: no unaccepted findings from gating rules {sorted(gating)}")
    return EXIT_OK


def _cmd_baseline(args) -> int:
    """Record the violations a project accepts for now."""
    from xforge.baseline import Baseline, BaselineError

    design = _read(args.netlist)
    config = Config.load(args.config)
    findings = run(design, config)

    if args.prune:
        try:
            current = Baseline.load(args.out)
        except BaselineError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return EXIT_ERROR
        stale = current.stale(findings)
        baseline = current.pruned(findings)
        for e in stale:
            print(f"  dropped  {e.rule}  {e.key}")
        print(f"{len(stale)} stale entr(ies) removed, {len(baseline)} remain")
    else:
        # Only rules that can gate, unless asked otherwise: see
        # Baseline.from_findings for why a wider file is a liability.
        rules = None
        if not args.all:
            rules = config.gating_rules or {
                r for r, v in registry().items() if v.blocking
            }
        baseline = Baseline.from_findings(
            findings, source=args.netlist.as_posix(), note=args.note, rules=rules
        )
        by_rule: dict[str, int] = {}
        for e in baseline.entries:
            by_rule[e.rule] = by_rule.get(e.rule, 0) + 1
        for rule in sorted(by_rule):
            print(f"  {rule}  {by_rule[rule]}")
        print(f"{len(baseline)} violation(s) accepted")

    baseline.save(args.out)
    print(f"baseline: {args.out}")
    return EXIT_OK


def _finding_json(f) -> dict:
    """A finding as the diff reports it.

    `key` is what makes this trackable across revisions - a net, a refdes, a
    sheet - so a downstream tool can follow one defect through a series of
    revisions without matching on prose.
    """
    return {
        "rule": f.rule_id,
        "severity": f.severity.label,
        "key": f.key,
        "summary": f.summary,
    }


def _cmd_diff(args) -> int:
    """Compare two revisions: what changed electrically, and did it help."""
    from xforge import diff as diffmod
    from xforge.rules import run

    old = _read(args.old)
    new = _read(args.new)
    config = Config.load(args.config)
    result = diffmod.compare(old, new, run(old, config), run(new, config))

    print(f"{args.old.name} -> {args.new.name}")
    print(f"  {result.verdict}")
    print()

    c = result.counts()
    print(
        f"  components  +{c['components_added']} -{c['components_removed']} "
        f"~{c['components_changed']}"
    )
    print(
        f"  nets        +{c['nets_added']} -{c['nets_removed']} "
        f"~{c['nets_changed']}"
        + (f"  merged {c['nets_merged']}" if c["nets_merged"] else "")
    )
    print()

    if result.merges:
        print("  connections made:")
        for m in result.merges:
            print(f"    {m.describe()}")
        print()

    for label, group in (
        ("resolved", result.findings.resolved),
        ("introduced", result.findings.introduced),
    ):
        if not group:
            continue
        print(f"  {label} ({len(group)}):")
        shown = group if args.verbose else group[:10]
        for f in shown:
            print(f"    [{f.severity.label:8s}] {f.rule_id}  {f.summary}")
        if len(group) > len(shown):
            print(f"    ... {len(group) - len(shown)} more (-v for all)")
        print()

    if args.verbose:
        for heading, items in (
            ("component changes", result.components),
            ("net changes", result.nets),
        ):
            if not items:
                continue
            print(f"  {heading}:")
            for item in items:
                print(f"    {item.describe()}")
            print()

    if args.json:
        import json

        args.json.write_text(
            json.dumps(
                {
                    "schema": "xforge.diff/1",
                    "old": str(args.old),
                    "new": str(args.new),
                    "verdict": result.verdict,
                    "counts": c,
                    "merges": [m.describe() for m in result.merges],
                    "resolved": [_finding_json(f) for f in result.findings.resolved],
                    "introduced": [
                        _finding_json(f) for f in result.findings.introduced
                    ],
                    "unchanged": [
                        _finding_json(f) for f in result.findings.unchanged
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  json: {args.json}")

    # A revision that adds violations fails when asked to gate, so a
    # regression cannot be merged without someone deciding to accept it.
    if args.gate and result.findings.net_change > 0:
        print()
        print(
            f"FAIL: this revision introduces {result.findings.net_change} "
            "more violation(s)"
        )
        return EXIT_FINDINGS
    return EXIT_OK


def _cmd_comms(args) -> int:
    """Generate every communications artefact from one spec."""
    from xforge.comms import CommsSpec, SpecError, build

    try:
        spec = CommsSpec.load(args.spec)
    except SpecError as exc:
        # SpecError always names the offending signal, message or register,
        # so the message is the whole error report.
        print(f"xforge: {exc}", file=sys.stderr)
        return EXIT_ERROR

    written = build(spec, args.out, source_name=str(args.spec))
    for path in written:
        print(path)
    print()
    print(f"{len(written)} artefact(s) from {args.spec}")
    return EXIT_OK


def _cmd_ui(args) -> int:
    """Start the local app."""
    from xforge.ui import serve

    serve(
        project=args.project,
        netlist=args.netlist,
        config=args.config,
        model=args.model,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return EXIT_OK


def _cmd_formulas(args) -> int:
    """Every calculation the tool can perform, and where it came from."""
    from xforge.physics import formula

    reg = formula.registry()
    if args.id:
        print(formula.get(args.id).explain())
        return EXIT_OK

    for tier in (
        formula.Tier.PRIMARY,
        formula.Tier.PUBLIC_FORM,
        formula.Tier.SECONDARY,
        formula.Tier.CONVENTION,
    ):
        group = [f for f in reg.values() if f.tier is tier]
        if not group:
            continue
        gate = "may gate a build" if tier.may_gate else "advisory only"
        print(f"tier {tier} - {tier.label} ({gate})")
        for f in sorted(group, key=lambda x: x.id):
            print(f"  {f.id:22s} {f.equation}")
            print(f"  {'':22s} {f.source}")
        print()
    return EXIT_OK


def _cmd_power(args) -> int:
    from xforge import power

    design = _read(args.netlist)
    config = Config.load(args.config)
    report = power.analyse(design, config)

    if not report.nets and not report.unmatched_specs:
        print(
            "No currents declared. Add a `currents:` block to the project "
            "config; a netlist cannot tell us what a net carries."
        )
        return EXIT_OK

    s = report.stackup
    print(f"{report.design}")
    print(
        f"  stackup: {s.layers} layer, {s.outer_copper_oz} oz outer / "
        f"{s.inner_copper_oz} oz inner, max rise {s.max_temp_rise_c} C"
    )
    print()
    print(
        f"  {'net':36s} {'A':>7s} {'outer mm':>9s} {'inner mm':>9s} "
        f"{'vias':>5s}  class"
    )
    oversized = []
    for n in report.nets:
        amps = f"{n.peak_a or n.continuous_a:.1f}"
        mark = " *" if n.exceeds_trace_limit else "  "
        print(
            f"  {n.net[:36]:36s} {amps:>7s} "
            f"{n.outer.width_mm:>9.2f} {n.inner.width_mm:>9.2f} "
            f"{n.vias.count:>5d}  {n.netclass}{mark}"
        )
        if n.exceeds_trace_limit:
            oversized.append(n)

    if oversized:
        print()
        print(
            f"  * wider than the {config.trace_limit_mm:.0f} mm trace limit - "
            "not a trace. Carry these as a busbar or heavy-copper pour:"
        )
        for n in oversized:
            leaf = n.net.rsplit("/", 1)[-1]
            print(
                f"      {leaf:28s} {n.peak_a or n.continuous_a:>6.0f} A  ->  "
                f"{n.busbar_mm2:>6.1f} mm2 at 2.0 A/mm2 "
                f"(e.g. {n.busbar_mm2 / 3:.0f} x 3 mm bar)"
            )
        print(
            "    Busbar current density is industry convention, not a "
            "standard value - see docs/standards.md."
        )
    if report.unmatched_specs:
        print()
        print("  declared currents that matched no net:")
        for spec in report.unmatched_specs:
            what = spec.role or ", ".join(spec.nets)
            print(f"    {spec.continuous_a} A  ->  {what}")

    print()
    from xforge.physics.ampacity import IPC2221_TRACE

    print(f"  method: {IPC2221_TRACE.citation()}")
    print(f"          run `xforge formulas {IPC2221_TRACE.id}` for the full basis")

    if args.netclasses:
        import json

        args.netclasses.write_text(
            json.dumps(report.netclasses, indent=2), encoding="utf-8"
        )
        print(f"  netclasses: {args.netclasses}")
    if args.csv:
        import csv

        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(
                ["net", "continuous_a", "peak_a", "outer_mm", "inner_mm",
                 "min_vias", "netclass", "method"]
            )
            for n in report.nets:
                w.writerow([
                    n.net, n.continuous_a, n.peak_a or "",
                    round(n.outer.width_mm, 3), round(n.inner.width_mm, 3),
                    n.vias.count, n.netclass, n.outer.method,
                ])
        print(f"  csv       : {args.csv}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xforge",
        description="Design rule checking for Xbattery hardware.",
    )
    p.add_argument("--version", action="version", version=f"xforge {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="run design rules against a netlist")
    c.add_argument("netlist", type=Path, help="KiCad or atopile netlist (.net)")
    c.add_argument("-c", "--config", type=Path, default=None, help="xforge.yaml")
    c.add_argument("--html", type=Path, default=None, help="write an HTML report")
    c.add_argument("--json", type=Path, default=None, help="write findings as JSON")
    c.add_argument("-v", "--verbose", action="store_true", help="list subjects")
    c.add_argument("-q", "--quiet", action="store_true", help="warnings and above")
    c.add_argument(
        "--gate",
        action="store_true",
        help="fail on errors from any gating-capable rule (CI use)",
    )
    c.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="accept the violations in this file; fail only on new ones",
    )
    c.set_defaults(func=_cmd_check)

    b = sub.add_parser(
        "baseline", help="record the violations a project accepts for now"
    )
    b.add_argument("netlist", type=Path)
    b.add_argument("-c", "--config", type=Path, default=None)
    b.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("xforge.baseline.json"),
        help="where to write it (default: xforge.baseline.json)",
    )
    b.add_argument(
        "--prune",
        action="store_true",
        help="drop entries that no longer fire, instead of rewriting it",
    )
    b.add_argument(
        "--all",
        action="store_true",
        help="record every violation, not only the ones that can gate",
    )
    b.add_argument("--note", default="", help="why these are accepted")
    b.set_defaults(func=_cmd_baseline)

    p2 = sub.add_parser(
        "power", help="conductor requirements for declared currents"
    )
    p2.add_argument("netlist", type=Path)
    p2.add_argument("-c", "--config", type=Path, default=None)
    p2.add_argument(
        "--netclasses", type=Path, default=None, help="write netclass JSON"
    )
    p2.add_argument("--csv", type=Path, default=None, help="write a constraint CSV")
    p2.set_defaults(func=_cmd_power)

    df = sub.add_parser("diff", help="compare two revisions of a design")
    df.add_argument("old", type=Path, help="the earlier netlist")
    df.add_argument("new", type=Path, help="the netlist under review")
    df.add_argument("-c", "--config", type=Path, default=None)
    df.add_argument(
        "--json", type=Path, default=None, help="write the delta as JSON"
    )
    df.add_argument("-v", "--verbose", action="store_true")
    df.add_argument(
        "--gate", action="store_true",
        help="fail if the new revision has more violations (CI use)",
    )
    df.set_defaults(func=_cmd_diff)

    cm = sub.add_parser(
        "comms", help="generate DBC, register map and firmware from one spec"
    )
    cm.add_argument("spec", type=Path, help="comms spec (YAML)")
    cm.add_argument("--out", type=Path, default=Path("out/comms"))
    cm.set_defaults(func=_cmd_comms)

    u = sub.add_parser("ui", help="start the local app (part search + board viewer)")
    u.add_argument(
        "--project", type=Path, default=Path.cwd(),
        help="project root; imported parts are vendored here",
    )
    u.add_argument("--netlist", type=Path, default=None)
    u.add_argument("-c", "--config", type=Path, default=None)
    u.add_argument("--model", type=Path, default=None, help="STEP file to view")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=7800)
    u.add_argument("--no-browser", action="store_true")
    u.set_defaults(func=_cmd_ui)

    fm = sub.add_parser(
        "formulas", help="list the calculations and their provenance"
    )
    fm.add_argument("id", nargs="?", help="explain one formula in full")
    fm.set_defaults(func=_cmd_formulas)

    i = sub.add_parser("inspect", help="summarise a netlist")
    i.add_argument("netlist", type=Path)
    i.set_defaults(func=_cmd_inspect)

    r = sub.add_parser("rules", help="list registered rules")
    r.set_defaults(func=_cmd_rules)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"xforge: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except ValueError as exc:
        print(f"xforge: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
