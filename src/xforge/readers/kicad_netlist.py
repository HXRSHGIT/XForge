"""Reader for KiCad's Eeschema netlist export (the `(export (version "E") ...)` form).

Produced by `kicad-cli sch export netlist --format kicadsexpr`, and by
Eeschema's File -> Export -> Netlist. atopile's `ato build` emits the same
shape, so this reader covers both inputs.
"""

from __future__ import annotations

from pathlib import Path

from xforge import sexp
from xforge.model import Component, Design, Net, Pin


class NetlistFormatError(ValueError):
    """The file parsed as S-expressions but is not a KiCad netlist."""


def read(path: str | Path) -> Design:
    """Read the KiCad netlist at *path* into a `Design`."""
    path = Path(path)
    root = sexp.load(path)
    if sexp.head(root) != "export":
        raise NetlistFormatError(
            f"{path.name}: expected a KiCad netlist starting with '(export', "
            f"found '{sexp.head(root)}'"
        )
    design = _read_design_header(root, path)
    design.components = _read_components(root)
    design.nets = _read_nets(root)
    return design


def _read_design_header(root: sexp.SExp, path: Path) -> Design:
    block = sexp.child(root, "design")
    name = path.stem
    source = tool = revision = company = None
    if block is not None:
        source = sexp.value(block, "source")
        tool = sexp.value(block, "tool")
        # The root sheet carries the title block.
        for sheet in sexp.children(block, "sheet"):
            title_block = sexp.child(sheet, "title_block")
            if title_block is None:
                continue
            name = sexp.value(title_block, "title") or name
            revision = sexp.value(title_block, "rev")
            company = sexp.value(title_block, "company")
            break
    return Design(
        name=name, source=source, tool=tool, revision=revision, company=company
    )


def _read_components(root: sexp.SExp) -> list[Component]:
    block = sexp.child(root, "components")
    if block is None:
        return []
    out: list[Component] = []
    for node in sexp.children(block, "comp"):
        ref = sexp.value(node, "ref")
        if ref is None:
            continue
        out.append(
            Component(
                ref=ref,
                value=sexp.value(node, "value"),
                footprint=sexp.value(node, "footprint"),
                library_part=_libsource(node),
                description=sexp.value(node, "description"),
                sheet=_property(node, "Sheetname"),
                properties=_properties(node),
            )
        )
    return out


def _libsource(node: sexp.SExp) -> str | None:
    src = sexp.child(node, "libsource")
    if src is None:
        return None
    lib = sexp.value(src, "lib")
    part = sexp.value(src, "part")
    if lib and part:
        return f"{lib}:{part}"
    return part or lib


def _properties(node: sexp.SExp) -> dict[str, str]:
    """KiCad writes properties as `(property (name X) (value Y))`."""
    out: dict[str, str] = {}
    for prop in sexp.children(node, "property"):
        key = sexp.value(prop, "name")
        if key is None:
            continue
        out[key] = sexp.value(prop, "value", "") or ""
    return out


def _property(node: sexp.SExp, name: str) -> str | None:
    return _properties(node).get(name) or None


def _read_nets(root: sexp.SExp) -> list[Net]:
    block = sexp.child(root, "nets")
    if block is None:
        return []
    out: list[Net] = []
    for node in sexp.children(block, "net"):
        name = sexp.value(node, "name")
        if name is None:
            continue
        pins = [
            Pin(
                ref=ref,
                number=sexp.value(n, "pin", "") or "",
                function=sexp.value(n, "pinfunction"),
                type=sexp.value(n, "pintype"),
            )
            for n in sexp.children(node, "node")
            if (ref := sexp.value(n, "ref")) is not None
        ]
        out.append(Net(name=name, code=sexp.value(node, "code"), pins=pins))
    return out
