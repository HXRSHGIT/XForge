"""Rule tests.

Each rule gets a synthetic case proving it fires, a synthetic case proving
it does NOT fire on the legitimate lookalike, and a golden assertion against
the real BJB netlist so the false-positive rate cannot drift silently.
"""

from pathlib import Path

import pytest

from xforge.config import Config, Domain
from xforge.model import Component, Design, Net, Pin
from xforge.readers import kicad_netlist
from xforge.rules import Severity, Status, run

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"


@pytest.fixture(scope="module")
def bjb():
    return kicad_netlist.read(FIXTURE)


def _design(nets, components=()):
    return Design(name="t", components=list(components), nets=list(nets))


def _findings(design, config=None, rule_id=None):
    out = run(design, config or Config())
    return [f for f in out if rule_id is None or f.rule_id == rule_id]


class TestXF001SignalSplit:
    def test_fires_when_one_name_is_two_nets(self):
        d = _design(
            [
                Net("/SheetA/FAULT_N", pins=[Pin("J1", "1")]),
                Net("/SheetB/FAULT_N", pins=[Pin("U1", "5"), Pin("R1", "2")]),
            ]
        )
        found = _findings(d, rule_id="XF001")
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR

    def test_ignores_power_rails(self):
        d = _design(
            [
                Net("/SheetA/GND", pins=[Pin("U1", "1")]),
                Net("GND", pins=[Pin("U2", "1")]),
            ]
        )
        assert _findings(d, rule_id="XF001") == []

    def test_ignores_all_no_connect(self):
        d = _design(
            [
                Net("/A/SPARE", pins=[Pin("U1", "1", type="passive+no_connect")]),
                Net("/B/SPARE", pins=[Pin("U2", "1", type="passive+no_connect")]),
            ]
        )
        assert _findings(d, rule_id="XF001") == []

    def test_golden_on_bjb(self, bjb):
        """The BJB handoff netlist splits exactly these 11 signals."""
        names = sorted(
            f.summary.split("'")[1] for f in _findings(bjb, rule_id="XF001")
        )
        assert names == [
            "BUS_V_SENSE",
            "FUSE_DROP_SENSE",
            "MAIN_FB",
            "PRECHARGE_FB",
            "SAFE_VOLT_MON",
            "SC_FAULT_N",
            "SC_RESET_N",
            "TEMP_CONTACTOR",
            "TEMP_PRECHARGE",
            "TEMP_SHUNT",
            "WELD_MON",
        ]


class TestXF002Dangling:
    def test_fires_on_single_pin_net(self):
        d = _design([Net("/A/SIG", pins=[Pin("U1", "3", type="bidirectional")])])
        assert len(_findings(d, rule_id="XF002")) == 1

    def test_silent_on_explicit_no_connect(self):
        d = _design([Net("/A/SIG", pins=[Pin("U1", "3", type="output+no_connect")])])
        assert _findings(d, rule_id="XF002") == []

    def test_respects_expected_dangling_config(self):
        d = _design([Net("/A/TP_SPARE", pins=[Pin("TP1", "1", type="passive")])])
        cfg = Config(expected_dangling=["TP_*"])
        assert _findings(d, cfg, rule_id="XF002") == []


class TestXF008BarrierCrossing:
    def _cfg(self):
        return Config(
            domains=[
                Domain(name="HV", nets=["PACK_*"], working_voltage=800.0),
                Domain(name="LV", nets=["CTRL_*"], working_voltage=12.0),
            ]
        )

    def test_errors_on_undeclared_non_isolator(self):
        d = _design(
            [
                Net("/PACK_POS", pins=[Pin("U1", "1")]),
                Net("/CTRL_EN", pins=[Pin("U1", "8")]),
            ],
            [Component(ref="U1", value="74HC00")],
        )
        found = [f for f in _findings(d, self._cfg(), rule_id="XF008")
                 if f.status is Status.VIOLATION]
        assert len(found) == 1
        assert found[0].severity is Severity.ERROR

    def test_declared_crossing_passes(self):
        cfg = self._cfg()
        cfg.crossings = ["U1"]
        d = _design(
            [
                Net("/PACK_POS", pins=[Pin("U1", "1")]),
                Net("/CTRL_EN", pins=[Pin("U1", "8")]),
            ],
            [Component(ref="U1", value="ISO1050DUB")],
        )
        found = _findings(d, cfg, rule_id="XF008")
        assert [f.status for f in found] == [Status.PASS]

    def test_recognised_isolator_is_advisory_not_error(self):
        d = _design(
            [
                Net("/PACK_POS", pins=[Pin("U1", "1")]),
                Net("/CTRL_EN", pins=[Pin("U1", "8")]),
            ],
            [Component(ref="U1", value="ISO1050DUB")],
        )
        found = [f for f in _findings(d, self._cfg(), rule_id="XF008")
                 if f.status is Status.VIOLATION]
        assert len(found) == 1
        assert found[0].severity is Severity.ADVISORY

    def test_does_not_infer_domains_transitively(self):
        """A ground shared with an HV part must not become an HV net.

        This is the false positive the first implementation had: inferring
        domain membership through components made every ground bridge
        everything.
        """
        d = _design(
            [
                Net("/PACK_POS", pins=[Pin("U1", "1")]),
                Net("/CTRL_EN", pins=[Pin("U2", "1")]),
                Net("GND", pins=[Pin("U1", "2"), Pin("U2", "2")]),
            ],
            [Component(ref="U1"), Component(ref="U2")],
        )
        violations = [f for f in _findings(d, self._cfg(), rule_id="XF008")
                      if f.status is Status.VIOLATION]
        assert violations == []

    def test_reports_blocked_without_two_domains(self):
        d = _design([Net("/PACK_POS", pins=[Pin("U1", "1")])])
        found = _findings(d, Config(), rule_id="XF008")
        assert [f.status for f in found] == [Status.BLOCKED]


class TestSuiteLevel:
    def test_bjb_finding_totals_are_pinned(self, bjb):
        """Golden totals. A change here is a change in behaviour."""
        cfg = Config.load(Path(__file__).parents[1] / "xforge.bjb.yaml")
        found = run(bjb, cfg)
        violations = [f for f in found if f.status is Status.VIOLATION]
        counts = {
            s.label: sum(1 for f in violations if f.severity is s) for s in Severity
        }
        # 11 XF001 splits + 2 XF005 orphaned sheets + 2 XF006 TBD ratings.
        assert counts["Error"] == 15
        # 47 XF002 dangling + 6 XF011 unclamped coils + 3 XF012 thermistors.
        assert counts["Warning"] == 56
        # XF008 is silent on RevC by construction: with both sheets orphaned
        # (XF005) nothing crosses a domain boundary because nothing crosses
        # anything. It becomes meaningful once the sheet pins are wired.
        assert counts["Advisory"] == 0
        # XF008 "nothing bridges the domains" and XF010 "chain continuous".
        assert sum(1 for f in found if f.status is Status.PASS) == 2

    def test_every_rule_cites_a_source(self):
        from xforge.rules import registry

        for rid, r in registry().items():
            assert r.source.strip(), f"{rid} has no cited source"


class TestXF005OrphanedSheet:
    def test_fires_on_sheet_with_no_external_net(self):
        d = _design(
            [
                Net("/Alone/SIG", pins=[Pin("U9", "1"), Pin("R9", "1")]),
                Net("/Main/OTHER", pins=[Pin("U1", "1"), Pin("U2", "1")]),
            ],
            [
                Component(ref="U9", sheet="Alone"),
                Component(ref="R9", sheet="Alone"),
                Component(ref="U1", sheet="Main"),
                Component(ref="U2", sheet="Main"),
            ],
        )
        found = _findings(d, rule_id="XF005")
        assert len(found) == 2  # neither sheet touches the other
        assert {f.summary.split("'")[1] for f in found} == {"Alone", "Main"}

    def test_silent_when_sheets_share_a_net(self):
        d = _design(
            [Net("SHARED", pins=[Pin("U9", "1"), Pin("U1", "1")])],
            [Component(ref="U9", sheet="A"), Component(ref="U1", sheet="B")],
        )
        assert _findings(d, rule_id="XF005") == []

    def test_mechanical_only_sheet_is_allowed_to_float(self):
        d = _design(
            [
                Net("/Mech/NC", pins=[Pin("H1", "1")]),
                Net("/Main/A", pins=[Pin("U1", "1"), Pin("U2", "1")]),
                Net("/Main/B", pins=[Pin("U1", "2"), Pin("U3", "1")]),
            ],
            [
                Component(ref="H1", sheet="Mech"),
                Component(ref="U1", sheet="Main"),
                Component(ref="U2", sheet="Main"),
                Component(ref="U3", sheet="Main"),
            ],
        )
        sheets = {f.summary.split("'")[1] for f in _findings(d, rule_id="XF005")}
        assert "Mech" not in sheets

    def test_golden_on_bjb(self, bjb):
        """RevC orphans exactly the two sheets added on 24 Sep."""
        found = _findings(bjb, rule_id="XF005")
        assert {f.summary.split("'")[1] for f in found} == {
            "Control, Diagnostics & IoT",
            "HV Power-Path & Safety",
        }
