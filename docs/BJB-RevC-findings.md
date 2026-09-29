# BJB RevC — first xforge findings

**Design:** BJB System Architecture, rev BJB-CONCEPT-2.0, Xbattery Energy Pvt. Ltd.
**Netlist:** `BJB_RevC_Handoff/Verification/BJB_RevC_Netlist.net`, exported 24 Sep 2026 12:59 from Eeschema 10.0.6
**Checked:** 27 Sep 2026 · 191 components · 188 nets · 549 pins

## Summary

| | |
|---|---|
| Errors | 13 — 11 split signals, 2 orphaned sheets |
| Warnings | 47 dangling nets |
| Advisory | 0 |
| Info | 1 — 34 placeholder footprints |

**All 13 errors have a single root cause.** They are one defect, not thirteen.

## The defect

The two sheets added on 24 Sep 2026 are placed on the root schematic with
**no sheet pins**:

```
sheet 'Control, Diagnostics & IoT'   file=BJB_Control_IoT.kicad_sch        pins=0
sheet 'HV Power-Path & Safety'       file=BJB_Safety_PowerPath.kicad_sch   pins=0
```

Every other sheet has them:

```
sheet 'MC33772C'            pins=12   RDTX_IN_N, RDTX_IN_P, DCLINK_POS_SEC_SENSE, ...
sheet 'SC400A'              pins=6    SHUNT_N, SHUNT_P, SC_5V, GND, SC_FAULT_N, SC_RESET_N
sheet 'HV Switches'         pins=4    CTRL_CHARGER_POS, CTRL_DCLINK_POS_SEC, HV_CTRL_S4, HV_CTRL_S5
sheet 'HV Sensing Lines'    pins=5    ...
sheet 'Power_Supply'        pins=3    VSUP, GND, SC_5V
sheet 'TPL Communication'   pins=2    RDTX_IN_P_PRIM, RDTX_IN_N_PRIM
sheet 'AC_Sense'            pins=3    GND, Sense_Out, Sense_VCC
```

In KiCad a sub-sheet reaches the rest of the design only through sheet pins.
With none, every hierarchical label inside those two sheets becomes a net that
exists nowhere else. The drawing reads as connected; the netlist says
otherwise. **40 components and 72 nets are electrically isolated from the
design.**

## Consequence — the 11 split signals

Each of these now exists as two separate, unconnected nets:

| Signal | Control sheet | HV sheet | Elsewhere |
|---|---|---|---|
| `SC_FAULT_N` | — | 1 pin (J920.2) | **6 pins** on `/SC_FAULT_N` |
| `SC_RESET_N` | — | 1 pin (J920.3) | 2 pins on `/SC_RESET_N` |
| `MAIN_FB` | 1 pin (U900.13) | 1 pin (J917.1) | — |
| `PRECHARGE_FB` | 1 pin (U900.44) | 1 pin (J917.2) | — |
| `TEMP_SHUNT` | 1 pin (U900.19) | 2 pins | — |
| `TEMP_PRECHARGE` | 1 pin (U900.20) | 2 pins | — |
| `TEMP_CONTACTOR` | 1 pin (U900.21) | 2 pins | — |
| `BUS_V_SENSE` | 1 pin (U900.12) | 1 pin (J918.2) | — |
| `FUSE_DROP_SENSE` | 1 pin (U900.22) | 1 pin (J918.1) | — |
| `SAFE_VOLT_MON` | 1 pin (U900.26) | 1 pin (J919.1) | — |
| `WELD_MON` | 1 pin (U900.25) | 1 pin (J919.2) | — |

The sharpest case is `SC_FAULT_N`. The real fault network carries six pins —
`U3.6` (`~ALERT`, open collector), `U5.2` (`~RESET`, open collector), `J7.1`,
`R51.2`, `R55.1`, `TP22.1`. The HV sheet's connector pin `J920.2` is not on it.
**The hardware short-circuit fault line reaches the connector but not the
detector.**

Every contactor feedback, all three thermistor channels, weld detect and the
safe-voltage monitor are in the same state.

## When it appeared

| Netlist | Date | Components | Nets | Splits |
|---|---|---|---|---|
| `BJB_before_RevC.net` | 23 Sep 14:17 | 151 | 100 | 0 |
| `BJB_RevC.net` | 23 Sep 14:55 | 151 | 100 | 0 |
| `Verification_pre_fix.net` | 23 Sep 15:17 | 151 | 100 | 0 |
| `BJB_netlist_hierarchy_fix.net` | 23 Sep 15:26 | 151 | 100 | 0 |
| `fixed2_project.net` | 24 Sep 11:06 | 165 | 153 | 0 |
| **`BJB_RevC_Netlist.net` (handoff)** | **24 Sep 12:59** | **191** | **188** | **11** |

The **splits** are new in the handoff. The earlier `hierarchy_fix` work predates
them and addressed something else.

The two orphaned sheets did not arrive together, and that distinction matters
for where to look:

| Sheet | At 11:06 | At 12:59 | Orphaned |
|---|---|---|---|
| `Control, Diagnostics & IoT` | 14 parts | 20 parts | in **both** revisions |
| `HV Power-Path & Safety` | absent | 20 parts | new in the handoff |

So `Control, Diagnostics & IoT` was already floating at 11:06 and nobody
noticed for at least an hour and a half; it simply produced no *split* then,
because none of its net names yet collided with a root-level label. Adding
`HV Power-Path & Safety` � which carries the safety signals � turned a quiet
orphan into 11 split signals.

`xforge diff` separates these automatically: it reports
`HV Power-Path & Safety` as introduced and `Control, Diagnostics & IoT` as
unchanged, so the older mistake is not blamed on this handoff.

## Fix

On `BJB.kicad_sch`, add sheet pins to the two sheet symbols and wire them to the
matching root-level labels, then re-export.

`SC_FAULT_N` and `SC_RESET_N` already exist as root-level local labels (wired to
the SC400A sheet's pins), so those two connect directly. The remainder —
`MAIN_FB`, `PRECHARGE_FB`, `TEMP_*`, `BUS_V_SENSE`, `FUSE_DROP_SENSE`,
`SAFE_VOLT_MON`, `WELD_MON` — need the root-level connection between the two new
sheets drawn.

Re-run to confirm:

```bash
xforge check <new-netlist> -c xforge.bjb.yaml --html out/bjb.html
```

XF001 and XF005 should both go to zero.

## The 47 warnings

All trace back to the same cause: 39 of the 47 dangling nets are on the two
orphaned sheets. They are not separately actionable and should be re-assessed
after the fix rather than suppressed now — suppressing them would hide the
defect.

The remainder are MCU pins not yet assigned (`SWCLK`, `SWDIO`, `UART_TX/RX`,
`GPIO2`, `GPIO6`), which are expected at this stage of the design.

## Note on the domain configuration

`xforge.bjb.yaml` declares HV and LV **by sheet**, not by net-name pattern. The
first attempt used patterns like `BUS_*` and `PACK_*`; the netlist shows those
match `BUS_V_SENSE` and `PACK_V_SENSE`, which are ADC inputs on U900 — the
low-voltage end of a divider, not bus conductors. Sheet scope is the reliable
signal in a hierarchical design.

XF008 (barrier crossing) reports nothing on RevC, correctly: with both sheets
orphaned, nothing crosses a domain boundary because nothing crosses anything.
It becomes meaningful once the sheet pins are wired — which is worth keeping in
mind when reading a clean isolation result.

## Open questions

1. **Pack voltage class for this build.** Not derivable from the netlist, and
   every insulation rule depends on it.
2. **Domain assignment for `MC33772C`, `SC400A`, `TPL Communication`,
   `Power_Supply` and `AC_Sense`.** Deliberately left unassigned rather than
   guessed — see the comments in `xforge.bjb.yaml`.

---

# Second pass — safety-path rules (week 3)

Re-run after adding XF006–XF012. The hierarchy defect above is unchanged; these
are the additional findings.

## Summary

| | |
|---|---|
| Errors | 15 — 11 split signals, 2 orphaned sheets, **2 unspecified ratings** |
| Warnings | 56 — 47 dangling nets, **6 unclamped coil nets**, **3 unbiased thermistors** |
| Passed | 2 |
| Not evaluable | 0 |

## New errors — safety-critical parts with no rating

Two parts on the HV Power-Path & Safety sheet carry placeholder values:

| Ref | Value | Why it is an error rather than a warning |
|---|---|---|
| `F900` | `Fuse (I/V/I2t rating TBD)` | A fuse's rating *is* its protective function. Until I²t is chosen, nothing about the short-circuit behaviour of this design can be evaluated. |
| `R902` | `PRECHARGE_R (ohms/energy TBD)` | Precharge resistance sets both the inrush current and the energy the resistor absorbs per event. `3RC` against the downstream bulk capacitance is the sizing constraint, and the pulse rating has to exceed `½CV²` per precharge cycle. |

Both are honest notes by the designer. Both would survive into a build.

## Passed — worth stating

**XF010: the interlock chain is series-continuous across 4 switches.** Traced
from the netlist, not declared:

```
SW900 --[HVIL_OK]--        SW901
SW901 --[ESTOP_OK]--       SW902
SW902 --[SAFETY_LOOP_OK]-- SW903

SW900  HVIL (NC)
SW901  E_STOP / crash loop (NC)
SW902  MSD / cover loop (NC)
SW903  SC trip inhibit contact (NC)
```

Coil supply reaches `COIL_ENABLE_HW` only through all four normally-closed
contacts in series, and no link net carries a third connection that could bypass
a contact. Breaking any one opens the chain. **This part of the design is
correct** — confirm the order matches the intended sequence.

**XF008: nothing bridges the declared domains.** Read this together with XF005:
with both sheets orphaned, nothing crosses a barrier because nothing crosses
anything. It will mean something once the sheet pins are wired.

## New warnings

**Six coil nets with no clamp element** — `MAIN_COIL-`, `PRECHARGE_COIL-`,
`COIL_SUPPLY+`, `COIL_SUPPLY+_RET`, `COIL_RETURN`, `COIL_ENABLE_HW`. The
contactors are external and reach the board through `J915`/`J916`, so the clamp
may well be inside the contactor. That needs confirming against its datasheet and
recording, rather than assuming. Worth noting the trade-off either way: a plain
flyback diode slows contactor opening and can reduce breaking capacity.

**Three thermistors with no bias resistor** — `TH900` (NTC_SHUNT), `TH901`
(NTC_PRECHARGE), `TH902` (NTC_CONTACTOR). Each has one terminal on a `TEMP_*`
net to connector `J914` and the other on `GND`. No divider resistor appears on
either net, so as netlisted these cannot be read. The bias is presumably intended
on the Control sheet — which is the sheet XF005 reports as orphaned.

## Isolation crossings now declared

Four parts are recorded in `xforge.bjb.yaml` as intentional barrier crossings:

| Ref | Part | Role |
|---|---|---|
| `U903` | ISO1050DUB | Isolated CAN transceiver |
| `Q2` | APC-817C1-SL | Optocoupler, AC sense |
| `PS1` | ITR0312S12 | Isolated DC-DC converter |
| `T1` | HM2103NLT | TPL isolation transformer |

Declaring one is a recorded decision. Each still needs its rated isolation
voltage checked against the working voltage once that is known.

## Two false positives found and fixed

Worth recording, because both were the rule engine being confidently wrong:

1. **`J911` read as a switch, `J914` as a thermistor.** Classification was
   matching against the free-text `description` field — *"Protected HV port to
   rated external **switch**gear"* and *"Power-path **NTC** harness"*. Both are
   connectors. Fixed: descriptions are prose written for humans and are no longer
   used for classification, and an unambiguous designator prefix (`J`, `P`, `TP`,
   `H`) now settles what a part is.

2. **`TEMP_CONTACTOR` and `CONTACTOR_CMD` flagged as unclamped coils.** The coil
   pattern list included `*CONTACTOR*`, which swept in a thermistor sense line and
   a logic command. Neither is an inductive load. Narrowed to `*COIL*` and
   `*SOLENOID*`.

Both now have regression tests.
