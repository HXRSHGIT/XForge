"""IDF 3.0 board reader.

IDF is the mechanical handoff format every ECAD tool writes: a board outline
with its cutouts, and every component's placement and height. Allegro emits
it as a `.emn` (board) plus `.emp` (package library) pair.

It is used here in preference to the STEP export for three reasons. It is
plain text, so it needs no CAD kernel and works on a locked-down machine. It
is small. And crucially it keeps reference designators attached to geometry,
which a tessellated STEP file throws away - so a finding that names R902 can
light up R902 in the viewport.

Specification: IDF 3.0, "Intermediate Data Format for the transfer of
printed circuit assembly design data", 1998. The format is public.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

THOU_TO_MM = 0.0254


class IdfError(ValueError):
    """The file is not IDF, or is malformed in a way worth naming."""


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass
class Loop:
    """One closed polygon. Label 0 is an outer boundary, 1+ are cutouts."""

    label: int
    points: list[Point] = field(default_factory=list)

    @property
    def is_cutout(self) -> bool:
        return self.label != 0


@dataclass
class Outline:
    """A named outline section: the board, a keepout, a placement area."""

    kind: str
    owner: str
    thickness_mm: float
    loops: list[Loop] = field(default_factory=list)

    @property
    def outer(self) -> list[Loop]:
        return [lp for lp in self.loops if not lp.is_cutout]

    @property
    def cutouts(self) -> list[Loop]:
        return [lp for lp in self.loops if lp.is_cutout]


@dataclass
class Package:
    """A component footprint outline and its height, from the .emp library."""

    geometry: str
    part_number: str
    height_mm: float
    loops: list[Loop] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.geometry, self.part_number)


@dataclass
class Placement:
    """One placed component."""

    geometry: str
    part_number: str
    refdes: str
    x_mm: float
    y_mm: float
    z_mm: float
    rotation_deg: float
    side: str  # TOP or BOTTOM
    status: str  # PLACED, ECAD, MCAD, UNPLACED

    @property
    def key(self) -> tuple[str, str]:
        return (self.geometry, self.part_number)


@dataclass
class Board:
    """Everything the viewer needs, in millimetres."""

    name: str
    source: Path
    units: str
    thickness_mm: float
    generator: str = ""
    created: str = ""
    outline: Outline | None = None
    other_outlines: list[Outline] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    packages: dict[tuple[str, str], Package] = field(default_factory=dict)

    @property
    def extents_mm(self) -> tuple[float, float, float, float]:
        """min x, min y, max x, max y of the board outline."""
        pts = [p for lp in (self.outline.outer if self.outline else []) for p in lp.points]
        if not pts:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def size_mm(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.extents_mm
        return (x1 - x0, y1 - y0)

    def package_for(self, placement: Placement) -> Package | None:
        return self.packages.get(placement.key)

    def height_of(self, placement: Placement) -> float:
        """Component height, falling back to a thin box when unknown.

        An unknown height is drawn rather than skipped: a component missing
        from the library is exactly the thing worth seeing in the viewport.
        """
        pkg = self.package_for(placement)
        return pkg.height_mm if pkg and pkg.height_mm > 0 else 0.5


# ── parsing ───────────────────────────────────────────────────────────

_SECTION = re.compile(r"^\.(?P<name>[A-Z_]+)(?P<rest>.*)$")


def _tokens(line: str) -> list[str]:
    """Split an IDF record, honouring quoted fields with spaces in them."""
    return [t for t in re.findall(r'"[^"]*"|\S+', line)]


def _unquote(tok: str) -> str:
    return tok[1:-1] if len(tok) >= 2 and tok.startswith('"') else tok


def _sections(text: str) -> Iterator[tuple[str, str, list[str]]]:
    """Yield (section name, header remainder, body lines)."""
    name: str | None = None
    rest = ""
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _SECTION.match(line)
        if m:
            tag = m.group("name")
            if tag.startswith("END_"):
                if name == tag[4:]:
                    yield name, rest, body
                name, rest, body = None, "", []
            else:
                name, rest, body = tag, m.group("rest").strip(), []
            continue
        if name is not None:
            body.append(line)


def _scale(units: str) -> float:
    u = units.strip().upper()
    if u.startswith("THOU"):
        return THOU_TO_MM
    if u.startswith("MM"):
        return 1.0
    raise IdfError(f"Unsupported IDF units {units!r}; expected THOU or MM")


def _loops(body: list[str], scale: float) -> list[Loop]:
    """Group point records into closed loops by their label."""
    loops: list[Loop] = []
    current: Loop | None = None
    for line in body:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            label = int(float(parts[0]))
            x, y = float(parts[1]) * scale, float(parts[2]) * scale
        except ValueError:
            continue
        if current is None or current.label != label:
            current = Loop(label=label)
            loops.append(current)
        current.points.append(Point(x, y))
    return loops


def read_board(emn_path: str | Path, emp_path: str | Path | None = None) -> Board:
    """Read an IDF board file, and its package library if one sits beside it."""
    emn = Path(emn_path)
    if not emn.exists():
        raise FileNotFoundError(f"IDF board file not found: {emn}")
    text = emn.read_text(encoding="utf-8", errors="replace")

    sections = list(_sections(text))
    head = next((b for n, _, b in sections if n == "HEADER"), None)
    if head is None:
        raise IdfError(f"{emn.name}: no .HEADER section; this is not an IDF file")

    fields = _tokens(head[0]) if head else []
    if not fields or fields[0].upper() != "BOARD_FILE":
        raise IdfError(
            f"{emn.name}: header says {fields[0] if fields else '?'}, expected BOARD_FILE"
        )
    generator = fields[2] if len(fields) > 2 else ""
    created = fields[3] if len(fields) > 3 else ""
    name_line = _tokens(head[1]) if len(head) > 1 else []
    board_name = _unquote(name_line[0]) if name_line else emn.stem
    units = name_line[1] if len(name_line) > 1 else "THOU"
    scale = _scale(units)

    board = Board(
        name=board_name,
        source=emn,
        units=units.upper(),
        thickness_mm=0.0,
        generator=generator,
        created=created,
    )

    for section, rest, body in sections:
        if section in ("HEADER", "DRILLED_HOLES", "NOTES"):
            continue
        if section == "PLACEMENT":
            board.placements.extend(_placements(body, scale))
            continue
        if not body:
            continue
        # Outline sections lead with their thickness or height.
        try:
            thickness = float(body[0].split()[0]) * scale
            loop_body = body[1:]
        except (ValueError, IndexError):
            thickness, loop_body = 0.0, body
        outline = Outline(
            kind=section, owner=rest or "", thickness_mm=thickness,
            loops=_loops(loop_body, scale),
        )
        if section == "BOARD_OUTLINE":
            board.outline = outline
            board.thickness_mm = thickness
        else:
            board.other_outlines.append(outline)

    if emp_path is None:
        for candidate in (emn.with_suffix(".emp"), emn.with_suffix(".EMP")):
            if candidate.exists():
                emp_path = candidate
                break
    if emp_path:
        board.packages = read_library(emp_path)
    return board


def _placements(body: list[str], scale: float) -> list[Placement]:
    """Placement records come in pairs: identity line, then position line."""
    out: list[Placement] = []
    for i in range(0, len(body) - 1, 2):
        ident = _tokens(body[i])
        pos = body[i + 1].split()
        if len(ident) < 3 or len(pos) < 5:
            continue
        try:
            x, y, z = (float(pos[0]) * scale, float(pos[1]) * scale, float(pos[2]) * scale)
            rot = float(pos[3])
        except ValueError:
            continue
        out.append(
            Placement(
                geometry=_unquote(ident[0]),
                part_number=_unquote(ident[1]),
                refdes=_unquote(ident[2]),
                x_mm=x, y_mm=y, z_mm=z,
                rotation_deg=rot,
                side=pos[4].upper() if len(pos) > 4 else "TOP",
                status=pos[5].upper() if len(pos) > 5 else "",
            )
        )
    return out


def read_library(emp_path: str | Path) -> dict[tuple[str, str], Package]:
    """Read an IDF package library (.emp): footprint outlines and heights."""
    emp = Path(emp_path)
    if not emp.exists():
        return {}
    text = emp.read_text(encoding="utf-8", errors="replace")

    packages: dict[tuple[str, str], Package] = {}
    for section, _, body in _sections(text):
        if section not in ("ELECTRICAL", "MECHANICAL") or not body:
            continue
        ident = _tokens(body[0])
        if len(ident) < 4:
            continue
        try:
            scale = _scale(ident[2])
            height = float(ident[3]) * scale
        except (ValueError, IdfError):
            continue
        pkg = Package(
            geometry=_unquote(ident[0]),
            part_number=_unquote(ident[1]),
            height_mm=height,
            loops=_loops(body[1:], scale),
        )
        packages[pkg.key] = pkg
    return packages


# ── viewer payload ────────────────────────────────────────────────────


def to_scene(board: Board, highlight: set[str] | None = None) -> dict:
    """The board as JSON the viewer extrudes client side.

    Sending polygons rather than a mesh keeps this small and keeps every
    solid addressable by reference designator, which is what lets a finding
    point at a part.
    """
    highlight = {h.upper() for h in (highlight or set())}
    x0, y0, x1, y1 = board.extents_mm
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)

    def shift(pts: list[Point]) -> list[list[float]]:
        return [[round(p.x - centre[0], 4), round(p.y - centre[1], 4)] for p in pts]

    parts = []
    missing = 0
    for p in board.placements:
        pkg = board.package_for(p)
        if pkg is None or not pkg.loops:
            missing += 1
        outline = pkg.loops[0].points if pkg and pkg.loops else []
        parts.append(
            {
                "ref": p.refdes,
                "package": p.geometry,
                "part": p.part_number,
                "x": round(p.x_mm - centre[0], 4),
                "y": round(p.y_mm - centre[1], 4),
                "rot": p.rotation_deg,
                "side": p.side,
                "height": round(board.height_of(p), 4),
                "outline": [[round(pt.x, 4), round(pt.y, 4)] for pt in outline],
                "flagged": p.refdes.upper() in highlight,
            }
        )

    return {
        "name": board.name,
        "generator": board.generator,
        "created": board.created,
        "units": "mm",
        "thickness": round(board.thickness_mm, 4),
        "size": [round(board.size_mm[0], 3), round(board.size_mm[1], 3)],
        "outline": [shift(lp.points) for lp in (board.outline.outer if board.outline else [])],
        "cutouts": [shift(lp.points) for lp in (board.outline.cutouts if board.outline else [])],
        "parts": parts,
        "stats": {
            "placements": len(board.placements),
            "packages": len(board.packages),
            "without_outline": missing,
        },
    }
