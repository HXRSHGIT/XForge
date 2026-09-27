"""Reader tests, pinned against the real BJB RevC netlist.

Using the actual design as the fixture is deliberate: a synthetic netlist
would not have caught the hierarchical-sheet split that XF001 found.
"""

from pathlib import Path

import pytest

from xforge import sexp
from xforge.readers import kicad_netlist

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"


@pytest.fixture(scope="module")
def design():
    return kicad_netlist.read(FIXTURE)


class TestSexp:
    def test_atoms_and_lists(self):
        assert sexp.loads("(a b (c d))") == ["a", "b", ["c", "d"]]

    def test_quoted_string_with_escapes(self):
        assert sexp.loads(r'(path "C:\\tmp\\x.kicad_sch")') == [
            "path",
            r"C:\tmp\x.kicad_sch",
        ]

    def test_empty_list(self):
        assert sexp.loads("(groups)") == ["groups"]

    def test_unterminated_list_reports_position(self):
        with pytest.raises(sexp.SExpError) as exc:
            sexp.loads("(a (b c)")
        assert "line 1" in str(exc.value)

    def test_unbalanced_close(self):
        with pytest.raises(sexp.SExpError):
            sexp.loads(")")

    def test_helpers(self):
        tree = sexp.loads('(comp (ref "R1") (value "10k"))')
        assert sexp.head(tree) == "comp"
        assert sexp.value(tree, "ref") == "R1"
        assert sexp.value(tree, "missing", "fallback") == "fallback"


class TestKicadNetlist:
    def test_header(self, design):
        assert design.name == "BJB System Architecture"
        assert design.company == "XBattery Energy Pvt. Ltd."
        assert design.tool.startswith("Eeschema")

    def test_census_is_stable(self, design):
        # Golden numbers. If the fixture is regenerated these must be
        # updated deliberately, which is the point.
        c = design.census()
        assert c["components"] == 191
        assert c["nets"] == 188
        assert c["pins"] == 549

    def test_components_indexed_by_ref(self, design):
        mcu = design.component("U900")
        assert mcu is not None
        assert mcu.value == "STM32G0B1CETx"

    def test_pins_carry_type_and_function(self, design):
        net = design.net("/SC_FAULT_N")
        assert net is not None
        types = {p.type for p in net.pins}
        assert "open_collector" in types

    def test_placeholder_detection(self, design):
        # The connectivity model uses BJB_TBD:* sentinels on purpose.
        assert design.census()["placeholders"] > 0

    def test_nets_of_maps_ref_to_nets(self, design):
        assert any(n.name == "/SC_FAULT_N" for n in design.nets_of["U3"])

    def test_rejects_non_netlist(self, tmp_path):
        bad = tmp_path / "x.net"
        bad.write_text("(kicad_pcb (version 20241229))", encoding="utf-8")
        with pytest.raises(kicad_netlist.NetlistFormatError):
            kicad_netlist.read(bad)
