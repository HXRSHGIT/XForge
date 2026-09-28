"""xforge comms - one spec, every downstream comms artefact.

`CommsSpec.load("comms.yaml")` reads a CAN/Modbus declaration; the rest of
this package turns it into the DBC, the register map and the firmware code
that all have to agree with it. See `docs/comms.md` for the spec format and
a worked example, including how a CLI subcommand should wire this up.
"""

from __future__ import annotations

from pathlib import Path

from xforge.comms.dbc import generate_dbc
from xforge.comms.firmware import generate_header, generate_source
from xforge.comms.modbus import generate_csv, generate_markdown
from xforge.comms.spec import (
    CanBus,
    CanMessage,
    CanSignal,
    CommsSpec,
    ModbusMap,
    ModbusRegister,
    SpecError,
)

__all__ = [
    "CanBus",
    "CanMessage",
    "CanSignal",
    "CommsSpec",
    "ModbusMap",
    "ModbusRegister",
    "SpecError",
    "generate_dbc",
    "generate_csv",
    "generate_markdown",
    "generate_header",
    "generate_source",
    "build",
]


def build(spec: CommsSpec, out_dir: str | Path, source_name: str = "the comms spec") -> list[Path]:
    """Write every artefact for a loaded spec into `out_dir`.

    One CAN bus emits `<bus>.dbc`, `<bus>.h` and `<bus>.c`; one Modbus map
    emits `<map>.csv` and `<map>.md`. Returns the paths written, so a CLI
    command has something to print.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for bus in spec.can_buses:
        dbc_path = out_dir / f"{bus.name}.dbc"
        dbc_path.write_text(generate_dbc(bus), encoding="utf-8")
        written.append(dbc_path)

        header_name = f"{bus.name}.h"
        header_path = out_dir / header_name
        header_path.write_text(generate_header(bus, source_name), encoding="utf-8")
        written.append(header_path)

        source_path = out_dir / f"{bus.name}.c"
        source_path.write_text(generate_source(bus, header_name), encoding="utf-8")
        written.append(source_path)

    for mapping in spec.modbus_maps:
        csv_path = out_dir / f"{mapping.name}.csv"
        csv_path.write_text(generate_csv(mapping), encoding="utf-8")
        written.append(csv_path)

        md_path = out_dir / f"{mapping.name}.md"
        md_path.write_text(generate_markdown(mapping), encoding="utf-8")
        written.append(md_path)

    return written
