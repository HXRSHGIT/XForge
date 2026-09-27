"""Rule framework: findings, severities, and the registry.

Every rule states where its criterion comes from. A rule without a citation
is a rule nobody can argue with, which is worse than no rule at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design


class Severity(IntEnum):
    INFO = 0
    ADVISORY = 1
    WARNING = 2
    ERROR = 3

    @property
    def label(self) -> str:
        return self.name.title()


class Status(StrEnum):
    """What kind of statement a finding is making."""

    VIOLATION = "violation"  # the design breaks the rule
    BLOCKED = "not-evaluable"  # the rule could not run; says why
    PASS = "pass"  # the rule ran and the design satisfies it

    @property
    def label(self) -> str:
        return {"violation": "Violation", "not-evaluable": "Not evaluable",
                "pass": "Pass"}[self.value]


@dataclass
class Finding:
    """One thing a rule wants a human to look at."""

    rule_id: str
    severity: Severity
    summary: str  # one line, states the defect
    detail: str = ""  # why it matters / what to check
    subjects: list[str] = field(default_factory=list)  # nets, refs, pins
    confidence: str = "verified"  # verified | probable | needs-review
    status: Status = Status.VIOLATION

    def sort_key(self):
        order = {Status.VIOLATION: 0, Status.BLOCKED: 1, Status.PASS: 2}
        return (order[self.status], -int(self.severity), self.rule_id, self.summary)


@dataclass(frozen=True)
class Rule:
    """A registered check."""

    id: str
    title: str
    source: str  # standard clause, app note, or "Xbattery convention"
    default_severity: Severity
    check: Callable[["Design", "Config"], Iterable[Finding]]
    blocking: bool = False  # may this rule fail CI once gating is enabled?


_REGISTRY: dict[str, Rule] = {}


def rule(
    id: str,
    title: str,
    source: str,
    severity: Severity = Severity.WARNING,
    blocking: bool = False,
):
    """Register a check function as a rule."""

    def decorator(func: Callable[["Design", "Config"], Iterable[Finding]]):
        if id in _REGISTRY:
            raise ValueError(f"duplicate rule id {id}")
        _REGISTRY[id] = Rule(
            id=id,
            title=title,
            source=source,
            default_severity=severity,
            check=func,
            blocking=blocking,
        )
        return func

    return decorator


def registry() -> dict[str, Rule]:
    """All registered rules, id -> Rule."""
    # Importing for side effects: each module registers its rules on import.
    from xforge.rules import (  # noqa: F401
        components,
        connectivity,
        hierarchy,
        isolation,
        safety,
    )

    return dict(_REGISTRY)


def run(design: "Design", config: "Config") -> list[Finding]:
    """Run every enabled rule and return findings, most severe first."""
    findings: list[Finding] = []
    for rid, r in registry().items():
        if rid in config.disabled_rules:
            continue
        for f in r.check(design, config):
            # A config override wins over the rule's default.
            if (override := config.severity_overrides.get(rid)) is not None:
                if f.status is Status.VIOLATION:
                    f.severity = override
            findings.append(f)
    findings.sort(key=lambda f: f.sort_key())
    return findings
