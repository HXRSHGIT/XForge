# Enforcement

When does XForge fail a build, and why it is allowed to.

## The problem this solves

A checker that fails a build on its first run against an existing design is
switched off within a week. A checker that never fails a build is read for a
month and then ignored. Both failure modes end in the same place, so the
enforcement model has to earn its way from one to the other.

XForge does that in three stages:

| Stage | What it means | How |
|---|---|---|
| **Advisory** | The rule reports. Nothing fails. | default |
| **Gating** | An Error from this rule fails the run. | listed in `gating_rules` |
| **Gating + baseline** | Fails on *new* Errors only. | `--baseline` |

Exit codes: `0` clean or advisory-only, `1` a gating rule fired on something
not accepted, `2` could not run.

## How a rule graduates

A rule may be promoted to `gating_rules` only when all four hold:

1. **It is marked `blocking=True` in code.** This is the rule author saying the
   rule is *capable* of gating — that it answers a yes/no question about
   connectivity or safety rather than making a judgement call.
2. **Any numbers it relies on are tier A or B.** A rule whose threshold comes
   from a secondary source or a house convention may not gate. This is enforced
   in code by `formula.gating_safe()`; see [`standards.md`](standards.md).
3. **Its false-positive rate on real boards is measured and zero.** Not
   estimated. Run it over every revision on record and check each firing by
   hand.
4. **The finding names something actionable.** A gating finding has to tell
   someone which net or sheet to go and look at, or it cannot be acted on.

Point 3 is the expensive one and it is the one that matters.

## XF001 and XF005: the evidence

Promoted 29 Sep 2026. Measured over every BJB netlist on record — ten exports
across two days, from **two different toolchains** (KiCad Eeschema 10.0.6 and
atopile `ato build`), including designs of very different size.

| Netlist | Exported | Comp | Nets | XF001 | XF005 | Orphaned sheets |
|---|---|---|---|---|---|---|
| `BJB_before_RevC.net` | 23 Sep 14:17 | 151 | 100 | 0 | 0 | — |
| `BJB_RevC.net` | 23 Sep 14:55 | 151 | 100 | 0 | 0 | — |
| `Verification_pre_fix.net` | 23 Sep 15:17 | 151 | 100 | 0 | 0 | — |
| `BJB_netlist_hierarchy_fix.net` | 23 Sep 15:26 | 151 | 100 | 0 | 0 | — |
| `status_check.net` | 23 Sep 16:02 | 151 | 100 | 0 | 0 | — |
| `fixed_project.net` | 24 Sep 11:04 | 151 | 100 | 0 | 0 | — |
| `fixed2_project.net` | 24 Sep 11:06 | 165 | 153 | 0 | **1** | Control, Diagnostics & IoT |
| `default.net` (atopile) | 24 Sep 12:29 | 20 | 34 | 0 | 0 | — |
| `handoff_netlist.net` | 24 Sep 12:59 | 191 | 188 | **11** | **2** | + HV Power-Path & Safety |
| `BJB_RevC_Netlist.net` | 24 Sep 12:59 | 191 | 188 | **11** | **2** | + HV Power-Path & Safety |

The last two are the same export under two names.

- **Firings: 3 of 10. True positives: 3 of 3. False positives: 0.**
- Every firing traces to one verified cause — sheet symbols placed with no
  pins — reproduced in the schematic and written up in
  [`BJB-RevC-findings.md`](BJB-RevC-findings.md).
- The seven clean revisions include hierarchical designs with real sheets, so
  silence is not an artifact of the rules being unable to see anything. The
  atopile export is a different generator entirely and is also clean, which is
  the check that the rules are not keyed to one tool's output.

Both rules are structural: they compare net membership across sheets and need
no physical constant, so criterion 2 is vacuous for them.

## Baselines

Gating XF001 and XF005 against the current BJB fails on 13 findings, because
the defect is real and not yet fixed. That is correct, and it is also useless
as a daily signal — a permanently red build is a build nobody reads.

`xforge.bjb.baseline.json` records those 13 as accepted. Gating then fails only
on findings *outside* the baseline.

```bash
# accept what is broken today
xforge baseline design.net -c xforge.yaml -o xforge.baseline.json \
    --note "why these are accepted, and who owns fixing them"

# fail only on new defects
xforge check design.net -c xforge.yaml --baseline xforge.baseline.json
```

Three properties make this safe rather than a blanket amnesty:

**Entries match on identity, not text.** A baseline entry is `(rule_id, key)`,
where the key names the net, refdes or sheet the finding is about. Reword a
message and the entry still matches; a *different* defect that happens to read
similarly does not.

**Only gating rules are recorded.** By default `xforge baseline` writes entries
only for rules that can currently gate. An entry for an advisory rule excuses
nothing today, but would silently excuse a genuine defect on the day that rule
graduates. Use `--all` if you really want the wider file.

**Stale entries are reported.** An entry that no longer matches any finding is
printed on every run, and `xforge baseline --prune` removes them. The file is a
ratchet: it is expected to shrink.

## Does it actually catch a regression?

The honest test is whether it would have stopped the defect that shipped.
Baseline the 24 Sep **11:06** revision, then gate the **12:59** handoff:

```
baseline: 1 known violation(s) accepted from bl.json

FAIL: 12 finding(s) from gating rules ['XF001', 'XF005']
  XF001  BUS_V_SENSE
  XF001  FUSE_DROP_SENSE
  XF001  MAIN_FB
  XF001  PRECHARGE_FB
  XF001  SAFE_VOLT_MON
  XF001  SC_FAULT_N
  XF001  SC_RESET_N
  XF001  TEMP_CONTACTOR
  XF001  TEMP_PRECHARGE
  XF001  TEMP_SHUNT
  XF001  WELD_MON
  XF005  HV Power-Path & Safety
```

Twelve new defects named, and the pre-existing orphan — `Control, Diagnostics
& IoT`, which was already floating at 11:06 — correctly *not* blamed on this
revision. This run fails, so the handoff would not have gone out.

## The other gate

`xforge diff --gate` is a different question: not "is this design clean" but
"did this revision make it worse". It fails when the violation count rises,
whatever the absolute number. Use it on a pull request; use `check --baseline`
on a branch. They are complementary, and neither subsumes the other.

## Rules not yet gating

| Rule | Why not |
|---|---|
| XF002 dangling net | Fires 47 times on RevC, nearly all downstream of the XF005 defect. Its independent rate is unknown until the sheets are wired. |
| XF004 placeholder footprint | Informational by design. |
| XF006 unspecified rating | Correct, but "TBD" is a legitimate state early in a design. Gate near release, not during. |
| XF007 fuse present | Answers a question about intent, not a defect. |
| XF008 isolation barrier | Needs the pack voltage class and a domain decision on five sheets. Both are open. |
| XF010 interlock chain | Currently passes. A rule that has never fired has no measured rate. |
| XF011 coil clamp / XF012 thermistor bias | Real findings, but both have plausible legitimate exceptions that have not been enumerated. |

Promoting any of these means repeating the evidence table above for that rule.
