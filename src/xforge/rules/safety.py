"""Safety-path rules for battery junction boxes.

These encode the review a BMS engineer does by eye: does the interlock chain
actually run in series, is there a clamp across every coil, can a thermistor
be read at all. None of them is a numbered clause - they are established
practice - so each reports what it found rather than asserting a threshold,
and says explicitly when it could not evaluate.
"""

from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

from xforge.physics import electrical as elec
from xforge.rules.base import Finding, Severity, Status, rule

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design, Net


def _leaf(name: str) -> str:
    return name.rsplit("/", 1)[-1]


@rule(
    id="XF010",
    title="Safety interlock chain is series-continuous",
    source=(
        "ISO 26262 decomposition practice; CEA BESS two-fault tolerance; "
        "Xbattery convention"
    ),
    severity=Severity.ERROR,
)
def interlock_chain(design: "Design", config: "Config") -> Iterable[Finding]:
    """Trace the normally-closed interlock switches and check they are in series.

    A hardware interlock only works if breaking any one contact removes power
    from the actuator. That means the switches form a chain in which every
    intermediate net touches exactly two switch poles - anything else is a
    bypass. This rule discovers the chain rather than being told it, and
    reports the chain it found so a reviewer can confirm the order.
    """
    prof = config.profile
    switches = [c for c in design.components if prof.is_kind(c, "switch", "relay")]
    if not switches:
        yield Finding(
            rule_id="XF010",
            severity=Severity.INFO,
            summary="No interlock switches found",
            detail=(
                "No component classifies as a switch or relay under the "
                f"'{prof.name}' profile, so there is no interlock chain to "
                "check. If the interlock is external and reaches the board "
                "through a connector only, this rule cannot see it - say so "
                "explicitly rather than reading this as a pass."
            ),
            status=Status.BLOCKED,
            confidence="verified",
        )
        return

    refs = {c.ref for c in switches}
    # Nets that join exactly two switches are the links of the chain.
    links: list[tuple[str, str, Net]] = []
    stubs: list[Net] = []
    for net in design.nets:
        on_chain = sorted(r for r in net.refs if r in refs)
        if len(on_chain) == 2 and net.degree == 2:
            links.append((on_chain[0], on_chain[1], net))
        elif len(on_chain) == 2:
            # Two switches plus something else: a tap off the chain.
            stubs.append(net)

    chained = {r for a, b, _ in links for r in (a, b)}
    # A switch sitting on a tapped link is already reported by the stub
    # finding below. Reporting it again as an orphan describes one cause
    # twice and makes the chain look more broken than it is.
    on_stub = {r for n in stubs for r in n.refs if r in refs}
    orphans = sorted(refs - chained - on_stub)

    chain_desc = [
        f"{a} --[{_leaf(n.name)}]-- {b}" for a, b, n in sorted(links, key=lambda x: x[2].name)
    ]

    if links and not orphans and not stubs:
        yield Finding(
            rule_id="XF010",
            severity=Severity.INFO,
            summary=(
                f"Interlock chain is series-continuous across "
                f"{len(chained)} switches"
            ),
            detail=(
                "Every interlock switch sits on a link net shared with exactly "
                "one other switch, and no link carries a third connection. "
                "Breaking any one contact breaks the chain. Confirm the order "
                "below matches the intended sequence."
            ),
            subjects=chain_desc
            + [f"{c.ref}: {c.value}" for c in sorted(switches, key=lambda c: c.ref)],
            status=Status.PASS,
            confidence="verified",
        )
        return

    if stubs:
        yield Finding(
            rule_id="XF010",
            severity=Severity.ERROR,
            summary=(
                f"Interlock chain has {len(stubs)} link net(s) with a third "
                "connection"
            ),
            detail=(
                "A net between two interlock switches also reaches something "
                "else. Anything tapping the chain between contacts can bypass "
                "the contacts upstream of it. Confirm each tap is a monitor "
                "with no current path around the switch."
            ),
            subjects=[
                f"{_leaf(n.name)}: {', '.join(str(p) for p in n.pins)}" for n in stubs
            ],
            confidence="needs-review",
        )

    if orphans:
        yield Finding(
            rule_id="XF010",
            severity=Severity.ERROR,
            summary=f"{len(orphans)} interlock switch(es) not in the chain",
            detail=(
                "These switches share no two-pin net with another interlock "
                "switch, so they are not in series with the chain. Either they "
                "belong to a separate loop, or the chain is broken here."
            ),
            subjects=[
                f"{r}: {(design.component(r).value if design.component(r) else '?')}"
                for r in orphans
            ],
            confidence="verified",
        )


@rule(
    id="XF011",
    title="Inductive coil drive without a clamp",
    source="General protection practice; TE Connectivity contactor guidance",
    severity=Severity.WARNING,
)
def coil_clamp(design: "Design", config: "Config") -> Iterable[Finding]:
    """A coil-drive net with no diode, TVS or zener on it.

    Switching an inductive load without a clamp produces hundreds of volts
    across the driver. When the contactor is external and reaches the board
    through a connector - as on the BJB - the clamp may legitimately live
    inside the contactor, so this reports rather than fails, and asks for the
    datasheet confirmation.
    """
    prof = config.profile
    if not prof.knows_role("coil"):
        yield Finding(
            rule_id="XF011",
            severity=Severity.INFO,
            summary=f"Profile '{prof.name}' defines no coil nets",
            detail=(
                "This rule needs to know which nets drive an inductive load. "
                "The active profile lists no patterns for the 'coil' role, so "
                "nothing was examined. Add patterns under net_roles.coil in "
                "the profile, or select a profile that has them."
            ),
            status=Status.BLOCKED,
            confidence="verified",
        )
        return

    coil_nets = prof.nets_with_role(design.nets, "coil")
    if not coil_nets:
        yield Finding(
            rule_id="XF011",
            severity=Severity.INFO,
            summary="No coil nets found in this design",
            detail=(
                f"The '{prof.name}' profile knows how to recognise coil nets "
                "but this design has none matching. If the board does drive a "
                "contactor or relay, the net naming does not match the "
                "profile - extend net_roles.coil rather than assuming a pass."
            ),
            status=Status.BLOCKED,
            confidence="verified",
        )
        return

    for net in sorted(coil_nets, key=lambda n: n.name):
        clamps = [
            r
            for r in sorted(net.refs)
            if (c := design.component(r)) is not None and prof.is_clamp(c)
        ]
        if clamps:
            continue
        external = [
            r
            for r in sorted(net.refs)
            if (c := design.component(r)) is not None
            and prof.is_kind(c, "connector")
        ]
        yield Finding(
            rule_id="XF011",
            severity=Severity.WARNING,
            summary=f"Coil net '{_leaf(net.name)}' has no clamp element",
            detail=(
                "No diode, TVS or zener sits on this net. "
                + (
                    "The coil reaches the board through a connector, so the "
                    "clamp may be inside the contactor - confirm against its "
                    "datasheet and record it, or add one on the board."
                    if external
                    else "Add a flyback path across the coil."
                )
                + " Note the trade-off: a plain flyback diode slows contactor "
                "opening and can reduce breaking capacity."
            ),
            subjects=[net.name]
            + [
                f"{p} ({(design.component(p.ref).value if design.component(p.ref) else '?')})"
                for p in net.pins
            ]
            + [
                "",
                "What to check, with the coil L and I from the contactor "
                "datasheet:",
                elec.FLYBACK_VOLTAGE.explain(),
                elec.COIL_ENERGY.explain(),
                "  worked example: a 100 mH coil at 0.3 A stores "
                f"{elec.coil_energy_j(0.1, 0.3) * 1000:.1f} mJ, which the "
                "driver absorbs as avalanche energy if nothing clamps it.",
            ],
            confidence="needs-review",
        )


@rule(
    id="XF012",
    title="Thermistor without a bias network",
    source="General measurement practice",
    severity=Severity.WARNING,
)
def thermistor_bias(design: "Design", config: "Config") -> Iterable[Finding]:
    """An NTC with no resistor on either terminal.

    A thermistor is only readable as part of a divider or a current-biased
    network. If neither of its nets reaches a resistor, nothing can measure
    it - unless the bias lives off-board or on a sheet this netlist does not
    connect, which is reported rather than assumed.
    """
    prof = config.profile
    thermistors = [c for c in design.components if prof.is_kind(c, "thermistor")]
    if not thermistors:
        yield Finding(
            rule_id="XF012",
            severity=Severity.INFO,
            summary="No thermistors found in this design",
            detail=(
                f"Nothing classifies as a thermistor under the '{prof.name}' "
                "profile, so nothing was examined."
            ),
            status=Status.BLOCKED,
            confidence="verified",
        )
        return

    for comp in sorted(thermistors, key=lambda c: c.ref):
        nets = design.nets_of.get(comp.ref, [])
        if not nets:
            continue
        biased = False
        reaches_connector = False
        for net in nets:
            for r in net.refs:
                if r == comp.ref:
                    continue
                other = design.component(r)
                if other is None:
                    continue
                if prof.is_kind(other, "resistor"):
                    biased = True
                if prof.is_kind(other, "connector"):
                    reaches_connector = True
        if biased:
            continue
        # A worked case for the common 10 k / B=3435 NTC, so the finding
        # carries a number rather than only an instruction.
        r25, beta = 10_000.0, 3435.0
        hot = elec.ntc_resistance(beta, r25, 85.0)
        cold = elec.ntc_resistance(beta, r25, -20.0)
        yield Finding(
            rule_id="XF012",
            severity=Severity.WARNING,
            summary=f"{comp.ref} ({comp.value}) has no bias resistor",
            detail=(
                "Neither terminal net reaches a resistor, so this thermistor "
                "cannot be read as a divider. "
                + (
                    "It does reach a connector, so the bias may be off-board "
                    "or on a sheet not connected in this netlist - confirm "
                    "which, and record it."
                    if reaches_connector
                    else "Add the bias network."
                )
            ),
            subjects=[comp.ref]
            + [f"{_leaf(n.name)} (deg={n.degree})" for n in nets]
            + [
                "",
                "Sizing the bias resistor:",
                elec.NTC_BIAS.explain(),
                elec.NTC_BETA.explain(),
                f"  worked example, 10 k NTC with B=3435: "
                f"{cold / 1000:.0f} k at -20 C, 10 k at 25 C, "
                f"{hot:.0f} ohm at 85 C. Biasing at 10 k maximises "
                "sensitivity near 25 C; bias lower to favour the hot end, "
                "where a contactor or shunt sensor actually lives.",
            ],
            confidence="needs-review",
        )
