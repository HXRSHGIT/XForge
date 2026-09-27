"""Reader for KiCad's XML netlist export.

`kicad-cli sch export netlist --format kicadxml` emits the same schema as the
S-expression form, just in XML. Supporting both matters because the two are
produced interchangeably and a checker that only reads one will be handed the
other on the day it is needed.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from xforge.model import Component, Design, Net, Pin


class NetlistFormatError(ValueError):
    """The file is XML but is not a KiCad netlist."""


def sniff(path: str | Path) -> bool:
    """True if *path* looks like a KiCad XML netlist."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(512).lstrip()
    return head.startswith("<?xml") or head.startswith("<export")


def read(path: str | Path) -> Design:
    """Read the KiCad XML netlist at *path* into a `Design`."""
    path = Path(path)
    root = ET.parse(path).getroot()
    if root.tag != "export":
        raise NetlistFormatError(
            f"{path.name}: expected a KiCad XML netlist with a root <export>, "
            f"found <{root.tag}>"
        )
    design = _read_header(root, path)
    design.components = _read_components(root)
    design.nets = _read_nets(root)
    return design


def _text(node, tag: str) -> str | None:
    found = node.find(tag)
    if found is None:
        return None
    value = (found.text or "").strip()
    return value or None


def _read_header(root: ET.Element, path: Path) -> Design:
    block = root.find("design")
    name = path.stem
    source = tool = revision = company = None
    if block is not None:
        source = _text(block, "source")
        tool = _text(block, "tool")
        sheet = block.find("sheet")
        if sheet is not None:
            title = sheet.find("title_block")
            if title is not None:
                name = _text(title, "title") or name
                revision = _text(title, "rev")
                company = _text(title, "company")
    return Design(
        name=name, source=source, tool=tool, revision=revision, company=company
    )


def _read_components(root: ET.Element) -> list[Component]:
    block = root.find("components")
    if block is None:
        return []
    out: list[Component] = []
    for comp in block.findall("comp"):
        ref = comp.get("ref")
        if not ref:
            continue
        props = {
            p.get("name", ""): p.get("value", "")
            for p in comp.findall("property")
            if p.get("name")
        }
        libsource = comp.find("libsource")
        library_part = None
        if libsource is not None:
            lib, part = libsource.get("lib"), libsource.get("part")
            library_part = f"{lib}:{part}" if lib and part else (part or lib)
        out.append(
            Component(
                ref=ref,
                value=_text(comp, "value"),
                footprint=_text(comp, "footprint"),
                library_part=library_part,
                description=_text(comp, "description"),
                sheet=props.get("Sheetname") or None,
                properties=props,
            )
        )
    return out


def _read_nets(root: ET.Element) -> list[Net]:
    block = root.find("nets")
    if block is None:
        return []
    out: list[Net] = []
    for net in block.findall("net"):
        name = net.get("name")
        if name is None:
            continue
        pins = [
            Pin(
                ref=ref,
                number=node.get("pin", ""),
                function=node.get("pinfunction"),
                type=node.get("pintype"),
            )
            for node in net.findall("node")
            if (ref := node.get("ref"))
        ]
        out.append(Net(name=name, code=net.get("code"), pins=pins))
    return out
