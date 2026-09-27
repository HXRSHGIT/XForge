"""Tests for the component and safety-path rules (XF006-XF012).

Same discipline as the connectivity tests: every rule gets a case proving it
fires, a case proving it stays quiet on the legitimate lookalike, and a golden
assertion against the real BJB netlist.
"""

from pathlib import Path

import pytest

from xforge.config import Config
from xforge.model import Component, Design, Net, Pin
from xforge.rules import Severity, Status, run

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"


@pytest.fixture(scope="module")
def bjb():
    from xforge import readers

    return readers.read(FIXTURE)


def _design(nets=(), components=()):
    return Design(name="t", components=list(components), nets=list(nets))


def _findings(design, config=None, rule_id=None):
    out = run(design, config or Config())
    return [f for f in out if rule_id is None or f.rule_id == rule_id]


class TestXF006UnspecifiedRating:
    def test_fires_on_tbd_value(self):
        d = _design(components=[Component(ref="R1", value="10k TBD")])
        assert len(_findings(d, rule_id="XF006")) == 1

    def test_escalates_for_a_protective_part(self):
        d = _design(components=[Component(ref="F1", value="Fuse (rating TBD)")])
        assert _findings(d, rule_id="XF006")[0].severity is Severity.ERROR

    def test_ordinary_part_is_only_a_warning(self):
        d = _design(components=[Component(ref="C1", value="100nF TODO")])
        assert _findings(d, rule_id="XF006")[0].severity is Severity.WARNING

    def test_silent_on_a_specified_value(self):
        d = _design(components=[Component(ref="R1", value="10k 1%")])
        assert _findings(d, rule_id="XF006") == []

    def test_golden_on_bjb(self, bjb):
        refs = sorted(f.summary.split()[0] for f in _findings(bjb, rule_id="XF006"))
        assert refs == ["F900", "R902"]


class TestXF010InterlockChain:
    def _chain(self):
        """SW1 -- A -- SW2 -- B -- SW3: a clean series interlock."""
        return _design(
            nets=[
                Net("/A", pins=[Pin("SW1", "2"), Pin("SW2", "1")]),
                Net("/B", pins=[Pin("SW2", "2"), Pin("SW3", "1")]),
            ],
            components=[
                Component(ref="SW1", value="HVIL (NC)", library_part="Switch:SW_SPST"),
                Component(ref="SW2", value="E_STOP (NC)", library_part="Switch:SW_SPST"),
                Component(ref="SW3", value="MSD (NC)", library_part="Switch:SW_SPST"),
            ],
        )

    def test_clean_chain_passes(self):
        found = _findings(self._chain(), rule_id="XF010")
        assert [f.status for f in found] == [Status.PASS]
        assert "3 switches" in found[0].summary

    def test_tap_between_contacts_is_an_error(self):
        d = self._chain()
        d.nets[0].pins.append(Pin("U1", "5"))  # a monitor tapping the chain
        found = [f for f in _findings(d, rule_id="XF010") if f.status is Status.VIOLATION]
        assert found and "third connection" in found[0].summary

    def test_switch_outside_the_chain_is_an_error(self):
        d = self._chain()
        d.components.append(
            Component(ref="SW9", value="stray (NC)", library_part="Switch:SW_SPST")
        )
        found = [f for f in _findings(d, rule_id="XF010") if f.status is Status.VIOLATION]
        assert found and "not in the chain" in found[0].summary

    def test_no_switches_reports_blocked_rather_than_passing(self):
        """Silence must not look like success when the rule could not run."""
        d = _design(nets=[Net("/X", pins=[Pin("U1", "1"), Pin("U2", "1")])])
        assert [f.status for f in _findings(d, rule_id="XF010")] == [Status.BLOCKED]

    def test_golden_on_bjb(self, bjb):
        """RevC wires HVIL -> E_STOP -> MSD -> SC-inhibit in series."""
        found = _findings(bjb, rule_id="XF010")
        assert [f.status for f in found] == [Status.PASS]
        assert "4 switches" in found[0].summary


class TestXF011CoilClamp:
    def test_fires_on_an_unclamped_coil(self):
        d = _design(
            nets=[Net("/MAIN_COIL-", pins=[Pin("J1", "3")])],
            components=[Component(ref="J1", value="Conn_01x04")],
        )
        assert len(_findings(d, rule_id="XF011")) == 1

    def test_silent_when_a_clamp_is_present(self):
        d = _design(
            nets=[Net("/MAIN_COIL-", pins=[Pin("J1", "3"), Pin("D1", "1")])],
            components=[
                Component(ref="J1", value="Conn_01x04"),
                Component(ref="D1", value="PMEG6010ER"),
            ],
        )
        assert _findings(d, rule_id="XF011") == []

    def test_does_not_match_sense_or_command_nets(self):
        """TEMP_CONTACTOR and CONTACTOR_CMD are not inductive loads.

        An earlier pattern list matched '*CONTACTOR*' and swept both in.
        """
        d = _design(
            nets=[
                Net("/TEMP_CONTACTOR", pins=[Pin("TH1", "1")]),
                Net("/CONTACTOR_CMD", pins=[Pin("U1", "16")]),
            ],
            components=[
                Component(ref="TH1", value="NTC"),
                Component(ref="U1", value="STM32G0B1CETx"),
            ],
        )
        assert _findings(d, rule_id="XF011") == []

    def test_golden_on_bjb(self, bjb):
        nets = sorted(f.summary.split("'")[1] for f in _findings(bjb, rule_id="XF011"))
        assert nets == [
            "COIL_ENABLE_HW",
            "COIL_RETURN",
            "COIL_SUPPLY+",
            "COIL_SUPPLY+_RET",
            "MAIN_COIL-",
            "PRECHARGE_COIL-",
        ]


class TestXF012ThermistorBias:
    def test_fires_without_a_resistor(self):
        d = _design(
            nets=[
                Net("/TEMP", pins=[Pin("TH1", "1"), Pin("J1", "1")]),
                Net("GND", pins=[Pin("TH1", "2")]),
            ],
            components=[
                Component(
                    ref="TH1",
                    value="NTC_SHUNT",
                    library_part="Device:Thermistor_NTC",
                ),
                Component(ref="J1", value="Conn_01x02"),
            ],
        )
        assert len(_findings(d, rule_id="XF012")) == 1

    def test_silent_with_a_divider(self):
        d = _design(
            nets=[
                Net("/TEMP", pins=[Pin("TH1", "1"), Pin("R1", "2")]),
                Net("GND", pins=[Pin("TH1", "2")]),
            ],
            components=[
                Component(
                    ref="TH1",
                    value="NTC_SHUNT",
                    library_part="Device:Thermistor_NTC",
                ),
                Component(ref="R1", value="10k"),
            ],
        )
        assert _findings(d, rule_id="XF012") == []

    def test_connector_is_not_mistaken_for_a_thermistor(self):
        """J914's description reads 'Power-path NTC harness'. It is a connector."""
        d = _design(
            nets=[Net("/TEMP", pins=[Pin("J914", "1")])],
            components=[
                Component(
                    ref="J914",
                    value="Conn_01x04",
                    library_part="Connector_Generic:Conn_01x04",
                    description="Power-path NTC harness; use specified curve/value",
                )
            ],
        )
        assert _findings(d, rule_id="XF012") == []

    def test_golden_on_bjb(self, bjb):
        refs = sorted(f.summary.split()[0] for f in _findings(bjb, rule_id="XF012"))
        assert refs == ["TH900", "TH901", "TH902"]


class TestClassification:
    def test_designator_beats_prose(self, bjb):
        """A connector stays a connector whatever its description says.

        J911 is described as a 'Protected HV port to rated external
        switchgear' and J914 as a 'Power-path NTC harness'. Substring
        matching on those read them as a switch and a thermistor.
        """
        assert bjb.component("J911").kinds() == {"connector"}
        assert bjb.component("J914").kinds() == {"connector"}

    def test_real_parts_classify(self, bjb):
        assert bjb.component("SW900").is_kind("switch")
        assert bjb.component("TH900").is_kind("thermistor")
        assert bjb.component("D2").is_clamp
        assert bjb.component("Z1").is_clamp
        assert bjb.component("F900").is_kind("fuse")
        assert bjb.component("U903").is_kind("isolator")
