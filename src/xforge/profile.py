"""Technology profiles: the vocabulary rules are written against.

A rule holds an algorithm — "find the interlock switches and check they are
in series". A profile holds the vocabulary that algorithm needs — what an
interlock switch is called on this kind of product. Separating them is what
lets the same rule work on a battery junction box and on a motor controller,
and what makes an inapplicable rule say so instead of quietly passing.

Profiles stack. `bms` extends `base`; a project selects one and may override
any key. Lists concatenate, dicts merge key-wise, so a project adds to the
vocabulary rather than replacing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from xforge.model import Component, Net

PROFILE_DIR = Path(__file__).parent / "profiles"


class ProfileError(ValueError):
    """A profile could not be loaded or is malformed."""


@dataclass
class Profile:
    """A named vocabulary, already merged with everything it extends."""

    name: str
    designators: dict[str, str] = field(default_factory=dict)
    authoritative_prefixes: set[str] = field(default_factory=set)
    part_taxonomy: dict[str, list[str]] = field(default_factory=dict)
    clamp_kinds: list[str] = field(default_factory=list)
    crossing_kinds: list[str] = field(default_factory=list)
    safety_critical_kinds: list[str] = field(default_factory=list)
    safety_critical_hints: list[str] = field(default_factory=list)
    net_roles: dict[str, list[str]] = field(default_factory=dict)
    multi_instance_roles: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)

    # ── classification ────────────────────────────────────────────────

    def kinds(self, component: "Component") -> set[str]:
        """Best-effort classification of a part, e.g. {'diode', 'tvs'}.

        A set, because a PESD5V0S1BA is both a diode and a TVS and a rule
        asking "is there a clamp here" should match either.
        """
        prefix = component.designator_prefix
        by_prefix = self.designators.get(prefix)

        if prefix in self.authoritative_prefixes:
            return {by_prefix} if by_prefix else set()

        # `description` is deliberately excluded — see profiles/base.yaml.
        blob = " ".join(
            x for x in (component.value, component.library_part) if x
        ).lower()
        found = {
            kind
            for kind, needles in self.part_taxonomy.items()
            if any(n in blob for n in needles)
        }
        if by_prefix:
            found.add(by_prefix)
        if found & {"tvs", "zener"}:
            found.add("diode")
        return found

    def is_kind(self, component: "Component", *kinds: str) -> bool:
        mine = self.kinds(component)
        return any(k in mine for k in kinds)

    def is_clamp(self, component: "Component") -> bool:
        return self.is_kind(component, *self.clamp_kinds)

    def is_crossing_device(self, component: "Component") -> bool:
        return self.is_kind(component, *self.crossing_kinds)

    def is_safety_critical(self, component: "Component") -> bool:
        """A part whose rating is itself a protective function."""
        if self.is_kind(component, *self.safety_critical_kinds):
            return True
        blob = f"{component.value or ''} {component.ref}".lower()
        return any(h in blob for h in self.safety_critical_hints)

    # ── net roles ─────────────────────────────────────────────────────

    def patterns_for(self, role: str) -> list[str]:
        """The patterns defining a role. Empty means the profile has none."""
        return list(self.net_roles.get(role, []))

    def knows_role(self, role: str) -> bool:
        """Can this profile identify nets of this role at all?

        Rules key their `not evaluable` result on this: a role with no
        patterns means the rule cannot look, which is a different statement
        from looking and finding nothing wrong.
        """
        return bool(self.net_roles.get(role))

    def net_has_role(self, net: "Net", role: str) -> bool:
        patterns = self.patterns_for(role)
        if not patterns:
            return False
        full = net.name.upper()
        leaf = net.name.rsplit("/", 1)[-1].upper()
        return any(
            fnmatchcase(full, p.upper()) or fnmatchcase(leaf, p.upper())
            for p in patterns
        )

    def nets_with_role(self, nets, role: str) -> list["Net"]:
        return [n for n in nets if self.net_has_role(n, role)]

    def roles_of(self, net: "Net") -> set[str]:
        return {r for r in self.net_roles if self.net_has_role(net, r)}

    def is_multi_instance(self, net: "Net") -> bool:
        """May this net legitimately exist as several separate nets?"""
        return any(
            self.net_has_role(net, r)
            for r in self.multi_instance_roles
            if self.net_roles.get(r)
        )


# ── loading ───────────────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ProfileError(
            f"{path.name}: profiles are YAML and PyYAML is not installed"
        ) from exc


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Merge *over* onto *base*: lists concatenate, dicts merge key-wise.

    Concatenating rather than replacing is deliberate. A project adding one
    coil-net pattern should not silently discard the profile's others.
    """
    out = dict(base)
    for key, value in over.items():
        if key in ("name", "extends"):
            out[key] = value
        elif isinstance(value, list) and isinstance(out.get(key), list):
            seen, merged = set(), []
            for item in [*out[key], *value]:
                marker = item if isinstance(item, str) else repr(item)
                if marker not in seen:
                    seen.add(marker)
                    merged.append(item)
            out[key] = merged
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve(name: str, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in seen:
        raise ProfileError(f"profile inheritance loop: {' -> '.join([*seen, name])}")
    path = PROFILE_DIR / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))
        raise ProfileError(
            f"unknown profile '{name}'. Available: {', '.join(available)}"
        )
    raw = _read_yaml(path)
    parent = raw.get("extends")
    if parent:
        raw = merge(_resolve(parent, (*seen, name)), raw)
    raw.setdefault("lineage", [])
    raw["lineage"] = [*raw.get("lineage", []), name]
    return raw


@lru_cache(maxsize=None)
def _cached(name: str) -> dict[str, Any]:
    return _resolve(name)


def load(name: str = "base", overrides: dict[str, Any] | None = None) -> Profile:
    """Load a profile by name, optionally merging project overrides onto it."""
    raw = dict(_cached(name))
    if overrides:
        raw = merge(raw, overrides)
    return Profile(
        name=raw.get("name", name),
        designators=dict(raw.get("designators", {})),
        authoritative_prefixes=set(raw.get("authoritative_prefixes", [])),
        part_taxonomy={k: list(v) for k, v in (raw.get("part_taxonomy") or {}).items()},
        clamp_kinds=list(raw.get("clamp_kinds", [])),
        crossing_kinds=list(raw.get("crossing_kinds", [])),
        safety_critical_kinds=list(raw.get("safety_critical_kinds", [])),
        safety_critical_hints=list(raw.get("safety_critical_hints", [])),
        net_roles={k: list(v or []) for k, v in (raw.get("net_roles") or {}).items()},
        multi_instance_roles=list(raw.get("multi_instance_roles", [])),
        lineage=list(raw.get("lineage", [name])),
    )


def available() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))
