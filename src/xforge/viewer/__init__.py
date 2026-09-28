"""Board geometry for the viewport.

Two readers, chosen by what a project actually has.

`idf` reads the IDF 3.0 mechanical handoff that every ECAD tool writes: the
board outline with its cutouts, and every component's placement, rotation,
side and height. It is plain text, needs no CAD kernel, and keeps reference
designators attached to the geometry - so a finding that names R902 can light
up R902 in the viewport.

`step` reads a STEP export through OpenCASCADE. It is prettier, it needs a
heavy optional extra, and a tessellated solid has no idea which component it
is. It is also the path most likely to be unavailable: on this machine
Windows Smart App Control blocks one of OpenCASCADE's DLLs outright.

IDF is the default for those reasons, not because it renders better. The
STEP path is imported lazily so this package works without it.
"""

from xforge.viewer.idf import Board, IdfError, read_board, read_library, to_scene

__all__ = [
    "Board",
    "IdfError",
    "read_board",
    "read_library",
    "to_scene",
    "convert",
    "info",
]


def __getattr__(name: str):
    """Expose the STEP reader only when someone asks for it.

    Keeps `import xforge.viewer` working on a machine where OpenCASCADE
    cannot load, which is most of the reason IDF is the default path.
    """
    if name in ("convert", "info", "ModelInfo"):
        try:
            from xforge.viewer import step
        except ImportError as exc:
            raise AttributeError(
                f"xforge.viewer.{name} needs the STEP reader. "
                'Install it with: pip install -e ".[viewer]"'
            ) from exc
        return getattr(step, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
