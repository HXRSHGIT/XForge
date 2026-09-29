"""Compare two revisions of a design.

A text diff of a netlist is close to useless: net order changes, hierarchical
paths shift, and a one-line edit in the schematic rewrites hundreds of lines.
What a reviewer needs is the electrical change - which nets appeared, which
pins moved, which parts changed value - and, more than any of that, whether
the findings went up or down.

That last part is the point. When a defect is fixed, the proof is that the
rule stops firing. This module makes that a first-class result rather than
something you eyeball across two reports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from xforge.model import Design, Net
from xforge.rules.base import Finding, Severity, Status


class Change(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


def _leaf(name: str) -> str:
    return name.rsplit("/", 1)[-1]


# ── components ────────────────────────────────────────────────────────


@dataclass
class ComponentChange:
    ref: str
    change: Change
    before: str | None = None
    after: str | None = None
    field: str = "value"

    def describe(self) -> str:
        if self.change is Change.ADDED:
            return f"{self.ref} added ({self.after or '?'})"
        if self.change is Change.REMOVED:
            return f"{self.ref} removed (was {self.before or '?'})"
        return f"{self.ref} {self.field}: {self.before or '?'} -> {self.after or '?'}"


def compare_components(old: Design, new: Design) -> list[ComponentChange]:
    """Parts added, removed, or with a changed value or footprint."""
    out: list[ComponentChange] = []
    old_by, new_by = old.by_ref, new.by_ref

    for ref in sorted(set(new_by) - set(old_by)):
        out.append(ComponentChange(ref, Change.ADDED, after=new_by[ref].value))
    for ref in sorted(set(old_by) - set(new_by)):
        out.append(ComponentChange(ref, Change.REMOVED, before=old_by[ref].value))

    for ref in sorted(set(old_by) & set(new_by)):
        a, b = old_by[ref], new_by[ref]
        for attr in ("value", "footprint"):
            if (getattr(a, attr) or "") != (getattr(b, attr) or ""):
                out.append(
                    ComponentChange(
                        ref,
                        Change.CHANGED,
                        before=getattr(a, attr),
                        after=getattr(b, attr),
                        field=attr,
                    )
                )
    return out


# ── nets ──────────────────────────────────────────────────────────────


@dataclass
class NetChange:
    name: str
    change: Change
    pins_added: list[str] = field(default_factory=list)
    pins_removed: list[str] = field(default_factory=list)
    degree_before: int = 0
    degree_after: int = 0

    def describe(self) -> str:
        if self.change is Change.ADDED:
            return f"{_leaf(self.name)} added ({self.degree_after} pins)"
        if self.change is Change.REMOVED:
            return f"{_leaf(self.name)} removed (had {self.degree_before} pins)"
        bits = []
        if self.pins_added:
            bits.append(f"+{', '.join(self.pins_added)}")
        if self.pins_removed:
            bits.append(f"-{', '.join(self.pins_removed)}")
        return (
            f"{_leaf(self.name)} {self.degree_before} -> {self.degree_after} pins"
            + (f"  {'  '.join(bits)}" if bits else "")
        )


@dataclass
class MergedNets:
    """Two nets in the old revision that are one net in the new one.

    This is the shape of a fixed hierarchical connection, which is exactly
    what the BJB sheet-pin defect needs to produce when it is repaired.
    """

    result: str
    sources: list[str]
    degree: int

    def describe(self) -> str:
        return (
            f"{_leaf(self.result)} now joins "
            + " + ".join(_leaf(s) for s in self.sources)
            + f" ({self.degree} pins)"
        )


def _pin_keys(net: Net) -> set[str]:
    return {str(p) for p in net.pins}


def compare_nets(old: Design, new: Design) -> tuple[list[NetChange], list[MergedNets]]:
    """Net-level changes, plus the merges that a connection fix produces.

    Nets are matched by full hierarchical name. A net whose name did not
    survive is reported as removed, and its pins are looked for elsewhere -
    that is how a merge is detected rather than guessed.
    """
    old_by, new_by = old.by_net_name, new.by_net_name
    changes: list[NetChange] = []

    for name in sorted(set(new_by) - set(old_by)):
        changes.append(
            NetChange(name, Change.ADDED, degree_after=new_by[name].degree)
        )
    for name in sorted(set(old_by) - set(new_by)):
        changes.append(
            NetChange(name, Change.REMOVED, degree_before=old_by[name].degree)
        )
    for name in sorted(set(old_by) & set(new_by)):
        a, b = _pin_keys(old_by[name]), _pin_keys(new_by[name])
        if a == b:
            continue
        changes.append(
            NetChange(
                name,
                Change.CHANGED,
                pins_added=sorted(b - a),
                pins_removed=sorted(a - b),
                degree_before=len(a),
                degree_after=len(b),
            )
        )

    # A merge: several old nets whose pins now all sit on one new net.
    merges: list[MergedNets] = []
    gone = {n: _pin_keys(old_by[n]) for n in set(old_by) - set(new_by)}
    if gone:
        by_pin: dict[str, str] = {}
        for name, net in new_by.items():
            for pin in _pin_keys(net):
                by_pin[pin] = name
        landed: dict[str, list[str]] = defaultdict(list)
        for old_name, pins in gone.items():
            targets = {by_pin[p] for p in pins if p in by_pin}
            if len(targets) == 1:
                landed[targets.pop()].append(old_name)
        for target, sources in sorted(landed.items()):
            # One source that simply changed name is a rename, not a merge.
            if len(sources) >= 2 or target in old_by:
                merges.append(
                    MergedNets(target, sorted(sources), new_by[target].degree)
                )
    return changes, merges


# ── findings ──────────────────────────────────────────────────────────


@dataclass
class FindingDelta:
    """What the rules say now against what they said before."""

    resolved: list[Finding] = field(default_factory=list)
    introduced: list[Finding] = field(default_factory=list)
    unchanged: list[Finding] = field(default_factory=list)

    @property
    def net_change(self) -> int:
        """Negative is an improvement."""
        return len(self.introduced) - len(self.resolved)

    def by_severity(self, group: list[Finding]) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in group:
            out[f.severity.label] = out.get(f.severity.label, 0) + 1
        return out


def _identity(f: Finding) -> tuple[str, str]:
    """What makes two findings the same finding across revisions.

    Delegates to the finding's own key, which names the net, part or sheet
    the finding is about. Falling back to the summary would make a sheet that
    merely grew from 14 to 20 parts look like one defect resolved and a
    different one introduced.
    """
    return f.identity


def compare_findings(
    before: list[Finding], after: list[Finding]
) -> FindingDelta:
    """Which findings went away, which appeared, which persisted."""
    old_v = {_identity(f): f for f in before if f.status is Status.VIOLATION}
    new_v = {_identity(f): f for f in after if f.status is Status.VIOLATION}

    return FindingDelta(
        resolved=[old_v[k] for k in sorted(set(old_v) - set(new_v))],
        introduced=[new_v[k] for k in sorted(set(new_v) - set(old_v))],
        unchanged=[new_v[k] for k in sorted(set(old_v) & set(new_v))],
    )


# ── the whole comparison ──────────────────────────────────────────────


@dataclass
class DesignDiff:
    old_name: str
    new_name: str
    components: list[ComponentChange] = field(default_factory=list)
    nets: list[NetChange] = field(default_factory=list)
    merges: list[MergedNets] = field(default_factory=list)
    findings: FindingDelta = field(default_factory=FindingDelta)
    census_before: dict = field(default_factory=dict)
    census_after: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.components or self.nets or self.merges)

    @property
    def verdict(self) -> str:
        """One line a reviewer can act on."""
        d = self.findings.net_change
        if d < 0:
            return f"{-d} fewer violation(s)"
        if d > 0:
            return f"{d} more violation(s)"
        if self.is_empty:
            return "no electrical change"
        return "electrical changes, no change in violations"

    def counts(self) -> dict[str, int]:
        return {
            "components_added": sum(
                1 for c in self.components if c.change is Change.ADDED
            ),
            "components_removed": sum(
                1 for c in self.components if c.change is Change.REMOVED
            ),
            "components_changed": sum(
                1 for c in self.components if c.change is Change.CHANGED
            ),
            "nets_added": sum(1 for n in self.nets if n.change is Change.ADDED),
            "nets_removed": sum(1 for n in self.nets if n.change is Change.REMOVED),
            "nets_changed": sum(1 for n in self.nets if n.change is Change.CHANGED),
            "nets_merged": len(self.merges),
            "resolved": len(self.findings.resolved),
            "introduced": len(self.findings.introduced),
        }


def compare(
    old: Design,
    new: Design,
    before: list[Finding] | None = None,
    after: list[Finding] | None = None,
) -> DesignDiff:
    """Compare two revisions, including their findings when both are given."""
    nets, merges = compare_nets(old, new)
    return DesignDiff(
        old_name=old.name,
        new_name=new.name,
        components=compare_components(old, new),
        nets=nets,
        merges=merges,
        findings=(
            compare_findings(before, after)
            if before is not None and after is not None
            else FindingDelta()
        ),
        census_before=old.census(),
        census_after=new.census(),
    )
