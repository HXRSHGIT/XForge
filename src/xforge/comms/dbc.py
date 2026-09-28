"""Emit a Vector `.dbc` from a `CommsSpec`.

Written as plain text rather than built through cantools' own `Database`
object: generation stays dependency-free (the `comms` extra only has to be
installed to *parse* what this writes, in the round-trip test and by anyone
consuming the DBC downstream), and it keeps the emitted layout in full view
next to the real LuxPower/Deye/Pylon files it is meant to reproduce.
"""

from __future__ import annotations

from xforge.comms.spec import CanBus, CanMessage, CanSignal, valid_identifier

# Every receiver is declared "don't care" rather than modelled explicitly -
# the spec doesn't ask for a receiver list, and Vector__XXX is the standard
# DBC placeholder for that, recognised by cantools and other tooling without
# needing to appear in BU_.
_NO_RECEIVER = "Vector__XXX"

_HEADER_KEYWORDS = [
    "NS_DESC_", "CM_", "BA_DEF_", "BA_", "VAL_", "CAT_DEF_", "CAT_", "FILTER",
    "BA_DEF_DEF_", "EV_DATA_", "ENVVAR_DATA_", "SGTYPE_", "SIG_TYPE_REF_",
    "VAL_TABLE_", "SIG_GROUP_", "SIG_VALTYPE_", "BA_DEF_REL_", "BA_REL_",
    "BA_SGTYPE_REL_", "SG_MUL_VAL_",
]


def _fmt_num(x: float) -> str:
    """DBC writes whole numbers bare ("1", "0.1"), not "1.0" - matches every
    real file on hand and keeps the output easy to eyeball against them."""
    if float(x) == int(x):
        return str(int(x))
    return repr(float(x))


def _escape(text: str) -> str:
    return text.replace('"', "'")


def _signal_line(sig: CanSignal) -> str:
    order_bit = "1" if sig.byte_order == "little" else "0"
    sign = "-" if sig.is_signed else "+"
    lo, hi = sig.effective_range()
    return (
        f" SG_ {valid_identifier(sig.name)} : {sig.start_bit}|{sig.length}@{order_bit}{sign} "
        f"({_fmt_num(sig.scale)},{_fmt_num(sig.offset)}) [{_fmt_num(lo)}|{_fmt_num(hi)}] "
        f'"{_escape(sig.unit)}" {_NO_RECEIVER}'
    )


# DBC has no separate field for the addressing mode: a 29-bit identifier is
# marked by setting bit 31 of the id written in the BO_ record. Without it a
# reader treats 0x1801A1F0 as a standard frame and rejects it for being wider
# than 11 bits, which is what cantools does.
_EXTENDED_FLAG = 0x80000000


def dbc_frame_id(msg_id: int, addressing: str) -> int:
    """The identifier as a DBC file encodes it, including the extended flag."""
    return msg_id | _EXTENDED_FLAG if addressing == "extended" else msg_id


def _message_lines(msg: CanMessage, addressing: str = "standard") -> list[str]:
    frame_id = dbc_frame_id(msg.id, addressing)
    lines = [
        f"BO_ {frame_id} {valid_identifier(msg.name)}: "
        f"{msg.dlc} {valid_identifier(msg.sender)}"
    ]
    lines.extend(_signal_line(sig) for sig in msg.signals)
    return lines


def generate_dbc(bus: CanBus, version: str = "") -> str:
    """Render one CAN bus as DBC text.

    A DBC file describes one bus, so multi-bus specs call this once per
    `CanBus` and write one file each - matching how a DBC is actually
    consumed (a CAN tool loads one database per physical network).
    """
    nodes: list[str] = []
    for msg in bus.messages:
        if msg.sender not in nodes:
            nodes.append(msg.sender)

    lines: list[str] = [f'VERSION "{_escape(version or bus.name)}"', "", ""]
    lines.append("NS_ :")
    lines.extend(f"\t{kw}" for kw in _HEADER_KEYWORDS)
    lines.append("")
    lines.append("BS_:")
    lines.append("")
    lines.append(f"BU_: {' '.join(valid_identifier(n) for n in nodes)}")
    lines.append("")

    for msg in bus.messages:
        lines.extend(_message_lines(msg, bus.addressing))
        lines.append("")

    comments: list[str] = []
    for msg in bus.messages:
        if msg.comment:
            comments.append(
                f'CM_ BO_ {dbc_frame_id(msg.id, bus.addressing)} '
                f'"{_escape(msg.comment)}";'
            )
        for sig in msg.signals:
            if sig.comment:
                comments.append(
                    f'CM_ SG_ {dbc_frame_id(msg.id, bus.addressing)} '
                    f'{valid_identifier(sig.name)} "{_escape(sig.comment)}";'
                )
    if comments:
        lines.extend(comments)
        lines.append("")

    # GenMsgCycleTime is the DBC-native way to carry cycle time (cantools
    # reads it straight into Message.cycle_time), matching pylon.dbc's own
    # convention rather than burying the number in free-text comments only.
    if any(m.cycle_time_ms is not None for m in bus.messages):
        lines.append('BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;')
        lines.append('BA_DEF_DEF_ "GenMsgCycleTime" 0;')
        for msg in bus.messages:
            if msg.cycle_time_ms is not None:
                lines.append(
                    f'BA_ "GenMsgCycleTime" BO_ '
                    f'{dbc_frame_id(msg.id, bus.addressing)} {msg.cycle_time_ms};'
                )
        lines.append("")

    val_lines = []
    for msg in bus.messages:
        for sig in msg.signals:
            if not sig.values:
                continue
            pairs = " ".join(f'{raw} "{_escape(label)}"' for raw, label in sorted(sig.values.items()))
            val_lines.append(
                f"VAL_ {dbc_frame_id(msg.id, bus.addressing)} "
                f"{valid_identifier(sig.name)} {pairs} ;"
            )
    if val_lines:
        lines.extend(val_lines)

    return "\n".join(lines).rstrip() + "\n"
