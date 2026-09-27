# Standards provenance

The rule engine is only as trustworthy as the numbers in it. This page records
where every constant comes from and what we are still missing. **A rule may not
gate a build on a number we cannot cite to a clause.**

## Tiers of evidence

| Tier | Meaning | May a rule gate on it? |
|---|---|---|
| **A — primary** | Read from the purchased standard; cited to table, row, column | Yes |
| **B — public formula** | Published closed form, reproduced identically across independent sources | Yes, with the conservatism noted |
| **C — secondary** | Consultancy blog, app note, calculator tool | **No.** Advisory only |
| **D — convention** | Industry practice with no standard behind it | **No.** Advisory only |

## What we have

### Tier B — safe to implement now

**IPC-2221 conductor sizing.** `I = k · ΔT^0.44 · A^0.725`, with `A` in mil²,
`ΔT` in °C, `k = 0.048` external and `k = 0.024` internal. Inverted for
checking: `A_required = (I / (k · ΔT^0.44))^(1/0.725)`.

An empirical curve fit, reproduced identically across every source checked.
Note it is **conservative** relative to IPC-2152: the 2:1 internal/external
penalty is pessimistic for real multilayer boards with adjacent pours, so
IPC-2221 asks for wider traces than IPC-2152 would. Being conservative on
ampacity is the safe direction, and we say so in the finding text.

### Tier C — advisory only until purchased

**Creepage and clearance (IEC 60664-1, IEC 62368-1).** Independent secondary
sources disagree by up to about 25% at the same nominal operating point. One
example: at 800 V DC, pollution degree 2, material group IIIa, one source gives
6.3 mm creepage and another 8.0 mm.

The *methodology* is consistent everywhere and is what the engine implements —
the required distance is a function of working voltage, insulation class
(functional / basic / supplementary / double / reinforced), pollution degree,
material group (CTI), overvoltage category, and altitude. Only the table values
are in doubt.

**Action: buy IEC 60664-1:2020+AMD1** (~CHF 345). It is the insulation
coordination standard and the one that matters most. Extract Tables F.2 and F.4
verbatim into `src/xforge/data/clearance.py`, with the table, row and column
cited in a comment beside each constant. Until then `XF003` and anything
downstream of it stays advisory.

**Altitude correction.** The 1.48× factor at 5000 m referenced to ≤2000 m is
corroborated by three independent sources. One source gives a linear
approximation instead; that contradicts the discrete-table approach and looks
like a simplification. Use the discrete table once we have it. Hyderabad is
~500 m, so this is not material for the domestic product.

**Conformal coating.** A "coated: yes" flag must **never** reduce the assumed
pollution degree. Only a specific qualified coating system, tested per
IEC 60664-3 / IPC-CC-830, may justify PD2 → PD1, and the certificate reference
has to be recorded in the design. The engine must require the reference, not
the boolean.

### Tier C — data acquisition, not a formula

**IPC-2152.** Chart-based; the standard publishes no closed form. Any
"IPC-2152 formula" found online is a third-party curve fit. Implementing it
properly means purchasing the standard and digitising the figures plus the
correction factors for copper weight, layer position, board thickness and
adjacent planes. It also references **local board temperature**, not lab
ambient — for a sealed IP-rated enclosure that is meaningfully hotter, and the
engine must let that be a parameter rather than assuming 25 °C.

Deferred. IPC-2221 ships first with its conservatism documented.

### Tier D — convention, advisory forever unless a standard is found

- Busbar current density, commonly 1.5–2.0 A/mm² for naturally convected
  copper. No IPC number behind it.
- Via ampacity: barrel modelled as a flat conductor of cross-section
  `π × drill_diameter × plating_thickness`; a via landing on a plane credited
  with ~1.2× an isolated one. Single-source rule of thumb.
- Kelvin sensing, cell-tap RC and fusing, contactor flyback, precharge sizing,
  reverse-polarity topology. All established practice, none of it a numbered
  clause. These make good **structural** rules — "is the element present" — and
  bad **numeric** ones.

## Rule-to-evidence map

| Rule | Tier | Gating allowed |
|---|---|---|
| XF001 signal split across sheets | D (but purely structural, verifiable from the netlist itself) | Yes |
| XF002 dangling net | D, structural | Not yet — needs `expected_dangling` tuned per project |
| XF003 barrier straddle | C | No, until IEC 60664-1 is in hand |
| XF004 placeholder footprint | D, structural | No, it is informational |
| XF005 orphaned sheet | D, structural | Yes |

Structural rules are the exception to the citation requirement: XF001 and
XF005 do not assert a physical threshold, they assert that the netlist
disagrees with what the drawing implies. That is checkable from the file
alone, which is why they are the first gating candidates.
