"""Conductor requirements for the current a design carries.

A netlist says nothing about current, so the currents come from the project
config — either per net pattern or per profile net role. This module turns
those declarations plus a stackup into the geometry each net needs, and into
constraint files the layout tool can consume.

There is no board geometry to check against yet: the BJB layout lives in
Cadence and no .kicad_pcb exists. So this produces *requirements*, which is
the useful half either way — it tells the layout engineer what to hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from xforge.physics.ampacity import (
    Layer,
    busbar_area_mm2,
    TraceRequirement,
    ViaRequirement,
    required_trace,
    required_vias,
)

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design, Net


@dataclass
class Stackup:
    """What the fabricator will build."""

    layers: int = 2
    outer_copper_oz: float = 1.0
    inner_copper_oz: float = 0.5
    max_temp_rise_c: float = 20.0
    ambient_c: float = 25.0
    via_drill_mm: float = 0.3
    via_plating_um: float = 25.0

    @classmethod
    def from_raw(cls, raw: dict | None) -> "Stackup":
        raw = raw or {}
        return cls(
            layers=int(raw.get("layers", 2)),
            outer_copper_oz=float(raw.get("outer_copper_oz", 1.0)),
            inner_copper_oz=float(raw.get("inner_copper_oz", 0.5)),
            max_temp_rise_c=float(raw.get("max_temp_rise_c", 20.0)),
            ambient_c=float(raw.get("ambient_c", 25.0)),
            via_drill_mm=float(raw.get("via_drill_mm", 0.3)),
            via_plating_um=float(raw.get("via_plating_um", 25.0)),
        )


@dataclass
class CurrentSpec:
    """A declared current, applying to nets by pattern or by profile role."""

    continuous_a: float
    peak_a: float | None = None
    nets: list[str] = field(default_factory=list)
    role: str | None = None
    note: str = ""

    @classmethod
    def from_raw(cls, raw: dict) -> "CurrentSpec":
        return cls(
            continuous_a=float(raw["continuous_a"]),
            peak_a=(float(raw["peak_a"]) if raw.get("peak_a") is not None else None),
            nets=list(raw.get("nets", []) or []),
            role=raw.get("role"),
            note=raw.get("note", ""),
        )

    def matches(self, net: "Net", profile) -> bool:
        if self.role and profile.net_has_role(net, self.role):
            return True
        if not self.nets:
            return False
        full = net.name.upper()
        leaf = net.name.rsplit("/", 1)[-1].upper()
        return any(
            fnmatchcase(full, p.upper()) or fnmatchcase(leaf, p.upper())
            for p in self.nets
        )


# Above roughly this width a PCB trace stops being the sensible conductor:
# the copper is wider than most routing channels, and a busbar or a heavy-
# copper pour is the real answer. Configurable per project.
PRACTICAL_TRACE_LIMIT_MM = 20.0


@dataclass
class NetPower:
    """The computed requirement for one net."""

    net: str
    continuous_a: float
    peak_a: float | None
    outer: TraceRequirement
    inner: TraceRequirement
    vias: ViaRequirement
    note: str = ""
    trace_limit_mm: float = PRACTICAL_TRACE_LIMIT_MM

    @property
    def exceeds_trace_limit(self) -> bool:
        """Is the required copper too wide to be a trace at all?"""
        return self.outer.width_mm > self.trace_limit_mm

    @property
    def busbar_mm2(self) -> float:
        """Cross-section if this is carried as a busbar instead.

        Uses 2.0 A/mm2, an industry convention rather than a standard value.
        """
        return busbar_area_mm2(self.peak_a or self.continuous_a, 2.0)

    @property
    def netclass(self) -> str:
        """A netclass name banded by current, so nets of like size share one."""
        a = self.continuous_a
        for threshold in (1, 2, 5, 10, 20, 50, 100, 200, 500):
            if a <= threshold:
                return f"PWR_{threshold}A"
        return "PWR_MAX"


@dataclass
class PowerReport:
    design: str
    stackup: Stackup
    nets: list[NetPower] = field(default_factory=list)
    unmatched_specs: list[CurrentSpec] = field(default_factory=list)

    @property
    def netclasses(self) -> dict[str, dict]:
        """Netclass name -> the widest requirement of any net in it."""
        out: dict[str, dict] = {}
        for np in self.nets:
            entry = out.setdefault(
                np.netclass,
                {"track_width_mm": 0.0, "current_a": 0.0, "nets": []},
            )
            entry["track_width_mm"] = max(
                entry["track_width_mm"], round(np.outer.width_mm, 3)
            )
            entry["current_a"] = max(entry["current_a"], np.continuous_a)
            entry["nets"].append(np.net)
        return out


def analyse(design: "Design", config: "Config") -> PowerReport:
    """Compute conductor requirements for every net with a declared current."""
    profile = config.profile
    stackup = config.stackup
    specs = config.currents

    report = PowerReport(design=design.name, stackup=stackup)
    matched_specs: set[int] = set()

    for net in design.nets:
        spec = next(
            (s for s in specs if s.matches(net, profile)),
            None,
        )
        if spec is None:
            continue
        matched_specs.add(id(spec))
        sizing_current = spec.peak_a or spec.continuous_a
        report.nets.append(
            NetPower(
                net=net.name,
                continuous_a=spec.continuous_a,
                peak_a=spec.peak_a,
                outer=required_trace(
                    sizing_current,
                    stackup.max_temp_rise_c,
                    stackup.outer_copper_oz,
                    Layer.EXTERNAL,
                ),
                inner=required_trace(
                    sizing_current,
                    stackup.max_temp_rise_c,
                    stackup.inner_copper_oz,
                    Layer.INTERNAL,
                ),
                vias=required_vias(
                    sizing_current,
                    stackup.via_drill_mm,
                    stackup.via_plating_um,
                    stackup.max_temp_rise_c,
                ),
                note=spec.note,
                trace_limit_mm=config.trace_limit_mm,
            )
        )

    report.unmatched_specs = [s for s in specs if id(s) not in matched_specs]
    report.nets.sort(key=lambda n: (-n.continuous_a, n.net))
    return report
