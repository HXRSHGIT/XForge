"""Isolation rules — declared crossings, and everything else.

XF003 (in connectivity.py) reports every part that straddles two declared
domains. That is the raw observation. This module turns it into a judgement:
a straddle through a part declared as an isolator is the design working, and
a straddle through anything else is a barrier violation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, TYPE_CHECKING

from xforge.rules.base import Finding, Severity, Status, rule

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design

# Part kinds that exist to carry signal or power across a barrier.
_CROSSING_KINDS = ("isolator", "optocoupler", "transformer")


def _leaf(name: str) -> str:
    return name.rsplit("/", 1)[-1]


@rule(
    id="XF008",
    title="Undeclared component bridges an isolation barrier",
    source="IEC 60664-1 insulation coordination; declared domains and crossings",
    severity=Severity.ERROR,
)
def undeclared_crossing(design: "Design", config: "Config") -> Iterable[Finding]:
    """A part spanning two domains that is neither declared nor recognisable
    as a crossing device.

    Declared crossings are listed in `crossings:` in the project config.
    Parts that classify as an isolator, optocoupler or transformer are
    accepted with an advisory so the creepage of the barrier still gets
    looked at. Anything else spanning the barrier is an error.
    """
    if len(config.domains) < 2:
        yield Finding(
            rule_id="XF008",
            severity=Severity.INFO,
            summary="Fewer than two domains declared",
            detail=(
                "Isolation cannot be checked without at least two domains in "
                "the project config. Declare them by sheet or by net pattern."
            ),
            status=Status.BLOCKED,
            confidence="verified",
        )
        return

    net_domain: dict[str, str] = {}
    for net in design.nets:
        d = config.domain_of(net.name)
        if d is not None:
            net_domain[net.name] = d.name

    straddlers: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for net in design.nets:
        dom = net_domain.get(net.name)
        if dom is None:
            continue
        for ref in net.refs:
            straddlers[ref][dom].add(_leaf(net.name))

    found_any = False
    for ref, doms in sorted(straddlers.items()):
        if len(doms) < 2:
            continue
        found_any = True
        comp = design.component(ref)
        what = (comp.value or comp.library_part or "?") if comp else "?"
        nets_desc = [f"{d}: {', '.join(sorted(n))}" for d, n in sorted(doms.items())]

        if config.is_declared_crossing(ref, comp):
            yield Finding(
                rule_id="XF008",
                severity=Severity.INFO,
                summary=f"{ref} ({what}) is a declared isolation crossing",
                detail=(
                    "Spanning the barrier is this part's job. Confirm its "
                    "rated isolation voltage covers the working voltage, and "
                    "that the board keeps the barrier's creepage and clearance "
                    "underneath it."
                ),
                subjects=[ref] + nets_desc,
                status=Status.PASS,
                confidence="verified",
            )
        elif comp is not None and comp.is_kind(*_CROSSING_KINDS):
            yield Finding(
                rule_id="XF008",
                severity=Severity.ADVISORY,
                summary=(
                    f"{ref} ({what}) looks like a crossing device but is not "
                    "declared"
                ),
                detail=(
                    "This part classifies as an isolator, optocoupler or "
                    "transformer, so the straddle is probably intended. Add it "
                    "to `crossings:` in the project config to record that "
                    "decision, along with its rated isolation."
                ),
                subjects=[ref] + nets_desc,
                confidence="probable",
            )
        else:
            yield Finding(
                rule_id="XF008",
                severity=Severity.ERROR,
                summary=f"{ref} ({what}) bridges domains and is not an isolator",
                detail=(
                    "A conductor path through this part connects two "
                    "galvanically separated domains, which defeats the "
                    "barrier. Either it is a crossing device that should be "
                    "declared, or the barrier is compromised here."
                ),
                subjects=[ref] + nets_desc,
                confidence="needs-review",
            )

    if not found_any:
        yield Finding(
            rule_id="XF008",
            severity=Severity.INFO,
            summary="No part bridges the declared domains",
            detail=(
                "Nothing spans a barrier. Read this together with XF005: if "
                "sheets are orphaned, nothing crosses a barrier because "
                "nothing crosses anything, and this result means less than it "
                "appears to."
            ),
            status=Status.PASS,
            confidence="verified",
        )
