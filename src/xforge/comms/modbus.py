"""Emit a Modbus register map as CSV and Markdown.

Both read from the same `ModbusMap`, so the CSV a test rig imports and the
table in the integration manual are never two hand-kept copies of the same
information.
"""

from __future__ import annotations

import csv
import io

from xforge.comms.spec import ModbusMap

_COLUMNS = [
    "address", "name", "type", "data_type", "scale", "offset",
    "unit", "access", "description",
]


def _row(reg) -> list[str]:
    return [
        hex(reg.address),
        reg.name,
        reg.type,
        reg.data_type,
        _fmt(reg.scale),
        _fmt(reg.offset),
        reg.unit,
        reg.access,
        reg.description,
    ]


def _fmt(x: float) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)


def _sorted_registers(mapping: ModbusMap):
    return sorted(mapping.registers, key=lambda r: (r.type, r.address))


def generate_csv(mapping: ModbusMap) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_COLUMNS)
    for reg in _sorted_registers(mapping):
        writer.writerow(_row(reg))
    return buf.getvalue()


def generate_markdown(mapping: ModbusMap) -> str:
    lines = [f"# {mapping.name}", ""]
    lines.append("| " + " | ".join(_COLUMNS) + " |")
    lines.append("|" + "---|" * len(_COLUMNS))
    for reg in _sorted_registers(mapping):
        cells = [c.replace("|", "\\|") for c in _row(reg)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)
