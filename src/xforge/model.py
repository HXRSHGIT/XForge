"""The design model every rule runs against.

Reader-agnostic on purpose: KiCad today, atopile and Cadence next, all
normalised into these types so a rule never has to know where the data
came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property


@dataclass(frozen=True)
class Pin:
    """One pin of one component, as referenced by a net."""

    ref: str  # component reference designator, e.g. "K1"
    number: str  # pin number as printed, e.g. "2" or "A1"
    function: str | None = None  # pin name from the symbol, e.g. "COIL+"
    type: str | None = None  # electrical type: passive, power_in, output, ...

    def __str__(self) -> str:
        return f"{self.ref}.{self.number}"


@dataclass
class Component:
    """A placed part."""

    ref: str
    value: str | None = None
    footprint: str | None = None
    library_part: str | None = None  # "lib:part"
    description: str | None = None
    sheet: str | None = None
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def designator_prefix(self) -> str:
        """Leading letters of the reference, e.g. 'R' for 'R17'."""
        out = []
        for ch in self.ref:
            if ch.isalpha():
                out.append(ch)
            else:
                break
        return "".join(out)

    @property
    def is_placeholder(self) -> bool:
        """True for sentinel parts that carry no real footprint.

        The BJB connectivity model uses `BJB_TBD:*` footprints deliberately;
        a rule that needs real geometry must skip these rather than report
        a false failure.
        """
        fp = (self.footprint or "").upper()
        return not fp or "TBD" in fp or fp.endswith(":")

    def __str__(self) -> str:
        return self.ref


@dataclass
class Net:
    """An electrical net and the pins on it."""

    name: str
    code: str | None = None
    pins: list[Pin] = field(default_factory=list)

    @property
    def degree(self) -> int:
        return len(self.pins)

    @property
    def refs(self) -> set[str]:
        """Reference designators of every component touching this net."""
        return {p.ref for p in self.pins}

    def __str__(self) -> str:
        return self.name


@dataclass
class Design:
    """A whole design: components, nets, and where it came from."""

    name: str
    source: str | None = None
    tool: str | None = None
    revision: str | None = None
    company: str | None = None
    components: list[Component] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)

    @cached_property
    def by_ref(self) -> dict[str, Component]:
        return {c.ref: c for c in self.components}

    @cached_property
    def by_net_name(self) -> dict[str, Net]:
        return {n.name: n for n in self.nets}

    @cached_property
    def nets_of(self) -> dict[str, list[Net]]:
        """Reference designator -> the nets it touches."""
        out: dict[str, list[Net]] = {}
        for net in self.nets:
            for ref in net.refs:
                out.setdefault(ref, []).append(net)
        return out

    def net(self, name: str) -> Net | None:
        return self.by_net_name.get(name)

    def component(self, ref: str) -> Component | None:
        return self.by_ref.get(ref)

    def nets_matching(self, *patterns: str) -> list[Net]:
        """Nets whose full name or leaf name matches any fnmatch pattern.

        Matching the leaf as well as the full path matters in a hierarchical
        design, where every net name is prefixed with its sheet.
        """
        from fnmatch import fnmatchcase

        def hit(net: Net) -> bool:
            full = net.name.upper()
            leaf = net.name.rsplit("/", 1)[-1].upper()
            return any(
                fnmatchcase(full, p.upper()) or fnmatchcase(leaf, p.upper())
                for p in patterns
            )

        return [n for n in self.nets if hit(n)]

    @cached_property
    def sheets(self) -> dict[str, list[Component]]:
        """Sheet name -> the components on it."""
        out: dict[str, list[Component]] = {}
        for c in self.components:
            out.setdefault(c.sheet or "(root)", []).append(c)
        return out

    def sheet_of_net(self, net: Net) -> str | None:
        """The sheet a net's name is scoped to, if it is scoped at all."""
        if "/" not in net.name.strip("/"):
            return None
        return net.name.strip("/").rsplit("/", 1)[0] or None

    def census(self) -> dict[str, int]:
        """Headline counts, used by `xforge inspect` and the report header."""
        prefixes: dict[str, int] = {}
        for c in self.components:
            prefixes[c.designator_prefix or "?"] = (
                prefixes.get(c.designator_prefix or "?", 0) + 1
            )
        return {
            "components": len(self.components),
            "placeholders": sum(1 for c in self.components if c.is_placeholder),
            "nets": len(self.nets),
            "pins": sum(n.degree for n in self.nets),
            "single_pin_nets": sum(1 for n in self.nets if n.degree == 1),
            "distinct_prefixes": len(prefixes),
        }
