# xforge comms

One YAML file declares a CAN bus or a Modbus register map. `xforge.comms`
turns it into a `.dbc`, a firmware header/source pair, and a register-map
CSV/Markdown - so the same CAN ID never has to be typed into four places by
hand and drift the fourth time someone changes it.

```python
from xforge.comms import CommsSpec, build

spec = CommsSpec.load("comms.yaml")   # raises SpecError on anything that
                                        # doesn't fit - see below
build(spec, out_dir="out/comms")       # writes <bus>.dbc/.h/.c, <map>.csv/.md
```

Or reach for the pieces directly: `generate_dbc(bus)`, `generate_header(bus)`,
`generate_source(bus, header_name)`, `generate_csv(map_)`,
`generate_markdown(map_)` all take the dataclasses from `xforge.comms.spec`
and return text.

## Install

The spec loader and every generator are dependency-free (PyYAML is already a
base xforge dependency). Parsing a DBC back - which only the round-trip test
and anyone consuming the output downstream need to do - needs `cantools`:

```bash
.venv/Scripts/python -m pip install -e ".[comms]"
```

## Spec format

```yaml
can_buses:
  - name: battery_can
    bitrate: 500000
    addressing: standard      # "standard" (11-bit) or "extended" (29-bit)
    fd: false
    messages:
      - name: BatteryLimits_0x351
        id: 0x351              # decimal or hex string, either is fine
        dlc: 8
        sender: BMS
        cycle_time_ms: 1000    # optional; becomes GenMsgCycleTime in the DBC
        byte_order: little      # default for signals in this message
        comment: "Charge/discharge limits, as read by the inverter"
        signals:
          - name: Charge_voltage_recommand
            start_bit: 0
            length: 16
            scale: 0.1
            offset: 0
            minimum: 0          # optional; defaults from the raw bit width
            maximum: 1000       # if you leave both minimum and maximum out
            unit: V
            comment: "Charge voltage recommand (0.1 V)"
          - name: Pack_current
            start_bit: 16
            length: 16
            is_signed: true
            scale: 0.1
            unit: A
          - name: Fault_flag
            start_bit: 32
            length: 1
            values: {0: NoFault, 1: Fault}   # becomes a DBC VAL_ table and
                                               # a #define pair in the header

modbus_maps:
  - name: inverter_registers
    registers:
      - address: 0x9C40
        name: battery_soc
        type: holding           # holding | input | coil | discrete
        data_type: u16          # u16 | i16 | u32 | i32 | f32
        scale: 1
        offset: 0
        unit: "%"
        access: r               # r | rw
        description: "State of charge"
```

Everything under `signals:` and `registers:` accepts the field names above;
anything left out takes the default shown in `xforge/comms/spec.py`.

### Bit numbering: this deliberately follows the DBC convention, not a friendlier one

`start_bit` means exactly what it means in a `.dbc` file, because the whole
point of this generator is to reproduce the shape of the real reverse-engineered
inverter DBCs (LuxPower, Deye, Pylon - all on the Desktop) rather than invent a
cleaner numbering that would then need translating on the way out:

- **`byte_order: little`** (DBC `@1`, Intel): `start_bit` is the signal's
  least significant bit, numbered flat across the frame - byte 0 bit 0 is 0,
  byte 1 bit 0 is 8, and so on up to `8*dlc - 1`. This is what all three real
  files use for every signal without exception.
- **`byte_order: big`** (DBC `@0`, Motorola): `start_bit` is the physical bit
  position of the signal's *most* significant bit (same 0-at-byte0-LSB
  numbering as above). Walking toward the LSB moves down by one bit normally;
  on reaching a byte's own LSB, the next bit is the *next* byte's MSB, 15 bits
  higher. `CanSignal.bit_mapping()` is the one place that walk happens, and it
  is checked directly against cantools' own encode/decode in
  `tests/test_comms.py` rather than trusted from the DBC spec text - several
  independent tools and write-ups describe Motorola numbering differently,
  and cantools is the practical ground truth here since it's what anything
  downstream will use to read the file.

### What changed once real DBCs were in hand

- All three reverse-engineered files (LuxPower, Deye, Pylon) use Intel/little-
  endian for every signal, including ones that visually look like bitfields
  (`Protection1_...`, `Alarm2_...`). There is no real Motorola example on this
  machine to check against, so that path is exercised only by a hand-built
  test and cross-checked against cantools directly (see `TestBitMapping` and
  `TestDbcRoundTrip.test_encode_decode_agrees_with_a_pure_python_reference`
  in `tests/test_comms.py`) - treat it as less battle-tested than the little-
  endian path.
- Signals do not have to cover every bit of a message (`ProtDischargeOverCurrent`
  in pylon.dbc sits at bit 7 with bit 0 unused) and multiple signals routinely
  share one byte at sub-byte offsets (`BatteryBrand_ByteN` in the Deye file is
  eight 2-bit fields, one per byte, at bit offset 3). Neither is an error - the
  validator only rejects a genuine bit collision, not a gap or a tight pack.
- Every real file uses `Vector__XXX` as the receiver on every signal rather
  than naming one - none of them models bus topology, only the payload. This
  generator does the same: `CanBus`/`CanMessage` declare a sender per message
  (needed for `BU_:` and to know who owns the frame) but no receiver list,
  since nothing here needed one.
- Cycle time is carried two different ways in the wild: LuxPower and Deye put
  it in a free-text `CM_` comment only; Pylon's file uses the actual
  `GenMsgCycleTime` DBC attribute, which cantools reads straight into
  `Message.cycle_time`. This generator uses the attribute (Pylon's approach)
  whenever `cycle_time_ms` is set, since it round-trips through a real parser
  instead of living only in a comment a human has to read.
- Modbus collision checking treats coils, discrete inputs, input registers and
  holding registers as four separate address spaces, because that is what
  Modbus actually is - address 0 as a coil and address 0 as a holding register
  are two different things, not a conflict.

## Firmware output

`generate_header`/`generate_source` emit one struct and one pack/unpack
function pair per message. The struct holds the **raw** (pre-scale) integer a
signal carries on the wire, in the narrowest `stdint.h` type that fits (a
17-63 bit signal is not possible - DBC signals are 1-64 bits, and this picks
8/16/32/64 as needed). Scale, offset and unit are documented in a comment next
to the field rather than turned into a float in the struct, since firmware on
a CAN transceiver doesn't get to assume there's an FPU nearby.

```c
#define BATTERYLIMITS_0X351_ID 0x351u
#define BATTERYLIMITS_0X351_DLC 8u

typedef struct {
    uint16_t Charge_voltage_recommand;  /* bits 0..15 (little-endian); physical = raw * 0.1 + 0 V */
    int16_t Pack_current;               /* bits 16..31 (little-endian); physical = raw * 0.1 + 0 A */
} BatteryLimits_0x351_t;

void batterylimits_0x351_pack(uint8_t data[8], const BatteryLimits_0x351_t *msg);
void batterylimits_0x351_unpack(BatteryLimits_0x351_t *msg, const uint8_t data[8]);
```

`pack()`/`unpack()` are generated one line per bit, straight off the same
`bit_mapping()` the spec's own overlap validator uses - more verbose than a
hand-rolled shift-and-mask, but every line is independently checkable against
the DBC bit position it came from. **This code is not compiled as part of the
test suite** (no C toolchain on the machine this was built on) - it is C99,
consistently formatted, and its bit arithmetic is exercised indirectly by
cross-checking the same `bit_mapping()` against cantools, but nobody has fed
it through a real compiler. Compile it before trusting it on a target.

## What the CLI wiring should look like

This package intentionally does not touch `src/xforge/cli.py` - that file
is being edited concurrently. The subcommand it should grow:

```python
from xforge.comms import CommsSpec, build

def _cmd_comms(args) -> int:
    spec = CommsSpec.load(args.spec)          # raises SpecError -> caller
                                                # should catch and print it,
                                                # then return EXIT_ERROR
    written = build(spec, args.out)
    for path in written:
        print(path)
    return EXIT_OK

# subparser:
#   xforge comms comms.yaml --out out/comms
p_comms = subparsers.add_parser("comms", help="generate DBC/Modbus/firmware from a comms spec")
p_comms.add_argument("spec", type=Path)
p_comms.add_argument("--out", type=Path, default=Path("out/comms"))
p_comms.set_defaults(func=_cmd_comms)
```

`SpecError` (from `xforge.comms`) is a `ValueError` subclass and always names
the offending signal, message or register - printing `str(exc)` is enough for
the error path.

## Tests

```bash
.venv/Scripts/python -m pytest tests/test_comms.py -q
```

The DBC round-trip and LuxPower golden tests need `cantools`
(`pip install -e ".[comms]"`); they skip cleanly if it isn't installed rather
than failing the whole suite.
