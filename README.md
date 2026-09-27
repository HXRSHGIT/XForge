# xforge

Design rule checking and generation for Xbattery hardware.

Built because the tools we evaluated have no model of current, isolation,
creepage or clearance — the four things that decide whether a 51.2 V to 800 V
battery product is safe. See `docs/` and the platform study on the Desktop for
the reasoning behind this.

**Status: week 1.** `xforge check` runs connectivity rules against a KiCad or
atopile netlist. Power and comms tooling follow.

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

Python 3.11 or newer. The only runtime dependency is PyYAML, and the checker
degrades to JSON config if even that is missing — the tool has to run on a CI
runner we do not control.

## Use

```bash
xforge check design.net -c xforge.yaml --html report.html --json findings.json
xforge inspect design.net       # census only
xforge rules                    # what is registered and where each rule comes from
```

Getting a netlist out of KiCad:

```bash
kicad-cli sch export netlist --format kicadsexpr -o design.net design.kicad_sch
```

`ato build` emits the same shape, so an atopile project works unchanged.

## Rules

| ID | Rule | Default | Source |
|---|---|---|---|
| XF001 | Signal split across sheets | Error | Xbattery convention; KiCad hierarchical sheet pins |
| XF002 | Dangling net | Warning | Xbattery convention |
| XF003 | Component straddles an isolation barrier | Advisory | IEC 60664-1; declared domains |
| XF004 | Placeholder footprint | Info | Xbattery convention |

Every rule cites where its criterion comes from, and a test asserts that it
does. A rule nobody can trace to a source is a rule nobody can argue with,
which is worse than no rule.

## Enforcement

**Advisory by default.** Nothing fails a build until a rule has been listed in
`gating_rules` in the project config, or `--gate` is passed. This is deliberate:
one false positive early on is enough for a team to start ignoring the tool.
Rules graduate to gating once their false-positive rate on real boards is known.

Exit codes: `0` clean or advisory-only, `1` a gating rule fired, `2` could not run.

## Config

`xforge.yaml` holds what a netlist cannot state — which nets are HV, which are
LV, which single-pin nets are intentional. See `xforge.bjb.yaml` for a worked
example against the Battery Junction Box.

## Layout

```
src/xforge/
  sexp.py            dependency-free S-expression reader for KiCad formats
  model.py           Design / Component / Net / Pin — reader-agnostic
  config.py          xforge.yaml: domains, expectations, policy
  readers/           format readers (KiCad netlist today)
  rules/             base.py = framework, one module per rule family
  report.py          single-file HTML + JSON output
  cli.py             argparse CLI
tests/
  fixtures/bjb_revc.net   the real BJB RevC handoff netlist
```

The fixture is a real design on purpose. A synthetic netlist would not have
caught the hierarchical split that XF001 found on its first run.

## Tests

```bash
.venv/Scripts/python -m pytest
```

Golden assertions pin the finding counts on the BJB fixture. If those numbers
move, behaviour changed, and the change has to be deliberate.

---

Xbattery Energy Pvt. Ltd. — internal.
