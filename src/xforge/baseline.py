"""Accepted violations, so gating can be switched on before the board is clean.

Turning a checker on against an existing design fails immediately, because
existing designs have existing defects. The usual responses are both bad: keep
everything advisory forever and watch the team stop reading it, or gate and
watch the team disable it.

A baseline is the third option. It records the violations that are known and
accepted right now. Gating then fails only on violations that are *not* in the
baseline - so a pre-existing defect does not block anyone, and a newly
introduced one does.

The baseline is a ratchet, not an amnesty. Entries that no longer match any
finding are reported as stale so the file shrinks as the design is fixed, and
`xforge baseline --prune` removes them.

Entries are matched on a finding's identity - (rule_id, key) - not on its
summary text, so a baseline survives a reworded message and does not silently
absorb a different defect that happens to read the same.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from xforge.rules.base import Finding, Status

SCHEMA = "xforge.baseline/1"


@dataclass(frozen=True)
class Entry:
    """One accepted violation."""

    rule: str
    key: str
    severity: str = ""
    summary: str = ""
    note: str = ""

    @property
    def identity(self) -> tuple[str, str]:
        return (self.rule, self.key)

    def to_json(self) -> dict:
        d = {"rule": self.rule, "key": self.key}
        if self.severity:
            d["severity"] = self.severity
        if self.summary:
            d["summary"] = self.summary
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_json(cls, raw: dict) -> Entry:
        if "rule" not in raw:
            raise BaselineError(f"baseline entry has no 'rule': {raw!r}")
        if "key" not in raw:
            raise BaselineError(
                f"baseline entry for {raw['rule']} has no 'key'. A baseline "
                "matches on identity, so an entry without a key cannot match "
                "anything."
            )
        return cls(
            rule=str(raw["rule"]),
            key=str(raw["key"]),
            severity=str(raw.get("severity", "")),
            summary=str(raw.get("summary", "")),
            note=str(raw.get("note", "")),
        )

    @classmethod
    def of(cls, f: Finding, note: str = "") -> Entry:
        return cls(
            rule=f.rule_id,
            key=f.key or f.summary,
            severity=f.severity.label,
            summary=f.summary,
            note=note,
        )


class BaselineError(Exception):
    """A baseline file that cannot be trusted to mean what it says."""


@dataclass
class Baseline:
    """The set of violations a project has accepted for now."""

    entries: list[Entry] = field(default_factory=list)
    source: str = ""
    created: str = ""
    note: str = ""

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def identities(self) -> set[tuple[str, str]]:
        return {e.identity for e in self.entries}

    def accepts(self, f: Finding) -> bool:
        """Is this exact finding already known and accepted?"""
        return f.identity in self.identities

    def unaccepted(self, findings: list[Finding]) -> list[Finding]:
        """Violations this baseline does not cover - the ones that matter."""
        known = self.identities
        return [
            f
            for f in findings
            if f.status is Status.VIOLATION and f.identity not in known
        ]

    def stale(self, findings: list[Finding]) -> list[Entry]:
        """Entries with nothing left to excuse.

        These are the ratchet. A stale entry means a defect was fixed, or a
        rule stopped being able to see it - either way the baseline is now
        broader than the truth and should be narrowed.
        """
        present = {
            f.identity for f in findings if f.status is Status.VIOLATION
        }
        return [e for e in self.entries if e.identity not in present]

    # ── io ────────────────────────────────────────────────────────────

    @classmethod
    def from_findings(
        cls,
        findings: list[Finding],
        source: str = "",
        note: str = "",
        rules: set[str] | None = None,
    ) -> Baseline:
        """Accept the current violations.

        `rules` limits the file to the rules that can actually gate. That is
        the default caller's behaviour on purpose: an entry for a rule nobody
        gates on excuses nothing today, but would silently excuse a real
        defect on the day that rule graduates.
        """
        violations = [
            f
            for f in findings
            if f.status is Status.VIOLATION
            and (rules is None or f.rule_id in rules)
        ]
        return cls(
            entries=sorted(
                (Entry.of(f) for f in violations),
                key=lambda e: (e.rule, e.key),
            ),
            source=source,
            created=date.today().isoformat(),
            note=note,
        )

    @classmethod
    def load(cls, path: Path) -> Baseline:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise BaselineError(f"no baseline at {path}")
        except json.JSONDecodeError as e:
            raise BaselineError(f"{path} is not valid JSON: {e}")

        schema = raw.get("schema")
        if schema != SCHEMA:
            raise BaselineError(
                f"{path} declares schema {schema!r}, expected {SCHEMA!r}. "
                "Refusing to guess - regenerate it with `xforge baseline`."
            )
        return cls(
            entries=[Entry.from_json(e) for e in raw.get("accepted", [])],
            source=str(raw.get("source", "")),
            created=str(raw.get("created", "")),
            note=str(raw.get("note", "")),
        )

    def save(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "source": self.source,
                    "created": self.created,
                    "note": self.note
                    or "Violations accepted for now. Gating fails on anything "
                    "not listed here. Shrink this file; do not grow it.",
                    "accepted": [e.to_json() for e in self.entries],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def pruned(self, findings: list[Finding]) -> Baseline:
        """A copy with stale entries dropped."""
        dead = {e.identity for e in self.stale(findings)}
        return Baseline(
            entries=[e for e in self.entries if e.identity not in dead],
            source=self.source,
            created=self.created,
            note=self.note,
        )
