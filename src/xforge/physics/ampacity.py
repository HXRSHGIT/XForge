"""Conductor sizing from current.

Implements the IPC-2221 closed form. That standard is an empirical curve fit,
published identically across every independent source checked, so it is safe
to implement directly — see docs/standards.md, evidence tier B.

IPC-2152 supersedes it and generally yields *narrower* traces, because
IPC-2221's 2:1 internal/external penalty is pessimistic for real multilayer
boards with adjacent copper pours. IPC-2152 is chart-based with no published
closed form, so it needs the standard purchased and digitised. Until then this
module is deliberately the conservative one, and says so in what it returns.

Nothing here is battery-specific. It is geometry and heat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from xforge.physics.formula import Formula, Tier, Variable, decorate, register

# IPC-2221 constants. I = k * dT^0.44 * A^0.725, with A in mil^2 and dT in C.
# k differs by layer because an outer trace sheds heat to open air.
_K_EXTERNAL = 0.048
_K_INTERNAL = 0.024
_EXP_DT = 0.44
_EXP_AREA = 0.725

# 1 oz/ft^2 of copper is 1.37 mil (34.8 um) of thickness.
MIL_PER_OZ = 1.37
MM_PER_MIL = 0.0254


# ── provenance ────────────────────────────────────────────────────────

IPC2221_TRACE = register(
    Formula(
        id="ipc2221.trace",
        name="Conductor cross-section for a current (IPC-2221)",
        equation="A = (I / (k * dT^0.44))^(1/0.725)",
        variables=(
            Variable("A", "conductor cross-section", "mil^2"),
            Variable("I", "current", "A"),
            Variable("dT", "temperature rise above ambient", "degC"),
        ),
        constants={
            "k (external layer)": "0.048",
            "k (internal layer)": "0.024",
            "copper thickness": "1.37 mil per oz/ft^2",
        },
        source="IPC-2221B section 6.2, conductor-sizing charts",
        tier=Tier.PUBLIC_FORM,
        validity=(
            "Still air, no forced convection, no adjacent heat sources. "
            "dT is a rise above local ambient, which inside a sealed "
            "enclosure is well above lab ambient."
        ),
        notes=(
            "Conservative relative to IPC-2152: the 2:1 internal/external "
            "penalty is pessimistic for multilayer boards with adjacent "
            "pours, so this asks for wider copper than IPC-2152 would. "
            "IPC-2152 is chart-based with no published closed form."
        ),
    )
)

IPC2221_CURRENT = register(
    Formula(
        id="ipc2221.current",
        name="Current a conductor can carry (IPC-2221, forward form)",
        equation="I = k * dT^0.44 * A^0.725",
        variables=(
            Variable("I", "current", "A"),
            Variable("dT", "temperature rise above ambient", "degC"),
            Variable("A", "conductor cross-section", "mil^2"),
        ),
        constants={"k (external)": "0.048", "k (internal)": "0.024"},
        source="IPC-2221B section 6.2",
        tier=Tier.PUBLIC_FORM,
        validity="As above.",
    )
)

VIA_BARREL = register(
    Formula(
        id="via.barrel_area",
        name="Plated via barrel cross-section",
        equation="A = pi * d * t",
        variables=(
            Variable("A", "barrel cross-section", "mil^2"),
            Variable("d", "finished drill diameter", "mil"),
            Variable("t", "copper plating thickness", "mil"),
        ),
        source=(
            "Neither IPC-2221 nor IPC-2152 publishes a via current table; "
            "modelling the barrel as an unrolled flat conductor and applying "
            "the trace relation is standard practice"
        ),
        tier=Tier.CONVENTION,
        validity=(
            "Treats the barrel as a buried conductor, so the internal k "
            "applies. Ignores the pad and any adjacent copper."
        ),
        notes=(
            "A via landing on a plane is commonly credited with about 1.2x "
            "the current of an isolated one. That multiplier is a single "
            "secondary source and is flagged wherever it is applied."
        ),
    )
)

BUSBAR_AREA = register(
    Formula(
        id="busbar.area",
        name="Busbar cross-section from current density",
        equation="A = I / J",
        variables=(
            Variable("A", "conductor cross-section", "mm^2"),
            Variable("I", "current", "A"),
            Variable("J", "allowed current density", "A/mm^2"),
        ),
        constants={
            "J, natural convection": "1.5-2.0 A/mm^2",
            "J, enclosed": "1.2-1.8 A/mm^2",
            "J, well ventilated": "1.8-2.5 A/mm^2",
        },
        source="Industry convention; no IPC or IEC number governs this",
        tier=Tier.CONVENTION,
        validity=(
            "Bare or plated copper. The density chosen encodes the cooling "
            "assumption, so it must be stated with the result."
        ),
    )
)


class Layer(StrEnum):
    EXTERNAL = "external"
    INTERNAL = "internal"

    @property
    def k(self) -> float:
        return _K_EXTERNAL if self is Layer.EXTERNAL else _K_INTERNAL


class AmpacityError(ValueError):
    """The inputs cannot produce a meaningful answer."""


@dataclass(frozen=True)
class TraceRequirement:
    """What a conductor must be to carry a current within a temperature rise."""

    current_a: float
    temp_rise_c: float
    copper_oz: float
    layer: Layer
    area_mil2: float
    width_mm: float
    width_mil: float
    method: str = "IPC-2221"

    @property
    def formula(self) -> Formula:
        return IPC2221_TRACE

    @property
    def note(self) -> str:
        return IPC2221_TRACE.notes

    def explain(self) -> str:
        """The equation, the inputs used, and the source."""
        return IPC2221_TRACE.explain(
            I=f"{self.current_a} A",
            dT=f"{self.temp_rise_c} degC",
            k=f"{self.layer.k} ({self.layer.value})",
            copper=f"{self.copper_oz} oz",
        )


def _validate(current_a: float, temp_rise_c: float, copper_oz: float) -> None:
    if current_a <= 0:
        raise AmpacityError(f"current must be positive, got {current_a} A")
    if temp_rise_c <= 0:
        raise AmpacityError(
            f"temperature rise must be positive, got {temp_rise_c} C"
        )
    if copper_oz <= 0:
        raise AmpacityError(f"copper weight must be positive, got {copper_oz} oz")


@decorate(IPC2221_TRACE)
def required_area_mil2(
    current_a: float, temp_rise_c: float, layer: Layer = Layer.EXTERNAL
) -> float:
    """Minimum cross-section for *current_a* within *temp_rise_c*.

    Inverting I = k * dT^0.44 * A^0.725 for A.
    """
    _validate(current_a, temp_rise_c, 1.0)
    return (current_a / (layer.k * temp_rise_c**_EXP_DT)) ** (1 / _EXP_AREA)


@decorate(IPC2221_CURRENT)
def current_for_area(
    area_mil2: float, temp_rise_c: float, layer: Layer = Layer.EXTERNAL
) -> float:
    """The forward direction: what a given cross-section can carry."""
    if area_mil2 <= 0:
        raise AmpacityError(f"area must be positive, got {area_mil2} mil^2")
    _validate(1.0, temp_rise_c, 1.0)
    return layer.k * temp_rise_c**_EXP_DT * area_mil2**_EXP_AREA


@decorate(IPC2221_TRACE)
def required_trace(
    current_a: float,
    temp_rise_c: float = 20.0,
    copper_oz: float = 1.0,
    layer: Layer = Layer.EXTERNAL,
) -> TraceRequirement:
    """Minimum trace width for a current, at a copper weight and layer."""
    _validate(current_a, temp_rise_c, copper_oz)
    area = required_area_mil2(current_a, temp_rise_c, layer)
    width_mil = area / (copper_oz * MIL_PER_OZ)
    return TraceRequirement(
        current_a=current_a,
        temp_rise_c=temp_rise_c,
        copper_oz=copper_oz,
        layer=layer,
        area_mil2=area,
        width_mil=width_mil,
        width_mm=width_mil * MM_PER_MIL,
    )


@dataclass(frozen=True)
class ViaRequirement:
    """How many vias a current needs, given a barrel geometry."""

    current_a: float
    drill_mm: float
    plating_um: float
    temp_rise_c: float
    per_via_a: float
    count: int
    on_plane: bool

    @property
    def formula(self) -> Formula:
        return VIA_BARREL

    def explain(self) -> str:
        return VIA_BARREL.explain(
            d=f"{self.drill_mm} mm",
            t=f"{self.plating_um} um",
            dT=f"{self.temp_rise_c} degC",
        )

    @property
    def note(self) -> str:
        base = (
            "Barrel modelled as a flat conductor of cross-section "
            "pi * drill * plating, sized with the IPC-2221 relation. "
            "Neither IPC-2221 nor IPC-2152 publishes a via table."
        )
        if self.on_plane:
            base += (
                " A 1.2x credit was applied for landing on a plane - that is a "
                "single-source rule of thumb, not a standard value."
            )
        return base


# A via landing on a copper plane sheds heat into it. Widely quoted, single
# source, and flagged as such wherever it is used.
_PLANE_CREDIT = 1.2


@decorate(VIA_BARREL)
def required_vias(
    current_a: float,
    drill_mm: float = 0.3,
    plating_um: float = 25.0,
    temp_rise_c: float = 20.0,
    on_plane: bool = False,
) -> ViaRequirement:
    """How many vias of this geometry are needed to carry *current_a*."""
    _validate(current_a, temp_rise_c, 1.0)
    if drill_mm <= 0 or plating_um <= 0:
        raise AmpacityError("via drill and plating must be positive")

    circumference_mil = (math.pi * drill_mm / MM_PER_MIL)
    plating_mil = (plating_um / 1000.0) / MM_PER_MIL
    area_mil2 = circumference_mil * plating_mil

    # A via is a buried conductor, so the internal constant applies.
    per_via = current_for_area(area_mil2, temp_rise_c, Layer.INTERNAL)
    if on_plane:
        per_via *= _PLANE_CREDIT

    return ViaRequirement(
        current_a=current_a,
        drill_mm=drill_mm,
        plating_um=plating_um,
        temp_rise_c=temp_rise_c,
        per_via_a=per_via,
        count=max(1, math.ceil(current_a / per_via)),
        on_plane=on_plane,
    )


@decorate(BUSBAR_AREA)
def busbar_area_mm2(current_a: float, density_a_per_mm2: float = 2.0) -> float:
    """Cross-section for a busbar at a chosen current density.

    No IPC number governs this. Industry convention is roughly 1.5-2.0 A/mm2
    for naturally convected copper, tightening in an enclosed box. The caller
    supplies the density so the assumption is explicit and reviewable.
    """
    if current_a <= 0 or density_a_per_mm2 <= 0:
        raise AmpacityError("current and current density must be positive")
    return current_a / density_a_per_mm2
