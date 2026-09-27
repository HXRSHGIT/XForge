"""Connectivity rules — the ones that need only a netlist.

These catch the defect class that costs the most to find late: a signal that
looks connected on the drawing but is two separate nets in the netlist.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, TYPE_CHECKING

from xforge.rules.base import Finding, Severity, rule

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design, Net


def _leaf(name: str) -> str:
    """The signal name without its sheet path."""
    return name.rsplit("/", 1)[-1]


def _is_no_connect(net: "Net") -> bool:
    """True when every pin on the net is explicitly flagged no-connect."""
    return bool(net.pins) and all(
        "no_connect" in (p.type or "") for p in net.pins
    )


@rule(
    id="XF001",
    title="Signal split across sheets",
    source="Xbattery convention; KiCad hierarchical sheet-pin wiring",
    severity=Severity.ERROR,
    blocking=True,
)
def signal_split_across_sheets(
    design: "Design", config: "Config"
) -> Iterable[Finding]:
    """One signal name, more than one net.

    In a hierarchical schematic this almost always means a sheet pin was
    left unwired at the parent level: the drawing reads as connected, the
    netlist is not. Power rails legitimately appear per sheet, so those are
    excluded via `global_power_nets`.
    """
    by_leaf: dict[str, list[Net]] = defaultdict(list)
    for net in design.nets:
        by_leaf[_leaf(net.name).upper()].append(net)

    for leaf, nets in sorted(by_leaf.items()):
        if len(nets) < 2 or config.is_global_power(leaf):
            continue
        if all(_is_no_connect(n) for n in nets):
            continue

        # The telling shape: at least one fragment is barely connected.
        weakest = min(n.degree for n in nets)
        total = sum(n.degree for n in nets)
        detail = (
            f"'{leaf}' exists as {len(nets)} separate nets carrying {total} pins "
            f"in total; the smallest has {weakest}. "
            "Check the sheet pins on the parent sheet — if these should be one "
            "signal, the netlist currently says they are not connected."
        )
        yield Finding(
            rule_id="XF001",
            severity=Severity.ERROR if weakest <= 2 else Severity.WARNING,
            summary=f"Signal '{leaf}' is {len(nets)} unconnected nets",
            detail=detail,
            subjects=[f"{n.name} (deg={n.degree})" for n in nets],
            confidence="verified",
        )


@rule(
    id="XF002",
    title="Dangling net",
    source="Xbattery convention",
    severity=Severity.WARNING,
)
def dangling_net(design: "Design", config: "Config") -> Iterable[Finding]:
    """A net reaching exactly one pin, and not marked no-connect.

    Explicit no-connects are intentional and are not reported. Test points,
    spares and mounting hardware can be listed in `expected_dangling`.
    """
    for net in design.nets:
        if net.degree != 1 or _is_no_connect(net):
            continue
        if config.is_expected_dangling(net.name):
            continue
        pin = net.pins[0]
        comp = design.component(pin.ref)
        what = f"{comp.value or comp.library_part}" if comp else "unknown part"
        yield Finding(
            rule_id="XF002",
            severity=Severity.WARNING,
            summary=f"Net '{net.name}' reaches only {pin}",
            detail=(
                f"Single connection to {pin} ({what}), pin type "
                f"'{pin.type or 'unspecified'}'. Either the signal is "
                "incomplete, or it should carry an explicit no-connect flag."
            ),
            subjects=[net.name, str(pin)],
            confidence="verified",
        )


@rule(
    id="XF003",
    title="Component straddles an isolation barrier",
    source="IEC 60664-1 insulation coordination; declared domains in xforge.yaml",
    severity=Severity.ADVISORY,
)
def barrier_straddling_component(
    design: "Design", config: "Config"
) -> Iterable[Finding]:
    """A part with pins in two declared galvanic domains.

    Domain membership is taken only from a net's own name matching a declared
    pattern — never inferred transitively, or every ground would "bridge"
    everything. A part touching two domains is either a deliberate crossing
    (optocoupler, digital isolator, isolated DC-DC, Y-capacitor) or a barrier
    violation, and only a human can say which; hence advisory, listing the
    straddling parts for review.

    This is the defect class atopile gets silently wrong: its
    `has_single_electric_reference` trait merges power references across a
    barrier with no warning. Here the straddle is at least visible.
    """
    if len(config.domains) < 2:
        return

    # net -> domain, by direct pattern match only
    net_domain: dict[str, str] = {}
    for net in design.nets:
        d = config.domain_of(net.name)
        if d is not None:
            net_domain[net.name] = d.name

    if not net_domain:
        return

    # component -> {domain: [nets]}
    straddlers: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for net in design.nets:
        dom = net_domain.get(net.name)
        if dom is None:
            continue
        for ref in sorted(net.refs):
            straddlers[ref][dom].append(_leaf(net.name))

    for ref, doms in sorted(straddlers.items()):
        if len(doms) < 2:
            continue
        comp = design.component(ref)
        what = (comp.value or comp.library_part or "?") if comp else "?"
        detail_nets = "; ".join(
            f"{d}: {', '.join(sorted(set(n))[:6])}" for d, n in sorted(doms.items())
        )
        yield Finding(
            rule_id="XF003",
            severity=Severity.ADVISORY,
            summary=(
                f"{ref} ({what}) has pins in {len(doms)} domains: "
                f"{', '.join(sorted(doms))}"
            ),
            detail=(
                "This part bridges declared galvanic domains. Confirm it is an "
                "intended crossing device with a rated isolation barrier, and "
                "that its creepage and clearance meet the working voltage. If "
                "it is not a crossing device, the barrier is compromised. "
                f"Nets: {detail_nets}"
            ),
            subjects=[ref] + [f"{d}: {', '.join(sorted(set(n)))}" for d, n in sorted(doms.items())],
            confidence="needs-review",
        )


@rule(
    id="XF004",
    title="Placeholder footprint in a connectivity model",
    source="Xbattery convention",
    severity=Severity.INFO,
)
def placeholder_parts(design: "Design", config: "Config") -> Iterable[Finding]:
    """Parts with no real footprint.

    Expected while a design is a connectivity model; a blocker before layout.
    Reported at INFO so the count is visible without adding noise.
    """
    placeholders = [c for c in design.components if c.is_placeholder]
    if not placeholders:
        return
    refs = sorted(c.ref for c in placeholders)
    yield Finding(
        rule_id="XF004",
        severity=Severity.INFO,
        summary=f"{len(placeholders)} parts have no production footprint",
        detail=(
            "These carry placeholder or empty footprints, so they cannot be "
            "placed, routed or ordered. Expected in a connectivity-only model."
        ),
        subjects=refs[:40] + ([f"... and {len(refs) - 40} more"] if len(refs) > 40 else []),
        confidence="verified",
    )
