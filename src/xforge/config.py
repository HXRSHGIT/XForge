"""Project configuration: the facts a netlist cannot tell us.

Lives next to the design as `xforge.yaml`. Keeping domains, currents and
policy in one reviewed file is what lets a rule be specific instead of
guessing from net names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from xforge.rules.base import Severity

# Power rails are conventionally redrawn on every sheet, so seeing the same
# name as several nets is normal for them and only for them.
DEFAULT_GLOBAL_POWER_NETS = (
    "GND", "AGND", "DGND", "PGND", "EARTH", "CHASSIS",
    "VCC", "VDD", "VSS", "VBUS", "VBAT",
    "*_5V", "*_3V3", "*_12V", "*_24V", "*V3*", "+5V", "+3V3", "+12V", "+24V",
)


@dataclass
class Domain:
    """A galvanically separated part of the design."""

    name: str
    nets: list[str] = field(default_factory=list)  # fnmatch patterns
    sheets: list[str] = field(default_factory=list)  # fnmatch on sheet name
    working_voltage: float | None = None  # volts
    description: str = ""

    def matches_sheet(self, sheet_name: str | None) -> bool:
        if not sheet_name or not self.sheets:
            return False
        return any(fnmatchcase(sheet_name.upper(), p.upper()) for p in self.sheets)

    def matches(self, net_name: str) -> bool:
        leaf = net_name.rsplit("/", 1)[-1].upper()
        full = net_name.upper()
        return any(
            fnmatchcase(full, p.upper()) or fnmatchcase(leaf, p.upper())
            for p in self.nets
        )


@dataclass
class Config:
    """Everything a rule may need that is not in the netlist."""

    project: str = ""
    domains: list[Domain] = field(default_factory=list)
    # Nets that are allowed to be single-pin (test points, spares, mounting).
    expected_dangling: list[str] = field(default_factory=list)
    # Signal names that legitimately exist as several nets. Power rails are
    # drawn per sheet by convention, so they are excluded from XF001 unless
    # a project overrides this list.
    global_power_nets: list[str] = field(
        default_factory=lambda: list(DEFAULT_GLOBAL_POWER_NETS)
    )
    # Parts allowed to span two domains: refs or fnmatch patterns on the
    # ref, e.g. ["U903", "PS*"]. Declaring one is a recorded engineering
    # decision, which is the point.
    crossings: list[str] = field(default_factory=list)
    disabled_rules: set[str] = field(default_factory=set)
    severity_overrides: dict[str, Severity] = field(default_factory=dict)
    # Rules allowed to fail CI. Empty means advisory-only, which is the
    # deliberate default until false positives have been tuned out.
    gating_rules: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path is None:
            return cls()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"config not found: {path}")
        raw = _load_yaml(path)
        return cls(
            project=raw.get("project", ""),
            domains=[
                Domain(
                    name=d.get("name", f"domain{i}"),
                    nets=list(d.get("nets", []) or []),
                    sheets=list(d.get("sheets", []) or []),
                    working_voltage=d.get("working_voltage"),
                    description=d.get("description", ""),
                )
                for i, d in enumerate(raw.get("domains", []) or [])
            ],
            expected_dangling=list(raw.get("expected_dangling", []) or []),
            crossings=list(raw.get("crossings", []) or []),
            global_power_nets=list(
                raw.get("global_power_nets", DEFAULT_GLOBAL_POWER_NETS)
            ),
            disabled_rules=set(raw.get("disabled_rules", []) or []),
            severity_overrides={
                k: Severity[v.upper()]
                for k, v in (raw.get("severity_overrides", {}) or {}).items()
            },
            gating_rules=set(raw.get("gating_rules", []) or []),
        )

    def is_expected_dangling(self, net_name: str) -> bool:
        leaf = net_name.rsplit("/", 1)[-1].upper()
        return any(
            fnmatchcase(net_name.upper(), p.upper()) or fnmatchcase(leaf, p.upper())
            for p in self.expected_dangling
        )

    def is_declared_crossing(self, ref: str, component=None) -> bool:
        """Has this part been declared as an intentional barrier crossing?"""
        if any(fnmatchcase(ref.upper(), p.upper()) for p in self.crossings):
            return True
        if component is not None:
            for attr in ("value", "library_part"):
                val = getattr(component, attr, None)
                if val and any(
                    fnmatchcase(val.upper(), p.upper()) for p in self.crossings
                ):
                    return True
        return False

    def is_global_power(self, leaf_name: str) -> bool:
        return any(
            fnmatchcase(leaf_name.upper(), p.upper()) for p in self.global_power_nets
        )

    def domain_of(self, net_name: str) -> Domain | None:
        """Domain of a net, by explicit net pattern first, then by sheet.

        Net patterns win so a specific signal can be pulled out of the sheet
        it happens to be drawn on.
        """
        for d in self.domains:
            if d.matches(net_name):
                return d
        sheet = net_name.strip("/").rsplit("/", 1)[0] if "/" in net_name.strip("/") else None
        for d in self.domains:
            if d.matches_sheet(sheet):
                return d
        return None


def _load_yaml(path: Path) -> dict:
    """Load YAML if PyYAML is present, else fall back to a tiny subset reader.

    Avoiding a hard dependency keeps `xforge check` runnable on a bare
    Python install, which matters for a CI runner we do not control.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        import json

        # A JSON config is valid YAML; accept it as the no-dependency path.
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{path.name}: PyYAML is not installed and the file is not JSON. "
                "Install pyyaml, or write the config as JSON."
            ) from exc
