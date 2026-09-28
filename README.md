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
xforge power design.net -c xforge.yaml --netclasses nc.json --csv constraints.csv
xforge inspect design.net       # census only
xforge rules                    # what is registered and where each rule comes from
```

Both the S-expression and the XML netlist are accepted, chosen by content
rather than extension — KiCad writes both to `.net`.

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
| XF004 | Placeholder footprint | Info | Xbattery convention |
| XF005 | Sheet has no connection to the rest of the design | Error | Xbattery convention; KiCad sheet pins |
| XF006 | Component rating still unspecified | Warning / Error | Xbattery convention |
| XF007 | Fuse present on the power path | Info | IEC 62619 protection intent |
| XF008 | Undeclared component bridges an isolation barrier | Error | IEC 60664-1; declared domains and crossings |
| XF010 | Safety interlock chain is series-continuous | Error | ISO 26262 decomposition; CEA BESS two-fault tolerance |
| XF011 | Inductive coil drive without a clamp | Warning | General protection practice |
| XF012 | Thermistor without a bias network | Warning | General measurement practice |

XF003 was retired: XF008 answers the same question and adds the declared-crossing
whitelist, so keeping both meant shipping two rules that could disagree.

### Pass, violation, not evaluable

A rule reports one of three things. A **violation** is a defect. A **pass** is a
positive result worth stating — XF010 prints the interlock chain it traced, which
is what a reviewer actually wants to see. **Not evaluable** means the rule could
not run and says why, so silence is never mistaken for success.

Every rule cites where its criterion comes from, and a test asserts that it
does. A rule nobody can trace to a source is a rule nobody can argue with,
which is worse than no rule.

`docs/` holds the reasoning: [`standards.md`](docs/standards.md) for where every
constant comes from and which rules may gate a build,
[`BJB-RevC-findings.md`](docs/BJB-RevC-findings.md) for the first real run
against a live design, and
[`platform-study/`](docs/platform-study/atopile-analysis.md) for the analysis
that led to building this instead of adopting an existing tool.

## Enforcement

**Advisory by default.** Nothing fails a build until a rule has been listed in
`gating_rules` in the project config, or `--gate` is passed. This is deliberate:
one false positive early on is enough for a team to start ignoring the tool.
Rules graduate to gating once their false-positive rate on real boards is known.

Exit codes: `0` clean or advisory-only, `1` a gating rule fired, `2` could not run.

## The app

```bash
pip install -e ".[parts]"
xforge ui --project . --model board.stp --netlist design.net
```

Opens a local instrument at `127.0.0.1:7800` with two jobs: find a part that is
not in the project yet and bring it in, and look at the board.

**Part search goes online. Builds do not.** A part is fetched once, converted to
a normal KiCad symbol, footprint and 3D model, written into `parts/<LCSC>/`, and
recorded in `parts.lock.json`. Everything after that reads the vendored copy, so
a build two years from now resolves to the same parts with no network and no
supplier account. Nothing downstream depends on xforge having been involved.

Keyboard: `/` focuses the search field, arrow keys move through results, `Enter`
imports the selected part, `Escape` clears. A `?q=` in the URL prefills a search,
so a part can be sent to a colleague as a link.

The server binds to localhost. It serves a project's design files and talks to a
supplier on your behalf; neither belongs on a public interface.

## Conductor sizing

`xforge power` turns declared currents into the copper geometry they need.
A netlist cannot say what a net carries, so currents are declared in the
project config, by net pattern or by profile net role:

```yaml
stackup:
  layers: 4
  outer_copper_oz: 2.0
  inner_copper_oz: 1.0
  max_temp_rise_c: 20.0
  ambient_c: 55.0          # inside the enclosure, not lab ambient

currents:
  - nets: ["PACK_POS", "PACK_NEG", "MAIN_POS"]
    continuous_a: 100.0
    peak_a: 200.0
  - role: coil              # resolved through the profile
    continuous_a: 2.0
```

Output is the required outer and inner trace width, a minimum via count, and a
netclass band per net — exportable as netclass JSON and as a CSV the layout
engineer can work from. Sizing uses **IPC-2221**, which is public and
implementable; it is conservative relative to IPC-2152 and says so. See
`docs/standards.md`.

Where the required copper is wider than a trace can sensibly be, the report
says so and gives the busbar cross-section instead of printing an absurd
width:

```
  * wider than the 20 mm trace limit - not a trace. Carry these as a busbar:
      PACK_POS   200 A  ->  100.0 mm2 at 2.0 A/mm2 (e.g. 33 x 3 mm bar)
```

A declared current that matches no net is reported too — that is a config bug,
and silently sizing nothing would hide it.

## Profiles

A rule holds an algorithm. A **profile** holds the vocabulary that algorithm
needs — what parts are called, what designator prefixes mean, which net names
play which role. Keeping them apart is what stops a rule written for one board
from silently not applying to the next one.

```
profiles/base.yaml   generic electronics, no domain assumptions
profiles/bms.yaml    extends base: coil, interlock, cell-tap, current-sense
                     and temperature net roles; AFE, contactor, shunt,
                     isolated-transceiver part families
```

A project selects one and may extend it:

```yaml
profile: bms
profile_overrides:
  net_roles:
    coil: ["*PUMP_DRV*"]      # appended to the profile's, not replacing them
```

Lists concatenate on merge, so adding one pattern never discards the profile's.

### A rule that cannot look says so

If a rule needs a net role the active profile does not define, it reports
**not evaluable** and names the profile — it does not pass. The same design
checked twice:

```
$ xforge check bjb.net -c xforge.bjb.yaml      # profile: bms
  2 check(s) passed, 0 not evaluable

$ xforge check bjb.net                         # profile: base
 ?[Info    ] XF011  Profile 'base' defines no coil nets
  1 check(s) passed, 2 not evaluable
```

Silence and "I did not look" are different results, and the tool has to be able
to tell you which one it is.

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
