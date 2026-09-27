"""Reader dispatch and the XML netlist format."""

from pathlib import Path

import pytest

from xforge import readers
from xforge.readers import kicad_xml

FIXTURES = Path(__file__).parent / "fixtures"
SEXPR = FIXTURES / "bjb_revc.net"
XML = FIXTURES / "bjb_fixed2.xml.net"


class TestDispatch:
    def test_reads_sexpr_by_content(self):
        assert readers.read(SEXPR).name == "BJB System Architecture"

    def test_reads_xml_by_content_despite_net_extension(self):
        """Both formats are written to `.net`, so extension proves nothing."""
        assert kicad_xml.sniff(XML)
        assert readers.read(XML).name == "BJB System Architecture"

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            readers.read(FIXTURES / "nope.net")

    def test_unknown_format_names_the_file(self, tmp_path):
        bad = tmp_path / "x.net"
        bad.write_text("not a netlist at all", encoding="utf-8")
        with pytest.raises(readers.UnknownFormatError) as exc:
            readers.read(bad)
        assert "x.net" in str(exc.value)


class TestXmlReader:
    def test_header_and_census(self):
        d = kicad_xml.read(XML)
        assert d.company == "XBattery Energy Pvt. Ltd."
        c = d.census()
        assert c["components"] == 165
        assert c["nets"] == 153

    def test_pins_carry_type(self):
        d = kicad_xml.read(XML)
        assert any(p.type for n in d.nets for p in n.pins)

    def test_sheet_is_populated(self):
        d = kicad_xml.read(XML)
        assert any(c.sheet for c in d.components)

    def test_rejects_wrong_root(self, tmp_path):
        bad = tmp_path / "x.xml"
        bad.write_text('<?xml version="1.0"?><kicad_pcb/>', encoding="utf-8")
        with pytest.raises(kicad_xml.NetlistFormatError):
            kicad_xml.read(bad)
