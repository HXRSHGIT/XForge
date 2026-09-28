"""The local app: part normalisation, vendoring, and the HTTP surface.

Anything that talks to a supplier is marked `network` and skipped by default,
so the suite stays runnable offline and in CI. Run them with:
    pytest -m network
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from xforge.ui import parts
from xforge.ui.parts import Library, Part, PriceBreak
from xforge.ui.server import AppState, Handler

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"

_ROW = {
    "lcsc": "C2862742",
    "name": "TI BQ76952PFBR",
    "model": "BQ76952PFBR",
    "brand": "Texas Instruments",
    "package": "TQFP-48(7x7)",
    "category": "Battery Management",
    "stock": 10236,
    "type": "Extended",
    "price": 3.2788,
    "price_breaks": [
        {"qty": 1, "price": 3.2788},
        {"qty": 10, "price": 2.7997},
        {"qty": 100, "price": 2.1907},
    ],
    "min_qty": 1,
    "description": "Battery management IC",
    "datasheet": "https://example.invalid/ds.pdf",
    "url": "https://example.invalid/part",
}


class TestPartNormalisation:
    def test_maps_supplier_fields_to_our_own(self):
        p = parts._part_from_row(_ROW)
        assert p.lcsc == "C2862742"
        assert p.mpn == "BQ76952PFBR"
        assert p.brand == "Texas Instruments"
        assert p.package == "TQFP-48(7x7)"
        assert p.stock == 10236
        assert p.orderable

    def test_basic_flag_reads_the_supplier_type(self):
        assert not parts._part_from_row(_ROW).basic
        assert parts._part_from_row({**_ROW, "type": "Basic"}).basic

    def test_price_breaks_are_sorted_and_queryable(self):
        p = parts._part_from_row(_ROW)
        assert [b.qty for b in p.price_breaks] == [1, 10, 100]
        assert p.price_at(1) == pytest.approx(3.2788)
        assert p.price_at(50) == pytest.approx(2.7997)  # the qty-10 break
        assert p.price_at(5000) == pytest.approx(2.1907)

    def test_price_at_falls_back_when_below_every_break(self):
        p = Part(lcsc="C1", mpn="m", brand="b", package="p", price=9.0)
        assert p.price_at(1) == 9.0

    def test_zero_stock_is_not_orderable(self):
        assert not parts._part_from_row({**_ROW, "stock": 0}).orderable

    def test_missing_fields_do_not_crash(self):
        p = parts._part_from_row({"lcsc": "C9"})
        assert p.lcsc == "C9" and p.stock == 0 and p.price is None


class TestLibrary:
    def test_empty_project_has_no_parts(self, tmp_path):
        assert Library(tmp_path).load() == {}
        assert not Library(tmp_path).has("C1")

    def test_lockfile_round_trip(self, tmp_path):
        lib = Library(tmp_path)
        lib.save({"C2862742": {"mpn": "BQ76952PFBR", "files": ["a.kicad_sym"]}})
        assert lib.has("C2862742")
        assert lib.load()["C2862742"]["mpn"] == "BQ76952PFBR"

    def test_lockfile_declares_its_schema(self, tmp_path):
        lib = Library(tmp_path)
        lib.save({})
        payload = json.loads(lib.lockfile.read_text(encoding="utf-8"))
        assert payload["schema"] == "xforge.parts.lock/1"

    def test_corrupt_lockfile_says_which_file(self, tmp_path):
        lib = Library(tmp_path)
        lib.lockfile.write_text("{not json", encoding="utf-8")
        with pytest.raises(parts.PartsError) as exc:
            lib.load()
        assert "parts.lock.json" in str(exc.value)

    def test_has_is_case_insensitive(self, tmp_path):
        lib = Library(tmp_path)
        lib.save({"C2862742": {}})
        assert lib.has("c2862742")


class TestSearchGuards:
    def test_empty_query_does_not_call_the_supplier(self, monkeypatch):
        def explode():
            raise AssertionError("should not have been called")

        monkeypatch.setattr(parts, "_api", explode)
        assert parts.search("   ") == (0, [])

    def test_missing_extra_gives_an_actionable_message(self, monkeypatch):
        def no_extra():
            raise parts.SupplierUnavailable(
                "Part search needs the 'parts' extra. Install it with:\n"
                '    pip install -e ".[parts]"'
            )

        monkeypatch.setattr(parts, "_api", no_extra)
        with pytest.raises(parts.SupplierUnavailable) as exc:
            parts.search("anything")
        assert "pip install" in str(exc.value)

    def test_supplier_failure_is_wrapped_not_leaked(self, monkeypatch):
        class Boom:
            def search_jlcpcb_components(self, **kw):
                raise TimeoutError("connection reset")

        monkeypatch.setattr(parts, "_api", lambda: Boom())
        with pytest.raises(parts.PartsError) as exc:
            parts.search("bq76952")
        assert "TimeoutError" in str(exc.value)

    def test_unexpected_shape_is_reported(self, monkeypatch):
        class Odd:
            def search_jlcpcb_components(self, **kw):
                return ["not", "a", "dict"]

        monkeypatch.setattr(parts, "_api", lambda: Odd())
        with pytest.raises(parts.PartsError):
            parts.search("x")

    def test_detail_rejects_an_empty_id(self):
        with pytest.raises(parts.PartsError):
            parts.detail("")


# ── HTTP surface ──────────────────────────────────────────────────────


@pytest.fixture
def server(tmp_path):
    """A real server on an ephemeral port, so routing is exercised for real."""

    class Bound(Handler):
        pass

    Bound.state = AppState(project=tmp_path, netlist=FIXTURE, config=None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Bound)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


class TestHttp:
    def test_status_reports_the_project(self, server, tmp_path):
        code, body = get(server, "/api/status")
        assert code == 200
        assert body["project"] == str(tmp_path)
        assert body["vendored"] == 0

    def test_index_is_served(self, server):
        with urllib.request.urlopen(server + "/", timeout=15) as r:
            assert r.status == 200
            assert b"<title>xforge</title>" in r.read()

    def test_static_assets_are_served(self, server):
        for asset in ("/app.css", "/app.js"):
            with urllib.request.urlopen(server + asset, timeout=15) as r:
                assert r.status == 200

    def test_path_traversal_is_refused(self, server):
        """The server hands out design files; it must not hand out the repo."""
        code, _ = get(server, "/../pyproject.toml")
        assert code == 404

    def test_unknown_route_is_json_not_a_stack_trace(self, server):
        code, body = get(server, "/api/nope")
        assert code == 404
        assert "error" in body

    def test_check_runs_the_rules_over_the_loaded_netlist(self, server):
        code, body = get(server, "/api/check")
        assert code == 200
        assert body["design"] == "BJB System Architecture"
        assert any(f["rule"] == "XF001" for f in body["findings"])
        assert any(f["status"] == "pass" for f in body["findings"])

    def test_model_info_without_a_model_explains_itself(self, server):
        code, body = get(server, "/api/model/info")
        assert code == 404
        assert "hint" in body and "--model" in body["hint"]


# ── live supplier ─────────────────────────────────────────────────────


@pytest.mark.network
class TestLive:
    def test_search_returns_the_ti_part(self):
        total, found = parts.search("BQ76952", page_size=10)
        assert total > 0
        assert any(p.mpn == "BQ76952PFBR" and p.stock > 0 for p in found)

    def test_detail_reports_3d_availability(self):
        info = parts.detail("C2862742")
        assert info["mpn"] == "BQ76952PFBR"
        assert info["has_3d"] is True

    def test_vendoring_writes_a_usable_kicad_symbol(self, tmp_path):
        record = Library(tmp_path).vendor("C2862742")
        sym = tmp_path / "parts" / "C2862742" / "C2862742.kicad_sym"
        assert sym.exists()
        # A BQ76952 in TQFP-48 has 48 pins; a symbol with fewer is broken.
        assert sym.read_text(encoding="utf-8").count("(pin ") == 48
        assert Library(tmp_path).has("C2862742")
        assert record.mpn == "BQ76952PFBR"
