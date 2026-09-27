"""Conductor sizing: the physics, and the analysis built on it."""

import math

import pytest

from xforge.config import Config
from xforge.model import Component, Design, Net, Pin
from xforge.physics.ampacity import (
    AmpacityError,
    Layer,
    busbar_area_mm2,
    current_for_area,
    required_trace,
    required_vias,
)
from xforge.power import analyse


class TestIPC2221:
    """The formula is I = k * dT^0.44 * A^0.725, A in mil^2."""

    def test_matches_hand_calculation(self):
        """10 A, 20 C rise, external: 256 mil^2.

        (10 / (0.048 * 20^0.44))^(1/0.725)
          = (10 / 0.17930)^1.37931
          = 55.77^1.37931
          = 256.3 mil^2
        """
        r = required_trace(10, temp_rise_c=20, copper_oz=2, layer=Layer.EXTERNAL)
        assert r.area_mil2 == pytest.approx(256.3, rel=1e-3)
        assert r.width_mm == pytest.approx(2.376, rel=1e-3)

    def test_round_trip_is_exact(self):
        """Sizing for a current and reading it back must return that current."""
        for amps in (0.5, 1, 10, 100):
            for dt in (5, 10, 20, 40):
                for layer in (Layer.EXTERNAL, Layer.INTERNAL):
                    r = required_trace(amps, dt, 1.0, layer)
                    back = current_for_area(r.area_mil2, dt, layer)
                    assert back == pytest.approx(amps, rel=1e-9)

    def test_internal_needs_more_copper_than_external(self):
        ext = required_trace(5, 20, 1.0, Layer.EXTERNAL)
        int_ = required_trace(5, 20, 1.0, Layer.INTERNAL)
        assert int_.area_mil2 > ext.area_mil2
        # k halves, and area scales as (1/k)^(1/0.725).
        assert int_.area_mil2 / ext.area_mil2 == pytest.approx(
            2 ** (1 / 0.725), rel=1e-9
        )

    def test_heavier_copper_narrows_the_trace(self):
        thin = required_trace(10, 20, 1.0)
        thick = required_trace(10, 20, 2.0)
        assert thick.width_mm == pytest.approx(thin.width_mm / 2, rel=1e-9)

    def test_more_temperature_rise_allows_less_copper(self):
        assert required_trace(10, 40).area_mil2 < required_trace(10, 10).area_mil2

    def test_states_its_method(self):
        r = required_trace(1, 10)
        assert r.method == "IPC-2221"
        assert "IPC-2152" in r.note

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"current_a": 0},
            {"current_a": -1},
            {"current_a": 1, "temp_rise_c": 0},
            {"current_a": 1, "copper_oz": 0},
        ],
    )
    def test_rejects_nonsense(self, kwargs):
        with pytest.raises(AmpacityError):
            required_trace(**kwargs)


class TestVias:
    def test_count_scales_with_current(self):
        assert required_vias(10).count > required_vias(1).count

    def test_bigger_barrel_needs_fewer(self):
        small = required_vias(50, drill_mm=0.3)
        big = required_vias(50, drill_mm=0.6)
        assert big.count < small.count

    def test_plane_credit_is_flagged_as_a_rule_of_thumb(self):
        plain = required_vias(50, on_plane=False)
        on_plane = required_vias(50, on_plane=True)
        assert on_plane.per_via_a == pytest.approx(plain.per_via_a * 1.2)
        assert "rule of thumb" in on_plane.note
        assert "rule of thumb" not in plain.note

    def test_never_returns_zero_vias(self):
        assert required_vias(0.001).count == 1


class TestBusbar:
    def test_area_is_current_over_density(self):
        assert busbar_area_mm2(200, 2.0) == pytest.approx(100.0)

    def test_rejects_nonsense(self):
        with pytest.raises(AmpacityError):
            busbar_area_mm2(-1)


def _design():
    return Design(
        name="t",
        components=[Component(ref="J1", value="Conn_01x02")],
        nets=[
            Net("/HV/PACK_POS", pins=[Pin("J1", "1")]),
            Net("/HV/MAIN_COIL-", pins=[Pin("J1", "2")]),
            Net("/HV/SIGNAL", pins=[Pin("J1", "3")]),
        ],
    )


def _config(**kw):
    base = {
        "profile_name": "bms",
        "raw_stackup": {"outer_copper_oz": 2.0, "max_temp_rise_c": 20.0},
        "raw_currents": [
            {"nets": ["PACK_POS"], "continuous_a": 100.0, "peak_a": 200.0},
            {"role": "coil", "continuous_a": 2.0},
        ],
    }
    base.update(kw)
    return Config(**base)


class TestAnalysis:
    def test_matches_by_net_pattern_and_by_profile_role(self):
        report = analyse(_design(), _config())
        names = {n.net.rsplit("/", 1)[-1] for n in report.nets}
        assert names == {"PACK_POS", "MAIN_COIL-"}

    def test_nets_without_a_declared_current_are_left_alone(self):
        report = analyse(_design(), _config())
        assert not any(n.net.endswith("SIGNAL") for n in report.nets)

    def test_sizes_on_peak_not_continuous(self):
        report = analyse(_design(), _config())
        pack = next(n for n in report.nets if n.net.endswith("PACK_POS"))
        expected = required_trace(200, 20, 2.0, Layer.EXTERNAL)
        assert pack.outer.width_mm == pytest.approx(expected.width_mm)

    def test_flags_what_cannot_be_a_trace(self):
        report = analyse(_design(), _config())
        pack = next(n for n in report.nets if n.net.endswith("PACK_POS"))
        coil = next(n for n in report.nets if n.net.endswith("MAIN_COIL-"))
        assert pack.exceeds_trace_limit
        assert not coil.exceeds_trace_limit
        assert pack.busbar_mm2 == pytest.approx(100.0)

    def test_reports_declared_currents_that_matched_nothing(self):
        """A current declared for a net that does not exist is a config bug."""
        cfg = _config(
            raw_currents=[{"nets": ["NOT_A_NET"], "continuous_a": 50.0}]
        )
        report = analyse(_design(), cfg)
        assert report.nets == []
        assert len(report.unmatched_specs) == 1

    def test_netclasses_band_by_current_and_take_the_widest(self):
        report = analyse(_design(), _config())
        classes = report.netclasses
        assert "PWR_100A" in classes and "PWR_2A" in classes
        pack = next(n for n in report.nets if n.net.endswith("PACK_POS"))
        assert classes["PWR_100A"]["track_width_mm"] == pytest.approx(
            round(pack.outer.width_mm, 3)
        )

    def test_base_profile_cannot_match_a_role_it_does_not_know(self):
        """The coil spec must not silently match on a profile without coils."""
        report = analyse(_design(), _config(profile_name="base"))
        names = {n.net.rsplit("/", 1)[-1] for n in report.nets}
        assert names == {"PACK_POS"}
        assert len(report.unmatched_specs) == 1

    def test_no_declared_currents_produces_an_empty_report(self):
        report = analyse(_design(), Config(profile_name="bms"))
        assert report.nets == [] and report.unmatched_specs == []
