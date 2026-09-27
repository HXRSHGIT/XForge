"""Component-level rules — what a part is, not how it is wired."""

from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

from xforge.rules.base import Finding, Severity, Status, rule

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design

@rule(
    id="XF006",
    title="Component rating still unspecified",
    source="Xbattery convention",
    severity=Severity.WARNING,
)
def unspecified_rating(design: "Design", config: "Config") -> Iterable[Finding]:
    """A part whose value string says the rating is not decided.

    Catches `TBD`, `TODO`, `???`, `XXX`, `FIXME` in a value. These are honest
    notes by the designer, and exactly the kind of thing that survives into a
    handoff and then into a build. Raised to Error when the part is one whose
    rating is itself a protective function - a fuse cannot be "TBD" and still
    protect anything.
    """
    prof = config.profile
    for comp in sorted(design.components, key=lambda c: c.ref):
        if not comp.has_unspecified_rating:
            continue
        critical = prof.is_safety_critical(comp)
        yield Finding(
            rule_id="XF006",
            severity=Severity.ERROR if critical else Severity.WARNING,
            summary=f"{comp.ref} has no specified rating: \"{comp.value}\"",
            detail=(
                "The value string still carries a placeholder. "
                + (
                    "This part's rating is a protective function, so the "
                    "design cannot be evaluated for safety until it is set."
                    if critical
                    else "Set the value before this design is built."
                )
            ),
            subjects=[
                f"{comp.ref}  {comp.value}",
                f"sheet: {comp.sheet or '-'}",
                f"library: {comp.library_part or '-'}",
            ],
            confidence="verified",
        )


@rule(
    id="XF007",
    title="Fuse present on the power path",
    source="IEC 62619 protection intent; Xbattery convention",
    severity=Severity.INFO,
)
def fuse_present(design: "Design", config: "Config") -> Iterable[Finding]:
    """Confirms a fuse exists, and reports its rating.

    A positive check rather than a violation: on a battery junction box the
    absence of a fuse is a design decision somebody should have to look at,
    and the presence of one with an unreadable rating is worth stating next
    to the rest of the safety findings.
    """
    prof = config.profile
    fuses = [c for c in design.components if prof.is_kind(c, "fuse")]
    if not fuses:
        yield Finding(
            rule_id="XF007",
            severity=Severity.WARNING,
            summary="No fuse found anywhere in the design",
            detail=(
                "No component classifies as a fuse. On a battery junction box "
                "that is either an omission or a decision recorded elsewhere."
            ),
            confidence="probable",
        )
        return
    for f in sorted(fuses, key=lambda c: c.ref):
        rated = not f.has_unspecified_rating
        yield Finding(
            rule_id="XF007",
            severity=Severity.INFO,
            summary=f"{f.ref} fuse: {f.value}",
            detail=(
                "Rating is specified."
                if rated
                else "Rating is not specified - see XF006."
            ),
            subjects=[f"sheet: {f.sheet or '-'}"],
            status=Status.PASS if rated else Status.VIOLATION,
            confidence="verified",
        )
