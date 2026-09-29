"""Accepted violations, and the ratchet that keeps them honest.

The golden case is the one that matters: baseline the 24 Sep 11:06 revision,
gate the 12:59 handoff, and the twelve new defects must be named while the
pre-existing orphaned sheet must not.
"""

import json
from pathlib import Path

import pytest

from xforge import readers
from xforge.baseline import SCHEMA, Baseline, BaselineError, Entry
from xforge.config import Config
from xforge.rules import Severity, Status, run
from xforge.rules.base import Finding

BJB = Path(r"C:\Users\TempAdmin\Desktop\BJB_ShortCircuitAdded")
BEFORE = BJB / "BJB_RealSchematic_RevC" / "Verification" / "fixed2_project.net"
AFTER = BJB / "BJB_RevC_Handoff" / "Verification" / "BJB_RevC_Netlist.net"
CONFIG = Path(__file__).parents[1] / "xforge.bjb.yaml"
FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"
TRACKED = Path(__file__).parents[1] / "xforge.bjb.baseline.json"

real_revisions = pytest.mark.skipif(
    not (BEFORE.exists() and AFTER.exists()),
    reason="the two real BJB revisions are not on this machine",
)


def _finding(rule="XF001", key="SC_FAULT_N", summary="split", status=Status.VIOLATION):
    return Finding(
        rule_id=rule,
        severity=Severity.ERROR,
        summary=summary,
        key=key,
        status=status,
    )


class TestMatching:
    def test_an_accepted_finding_is_accepted(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N")])
        assert b.accepts(_finding())

    def test_a_different_key_is_not_accepted(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N")])
        assert not b.accepts(_finding(key="WELD_MON"))

    def test_a_different_rule_on_the_same_key_is_not_accepted(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N")])
        assert not b.accepts(_finding(rule="XF002"))

    def test_rewording_the_summary_does_not_break_a_match(self):
        """The reason entries key on identity rather than prose."""
        b = Baseline.from_findings([_finding(summary="is 2 unconnected nets")])
        assert b.accepts(_finding(summary="exists as 2 separate nets"))

    def test_unaccepted_returns_only_what_is_left(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N")])
        left = b.unaccepted([_finding(), _finding(key="WELD_MON")])
        assert [f.key for f in left] == ["WELD_MON"]

    def test_passes_are_never_unaccepted(self):
        """A rule reporting success is not something to baseline."""
        ok = _finding(status=Status.PASS, key="interlock")
        assert Baseline().unaccepted([ok]) == []


class TestRatchet:
    def test_an_entry_with_nothing_to_excuse_is_stale(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N"), Entry("XF001", "GONE")])
        stale = b.stale([_finding()])
        assert [e.key for e in stale] == ["GONE"]

    def test_pruning_drops_exactly_the_stale_entries(self):
        b = Baseline([Entry("XF001", "SC_FAULT_N"), Entry("XF001", "GONE")])
        assert [e.key for e in b.pruned([_finding()]).entries] == ["SC_FAULT_N"]

    def test_pruning_keeps_the_provenance(self):
        b = Baseline([Entry("XF001", "GONE")], source="a.net", created="2026-09-29")
        p = b.pruned([])
        assert p.source == "a.net" and p.created == "2026-09-29"

    def test_a_fully_fixed_design_prunes_to_empty(self):
        b = Baseline([Entry("XF001", "A"), Entry("XF005", "B")])
        assert len(b.pruned([])) == 0


class TestScope:
    def test_only_gating_rules_are_recorded_by_default(self):
        """An entry for an advisory rule would excuse it on graduation day."""
        findings = [_finding(rule="XF001"), _finding(rule="XF002", key="dangle")]
        b = Baseline.from_findings(findings, rules={"XF001"})
        assert [e.rule for e in b.entries] == ["XF001"]

    def test_no_rule_filter_records_everything(self):
        findings = [_finding(rule="XF001"), _finding(rule="XF002", key="dangle")]
        assert len(Baseline.from_findings(findings)) == 2

    def test_entries_are_sorted_so_the_file_diffs_cleanly(self):
        findings = [
            _finding(rule="XF005", key="Zulu"),
            _finding(rule="XF001", key="Bravo"),
            _finding(rule="XF001", key="Alpha"),
        ]
        b = Baseline.from_findings(findings)
        assert [(e.rule, e.key) for e in b.entries] == [
            ("XF001", "Alpha"),
            ("XF001", "Bravo"),
            ("XF005", "Zulu"),
        ]


class TestFile:
    def test_round_trip(self, tmp_path):
        p = tmp_path / "bl.json"
        Baseline.from_findings([_finding()], source="a.net").save(p)
        back = Baseline.load(p)
        assert back.source == "a.net"
        assert back.accepts(_finding())

    def test_a_missing_file_is_an_error_not_an_empty_baseline(self, tmp_path):
        """Silently accepting nothing would turn a typo into a green build."""
        with pytest.raises(BaselineError, match="no baseline"):
            Baseline.load(tmp_path / "absent.json")

    def test_an_unknown_schema_is_refused(self, tmp_path):
        p = tmp_path / "bl.json"
        p.write_text(json.dumps({"schema": "something/9", "accepted": []}))
        with pytest.raises(BaselineError, match="schema"):
            Baseline.load(p)

    def test_an_entry_without_a_key_is_refused(self, tmp_path):
        """It could never match, so accepting the file would mislead."""
        p = tmp_path / "bl.json"
        p.write_text(json.dumps({"schema": SCHEMA, "accepted": [{"rule": "XF001"}]}))
        with pytest.raises(BaselineError, match="has no 'key'"):
            Baseline.load(p)

    def test_malformed_json_names_the_file(self, tmp_path):
        p = tmp_path / "bl.json"
        p.write_text("{not json")
        with pytest.raises(BaselineError, match="not valid JSON"):
            Baseline.load(p)


@pytest.fixture(scope="module")
def findings():
    """The tracked fixture's findings, computed once."""
    return run(readers.read(FIXTURE), Config.load(CONFIG))


class TestTrackedBaseline:
    """The baseline committed to this repo has to stay true."""

    def test_it_covers_every_gating_violation_on_the_fixture(self, findings):
        """If this fails, CI is about to go red - which is the point."""
        left = Baseline.load(TRACKED).unaccepted(
            [f for f in findings if f.rule_id in {"XF001", "XF005"}]
        )
        assert [f"{f.rule_id} {f.key}" for f in left] == []

    def test_it_has_no_stale_entries(self, findings):
        assert Baseline.load(TRACKED).stale(findings) == []

    def test_it_records_only_gating_rules(self):
        assert {e.rule for e in Baseline.load(TRACKED).entries} == {"XF001", "XF005"}

    def test_it_says_why(self):
        note = Baseline.load(TRACKED).note
        assert "sheet" in note.lower()
        assert "BJB-RevC-findings.md" in note

    def test_it_does_not_hide_a_fixable_count(self, findings):
        """13 entries, one cause. If this grows, someone widened it."""
        assert len(Baseline.load(TRACKED)) == 13


@real_revisions
class TestItWouldHaveCaughtTheRegression:
    def test_baselining_1106_still_fails_the_1259_handoff(self):
        cfg = Config.load(CONFIG)
        gating = {"XF001", "XF005"}

        old = run(readers.read(BEFORE), cfg)
        baseline = Baseline.from_findings(old, rules=gating)
        assert len(baseline) == 1  # the sheet already floating at 11:06

        new = [f for f in run(readers.read(AFTER), cfg) if f.rule_id in gating]
        unaccepted = baseline.unaccepted(new)

        assert len(unaccepted) == 12
        assert {f.key for f in unaccepted if f.rule_id == "XF005"} == {
            "HV Power-Path & Safety"
        }
        assert len({f.key for f in unaccepted if f.rule_id == "XF001"}) == 11

    def test_the_older_orphan_is_not_blamed_on_the_handoff(self):
        cfg = Config.load(CONFIG)
        gating = {"XF001", "XF005"}
        baseline = Baseline.from_findings(run(readers.read(BEFORE), cfg), rules=gating)
        new = [f for f in run(readers.read(AFTER), cfg) if f.rule_id in gating]
        assert "Control, Diagnostics & IoT" not in {
            f.key for f in baseline.unaccepted(new)
        }
