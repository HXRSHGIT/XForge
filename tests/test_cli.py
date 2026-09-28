"""CLI smoke tests.

These exist because a syntax error once sat in cli.py through a full green
test run: nothing imported the module. Every subcommand is now exercised.
"""

from pathlib import Path

import pytest

from xforge import cli

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"
CONFIG = Path(__file__).parents[1] / "xforge.bjb.yaml"


def run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


class TestImports:
    def test_module_imports(self):
        """The failure this file was written for."""
        assert cli.main is not None

    def test_parser_builds(self):
        assert cli.build_parser() is not None


class TestSubcommands:
    def test_inspect(self, capsys):
        code, out = run(["inspect", str(FIXTURE)], capsys)
        assert code == cli.EXIT_OK
        assert "BJB System Architecture" in out
        assert "components" in out

    def test_rules(self, capsys):
        code, out = run(["rules"], capsys)
        assert code == cli.EXIT_OK
        assert "XF001" in out and "XF012" in out

    def test_formulas_lists_by_tier(self, capsys):
        code, out = run(["formulas"], capsys)
        assert code == cli.EXIT_OK
        assert "may gate a build" in out
        assert "advisory only" in out
        assert "ipc2221.trace" in out

    def test_formulas_explains_one(self, capsys):
        code, out = run(["formulas", "ipc2221.trace"], capsys)
        assert code == cli.EXIT_OK
        assert "IPC-2221B" in out
        assert "valid for" in out

    def test_check(self, capsys):
        code, out = run(["check", str(FIXTURE), "-c", str(CONFIG)], capsys)
        assert code == cli.EXIT_OK  # advisory: nothing gates yet
        assert "error," in out

    def test_check_verbose_renders_multiline_subjects(self, capsys):
        """A formula explanation is multi-line; every line must be indented."""
        code, out = run(["check", str(FIXTURE), "-c", str(CONFIG), "-v"], capsys)
        assert code == cli.EXIT_OK
        assert "R(T) = R0 * exp(B * (1/T - 1/T0))" in out
        for line in out.splitlines():
            if "R(T) = R0 * exp" in line:
                assert line.startswith("      "), "continuation not indented"

    def test_power(self, capsys):
        code, out = run(["power", str(FIXTURE), "-c", str(CONFIG)], capsys)
        assert code == cli.EXIT_OK
        assert "outer mm" in out
        assert "IPC-2221" in out

    def test_power_flags_what_cannot_be_a_trace(self, capsys):
        _, out = run(["power", str(FIXTURE), "-c", str(CONFIG)], capsys)
        assert "not a trace" in out
        assert "mm2" in out

    def test_power_without_declared_currents(self, capsys, tmp_path):
        cfg = tmp_path / "bare.yaml"
        cfg.write_text("project: bare\n", encoding="utf-8")
        code, out = run(["power", str(FIXTURE), "-c", str(cfg)], capsys)
        assert code == cli.EXIT_OK
        assert "No currents declared" in out


class TestExitCodes:
    def test_missing_file_is_an_error_not_a_crash(self, capsys):
        code = cli.main(["inspect", "does-not-exist.net"])
        assert code == cli.EXIT_ERROR

    def test_gate_flag_fails_on_a_gating_violation(self, capsys):
        """BJB has XF001 and XF005 errors, both gating-capable."""
        code, out = run(
            ["check", str(FIXTURE), "-c", str(CONFIG), "--gate", "-q"], capsys
        )
        assert code == cli.EXIT_FINDINGS
        assert "FAIL" in out

    def test_writes_html_and_json(self, capsys, tmp_path):
        html = tmp_path / "r.html"
        js = tmp_path / "r.json"
        run(
            ["check", str(FIXTURE), "-c", str(CONFIG), "--html", str(html),
             "--json", str(js)],
            capsys,
        )
        assert html.exists() and js.exists()
        assert "<html" in html.read_text(encoding="utf-8").lower()
        import json

        payload = json.loads(js.read_text(encoding="utf-8"))
        assert payload["schema"] == "xforge.findings/1"
        assert any(f["status"] == "pass" for f in payload["findings"])
