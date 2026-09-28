"""Provenance: every calculation must be able to say where it came from.

A warning backed by nothing is an opinion. These tests pin the contract that
every formula carries a source, a tier, and enough detail for an engineer to
redo the arithmetic by hand.
"""

import pytest

from xforge.physics import ampacity, formula
from xforge.physics.formula import Tier


class TestRegistry:
    def test_registry_is_populated_on_import(self):
        assert set(formula.registry()) >= {
            "ipc2221.trace",
            "ipc2221.current",
            "via.barrel_area",
            "busbar.area",
        }

    def test_unknown_id_lists_what_exists(self):
        with pytest.raises(KeyError) as exc:
            formula.get("nope")
        assert "ipc2221.trace" in str(exc.value)

    def test_every_formula_has_a_source_and_units(self):
        for fid, f in formula.registry().items():
            assert f.source.strip(), f"{fid} has no source"
            assert f.equation.strip(), f"{fid} has no equation"
            assert f.variables, f"{fid} declares no variables"
            for v in f.variables:
                assert v.unit.strip(), f"{fid}: {v.symbol} has no unit"

    def test_duplicate_registration_is_refused(self):
        with pytest.raises(ValueError):
            formula.register(formula.get("ipc2221.trace"))


class TestTiers:
    def test_only_traceable_tiers_may_gate(self):
        assert Tier.PRIMARY.may_gate
        assert Tier.PUBLIC_FORM.may_gate
        assert not Tier.SECONDARY.may_gate
        assert not Tier.CONVENTION.may_gate

    def test_ipc2221_is_gating_safe(self):
        assert formula.get("ipc2221.trace").tier.may_gate

    def test_busbar_density_is_not_gating_safe(self):
        """No standard governs busbar current density, so it must not block."""
        assert not formula.get("busbar.area").tier.may_gate

    def test_via_model_is_not_gating_safe(self):
        """No published via current table exists; the model is convention."""
        assert not formula.get("via.barrel_area").tier.may_gate

    def test_gating_safe_returns_only_a_and_b(self):
        for f in formula.gating_safe():
            assert f.tier in (Tier.PRIMARY, Tier.PUBLIC_FORM)


class TestExplanation:
    def test_explain_names_the_source_and_the_inputs(self):
        text = ampacity.required_trace(10, 20, 2.0).explain()
        assert "IPC-2221B" in text
        assert "A = (I / (k * dT^0.44))^(1/0.725)" in text
        assert "I=10 A" in text
        assert "dT=20 degC" in text

    def test_explain_states_validity_limits(self):
        text = ampacity.required_trace(1, 10).explain()
        assert "valid for" in text
        assert "ambient" in text

    def test_citation_is_one_line_with_tier(self):
        line = formula.get("ipc2221.trace").citation()
        assert "\n" not in line
        assert "public closed form" in line

    def test_functions_carry_their_formula(self):
        assert ampacity.required_trace.formula.id == "ipc2221.trace"
        assert ampacity.current_for_area.formula.id == "ipc2221.current"
        assert ampacity.required_vias.formula.id == "via.barrel_area"
        assert ampacity.busbar_area_mm2.formula.id == "busbar.area"

    def test_via_result_explains_itself(self):
        text = ampacity.required_vias(50, 0.3, 25).explain()
        assert "pi * d * t" in text
        assert "d=0.3 mm" in text


class TestConservatismIsStated:
    def test_ipc2221_declares_it_is_conservative(self):
        """The user must know this asks for more copper than IPC-2152 would."""
        notes = formula.get("ipc2221.trace").notes
        assert "IPC-2152" in notes
        assert "conservative" in notes.lower()

    def test_plane_credit_is_labelled_where_applied(self):
        assert "rule of thumb" in ampacity.required_vias(10, on_plane=True).note
