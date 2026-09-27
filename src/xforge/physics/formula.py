"""Formulas that carry their own provenance.

Every number a rule puts in front of an engineer should be traceable to
something. A warning that says "trace too narrow" is an opinion; one that says
"needs 2.38 mm by IPC-2221 section 6.2, and here is the equation and the
inputs" is a calculation the engineer can check and disagree with.

So a formula here is not a bare function. It is a function plus its equation
as written, its variables and units, where it came from, how far that source
can be trusted, and where it stops being valid. Rules cite the registry entry
rather than restating the maths in prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class Tier(StrEnum):
    """How far a source can be trusted, mirroring docs/standards.md."""

    PRIMARY = "A"  # read from the purchased standard, cited to a clause
    PUBLIC_FORM = "B"  # published closed form, reproduced identically elsewhere
    SECONDARY = "C"  # consultancy, vendor blog, calculator tool
    CONVENTION = "D"  # industry practice with no standard behind it

    @property
    def label(self) -> str:
        return {
            "A": "primary standard",
            "B": "public closed form",
            "C": "secondary source",
            "D": "industry convention",
        }[self.value]

    @property
    def may_gate(self) -> bool:
        """May a build be failed on a number from this tier?

        Only A and B. A rule must not block a release on a figure lifted
        from a vendor blog.
        """
        return self in (Tier.PRIMARY, Tier.PUBLIC_FORM)


@dataclass(frozen=True)
class Variable:
    symbol: str
    meaning: str
    unit: str


@dataclass(frozen=True)
class Formula:
    """A calculation, its provenance, and the limits of its validity."""

    id: str
    name: str
    equation: str  # as written, in plain text
    variables: tuple[Variable, ...]
    source: str  # standard + clause, or a URL
    tier: Tier
    constants: dict[str, str] = field(default_factory=dict)
    validity: str = ""
    notes: str = ""

    def citation(self) -> str:
        """One line naming where this came from and how much to trust it."""
        return f"{self.equation}  [{self.source}, {self.tier.label}]"

    def explain(self, **inputs) -> str:
        """The equation, the source, and the actual inputs used.

        This is what goes into a finding, so the engineer reading it can
        redo the arithmetic without opening the code.
        """
        lines = [
            f"{self.name}",
            f"  {self.equation}",
        ]
        if inputs:
            shown = ", ".join(f"{k}={v}" for k, v in inputs.items())
            lines.append(f"  with {shown}")
        units = ", ".join(f"{v.symbol} in {v.unit}" for v in self.variables)
        if units:
            lines.append(f"  where {units}")
        if self.constants:
            consts = ", ".join(f"{k} = {v}" for k, v in self.constants.items())
            lines.append(f"  constants: {consts}")
        lines.append(f"  source: {self.source} ({self.tier.label}, tier {self.tier})")
        if self.validity:
            lines.append(f"  valid for: {self.validity}")
        if self.notes:
            lines.append(f"  note: {self.notes}")
        return "\n".join(lines)


_REGISTRY: dict[str, Formula] = {}


def register(formula: Formula) -> Formula:
    """Add a formula to the registry, keyed by id."""
    if formula.id in _REGISTRY:
        raise ValueError(f"duplicate formula id {formula.id}")
    _REGISTRY[formula.id] = formula
    return formula


def get(formula_id: str) -> Formula:
    try:
        return _REGISTRY[formula_id]
    except KeyError:
        raise KeyError(
            f"unknown formula '{formula_id}'. Known: {', '.join(sorted(_REGISTRY))}"
        ) from None


def registry() -> dict[str, Formula]:
    """Every registered formula. Importing the physics package fills this."""
    from xforge.physics import ampacity  # noqa: F401  (registers on import)

    return dict(_REGISTRY)


def by_tier(tier: Tier) -> list[Formula]:
    return [f for f in registry().values() if f.tier is tier]


def gating_safe() -> list[Formula]:
    """Formulas a rule is allowed to fail a build on."""
    return [f for f in registry().values() if f.tier.may_gate]


def decorate(formula: Formula) -> Callable:
    """Attach a formula to the function that evaluates it.

    The function gains a `.formula` attribute, so a rule holding the callable
    can always reach the provenance without a second lookup.
    """

    def wrap(func: Callable) -> Callable:
        func.formula = formula  # type: ignore[attr-defined]
        return func

    return wrap
