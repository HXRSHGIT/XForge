"""Readers that normalise vendor formats into the xforge design model."""

from __future__ import annotations

from pathlib import Path

from xforge.model import Design
from xforge.readers import kicad_netlist, kicad_xml

__all__ = ["kicad_netlist", "kicad_xml", "read"]


class UnknownFormatError(ValueError):
    """The file is not a netlist format xforge understands."""


def read(path: str | Path) -> Design:
    """Read any supported netlist, choosing the reader by content.

    Content sniffing rather than file extension: KiCad writes both the
    S-expression and the XML netlist to `.net`, so the extension says nothing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"netlist not found: {path}")
    if kicad_xml.sniff(path):
        return kicad_xml.read(path)
    try:
        return kicad_netlist.read(path)
    except Exception as exc:
        raise UnknownFormatError(
            f"{path.name}: not a KiCad S-expression or XML netlist ({exc})"
        ) from exc
