"""The comms spec: one declaration, every downstream artefact.

A `CommsSpec` is the single place a CAN ID or a Modbus register gets typed
in. `dbc.py`, `modbus.py` and `firmware.py` all read from the same loaded
spec, so the DBC message, the firmware `#define` and the integration manual
row can never drift apart - there is only one number to edit.

Bit layout follows DBC convention directly rather than inventing a friendlier
one, because the point of this generator is to reproduce the shape of the
real reverse-engineered files (LuxPower, Deye, Pylon) exactly:

- Intel / little-endian (`byte_order: little`, DBC `@1`): `start_bit` is the
  signal's least significant bit, numbered flat across the frame from 0 at
  byte 0 bit 0 up to 8*DLC-1. This is what all three real DBC files use, and
  it is also the numbering the signal's other bits are found at: bit `i` of
  the raw value sits at physical bit `start_bit + i`.
- Motorola / big-endian (`byte_order: big`, DBC `@0`): `start_bit` is the
  signal's most significant bit, in the DBC "sawtooth" numbering where a
  byte's bits run 7..0 instead of 0..7. `CanSignal.bit_mapping()` is the one
  place that numbering is decoded, so overlap checking and firmware codegen
  can never disagree about which physical bit belongs to which signal.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BYTE_ORDERS = ("little", "big")
CAN_ADDRESSING = ("standard", "extended")
MODBUS_TYPES = ("holding", "input", "coil", "discrete")
MODBUS_DATA_TYPES = ("u16", "i16", "u32", "i32", "f32")

# Registers occupied by each Modbus data type. Coils and discrete inputs are
# single-bit values, but Modbus still addresses them one per register number,
# so the width table applies uniformly.
_MODBUS_WIDTH = {"u16": 1, "i16": 1, "u32": 2, "i32": 2, "f32": 2}

# 11-bit standard vs 29-bit extended CAN identifier ranges.
_CAN_ID_MAX = {"standard": 0x7FF, "extended": 0x1FFFFFFF}


class SpecError(ValueError):
    """A spec fails validation. Always names the offending signal/message."""


def valid_identifier(name: str) -> str:
    """A DBC/C identifier: letters, digits, underscore, not starting with a
    digit. Both emitted formats share this rule; checked once here so a bad
    name raises instead of silently corrupting either output file."""
    if not name or not (name[0].isalpha() or name[0] == "_"):
        raise SpecError(f"'{name}' is not a valid identifier (must start with a letter or _)")
    if not all(c.isalnum() or c == "_" for c in name):
        raise SpecError(f"'{name}' is not a valid identifier (letters, digits, _ only)")
    return name


def _parse_int(value, field_name: str) -> int:
    """Accept an int or a hex/decimal string ('0x351', '849') from YAML."""
    if isinstance(value, bool):  # bool is an int subclass; YAML "true" is not an id
        raise SpecError(f"{field_name}: expected an integer, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            raise SpecError(f"{field_name}: cannot parse {value!r} as an integer") from None
    raise SpecError(f"{field_name}: cannot parse {value!r} as an integer")


@dataclass
class CanSignal:
    """One field inside a CAN message."""

    name: str
    start_bit: int
    length: int
    byte_order: str = "little"
    is_signed: bool = False
    scale: float = 1.0
    offset: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    comment: str = ""
    values: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict, default_byte_order: str) -> "CanSignal":
        name = raw.get("name")
        if not name:
            raise SpecError("signal is missing a name")
        byte_order = raw.get("byte_order", default_byte_order)
        if byte_order not in BYTE_ORDERS:
            raise SpecError(
                f"signal '{name}': byte_order must be one of {BYTE_ORDERS}, got {byte_order!r}"
            )
        length = int(raw.get("length", 0))
        if length < 1 or length > 64:
            raise SpecError(f"signal '{name}': length must be 1-64 bits, got {length}")
        start_bit = int(raw.get("start_bit", raw.get("start-bit", -1)))
        if start_bit < 0:
            raise SpecError(f"signal '{name}': start_bit is required and must be >= 0")
        return cls(
            name=name,
            start_bit=start_bit,
            length=length,
            byte_order=byte_order,
            is_signed=bool(raw.get("is_signed", False)),
            scale=float(raw.get("scale", 1.0)),
            offset=float(raw.get("offset", 0.0)),
            minimum=(float(raw["minimum"]) if raw.get("minimum") is not None else None),
            maximum=(float(raw["maximum"]) if raw.get("maximum") is not None else None),
            unit=str(raw.get("unit", "")),
            comment=str(raw.get("comment", "")),
            values={int(k): str(v) for k, v in (raw.get("values", {}) or {}).items()},
        )

    def bit_mapping(self) -> list[tuple[int, int]]:
        """[(value_bit_index, physical_bit)] pairs.

        `value_bit_index` 0 is the LSB of the raw (pre-scale) integer.
        `physical_bit` is 0 at byte 0's LSB, counting up through the frame -
        the one representation overlap checking and firmware codegen share.
        """
        if self.byte_order == "little":
            return [(i, self.start_bit + i) for i in range(self.length)]
        # Motorola: start_bit is already the physical bit of the signal's
        # MSB (0 = byte 0's LSB, same physical numbering as the little-endian
        # case). Walking from there toward the LSB normally moves down by
        # one bit; on hitting a byte's own LSB (physical % 8 == 0) the next
        # bit toward the value's LSB is the *next* byte's MSB, 15 bits up -
        # confirmed empirically against cantools' own encode/decode rather
        # than derived from the DBC spec text, which several independent
        # tools describe inconsistently.
        mapping = []
        physical = self.start_bit
        for s in range(self.length):
            i = self.length - 1 - s
            mapping.append((i, physical))
            physical = physical + 15 if physical % 8 == 0 else physical - 1
        return mapping

    def physical_bits(self) -> set[int]:
        return {p for _, p in self.bit_mapping()}

    def raw_range(self) -> tuple[int, int]:
        """The bit width's own range, used when minimum/maximum are unset."""
        if self.is_signed:
            return (-(2 ** (self.length - 1)), 2 ** (self.length - 1) - 1)
        return (0, 2**self.length - 1)

    def effective_range(self) -> tuple[float, float]:
        """(minimum, maximum), defaulting to what the raw bit width implies."""
        if self.minimum is not None and self.maximum is not None:
            return (self.minimum, self.maximum)
        lo_raw, hi_raw = self.raw_range()
        lo = lo_raw * self.scale + self.offset
        hi = hi_raw * self.scale + self.offset
        return (min(lo, hi), max(lo, hi))


@dataclass
class CanMessage:
    """One CAN frame: an id, a sender, and the signals packed into it."""

    name: str
    id: int
    dlc: int
    sender: str
    cycle_time_ms: int | None = None
    byte_order: str = "little"  # default a signal inherits unless it overrides
    comment: str = ""
    signals: list[CanSignal] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict) -> "CanMessage":
        name = raw.get("name")
        if not name:
            raise SpecError("message is missing a name")
        byte_order = raw.get("byte_order", "little")
        if byte_order not in BYTE_ORDERS:
            raise SpecError(
                f"message '{name}': byte_order must be one of {BYTE_ORDERS}, got {byte_order!r}"
            )
        msg = cls(
            name=name,
            id=_parse_int(raw.get("id"), f"message '{name}' id"),
            dlc=int(raw.get("dlc", 8)),
            sender=str(raw.get("sender", "")),
            cycle_time_ms=(
                int(raw["cycle_time_ms"]) if raw.get("cycle_time_ms") is not None else None
            ),
            byte_order=byte_order,
            comment=str(raw.get("comment", "")),
            signals=[
                CanSignal.from_raw(s, byte_order) for s in raw.get("signals", []) or []
            ],
        )
        if not msg.sender:
            raise SpecError(f"message '{name}': sender is required")
        return msg

    def validate(self, fd: bool) -> None:
        dlc_limit = 64 if fd else 8
        if not (0 <= self.dlc <= dlc_limit):
            raise SpecError(
                f"message '{self.name}': dlc {self.dlc} out of range 0-{dlc_limit}"
            )
        names_seen: set[str] = set()
        for sig in self.signals:
            if sig.name in names_seen:
                raise SpecError(f"message '{self.name}': signal '{sig.name}' declared twice")
            names_seen.add(sig.name)
            bits = sig.physical_bits()
            if max(bits, default=-1) >= self.dlc * 8:
                raise SpecError(
                    f"message '{self.name}': signal '{sig.name}' (start_bit={sig.start_bit}, "
                    f"length={sig.length}) does not fit inside dlc={self.dlc} "
                    f"({self.dlc * 8} bits available)"
                )
        # Overlap check: every pair of signals, compared bit by bit. O(n^2)
        # over signals-per-message, which is small (single digits) in every
        # real message seen so far.
        owner: dict[int, str] = {}
        for sig in self.signals:
            for bit in sorted(sig.physical_bits()):
                if bit in owner:
                    raise SpecError(
                        f"message '{self.name}': signal '{sig.name}' overlaps "
                        f"'{owner[bit]}' at bit {bit}"
                    )
                owner[bit] = sig.name


@dataclass
class CanBus:
    """A physical CAN network: framing rules plus the messages on it."""

    name: str
    bitrate: int
    addressing: str = "standard"
    fd: bool = False
    messages: list[CanMessage] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict) -> "CanBus":
        name = raw.get("name")
        if not name:
            raise SpecError("CAN bus is missing a name")
        addressing = raw.get("addressing", "standard")
        if addressing not in CAN_ADDRESSING:
            raise SpecError(
                f"bus '{name}': addressing must be one of {CAN_ADDRESSING}, got {addressing!r}"
            )
        return cls(
            name=name,
            bitrate=int(raw.get("bitrate", 500000)),
            addressing=addressing,
            fd=bool(raw.get("fd", False)),
            messages=[CanMessage.from_raw(m) for m in raw.get("messages", []) or []],
        )

    def validate(self) -> None:
        id_max = _CAN_ID_MAX[self.addressing]
        seen: dict[int, str] = {}
        for msg in self.messages:
            if not (0 <= msg.id <= id_max):
                raise SpecError(
                    f"bus '{self.name}': message '{msg.name}' id {hex(msg.id)} is out of "
                    f"range for {self.addressing} addressing (max {hex(id_max)})"
                )
            if msg.id in seen:
                raise SpecError(
                    f"bus '{self.name}': message '{msg.name}' reuses id {hex(msg.id)} "
                    f"already used by '{seen[msg.id]}'"
                )
            seen[msg.id] = msg.name
            msg.validate(self.fd)


@dataclass
class ModbusRegister:
    """One row of a Modbus register map."""

    address: int
    name: str
    type: str
    data_type: str = "u16"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    access: str = "r"
    description: str = ""

    @classmethod
    def from_raw(cls, raw: dict) -> "ModbusRegister":
        name = raw.get("name")
        if not name:
            raise SpecError("Modbus register is missing a name")
        rtype = raw.get("type")
        if rtype not in MODBUS_TYPES:
            raise SpecError(
                f"register '{name}': type must be one of {MODBUS_TYPES}, got {rtype!r}"
            )
        data_type = raw.get("data_type", "u16")
        if data_type not in MODBUS_DATA_TYPES:
            raise SpecError(
                f"register '{name}': data_type must be one of {MODBUS_DATA_TYPES}, "
                f"got {data_type!r}"
            )
        access = raw.get("access", "r")
        if access not in ("r", "rw"):
            raise SpecError(f"register '{name}': access must be 'r' or 'rw', got {access!r}")
        return cls(
            address=_parse_int(raw.get("address"), f"register '{name}' address"),
            name=name,
            type=rtype,
            data_type=data_type,
            scale=float(raw.get("scale", 1.0)),
            offset=float(raw.get("offset", 0.0)),
            unit=str(raw.get("unit", "")),
            access=access,
            description=str(raw.get("description", "")),
        )

    @property
    def width(self) -> int:
        """Registers this entry occupies. Coils/discrete are single-bit but
        still take one register slot each in their own address space."""
        return _MODBUS_WIDTH[self.data_type]


@dataclass
class ModbusMap:
    """A Modbus register map: one node, several registers."""

    name: str
    registers: list[ModbusRegister] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict) -> "ModbusMap":
        name = raw.get("name")
        if not name:
            raise SpecError("Modbus map is missing a name")
        return cls(
            name=name,
            registers=[ModbusRegister.from_raw(r) for r in raw.get("registers", []) or []],
        )

    def validate(self) -> None:
        # Coils, discrete inputs, input registers and holding registers are
        # four separate Modbus address spaces - a collision only matters
        # within the same type, not across them.
        by_type: dict[str, list[ModbusRegister]] = defaultdict(list)
        for reg in self.registers:
            by_type[reg.type].append(reg)
        for rtype, regs in by_type.items():
            owner: dict[int, str] = {}
            for reg in sorted(regs, key=lambda r: r.address):
                for addr in range(reg.address, reg.address + reg.width):
                    if addr in owner:
                        raise SpecError(
                            f"map '{self.name}' ({rtype}): register '{reg.name}' at "
                            f"{hex(reg.address)} (width {reg.width}) collides with "
                            f"'{owner[addr]}' at register address {hex(addr)}"
                        )
                    owner[addr] = reg.name


@dataclass
class CommsSpec:
    """Everything declared for a project: every CAN bus and Modbus map."""

    can_buses: list[CanBus] = field(default_factory=list)
    modbus_maps: list[ModbusMap] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "CommsSpec":
        spec = cls(
            can_buses=[CanBus.from_raw(b) for b in raw.get("can_buses", []) or []],
            modbus_maps=[ModbusMap.from_raw(m) for m in raw.get("modbus_maps", []) or []],
        )
        spec.validate()
        return spec

    @classmethod
    def load(cls, path: str | Path) -> "CommsSpec":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"comms spec not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_dict(raw)

    def validate(self) -> None:
        for bus in self.can_buses:
            bus.validate()
        for m in self.modbus_maps:
            m.validate()
