"""Comparing two revisions.

The golden case is the real regression: between 24 Sep 11:06 and 12:59 the
BJB gained two sheets with no sheet pins. A text diff of those netlists says
nothing useful; the findings delta says 39 more violations.
"""

from pathlib import Path

import pytest

from xforge import readers
from xforge.config import Config
from xforge.diff import Change, compare, compare_components, compare_findings, compare_nets
from xforge.model import Component, Design, Net, Pin
from xforge.rules import Severity, Status, run
from xforge.rules.base import Finding

BJB = Path(r"C:\Users\TempAdmin\Desktop\BJB_ShortCircuitAdded")
BEFORE = BJB / "BJB_RealSchematic_RevC" / "Verification" / "fixed2_project.net"
AFTER = BJB / "BJB_RevC_Handoff" / "Verification" / "BJB_RevC_Netlist.net"

real_revisions = pytest.mark.skipif(
    not (BEFORE.exists() and AFTER.exists()),
    reason="the two real BJB revisions are not on this machine",
)

CONFIG = Path(__file__).parents[1] / "xforge.bjb.yaml"


@pytest.fixture(scope="module")
def result():
    """The real regression, checked once for the whole class."""
    cfg = Config.load(CONFIG)
    old, new = readers.read(BEFORE), readers.read(AFTER)
    return compare(old, new, run(old, cfg), run(new, cfg))


def _design(name="d", nets=(), components=()):
    return Design(name=name, components=list(components), nets=list(nets))


def _finding(rule="XF001", key="A", summary="something", sev=Severity.ERROR):
    return Finding(rule_id=rule, severity=sev, summary=summary, key=key)


class TestComponents:
    def test_added_and_removed(self):
        old = _design(components=[Component(ref="R1", value="10k")])
        new = _design(components=[Component(ref="R2", value="1k")])
        changes = {c.ref: c.change for c in compare_components(old, new)}
        assert changes == {"R1": Change.REMOVED, "R2": Change.ADDED}

    def test_value_change_is_reported_with_both_sides(self):
        old = _design(components=[Component(ref="R1", value="10k")])
        new = _design(components=[Component(ref="R1", value="4k7")])
        (c,) = compare_components(old, new)
        assert c.change is Change.CHANGED
        assert c.before == "10k" and c.after == "4k7"
        assert "10k -> 4k7" in c.describe()

    def test_footprint_change_is_reported_separately(self):
        old = _design(components=[Component(ref="R1", value="10k", footprint="0402")])
        new = _design(components=[Component(ref="R1", value="10k", footprint="0603")])
        (c,) = compare_components(old, new)
        assert c.field == "footprint"

    def test_identical_designs_report_nothing(self):
        d = _design(components=[Component(ref="R1", value="10k")])
        assert compare_components(d, d) == []


class TestNets:
    def test_pins_added_and_removed_on_a_surviving_net(self):
        old = _design(nets=[Net("/A", pins=[Pin("U1", "1")])])
        new = _design(nets=[Net("/A", pins=[Pin("U1", "1"), Pin("U2", "3")])])
        (c,) = compare_nets(old, new)[0]
        assert c.change is Change.CHANGED
        assert c.pins_added == ["U2.3"] and c.pins_removed == []
        assert c.degree_before == 1 and c.degree_after == 2

    def test_merge_is_detected_when_two_nets_become_one(self):
        """The shape a fixed hierarchical connection makes."""
        old = _design(
            nets=[
                Net("/SheetA/FAULT", pins=[Pin("J1", "2")]),
                Net("/SheetB/FAULT", pins=[Pin("U3", "6")]),
            ]
        )
        new = _design(
            nets=[Net("/FAULT", pins=[Pin("J1", "2"), Pin("U3", "6")])]
        )
        changes, merges = compare_nets(old, new)
        assert len(merges) == 1
        assert merges[0].result == "/FAULT"
        assert merges[0].sources == ["/SheetA/FAULT", "/SheetB/FAULT"]
        assert "now joins" in merges[0].describe()

    def test_a_plain_rename_is_not_called_a_merge(self):
        old = _design(nets=[Net("/OLD", pins=[Pin("U1", "1"), Pin("U2", "1")])])
        new = _design(nets=[Net("/NEW", pins=[Pin("U1", "1"), Pin("U2", "1")])])
        _, merges = compare_nets(old, new)
        assert merges == []

    def test_unchanged_nets_are_not_reported(self):
        d = _design(nets=[Net("/A", pins=[Pin("U1", "1"), Pin("U2", "1")])])
        assert compare_nets(d, d)[0] == []


class TestFindingIdentity:
    def test_same_key_with_a_changed_summary_is_unchanged(self):
        """A sheet growing from 14 to 20 parts is not a new defect.

        This is the bug the real diff exposed: keying on the summary made one
        persistent finding look like one resolved plus one introduced.
        """
        before = [_finding(key="Sheet A", summary="Sheet A ... (14 parts)")]
        after = [_finding(key="Sheet A", summary="Sheet A ... (20 parts)")]
        delta = compare_findings(before, after)
        assert delta.resolved == [] and delta.introduced == []
        assert len(delta.unchanged) == 1

    def test_different_keys_are_different_findings(self):
        delta = compare_findings([_finding(key="A")], [_finding(key="B")])
        assert len(delta.resolved) == 1 and len(delta.introduced) == 1

    def test_summary_is_the_fallback_when_no_key_is_set(self):
        a = Finding(rule_id="XF001", severity=Severity.ERROR, summary="x")
        b = Finding(rule_id="XF001", severity=Severity.ERROR, summary="y")
        assert a.identity != b.identity

    def test_only_violations_are_compared(self):
        """A pass turning into a different pass is not a regression."""
        before = [_finding(key="A")]
        after = [
            _finding(key="A"),
            Finding(
                rule_id="XF010", severity=Severity.INFO, summary="chain ok",
                key="interlock", status=Status.PASS,
            ),
        ]
        delta = compare_findings(before, after)
        assert delta.introduced == []

    def test_net_change_sign(self):
        assert compare_findings([], [_finding()]).net_change == 1
        assert compare_findings([_finding()], []).net_change == -1
        assert compare_findings([_finding()], [_finding()]).net_change == 0


class TestVerdict:
    def test_improvement(self):
        d = compare(_design(), _design(), [_finding()], [])
        assert d.verdict == "1 fewer violation(s)"

    def test_regression(self):
        d = compare(_design(), _design(), [], [_finding()])
        assert d.verdict == "1 more violation(s)"

    def test_no_change_at_all(self):
        d = compare(_design(), _design(), [], [])
        assert d.verdict == "no electrical change"
        assert d.is_empty

    def test_electrical_change_without_a_finding_change(self):
        old = _design(components=[Component(ref="R1", value="10k")])
        new = _design(components=[Component(ref="R1", value="4k7")])
        d = compare(old, new, [], [])
        assert d.verdict == "electrical changes, no change in violations"


@real_revisions
class TestRealRegression:
    def test_it_reports_the_regression(self, result):
        assert result.findings.net_change == 39
        assert result.verdict == "39 more violation(s)"

    def test_the_eleven_splits_all_arrive_in_this_revision(self, result):
        introduced = {
            f.key for f in result.findings.introduced if f.rule_id == "XF001"
        }
        assert introduced == {
            "BUS_V_SENSE", "FUSE_DROP_SENSE", "MAIN_FB", "PRECHARGE_FB",
            "SAFE_VOLT_MON", "SC_FAULT_N", "SC_RESET_N", "TEMP_CONTACTOR",
            "TEMP_PRECHARGE", "TEMP_SHUNT", "WELD_MON",
        }

    def test_the_new_sheet_parts_are_seen(self, result):
        added = {c.ref for c in result.components if c.change is Change.ADDED}
        assert "F900" in added  # the fuse
        assert len(added) == 26

    def test_adding_the_fuse_resolves_the_missing_fuse_finding(self, result):
        assert any(f.rule_id == "XF007" for f in result.findings.resolved)

    def test_a_different_defect_on_the_same_rule_is_not_a_fix(self, result):
        """XF007 sits on both sides, and that is correct.

        The old revision had no fuse at all; the new one has F900 with a TBD
        rating. Those are two different defects, so one resolves and another
        appears - not one persisting finding, and not a clean fix.
        """
        resolved = [f for f in result.findings.resolved if f.rule_id == "XF007"]
        introduced = [f for f in result.findings.introduced if f.rule_id == "XF007"]
        assert [f.key for f in resolved] == ["no-fuse"]
        assert [f.key for f in introduced] == ["F900"]

    def test_a_defect_that_predates_the_revision_is_not_blamed_on_it(self, result):
        """Only one sheet is newly orphaned.

        'Control, Diagnostics & IoT' was already orphaned in the earlier
        netlist, so it belongs in unchanged. Reporting it as introduced would
        pin an older mistake on this handoff.
        """
        orphaned = {
            group: [f.key for f in items if f.rule_id == "XF005"]
            for group, items in (
                ("introduced", result.findings.introduced),
                ("unchanged", result.findings.unchanged),
            )
        }
        assert orphaned["introduced"] == ["HV Power-Path & Safety"]
        assert orphaned["unchanged"] == ["Control, Diagnostics & IoT"]

    def test_no_identity_appears_on_both_sides(self, result):
        """The invariant the summary-keyed version broke."""
        resolved = {f.identity for f in result.findings.resolved}
        introduced = {f.identity for f in result.findings.introduced}
        assert not (resolved & introduced)

    def test_every_finding_carries_a_key(self, result):
        everything = (
            result.findings.resolved
            + result.findings.introduced
            + result.findings.unchanged
        )
        assert everything
        assert [f for f in everything if not f.key] == []

    def test_reversing_the_comparison_negates_the_verdict(self):
        cfg = Config.load(CONFIG)
        old, new = readers.read(AFTER), readers.read(BEFORE)
        back = compare(old, new, run(old, cfg), run(new, cfg))
        assert back.findings.net_change == -39
        assert back.verdict == "39 fewer violation(s)"
