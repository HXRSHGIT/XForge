"""STEP -> GLB: the cache has to be correct, and the missing-OCC path has to
fail cleanly rather than leaking an ImportError traceback at some random
call site downstream.

`_load_and_tessellate` is monkeypatched for the cache and error-handling
tests so they run identically whether or not `cadquery-ocp` is actually
importable in this environment - the geometry kernel is not what those
tests are checking. The real end-to-end test against the small fixture is
separate and skips itself if OpenCASCADE cannot be loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from xforge.viewer import step

FIXTURES = Path(__file__).parent / "fixtures"
MC33772C = FIXTURES / "MC33772C.step"

BJB_BOARD = Path(
    r"C:\Users\TempAdmin\Desktop\BJB_ShortCircuitAdded\RDBESS772BJBEVB-Design-Files"
    r"\BJB\Fabrication\LAY-91659_3D\LAY-91659.stp"
)


def _occ_importable() -> bool:
    try:
        import OCP.STEPControl  # noqa: F401
    except ImportError:
        return False
    return True


OCC_AVAILABLE = _occ_importable()


def _fake_tessellate(step_path, linear_deflection, angular_deflection):
    """Stand-in for `_load_and_tessellate`: one triangle, deterministic bbox."""
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2)]
    return vertices, faces, 1, (1.0, 1.0, 0.0)


class TestImportGuard:
    """cadquery-ocp missing (or, as on this machine, blocked by Smart App
    Control - either way `import OCP` raises ImportError) must not leak a
    raw traceback."""

    def test_missing_ocp_raises_actionable_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "OCP", None)
        target = tmp_path / "fake.step"
        target.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")

        with pytest.raises(RuntimeError) as exc:
            step.convert(target)

        assert "viewer" in str(exc.value)
        assert "pip install" in str(exc.value)
        # the real cause travels with it rather than being swallowed
        assert isinstance(exc.value.__cause__, ImportError)

    def test_missing_ocp_error_does_not_touch_the_filesystem_first(self, tmp_path, monkeypatch):
        """A file that doesn't exist should fail as FileNotFoundError, not
        get past that check and only then discover OCP is missing."""
        monkeypatch.setitem(sys.modules, "OCP", None)
        with pytest.raises(FileNotFoundError):
            step.convert(tmp_path / "nope.step")

    def test_info_needs_no_occ_at_all(self, monkeypatch):
        """info() must work even when OCP cannot be imported - it never tries."""
        monkeypatch.setitem(sys.modules, "OCP", None)
        result = step.info(MC33772C)
        assert result["name"]


class TestCache:
    def test_first_call_tessellates_and_second_call_is_cached(self, tmp_path, monkeypatch):
        calls = []

        def counting_fake(step_path, linear_deflection, angular_deflection):
            calls.append(1)
            return _fake_tessellate(step_path, linear_deflection, angular_deflection)

        monkeypatch.setattr(step, "_load_and_tessellate", counting_fake)

        first = step.convert(MC33772C, out_dir=tmp_path)
        assert first.cached is False
        assert len(calls) == 1
        assert first.glb.is_file()
        assert first.triangles == 1
        assert first.solids == 1
        assert first.bbox_mm == (1.0, 1.0, 0.0)
        assert first.glb_bytes > 0
        assert first.source_bytes == MC33772C.stat().st_size

        second = step.convert(MC33772C, out_dir=tmp_path)
        assert second.cached is True
        assert len(calls) == 1  # not re-tessellated
        assert second.glb == first.glb
        assert second.triangles == first.triangles
        assert second.solids == first.solids
        assert second.bbox_mm == first.bbox_mm
        assert second.glb_bytes == first.glb_bytes

    def test_force_bypasses_the_cache(self, tmp_path, monkeypatch):
        calls = []

        def counting_fake(step_path, linear_deflection, angular_deflection):
            calls.append(1)
            return _fake_tessellate(step_path, linear_deflection, angular_deflection)

        monkeypatch.setattr(step, "_load_and_tessellate", counting_fake)

        step.convert(MC33772C, out_dir=tmp_path)
        result = step.convert(MC33772C, out_dir=tmp_path, force=True)
        assert result.cached is False
        assert len(calls) == 2

    def test_different_deflection_is_a_different_cache_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(step, "_load_and_tessellate", _fake_tessellate)

        coarse = step.convert(MC33772C, out_dir=tmp_path, linear_deflection=0.5)
        fine = step.convert(MC33772C, out_dir=tmp_path, linear_deflection=0.05)
        assert coarse.glb != fine.glb
        assert coarse.glb.is_file() and fine.glb.is_file()

    def test_different_source_content_is_a_different_cache_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(step, "_load_and_tessellate", _fake_tessellate)

        a = tmp_path / "a.step"
        b = tmp_path / "b.step"
        a.write_bytes(MC33772C.read_bytes())
        b.write_bytes(MC33772C.read_bytes() + b"\n")  # one byte different

        result_a = step.convert(a, out_dir=tmp_path)
        result_b = step.convert(b, out_dir=tmp_path)
        assert result_a.glb != result_b.glb

    def test_missing_source_file_raises_cleanly(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            step.convert(tmp_path / "does_not_exist.step")


class TestInfo:
    def test_reads_the_mc33772c_fixture_header(self):
        result = step.info(MC33772C)
        assert result["name"] == "LQFP-48-1EP_7x7mm_P0.5mm_EP3.6x3.6mm.step"
        assert result["originating_system"] == "kicad StepUp"
        assert result["author"] == ["kicad StepUp", "ksu"]
        assert "214" in result["schema"][0]

    def test_rejects_a_non_step_file(self, tmp_path):
        junk = tmp_path / "not_a_step.txt"
        junk.write_text("this is not a STEP file, just some text\n" * 50)
        with pytest.raises(ValueError, match="ISO-10303-21"):
            step.info(junk)

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            step.info(tmp_path / "nope.step")

    @pytest.mark.skipif(not BJB_BOARD.exists(), reason="real BJB board STEP not present on this machine")
    def test_reads_the_real_bjb_board_header(self):
        """Golden assertion against the real Battery Junction Box export."""
        result = step.info(BJB_BOARD)
        assert result["name"] == "LAY-91659"
        assert result["originating_system"] == "allegro_17.4S033"
        assert result["author"] == ["111116"]
        assert "214" in result["schema"][0]


@pytest.mark.skipif(not OCC_AVAILABLE, reason="cadquery-ocp not importable in this environment")
class TestRealConversion:
    """End-to-end against the small real fixture. Skipped, not faked, when
    OpenCASCADE cannot be loaded - see the handoff report for why that is
    the case on this particular machine (Smart App Control)."""

    def test_converts_the_real_fixture(self, tmp_path):
        result = step.convert(MC33772C, out_dir=tmp_path)
        assert result.cached is False
        assert result.solids >= 1
        assert result.triangles > 0
        assert all(extent > 0 for extent in result.bbox_mm)
        assert result.glb.is_file()
        assert result.glb_bytes > 0

    @pytest.mark.skipif(not BJB_BOARD.exists(), reason="real BJB board STEP not present on this machine")
    def test_converts_the_real_bjb_board(self, tmp_path):
        result = step.convert(BJB_BOARD, out_dir=tmp_path)
        assert result.solids > 1  # a populated board, not a single part
        assert result.triangles > 0
        assert all(extent > 0 for extent in result.bbox_mm)
