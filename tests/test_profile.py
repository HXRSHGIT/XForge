"""Profile loading, stacking, and the not-evaluable contract.

The point of profiles is that a rule written for one board does not silently
fail to apply to the next one. These tests pin that contract.
"""

import pytest

from xforge import profile
from xforge.config import Config
from xforge.model import Component, Design, Net, Pin
from xforge.rules import Status, run


class TestLoading:
    def test_both_shipped_profiles_load(self):
        assert set(profile.available()) >= {"base", "bms"}

    def test_bms_extends_base(self):
        assert profile.load("bms").lineage == ["base", "bms"]

    def test_unknown_profile_lists_what_exists(self):
        with pytest.raises(profile.ProfileError) as exc:
            profile.load("nope")
        assert "base" in str(exc.value) and "bms" in str(exc.value)


class TestMerging:
    def test_lists_concatenate_rather_than_replace(self):
        """A project adding one pattern must not discard the profile's."""
        merged = profile.merge(
            {"net_roles": {"coil": ["*COIL*"]}},
            {"net_roles": {"coil": ["*K?_DRV*"]}},
        )
        assert merged["net_roles"]["coil"] == ["*COIL*", "*K?_DRV*"]

    def test_merge_deduplicates(self):
        merged = profile.merge({"a": ["x", "y"]}, {"a": ["y", "z"]})
        assert merged["a"] == ["x", "y", "z"]

    def test_dicts_merge_key_wise(self):
        merged = profile.merge(
            {"designators": {"R": "resistor"}}, {"designators": {"K": "relay"}}
        )
        assert merged["designators"] == {"R": "resistor", "K": "relay"}

    def test_bms_inherits_base_designators(self):
        assert profile.load("bms").designators["R"] == "resistor"

    def test_project_overrides_reach_the_profile(self):
        prof = profile.load("bms", {"net_roles": {"coil": ["*PUMP_DRV*"]}})
        assert "*PUMP_DRV*" in prof.patterns_for("coil")
        assert "*COIL*" in prof.patterns_for("coil")  # base kept


class TestVocabulary:
    def test_base_knows_no_domain_roles(self):
        base = profile.load("base")
        assert not base.knows_role("coil")
        assert not base.knows_role("interlock")
        assert base.knows_role("power")  # generic, so base has it

    def test_bms_knows_pack_roles(self):
        bms = profile.load("bms")
        for role in ("coil", "interlock", "current_sense", "cell_tap"):
            assert bms.knows_role(role), role

    def test_role_matches_leaf_and_full_path(self):
        bms = profile.load("bms")
        assert bms.net_has_role(Net("/HV Power-Path & Safety/MAIN_COIL-"), "coil")
        assert bms.net_has_role(Net("MAIN_COIL-"), "coil")

    def test_description_never_feeds_classification(self):
        """Prose written for a human must not decide what a part is."""
        bms = profile.load("bms")
        part = Component(
            ref="J914",
            value="Conn_01x04",
            library_part="Connector_Generic:Conn_01x04",
            description="Power-path NTC harness; use specified curve/value",
        )
        assert bms.kinds(part) == {"connector"}

    def test_authoritative_prefix_wins_over_text(self):
        bms = profile.load("bms")
        part = Component(ref="J1", value="relay switch contactor thing")
        assert bms.kinds(part) == {"connector"}

    def test_non_authoritative_prefix_still_uses_text(self):
        bms = profile.load("bms")
        part = Component(ref="U7", value="ISO1050DUB")
        kinds = bms.kinds(part)
        assert "isolator" in kinds and "can_transceiver" in kinds


class TestNotEvaluableContract:
    """A rule that cannot look must not read as a rule that found nothing."""

    def _coil_design(self):
        return Design(
            name="t",
            components=[Component(ref="J1", value="Conn_01x04")],
            nets=[Net("/MAIN_COIL-", pins=[Pin("J1", "3")])],
        )

    def test_base_profile_blocks_rather_than_passes(self):
        found = [
            f
            for f in run(self._coil_design(), Config(profile_name="base"))
            if f.rule_id == "XF011"
        ]
        assert [f.status for f in found] == [Status.BLOCKED]

    def test_bms_profile_evaluates_the_same_design(self):
        found = [
            f
            for f in run(self._coil_design(), Config(profile_name="bms"))
            if f.rule_id == "XF011"
        ]
        assert [f.status for f in found] == [Status.VIOLATION]

    def test_known_role_with_no_matching_nets_is_still_blocked(self):
        """Knowing how to look and finding nothing is not the same as a pass."""
        design = Design(
            name="t",
            components=[Component(ref="R1", value="10k")],
            nets=[Net("/SIG", pins=[Pin("R1", "1"), Pin("R1", "2")])],
        )
        found = [
            f
            for f in run(design, Config(profile_name="bms"))
            if f.rule_id == "XF011"
        ]
        assert [f.status for f in found] == [Status.BLOCKED]

    def test_severity_override_cannot_promote_a_pass(self):
        """Config must not be able to turn a pass into a failure."""
        from xforge.rules import Severity

        cfg = Config(
            profile_name="bms", severity_overrides={"XF010": Severity.ERROR}
        )
        design = Design(
            name="t",
            components=[
                Component(ref="SW1", library_part="Switch:SW_SPST"),
                Component(ref="SW2", library_part="Switch:SW_SPST"),
            ],
            nets=[Net("/A", pins=[Pin("SW1", "2"), Pin("SW2", "1")])],
        )
        found = [f for f in run(design, cfg) if f.rule_id == "XF010"]
        assert [f.status for f in found] == [Status.PASS]
        assert found[0].severity is Severity.INFO
