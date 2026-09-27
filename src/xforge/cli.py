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
            for s in f.subjects:
                print(f"                {s}")

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
    if fired:
        print(f"\nFAIL: {len(fired)} finding(s) from gating rules {sorted(gating)}")
        return EXIT_FINDINGS
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
    c.set_defaults(func=_cmd_check)

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
