"""Hierarchy rules — sheets that are drawn but not wired in.

XF005 exists because of a real defect: two sheets were added to the BJB
schematic with no sheet pins, so nothing inside them connected to anything
outside. The design looked complete and the netlist said otherwise. XF001
catches the symptom; this catches the cause, and names the sheet to fix.
"""

from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

from xforge.rules.base import Finding, Severity, rule

if TYPE_CHECKING:
    from xforge.config import Config
    from xforge.model import Design


@rule(
    id="XF005",
    title="Sheet has no electrical connection to the rest of the design",
    source="Xbattery convention; KiCad hierarchical sheet pins",
    severity=Severity.ERROR,
    blocking=True,
)
def orphaned_sheet(design: "Design", config: "Config") -> Iterable[Finding]:
    """A sheet whose components share no net with any other sheet.

    In KiCad a sub-sheet reaches the rest of the design only through sheet
    pins. A sheet symbol placed with no pins produces exactly this: every
    net inside it is sheet-local, every signal name that should cross the
    boundary becomes a second, separate net.

    A sheet holding only mechanical parts (mounting holes, fiducials) is
    legitimately unconnected, so those are not reported.
    """
    sheets = design.sheets
    if len(sheets) < 2:
        return

    # sheet -> refs on it, and ref -> sheet
    sheet_of: dict[str, str] = {}
    for sheet_name, comps in sheets.items():
        for c in comps:
            sheet_of[c.ref] = sheet_name

    # For each sheet, how many nets reach a component on a different sheet.
    external: dict[str, int] = {name: 0 for name in sheets}
    for net in design.nets:
        touched = {sheet_of.get(ref) for ref in net.refs}
        touched.discard(None)
        if len(touched) > 1:
            for name in touched:
                external[name] += 1  # type: ignore[index]

    for sheet_name, comps in sorted(sheets.items()):
        if external.get(sheet_name):
            continue
        # Mechanical-only sheets are allowed to float.
        prefixes = {c.designator_prefix for c in comps}
        if prefixes <= {"H", "FID", "MH", ""}:
            continue

        local_nets = [n for n in design.nets if design.sheet_of_net(n) == sheet_name]
        yield Finding(
            rule_id="XF005",
            severity=Severity.ERROR,
            key=sheet_name,
            summary=(
                f"Sheet '{sheet_name}' shares no net with any other sheet "
                f"({len(comps)} parts, {len(local_nets)} local nets)"
            ),
            detail=(
                "Every net on this sheet is sheet-local, so nothing inside it "
                "is electrically connected to the rest of the design. In KiCad "
                "this is what a sheet symbol placed without sheet pins looks "
                "like. Add the sheet pins on the parent sheet and wire them to "
                "the matching labels, then re-export the netlist."
            ),
            subjects=[f"parts: {', '.join(sorted(c.ref for c in comps)[:15])}"]
            + [f"local nets: {len(local_nets)}"],
            confidence="verified",
        )
