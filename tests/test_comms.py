"""Tests for xforge.comms: spec validation, DBC/Modbus/firmware generation.

The DBC round-trip tests need cantools (`pip install -e ".[comms]"`); they
are skipped rather than failed when it isn't installed, since generation
itself has no hard dependency on it.
"""

from __future__ import annotations

import csv
import io

import pytest

from xforge.comms import (
    CommsSpec,
    SpecError,
    generate_csv,
    generate_dbc,
    generate_header,
    generate_markdown,
    generate_source,
)
from xforge.comms.spec import CanBus, CanMessage, CanSignal, ModbusMap

cantools = pytest.importorskip("cantools", reason="comms extra not installed")


# ---------------------------------------------------------------------------
# Bit mapping: the thing overlap-checking and firmware codegen both build on
# ---------------------------------------------------------------------------

class TestBitMapping:
    def test_little_endian_is_flat_and_contiguous(self):
        """Matches every real file on hand: Intel start_bit is already the
        physical LSB position, extending upward through the frame."""
        sig = CanSignal(name="V", start_bit=16, length=16, byte_order="little")
        assert sig.physical_bits() == set(range(16, 32))
        # value bit 0 (LSB) sits at the lowest physical bit, matching a
        # little-endian multi-byte value (low byte first).
        assert dict(sig.bit_mapping())[0] == 16

    def test_big_endian_whole_byte_is_a_straight_bit_reversal(self):
        """A big-endian signal spanning exactly one byte does not move
        bytes, so its physical footprint is that byte, MSB-first."""
        sig = CanSignal(name="B", start_bit=7, length=8, byte_order="big")
        assert sig.physical_bits() == set(range(0, 8))

    def test_big_endian_crosses_byte_boundary_into_next_bytes_msb(self):
        """A 16-bit Motorola signal declared at byte0 bit7 must occupy
        byte0 (all 8 bits) and byte1 (all 8 bits) - not fold back into
        byte0 twice, which is the classic Motorola-numbering bug."""
        sig = CanSignal(name="W", start_bit=7, length=16, byte_order="big")
        assert sig.physical_bits() == set(range(0, 16))


# ---------------------------------------------------------------------------
# Validation: a case that fires, and the legitimate lookalike that must not
# ---------------------------------------------------------------------------

class TestSignalOverlap:
    def test_overlapping_signals_raise(self):
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [{
                "name": "Msg", "id": 1, "dlc": 8, "sender": "BMS",
                "signals": [
                    {"name": "A", "start_bit": 0, "length": 9},
                    {"name": "B", "start_bit": 8, "length": 8},
                ],
            }],
        }
        with pytest.raises(SpecError, match="overlaps"):
            CanBus.from_raw(raw).validate()

    def test_adjacent_signals_sharing_a_byte_do_not_overlap(self):
        """The legitimate lookalike: two signals packed into the same byte,
        touching but not sharing a bit - exactly how LuxPower's Protection/
        Alarm bitfields are packed."""
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [{
                "name": "Msg", "id": 1, "dlc": 8, "sender": "BMS",
                "signals": [
                    {"name": "Low", "start_bit": 0, "length": 4},
                    {"name": "High", "start_bit": 4, "length": 4},
                ],
            }],
        }
        CanBus.from_raw(raw).validate()  # must not raise


class TestSignalFitsDlc:
    def test_signal_beyond_dlc_raises(self):
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [{
                "name": "Msg", "id": 1, "dlc": 4, "sender": "BMS",
                "signals": [{"name": "Over", "start_bit": 24, "length": 16}],
            }],
        }
        with pytest.raises(SpecError, match="does not fit"):
            CanBus.from_raw(raw).validate()

    def test_signal_exactly_filling_the_last_byte_does_not_raise(self):
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [{
                "name": "Msg", "id": 1, "dlc": 4, "sender": "BMS",
                "signals": [{"name": "Fits", "start_bit": 24, "length": 8}],
            }],
        }
        CanBus.from_raw(raw).validate()  # must not raise


class TestCanIdRange:
    def test_duplicate_id_raises(self):
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [
                {"name": "A", "id": "0x351", "dlc": 8, "sender": "BMS", "signals": []},
                {"name": "B", "id": "0x351", "dlc": 8, "sender": "BMS", "signals": []},
            ],
        }
        with pytest.raises(SpecError, match="reuses id"):
            CanBus.from_raw(raw).validate()

    def test_distinct_ids_do_not_raise(self):
        raw = {
            "name": "bus", "bitrate": 500000,
            "messages": [
                {"name": "A", "id": "0x351", "dlc": 8, "sender": "BMS", "signals": []},
                {"name": "B", "id": "0x355", "dlc": 8, "sender": "BMS", "signals": []},
            ],
        }
        CanBus.from_raw(raw).validate()  # must not raise

    def test_id_beyond_11_bit_standard_range_raises(self):
        raw = {
            "name": "bus", "bitrate": 500000, "addressing": "standard",
            "messages": [{"name": "A", "id": "0x800", "dlc": 8, "sender": "BMS", "signals": []}],
        }
        with pytest.raises(SpecError, match="out of range"):
            CanBus.from_raw(raw).validate()

    def test_same_id_is_fine_under_extended_addressing(self):
        """The lookalike: 0x800 is invalid for standard addressing but is a
        perfectly ordinary 29-bit extended id."""
        raw = {
            "name": "bus", "bitrate": 500000, "addressing": "extended",
            "messages": [{"name": "A", "id": "0x800", "dlc": 8, "sender": "BMS", "signals": []}],
        }
        CanBus.from_raw(raw).validate()  # must not raise


class TestModbusCollision:
    def test_wide_register_colliding_with_the_next_one_raises(self):
        raw = {
            "name": "map",
            "registers": [
                {"name": "soc", "address": 100, "type": "holding", "data_type": "u32"},
                {"name": "soh", "address": 101, "type": "holding", "data_type": "u16"},
            ],
        }
        with pytest.raises(SpecError, match="collides"):
            ModbusMap.from_raw(raw).validate()

    def test_wide_register_followed_immediately_after_does_not_collide(self):
        """The legitimate lookalike: the u32 at 100-101 and a u16 starting
        exactly at 102 - adjacent, not overlapping."""
        raw = {
            "name": "map",
            "registers": [
                {"name": "soc", "address": 100, "type": "holding", "data_type": "u32"},
                {"name": "soh", "address": 102, "type": "holding", "data_type": "u16"},
            ],
        }
        ModbusMap.from_raw(raw).validate()  # must not raise

    def test_same_address_in_different_register_types_does_not_collide(self):
        """Coils, discrete inputs, holding and input registers are four
        separate Modbus address spaces - reusing a number across them is
        normal, not a defect."""
        raw = {
            "name": "map",
            "registers": [
                {"name": "enable", "address": 0, "type": "coil"},
                {"name": "soc", "address": 0, "type": "holding", "data_type": "u16"},
            ],
        }
        ModbusMap.from_raw(raw).validate()  # must not raise


# ---------------------------------------------------------------------------
# DBC generation: round-trip through cantools
# ---------------------------------------------------------------------------

def _load(dbc_text: str):
    return cantools.database.load_string(dbc_text, database_format="dbc")


class TestDbcRoundTrip:
    """Generate -> parse with cantools -> every message/signal survives."""

    def _spec(self) -> CommsSpec:
        return CommsSpec.from_dict({
            "can_buses": [{
                "name": "battery_can",
                "bitrate": 500000,
                "addressing": "standard",
                "messages": [
                    {
                        "name": "BatteryLimits_0x351",
                        "id": "0x351",
                        "dlc": 8,
                        "sender": "BMS",
                        "cycle_time_ms": 1000,
                        "comment": "Charge/discharge limits",
                        "signals": [
                            {
                                "name": "Charge_voltage_recommand",
                                "start_bit": 0, "length": 16,
                                "scale": 0.1, "offset": 0, "unit": "V",
                                "comment": "Charge voltage recommand",
                            },
                            {
                                "name": "Pack_current",
                                "start_bit": 16, "length": 16, "is_signed": True,
                                "scale": 0.1, "offset": 0, "minimum": -1000,
                                "maximum": 1000, "unit": "A",
                            },
                        ],
                    },
                    {
                        "name": "StatusFlags",
                        "id": "0x359",
                        "dlc": 8,
                        "sender": "BMS",
                        "signals": [
                            {
                                "name": "Over_voltage",
                                "start_bit": 1, "length": 1,
                                "values": {0: "NoFault", 1: "Fault"},
                            },
                            {
                                "name": "BE_Field",
                                "start_bit": 23, "length": 16, "byte_order": "big",
                                "is_signed": True, "scale": 0.5, "offset": -10,
                            },
                        ],
                    },
                ],
            }],
        })

    def test_every_message_and_signal_survives(self):
        bus = self._spec().can_buses[0]
        db = _load(generate_dbc(bus))

        assert {m.name for m in db.messages} == {m.name for m in bus.messages}

        for msg in bus.messages:
            parsed = db.get_message_by_name(msg.name)
            assert parsed.frame_id == msg.id
            assert parsed.length == msg.dlc
            assert parsed.senders == [msg.sender]
            if msg.cycle_time_ms is not None:
                assert parsed.cycle_time == msg.cycle_time_ms

            by_name = {s.name: s for s in parsed.signals}
            assert set(by_name) == {s.name for s in msg.signals}
            for sig in msg.signals:
                p = by_name[sig.name]
                assert p.start == sig.start_bit
                assert p.length == sig.length
                assert p.is_signed == sig.is_signed
                assert p.byte_order == (
                    "little_endian" if sig.byte_order == "little" else "big_endian"
                )
                assert p.scale == pytest.approx(sig.scale)
                assert p.offset == pytest.approx(sig.offset)
                if sig.values:
                    assert p.choices is not None
                    assert {k: v.name for k, v in p.choices.items()} == {
                        k: v for k, v in sig.values.items()
                    }

    def test_encode_decode_agrees_with_a_pure_python_reference(self):
        """Cross-checks CanSignal.bit_mapping() - the same mapping firmware.py
        codegen uses - against cantools' independent implementation, raw
        (unscaled) values in both directions. This is as close as this repo
        gets to compiling the generated C: same bit arithmetic, checked
        against a different implementation of the DBC bit-layout rules.
        """
        bus = self._spec().can_buses[0]
        db = _load(generate_dbc(bus))
        msg = bus.messages[1]  # StatusFlags: one bitfield + one big-endian signal
        parsed = db.get_message_by_name(msg.name)

        raw_values = {"Over_voltage": 1, "BE_Field": -12345 & 0xFFFF}
        # cantools wants signed ints for signed signals, not the raw bit
        # pattern, so give it the actual signed value for that one.
        cantools_input = dict(raw_values)
        cantools_input["BE_Field"] = -12345

        wire = parsed.encode(cantools_input, scaling=False)

        expected = bytearray(msg.dlc)
        for sig in msg.signals:
            value = raw_values[sig.name]
            for i, p in sig.bit_mapping():
                if (value >> i) & 1:
                    expected[p // 8] |= 1 << (p % 8)

        assert bytes(wire) == bytes(expected)

        decoded = parsed.decode(bytes(wire), decode_choices=False, scaling=False)
        assert decoded["Over_voltage"] == 1
        assert decoded["BE_Field"] == -12345


class TestLuxPowerGolden:
    """The generator must reproduce the exact bit layout of the real,
    reverse-engineered LuxPower DBC for the same message - PackStatus_0x356,
    transcribed from dbc_luxpower_v1.0.dbc on the Desktop."""

    def _spec(self) -> CommsSpec:
        return CommsSpec.from_dict({
            "can_buses": [{
                "name": "luxpower",
                "bitrate": 500000,
                "messages": [{
                    "name": "PackStatus_0x356",
                    "id": "0x356",
                    "dlc": 8,
                    "sender": "BMS",
                    "signals": [
                        {"name": "Pack_voltage", "start_bit": 0, "length": 16,
                         "scale": 0.01, "offset": 0, "minimum": 0, "maximum": 1000, "unit": "V"},
                        {"name": "Pack_current", "start_bit": 16, "length": 16,
                         "is_signed": True, "scale": 0.1, "offset": 0,
                         "minimum": -1000, "maximum": 1000, "unit": "A"},
                        {"name": "Cell_temperature", "start_bit": 32, "length": 16,
                         "is_signed": True, "scale": 0.1, "offset": 0,
                         "minimum": -100, "maximum": 100, "unit": "degC"},
                        {"name": "Reserved_Byte6", "start_bit": 48, "length": 8,
                         "minimum": 0, "maximum": 255},
                        {"name": "Reserved_Byte7", "start_bit": 56, "length": 8,
                         "minimum": 0, "maximum": 255},
                    ],
                }],
            }],
        })

    def test_matches_the_real_dbc_bit_layout(self):
        real = cantools.database.load_file(
            r"C:\Users\TempAdmin\Desktop\LuxPower-SNA5000-Comms\dbc_luxpower_v1.0.dbc"
        )
        real_msg = real.get_message_by_name("PackStatus_0x356")

        bus = self._spec().can_buses[0]
        generated = _load(generate_dbc(bus))
        gen_msg = generated.get_message_by_name("PackStatus_0x356")

        assert gen_msg.frame_id == real_msg.frame_id == 0x356
        real_by_name = {s.name: s for s in real_msg.signals}
        gen_by_name = {s.name: s for s in gen_msg.signals}
        assert set(gen_by_name) == set(real_by_name)
        for name, real_sig in real_by_name.items():
            gen_sig = gen_by_name[name]
            assert gen_sig.start == real_sig.start, name
            assert gen_sig.length == real_sig.length, name
            assert gen_sig.is_signed == real_sig.is_signed, name
            assert gen_sig.scale == pytest.approx(real_sig.scale), name
            assert gen_sig.offset == pytest.approx(real_sig.offset), name


# ---------------------------------------------------------------------------
# Modbus outputs
# ---------------------------------------------------------------------------

class TestModbusOutputs:
    def _map(self) -> ModbusMap:
        return ModbusMap.from_raw({
            "name": "inverter_registers",
            "registers": [
                {"name": "battery_soc", "address": "0x9C40", "type": "holding",
                 "data_type": "u16", "unit": "%", "access": "r",
                 "description": "State of charge"},
                {"name": "battery_soh", "address": "0x9C41", "type": "holding",
                 "data_type": "u16", "unit": "%", "access": "r"},
            ],
        })

    def test_csv_has_one_row_per_register_in_address_order(self):
        text = generate_csv(self._map())
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == [
            "address", "name", "type", "data_type", "scale", "offset",
            "unit", "access", "description",
        ]
        assert [r[1] for r in rows[1:]] == ["battery_soc", "battery_soh"]
        assert rows[1][0] == hex(0x9C40)

    def test_markdown_is_a_table_with_every_register(self):
        text = generate_markdown(self._map())
        assert "battery_soc" in text
        assert "battery_soh" in text
        assert text.count("\n|") >= 3  # header, separator, >=1 data row


# ---------------------------------------------------------------------------
# Firmware output
# ---------------------------------------------------------------------------

class TestFirmwareOutput:
    def _bus(self) -> CanBus:
        return CanBus.from_raw({
            "name": "battery_can",
            "bitrate": 500000,
            "messages": [{
                "name": "BatteryLimits_0x351",
                "id": "0x351",
                "dlc": 8,
                "sender": "BMS",
                "cycle_time_ms": 1000,
                "signals": [
                    {"name": "Charge_voltage", "start_bit": 0, "length": 16,
                     "scale": 0.1, "unit": "V"},
                    {"name": "Pack_current", "start_bit": 16, "length": 16,
                     "is_signed": True, "scale": 0.1, "unit": "A"},
                    {"name": "Fault", "start_bit": 32, "length": 1,
                     "values": {0: "NoFault", 1: "Fault"}},
                ],
            }],
        })

    def test_header_declares_id_dlc_struct_and_functions(self):
        header = generate_header(self._bus())
        assert "#define BATTERYLIMITS_0X351_ID 0x351u" in header
        assert "#define BATTERYLIMITS_0X351_DLC 8u" in header
        assert "#define BATTERYLIMITS_0X351_CYCLE_TIME_MS 1000u" in header
        assert "uint16_t Charge_voltage;" in header
        assert "int16_t Pack_current;" in header
        assert "#define BATTERYLIMITS_0X351_FAULT_NOFAULT 0" in header
        assert "#define BATTERYLIMITS_0X351_FAULT_FAULT 1" in header
        assert "void batterylimits_0x351_pack(uint8_t data[8]" in header
        assert "void batterylimits_0x351_unpack(BatteryLimits_0x351_t *msg" in header

    def test_source_packs_and_unpacks_every_signal(self):
        bus = self._bus()
        source = generate_source(bus, "battery_can.h")
        assert '#include "battery_can.h"' in source
        assert "void batterylimits_0x351_pack(uint8_t data[8]" in source
        assert "memset(data, 0, 8);" in source
        # One bit-test line per bit of the 16-bit Pack_current signal.
        assert source.count("raw >> ") >= 16
        # The signed 16-bit signal is the full chosen width (16 == 16), so
        # no sign-extension block should be emitted for it.
        assert "sign" not in source.lower()


class TestExtendedAddressing:
    """29-bit identifiers must be marked extended in the DBC.

    DBC has no addressing field: bit 31 of the id in the BO_ record carries
    it. Without that, a reader sees 0x1801A1F0 as a standard frame and
    rejects it for exceeding 11 bits. Every other record that references the
    message by id - CM_, BA_, VAL_ - has to use the same encoded value or it
    will not bind to the message.

    This is the addressing mode Xbattery's own BMS uses, and it was broken:
    the golden test used an 11-bit LuxPower id, so it never showed.
    """

    def _spec(self):
        from xforge.comms import CommsSpec

        return CommsSpec.from_dict(
            {
                "can_buses": [
                    {
                        "name": "pack",
                        "bitrate": 500000,
                        "addressing": "extended",
                        "messages": [
                            {
                                "name": "PackStatus",
                                "id": 0x1801A1F0,
                                "dlc": 8,
                                "sender": "BMS",
                                "cycle_time_ms": 100,
                                "comment": "Pack telemetry",
                                "signals": [
                                    {
                                        "name": "PackVoltage",
                                        "start_bit": 0,
                                        "length": 16,
                                        "scale": 0.01,
                                        "unit": "V",
                                    },
                                    {
                                        "name": "FaultFlag",
                                        "start_bit": 16,
                                        "length": 1,
                                        "values": {0: "NoFault", 1: "Fault"},
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        )

    def test_frame_id_carries_the_extended_flag(self):
        from xforge.comms.dbc import dbc_frame_id

        assert dbc_frame_id(0x1801A1F0, "extended") == 0x1801A1F0 | 0x80000000
        assert dbc_frame_id(0x356, "standard") == 0x356

    def test_cantools_reads_it_back_as_extended(self):
        cantools = pytest.importorskip("cantools")
        from xforge.comms import generate_dbc

        db = cantools.database.load_string(
            generate_dbc(self._spec().can_buses[0]), database_format="dbc"
        )
        msg = db.get_message_by_name("PackStatus")
        assert msg.is_extended_frame
        assert msg.frame_id == 0x1801A1F0

    def test_every_record_binds_to_the_message(self):
        """CM_, BA_ and VAL_ must use the encoded id, not the raw one."""
        cantools = pytest.importorskip("cantools")
        from xforge.comms import generate_dbc

        db = cantools.database.load_string(
            generate_dbc(self._spec().can_buses[0]), database_format="dbc"
        )
        msg = db.get_message_by_name("PackStatus")
        assert msg.comment == "Pack telemetry"          # CM_ bound
        assert msg.cycle_time == 100                     # BA_ bound
        choices = msg.get_signal_by_name("FaultFlag").choices
        assert dict(choices) == {0: "NoFault", 1: "Fault"}  # VAL_ bound

    def test_named_value_round_trips(self):
        cantools = pytest.importorskip("cantools")
        from xforge.comms import generate_dbc

        db = cantools.database.load_string(
            generate_dbc(self._spec().can_buses[0]), database_format="dbc"
        )
        raw = db.encode_message(
            "PackStatus", {"PackVoltage": 51.2, "FaultFlag": "Fault"}
        )
        out = db.decode_message("PackStatus", raw)
        assert out["PackVoltage"] == pytest.approx(51.2)
        assert str(out["FaultFlag"]) == "Fault"
