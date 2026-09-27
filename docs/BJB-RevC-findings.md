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

The defect is **new in the handoff**. The earlier `hierarchy_fix` work predates
both sheets and addressed something else. The two sheets were added between
11:06 and 12:59 on 24 Sep, and the splits arrived with them.

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

XF003 (barrier straddle) reports nothing on RevC, correctly: with both sheets
orphaned, nothing crosses a domain boundary because nothing crosses anything.
It becomes meaningful once the sheet pins are wired — which is a useful property
to keep in mind when reading a clean XF003 result.

## Open questions

1. **Pack voltage class for this build.** Not derivable from the netlist, and
   every insulation rule depends on it.
2. **Domain assignment for `MC33772C`, `SC400A`, `TPL Communication`,
   `Power_Supply` and `AC_Sense`.** Deliberately left unassigned rather than
   guessed — see the comments in `xforge.bjb.yaml`.
