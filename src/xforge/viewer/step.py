"""STEP -> GLB conversion for the web viewer.

A STEP file is exact BREP geometry: faces, edges, and the curves and
surfaces that bound them. A browser cannot draw that directly - WebGL wants
triangles. OpenCASCADE (via the `cadquery-ocp` bindings, module name `OCP`)
is the thing that tessellates BREP into triangles, so it is the only way to
get from a Cadence/Allegro STEP export to something `<model-viewer>` or
three.js can render.

That tessellation is slow (seconds to tens of seconds for a populated PCB
assembly) and OpenCASCADE itself is a ~150 MB dependency, so two design
choices follow directly:

- The import of `OCP` happens inside the functions that need it, never at
  module load time. `xforge.viewer.step` has to be importable, and its
  caching and error-handling logic has to be unit-testable, on a machine
  that never installs the `viewer` extra - the web UI and the DRC checker
  do not need OpenCASCADE, and a CI runner should not be forced to fetch it.
- Conversions are cached by content hash (source bytes + the deflection
  settings that shaped the mesh). Re-tessellating an unchanged board on
  every page load would make the viewer unusable.

`info()` is the cheap half: an ISO-10303-21 STEP file's HEADER section is
plain ASCII in the first few KB, and it names the authoring tool and
timestamp without needing a geometry kernel to open it. That has to work
even where OpenCASCADE is not installed at all - it is the fast path the UI
uses before deciding whether a full conversion is worth the wait.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

_VIEWER_EXTRA_HINT = (
    "STEP-to-GLB conversion needs OpenCASCADE and a mesh exporter, which are "
    "optional because they are heavy. Install the 'viewer' extra:\n"
    '  pip install -e ".[viewer]"'
)


@dataclass(frozen=True)
class ModelInfo:
    """What a viewer needs to know about one conversion."""

    source: Path
    glb: Path
    solids: int
    triangles: int
    bbox_mm: tuple[float, float, float]  # x, y, z extents
    source_bytes: int
    glb_bytes: int
    linear_deflection: float
    cached: bool  # True if a prior conversion was reused


def _hash_key(step_path: Path, linear_deflection: float, angular_deflection: float) -> str:
    """Content hash of the source plus the settings that shaped the mesh.

    Both go in: the same file tessellated at a coarser deflection is a
    different GLB, and it would be wrong to hand back a stale one.
    """
    digest = hashlib.sha256()
    with step_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    digest.update(f"|{linear_deflection}|{angular_deflection}".encode("ascii"))
    return digest.hexdigest()


def _cache_paths(step_path: Path, out_dir: Path, digest: str) -> tuple[Path, Path]:
    """The GLB and its metadata sidecar for a given hash.

    The hash is embedded in the filename rather than tracked in a separate
    index, so "does a cached conversion exist" is just `Path.is_file()` -
    nothing to get out of sync.
    """
    stem = step_path.stem
    glb_path = out_dir / f"{stem}.{digest[:16]}.glb"
    meta_path = glb_path.with_suffix(".json")
    return glb_path, meta_path


def _load_and_tessellate(
    step_path: Path, linear_deflection: float, angular_deflection: float
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], int, tuple[float, float, float]]:
    """Read the STEP file and tessellate it. The only function that touches OCP.

    Isolated on purpose: `convert()`'s caching and error-handling can be
    exercised in a test by monkeypatching this one function, without ever
    needing OpenCASCADE installed.

    Returns (vertices, triangle index tuples, solid count, bbox in mm).
    Allegro STEP exports declare millimetres as the length unit; this does
    not re-derive the unit from the file, so a STEP authored in inches
    would report a wrong bbox. That is a real gap, not an oversight - see
    the module docstring.
    """
    try:
        from OCP.Bnd import Bnd_Box
        from OCP.BRep import BRep_Tool
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
        from OCP.TopExp import TopExp, TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
        from OCP.TopTools import TopTools_IndexedMapOfShape
    except ImportError as exc:
        raise RuntimeError(f"{_VIEWER_EXTRA_HINT}\n(import failed: {exc})") from exc

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(step_path))
    if status != IFSelect_RetDone:
        raise ValueError(
            f"{step_path}: OpenCASCADE could not read this file as STEP "
            f"(STEPControl_Reader status {status})"
        )
    reader.TransferRoots()
    shape = reader.OneShape()

    solid_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solid_map)
    solids = solid_map.Extent()

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    bbox_mm = (xmax - xmin, ymax - ymin, zmax - zmin)

    # Mutates `shape` in place, attaching a Poly_Triangulation to every face.
    BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            # Triangulation nodes are in the face's local frame; the location
            # carries them back to the shape's placement.
            trsf = loc.Transformation()
            offset = len(vertices)
            n_nodes = tri.NbNodes()
            for i in range(1, n_nodes + 1):
                p = tri.Node(i).Transformed(trsf)
                vertices.append((p.X(), p.Y(), p.Z()))
            # A reversed face has its triangle winding backwards relative to
            # the outward normal; flip it back or the mesh lights inside-out.
            reversed_face = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                a, b, c = a - 1 + offset, b - 1 + offset, c - 1 + offset
                faces.append((a, c, b) if reversed_face else (a, b, c))
        explorer.Next()

    return vertices, faces, solids, bbox_mm


def _write_glb(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    glb_path: Path,
) -> None:
    """Serialise a triangle mesh to binary glTF.

    trimesh does the buffer/accessor bookkeeping; hand-rolling that part of
    the glTF spec would just be reproducing what it already gets right.
    """
    try:
        import numpy as np
        import trimesh
    except ImportError as exc:
        raise RuntimeError(f"{_VIEWER_EXTRA_HINT}\n(import failed: {exc})") from exc

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype="float64"),
        faces=np.asarray(faces, dtype="int64"),
        process=False,  # keep our winding/vertex count; do not let trimesh dedupe
    )
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(glb_path), file_type="glb")


def convert(
    step_path: str | Path,
    out_dir: str | Path | None = None,
    linear_deflection: float = 0.1,
    angular_deflection: float = 0.5,
    force: bool = False,
) -> ModelInfo:
    """Convert a STEP file to a GLB, reusing a prior conversion when possible.

    Cache key is the source content plus the deflection settings, so a
    change to either produces a new GLB rather than silently reusing a mesh
    tessellated for different settings. `force=True` re-tessellates and
    overwrites regardless of what is cached.
    """
    step_path = Path(step_path)
    if not step_path.is_file():
        raise FileNotFoundError(step_path)

    out_dir = Path(out_dir) if out_dir is not None else step_path.parent / "xforge_viewer_cache"
    out_dir.mkdir(parents=True, exist_ok=True)

    digest = _hash_key(step_path, linear_deflection, angular_deflection)
    glb_path, meta_path = _cache_paths(step_path, out_dir, digest)

    if not force and glb_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text())
        return ModelInfo(
            source=step_path,
            glb=glb_path,
            solids=meta["solids"],
            triangles=meta["triangles"],
            bbox_mm=tuple(meta["bbox_mm"]),
            source_bytes=meta["source_bytes"],
            glb_bytes=glb_path.stat().st_size,
            linear_deflection=linear_deflection,
            cached=True,
        )

    vertices, faces, solids, bbox_mm = _load_and_tessellate(
        step_path, linear_deflection, angular_deflection
    )
    _write_glb(vertices, faces, glb_path)

    source_bytes = step_path.stat().st_size
    triangles = len(faces)
    meta_path.write_text(
        json.dumps(
            {
                "solids": solids,
                "triangles": triangles,
                "bbox_mm": list(bbox_mm),
                "source_bytes": source_bytes,
            }
        )
    )

    return ModelInfo(
        source=step_path,
        glb=glb_path,
        solids=solids,
        triangles=triangles,
        bbox_mm=bbox_mm,
        source_bytes=source_bytes,
        glb_bytes=glb_path.stat().st_size,
        linear_deflection=linear_deflection,
        cached=False,
    )


# --- info(): a plain text read of the STEP header, no OCC involved -------

_HEADER_READ_BYTES = 8192  # generous for a header; real exports run under 1 KB


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _find_balanced_close(text: str, start: int) -> int:
    """Index of the ')' that closes the '(' immediately before `start`."""
    depth = 1
    in_string = False
    i = start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "'":
                in_string = False
        elif c == "'":
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced parentheses in STEP header")


def _extract_call(text: str, keyword: str) -> str | None:
    """Contents between the parentheses of `KEYWORD( ... )`, or None."""
    match = re.search(rf"{keyword}\s*\(", text)
    if not match:
        return None
    start = match.end()
    end = _find_balanced_close(text, start)
    return text[start:end]


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside nested parens or quotes."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_string = False
    for c in text:
        if in_string:
            buf.append(c)
            if c == "'":
                in_string = False
            continue
        if c == "'":
            in_string = True
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _unquote(field: str):
    """A STEP string literal, or a parenthesised list of them, as Python values."""
    field = field.strip()
    if field.startswith("(") and field.endswith(")"):
        return [_unquote(f) for f in _split_top_level(field[1:-1]) if f.strip()]
    if field.startswith("'") and field.endswith("'"):
        return field[1:-1]
    return field


def info(step_path: str | Path) -> dict:
    """Read an ISO-10303-21 STEP header without loading any geometry.

    Plain text parse of the first few KB - FILE_NAME, FILE_DESCRIPTION and
    FILE_SCHEMA are always near the top of the file by the standard's own
    layout, so this never has to scan the (potentially huge) DATA section.
    Works with no OCC installed; this is the fast path a UI calls before
    committing to a full `convert()`.
    """
    step_path = Path(step_path)
    raw = step_path.open("rb").read(_HEADER_READ_BYTES)
    text = raw.decode("ascii", errors="replace")

    if "ISO-10303-21" not in text:
        raise ValueError(f"{step_path}: not a STEP (ISO-10303-21) file")

    header_start = text.find("HEADER")
    header_end = text.find("ENDSEC", header_start if header_start != -1 else 0)
    header_text = _strip_comments(text[: header_end if header_end != -1 else len(text)])

    result: dict = {"path": str(step_path)}

    description = _extract_call(header_text, "FILE_DESCRIPTION")
    if description is not None:
        fields = _split_top_level(description)
        if len(fields) >= 1:
            result["description"] = _unquote(fields[0])
        if len(fields) >= 2:
            result["implementation_level"] = _unquote(fields[1])

    name = _extract_call(header_text, "FILE_NAME")
    if name is not None:
        fields = _split_top_level(name)
        keys = (
            "name",
            "time_stamp",
            "author",
            "organization",
            "preprocessor_version",
            "originating_system",
            "authorisation",
        )
        for key, field in zip(keys, fields):
            result[key] = _unquote(field)

    schema = _extract_call(header_text, "FILE_SCHEMA")
    if schema is not None:
        result["schema"] = _unquote(schema)

    if "name" not in result:
        raise ValueError(
            f"{step_path}: no FILE_NAME found in the STEP header "
            f"(first {_HEADER_READ_BYTES} bytes)"
        )

    return result
