"""IDF board reading.

The fixture is the real Battery Junction Box exported from Allegro. A
synthetic board would not have caught the things that actually matter here:
thirteen cutouts, bottom-side placements, quoted part numbers with spaces in
them, and a units line in THOU.
"""

from pathlib import Path

import pytest

from xforge.viewer import idf
from xforge.viewer.idf import IdfError, read_board, read_library, to_scene

FIXTURES = Path(__file__).parent / "fixtures"
EMN = FIXTURES / "bjb_board.emn"


@pytest.fixture(scope="module")
def board():
    return read_board(EMN)


class TestHeader:
    def test_reads_the_generator_and_units(self, board):
        assert board.generator == "allegro_17.4"
        assert board.units == "THOU"
        assert board.created.startswith("2024/02/08")

    def test_rejects_a_file_that_is_not_idf(self, tmp_path):
        bad = tmp_path / "x.emn"
        bad.write_text("just some text\n", encoding="utf-8")
        with pytest.raises(IdfError) as exc:
            read_board(bad)
        assert "no .HEADER" in str(exc.value)

    def test_rejects_a_library_file_given_as_a_board(self, tmp_path):
        bad = tmp_path / "x.emn"
        bad.write_text(
            ".HEADER\nLIBRARY_FILE 3.0 allegro 2024/01/01.00:00:00 1\n.END_HEADER\n",
            encoding="utf-8",
        )
        with pytest.raises(IdfError) as exc:
            read_board(bad)
        assert "expected BOARD_FILE" in str(exc.value)

    def test_missing_file_names_itself(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_board(tmp_path / "nope.emn")

    def test_unknown_units_are_refused_rather_than_guessed(self, tmp_path):
        bad = tmp_path / "x.emn"
        bad.write_text(
            ".HEADER\nBOARD_FILE 3.0 tool 2024/01/01.00:00:00 1\n"
            "board.brd FURLONGS\n.END_HEADER\n",
            encoding="utf-8",
        )
        with pytest.raises(IdfError) as exc:
            read_board(bad)
        assert "FURLONGS" in str(exc.value)


class TestGeometry:
    def test_board_size_in_mm(self, board):
        """THOU in, mm out. 171 x 194 mm is a plausible BJB."""
        w, h = board.size_mm
        assert w == pytest.approx(171.3, abs=0.5)
        assert h == pytest.approx(193.6, abs=0.5)

    def test_thickness_is_a_normal_pcb(self, board):
        assert board.thickness_mm == pytest.approx(1.564, abs=0.01)

    def test_outline_has_one_boundary_and_its_cutouts(self, board):
        assert len(board.outline.outer) == 1
        assert len(board.outline.cutouts) == 13

    def test_cutouts_are_labelled_separately_from_the_boundary(self, board):
        assert all(lp.label == 0 for lp in board.outline.outer)
        assert all(lp.is_cutout for lp in board.outline.cutouts)

    def test_keepouts_are_kept_apart_from_the_board_outline(self, board):
        kinds = {o.kind for o in board.other_outlines}
        assert "ROUTE_KEEPOUT" in kinds
        assert "BOARD_OUTLINE" not in kinds


class TestPlacements:
    def test_every_component_is_read(self, board):
        assert len(board.placements) == 289

    def test_refdes_survive(self, board):
        refs = {p.refdes for p in board.placements}
        assert "R15" in refs  # the 0.1 mOhm current shunt
        assert "J7" in refs

    def test_quoted_part_numbers_with_spaces_are_handled(self, board):
        """Allegro quotes descriptions like "...DISCRETE_0.1 MOHM"."""
        shunt = next(p for p in board.placements if p.refdes == "R15")
        assert " " in shunt.part_number
        assert not shunt.part_number.startswith('"')

    def test_rotation_and_side_are_read(self, board):
        shunt = next(p for p in board.placements if p.refdes == "R15")
        assert shunt.rotation_deg == pytest.approx(270.0)
        assert shunt.side in ("TOP", "BOTTOM")

    def test_positions_are_converted_to_mm(self, board):
        """Every part must land inside the board outline, in mm."""
        x0, y0, x1, y1 = board.extents_mm
        for p in board.placements:
            assert x0 - 20 <= p.x_mm <= x1 + 20, p.refdes
            assert y0 - 20 <= p.y_mm <= y1 + 20, p.refdes


class TestLibrary:
    def test_packages_are_read_from_the_sibling_emp(self, board):
        assert len(board.packages) == 68

    def test_heights_are_plausible(self, board):
        heights = [board.height_of(p) for p in board.placements]
        assert max(heights) == pytest.approx(25.5, abs=0.2)  # the varistor
        assert min(heights) > 0

    def test_tallest_part_is_the_varistor(self, board):
        tallest = max(board.placements, key=board.height_of)
        assert tallest.refdes == "RV1"

    def test_unknown_package_still_gets_a_height(self, board):
        """A part missing from the library is drawn, not skipped."""
        from xforge.viewer.idf import Placement

        orphan = Placement(
            geometry="NOT_IN_LIBRARY", part_number="?", refdes="X1",
            x_mm=0, y_mm=0, z_mm=0, rotation_deg=0, side="TOP", status="",
        )
        assert board.height_of(orphan) > 0

    def test_library_read_alone(self):
        packages = read_library(FIXTURES / "bjb_board.emp")
        assert len(packages) == 68

    def test_missing_library_is_not_fatal(self, tmp_path):
        assert read_library(tmp_path / "nope.emp") == {}


class TestScene:
    def test_payload_is_small(self, board):
        import json

        payload = json.dumps(to_scene(board))
        # The STEP export of this board is 8.4 MB. Polygons are not.
        assert len(payload) < 300_000

    def test_geometry_is_centred_on_the_origin(self, board):
        scene = to_scene(board)
        xs = [p[0] for loop in scene["outline"] for p in loop]
        ys = [p[1] for loop in scene["outline"] for p in loop]
        assert abs((min(xs) + max(xs)) / 2) < 0.5
        assert abs((min(ys) + max(ys)) / 2) < 0.5

    def test_every_part_carries_its_refdes(self, board):
        scene = to_scene(board)
        assert all(p["ref"] for p in scene["parts"])

    def test_every_part_has_an_outline_on_this_board(self, board):
        assert to_scene(board)["stats"]["without_outline"] == 0

    def test_highlighting_marks_only_the_named_parts(self, board):
        scene = to_scene(board, highlight={"R15", "J7"})
        flagged = {p["ref"] for p in scene["parts"] if p["flagged"]}
        assert flagged == {"R15", "J7"}

    def test_highlighting_is_case_insensitive(self, board):
        scene = to_scene(board, highlight={"r15"})
        assert any(p["flagged"] and p["ref"] == "R15" for p in scene["parts"])

    def test_no_highlight_flags_nothing(self, board):
        assert not any(p["flagged"] for p in to_scene(board)["parts"])


class TestUnits:
    def test_mm_files_are_not_rescaled(self, tmp_path):
        emn = tmp_path / "m.emn"
        emn.write_text(
            ".HEADER\nBOARD_FILE 3.0 tool 2024/01/01.00:00:00 1\n"
            "b.brd MM\n.END_HEADER\n"
            ".BOARD_OUTLINE ECAD\n1.6\n"
            "0 0.0 0.0 0.0\n0 100.0 0.0 0.0\n0 100.0 50.0 0.0\n"
            "0 0.0 50.0 0.0\n0 0.0 0.0 0.0\n.END_BOARD_OUTLINE\n",
            encoding="utf-8",
        )
        board = read_board(emn)
        assert board.size_mm == pytest.approx((100.0, 50.0))
        assert board.thickness_mm == pytest.approx(1.6)

    def test_thou_conversion_constant(self):
        assert idf.THOU_TO_MM == pytest.approx(0.0254)
