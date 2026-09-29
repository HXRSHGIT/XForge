"""The evidence pack.

The property that matters is not that it renders. It is that it never implies
coverage it does not have: a subject nobody checked has to appear as "not
covered", and an accepted deviation has to read as open, not as cleared.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from xforge import evidence, power, readers
from xforge.baseline import Baseline, Entry
from xforge.config import Config
from xforge.evidence import OUT_OF_SCOPE, Pack, assemble
from xforge.model import Component, Design, Net
from xforge.rules import Severity, Status, run
from xforge.rules.base import Finding

FIXTURE = Path(__file__).parent / "fixtures" / "bjb_revc.net"
CONFIG = Path(__file__).parents[1] / "xforge.bjb.yaml"
TRACKED = Path(__file__).parents[1] / "xforge.bjb.baseline.json"

VOID = {"meta", "br", "hr", "img", "link", "input", "source"}


class _Wellformed(HTMLParser):
    """Enough of a parser to prove no tag was left open or crossed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"</{tag}> with nothing open")
        elif self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.stack[-1]}>")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def _parse(src: str) -> _Wellformed:
    p = _Wellformed()
    p.feed(src)
    return p


def _finding(rule="XF001", key="A", sev=Severity.ERROR, status=Status.VIOLATION):
    return Finding(
        rule_id=rule, severity=sev, summary=f"{rule} on {key}", key=key, status=status
    )


def _pack(findings=(), gating=(), baseline=None):
    d = Design(name="T", components=[Component(ref="R1")], nets=[Net("/A")])
    return Pack(
        design=d,
        findings=list(findings),
        config=Config(),
        netlist=Path("t.net"),
        digest="0" * 64,
        baseline=baseline,
        generated="2026-09-29 00:00 UTC",
        gating=set(gating),
    )


class TestVerdict:
    def test_no_gating_rule_means_no_pass_criterion(self):
        state, sentence = _pack([_finding()]).verdict
        assert state == "ADVISORY"
        assert "establishes no pass criterion" in sentence

    def test_an_unaccepted_gating_error_fails(self):
        state, _ = _pack([_finding()], gating=["XF001"]).verdict
        assert state == "FAIL"

    def test_an_accepted_gating_error_passes_but_says_so(self):
        b = Baseline([Entry("XF001", "A")])
        state, sentence = _pack([_finding()], gating=["XF001"], baseline=b).verdict
        assert state == "PASS"
        assert "1 known deviation(s) are accepted" in sentence

    def test_a_warning_from_a_gating_rule_does_not_fail(self):
        """Gating is on Errors. A warning is information, not a stop."""
        f = _finding(sev=Severity.WARNING)
        assert _pack([f], gating=["XF001"]).verdict[0] == "PASS"

    def test_a_pass_status_never_counts_against_the_verdict(self):
        f = _finding(status=Status.PASS)
        assert _pack([f], gating=["XF001"]).verdict[0] == "PASS"


class TestCoverage:
    def test_a_rule_that_could_not_run_is_not_covered(self):
        """The whole reason this section exists."""
        blocked = _finding(rule="XF008", status=Status.BLOCKED)
        rows = {c.subject: c for c in _pack([blocked]).coverage()}
        xf008 = next(c for s, c in rows.items() if s.startswith("XF008"))
        assert xf008.state == "not covered"

    def test_a_rule_that_fired_is_verified(self):
        rows = _pack([_finding()]).coverage()
        xf001 = next(c for c in rows if c.subject.startswith("XF001"))
        assert xf001.state == "verified"
        assert "1 finding" in xf001.detail

    def test_a_rule_that_passed_is_verified(self):
        rows = _pack([_finding(rule="XF010", status=Status.PASS)]).coverage()
        xf010 = next(c for c in rows if c.subject.startswith("XF010"))
        assert xf010.state == "verified"

    def test_a_silent_rule_is_only_partial(self):
        """Silence is not evidence. It may mean the rule found nothing to look
        at, which is a different statement from 'checked and clean'."""
        rows = _pack([]).coverage()
        xf001 = next(c for c in rows if c.subject.startswith("XF001"))
        assert xf001.state == "partial"

    def test_every_out_of_scope_subject_is_listed(self):
        subjects = {c.subject for c in _pack([]).coverage()}
        for name, _ in OUT_OF_SCOPE:
            assert name in subjects

    def test_insulation_is_named_as_not_covered(self):
        """The open item most likely to be assumed closed."""
        c = next(
            c for c in _pack([]).coverage() if c.subject == "Insulation coordination"
        )
        assert c.state == "not covered"
        assert "IEC 60664-1" in c.detail

    def test_low_tier_formulas_are_declared(self):
        rows = _pack([]).coverage()
        weak = next(
            c for c in rows if c.subject == "Calculations below gating trust"
        )
        assert weak.state == "partial"
        assert "may not gate" in weak.detail


class TestDigest:
    def test_it_names_exactly_what_it_read(self, tmp_path):
        p = tmp_path / "a.net"
        p.write_bytes(b"(export)")
        import hashlib

        assert evidence.digest_of(p) == hashlib.sha256(b"(export)").hexdigest()

    def test_a_changed_netlist_changes_the_digest(self, tmp_path):
        a, b = tmp_path / "a.net", tmp_path / "b.net"
        a.write_bytes(b"(export (x))")
        b.write_bytes(b"(export (y))")
        assert evidence.digest_of(a) != evidence.digest_of(b)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """The real BJB pack, rendered once."""
    design = readers.read(FIXTURE)
    cfg = Config.load(CONFIG)
    pack = assemble(
        design,
        run(design, cfg),
        cfg,
        FIXTURE,
        baseline=Baseline.load(TRACKED),
        power=power.analyse(design, cfg),
    )
    out = tmp_path_factory.mktemp("ev") / "evidence.html"
    evidence.to_html(pack, out)
    return out.read_text(encoding="utf-8")


class TestRendering:
    def test_it_is_well_formed(self, rendered):
        p = _parse(rendered)
        assert p.errors == []
        assert p.stack == []

    def test_it_is_self_contained(self, rendered):
        """It has to open identically off a USB stick or an email attachment."""
        assert re.findall(r'(?:src|href)="(?!#)([^"]+)"', rendered) == []

    def test_no_unformatted_template_leaked(self, rendered):
        body = rendered.split("</style>", 1)[1]
        assert "{" not in body and "}" not in body

    def test_no_python_repr_leaked_into_the_text(self, rendered):
        text = "".join(_parse(rendered).text)
        assert "None" not in text
        assert "<class " not in text
        assert "object at 0x" not in text

    def test_it_states_the_netlist_digest(self, rendered):
        assert evidence.digest_of(FIXTURE) in rendered

    def test_every_section_is_present(self, rendered):
        text = "".join(_parse(rendered).text)
        for heading in (
            "Design under verification",
            "Rule register and authority",
            "Accepted deviations",
            "Findings",
            "Calculation provenance",
            "Conductor requirements",
            "Coverage boundary",
        ):
            assert heading in text

    def test_accepted_deviations_read_as_open_not_cleared(self, rendered):
        text = "".join(_parse(rendered).text)
        assert "known and open" in text
        assert "not resolved" in text

    def test_it_says_it_is_not_a_certificate(self, rendered):
        assert "not a certificate" in "".join(_parse(rendered).text)

    def test_every_rule_carries_its_authority(self, rendered):
        from xforge.rules.base import registry

        for rule in registry().values():
            assert rule.source in rendered, rule.id

    def test_findings_are_marked_accepted_where_they_are(self, rendered):
        assert "ACCEPTED" in rendered

    def test_gating_rules_are_shown_as_gating(self, rendered):
        assert "GATING" in rendered


class TestRealPack:
    def test_the_bjb_pack_passes_on_its_baseline(self):
        design = readers.read(FIXTURE)
        cfg = Config.load(CONFIG)
        pack = assemble(
            design, run(design, cfg), cfg, FIXTURE, baseline=Baseline.load(TRACKED)
        )
        assert pack.verdict[0] == "PASS"
        assert pack.unaccepted == []

    def test_without_the_baseline_the_same_design_fails(self):
        """The pack must not launder a defect by omitting the baseline."""
        design = readers.read(FIXTURE)
        cfg = Config.load(CONFIG)
        pack = assemble(design, run(design, cfg), cfg, FIXTURE)
        assert pack.verdict[0] == "FAIL"
        assert len(pack.unaccepted) == 13
