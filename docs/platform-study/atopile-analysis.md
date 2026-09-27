# Xbattery EDA Platform — atopile Analysis, Gap Study and Build Plan

| | |
|---|---|
| **Prepared for** | Xbattery, Hyderabad — BharatBMS · XB-5K |
| **Subject** | Reverse-engineering atopile 0.15.9, feature-gap analysis, and the design of a superior in-house schematic and PCB automation platform |
| **Date** | 27 September 2026 |
| **Author** | Done by Harsh Thakur |

---

## Contents

1. [Executive summary](#1-executive-summary)
2. [Method and evidence base](#2-method-and-evidence-base)
3. [atopile system analysis](#3-atopile-system-analysis)
4. [Verified defects and limitations](#4-verified-defects-and-limitations)
5. [Community and user research](#5-community-and-user-research)
6. [Competitive landscape](#6-competitive-landscape)
7. [Consolidated gap matrix](#7-consolidated-gap-matrix)
8. [Fit assessment for Xbattery](#8-fit-assessment-for-xbattery)
9. [Novel feature design](#9-novel-feature-design)
10. [Platform architecture](#10-platform-architecture)
11. [Phased implementation roadmap](#11-phased-implementation-roadmap)
12. [Risks and mitigations](#12-risks-and-mitigations)
13. [Xbattery design-system integration](#13-xbattery-design-system-integration)
14. [Appendices](#14-appendices)

---

## 1. Executive summary

### 1.1 The one-paragraph version

atopile is a genuinely good idea executed to about 60% of what Xbattery needs, and as of August 2026 its owners moved the product to a closed, browser-hosted, cloud-only environment and soft-deprecated the locally installable version that is on this machine. The open-source core that remains — an MIT-licensed constraint compiler, a typed circuit graph, a symbolic solver and a complete typed KiCad file engine written in Zig — is excellent, and represents roughly 134,000 lines of engineering that Xbattery should not rewrite. Everything Xbattery actually needs on top of it — the high-voltage, high-current, isolation, functional-safety, multi-source supply-chain and firmware co-generation layer — does not exist in atopile, and does not exist in any competitor either. **The recommendation is to fork the 0.15.9 core, freeze it, and build the battery-systems layer on top as an internal platform.** That is a three-engineer, twelve-month programme with useful output in week six.

### 1.2 The five findings that drive the recommendation

| # | Finding | Evidence | Consequence for Xbattery |
|---|---|---|---|
| 1 | **atopile has abandoned the local toolchain.** 0.16 is browser-only; the 0.15 line is "soft-deprecated" with a removal date to be announced; the parts-picker service for older versions was switched off before a migration path existed. | atopile's own post, 6 Aug 2026, quoted verbatim in §3.9 | You cannot build a production flow on the shipping product. Either fork it, or accept that your design database lives on someone else's server. |
| 2 | **Isolated grounds are silently shorted together.** The `has_single_electric_reference` trait walks the entire subtree and unifies every signal's power reference, including across a galvanic barrier. Its `exclude` escape hatch is accepted and then ignored. | Source read of `faebryk/library/has_single_electric_reference.py`; the behaviour is *asserted as correct* by the library's own unit test; open issue #1812 | The single most dangerous defect for a BMS company. An isolated CAN or isolated HV-sense domain gets netlisted with its ground tied to primary ground, with no warning, and fabricated that way. |
| 3 | **There is no concept of current, isolation, creepage, clearance, temperature or copper weight in the electrical model.** `max_current` exists as a parameter but feeds only a report. No netclasses and no design rules are ever written into the board. | Grep across the whole installed tree; inspection of the `.kicad_pcb` and `.kicad_pro` produced by a real build | Every rule that matters for a 51.2 V / 110 V / 800 V product lives outside the tool. The "single source of truth" claim breaks exactly where Xbattery needs it. |
| 4 | **Parts sourcing is single-supplier and cloud-locked.** The only supplier enum value is LCSC. Parametric selection covers only resistors, capacitors and inductors. Picking requires sign-in to atopile's servers. | `Pickable.py`, `picker_lib.py`, `picker/api/api.py`; five separate service-outage issues in seven months | Unusable for Indian production sourcing, approved-vendor discipline, second-source policy, or anything with an EOL horizon. |
| 5 | **The community's loudest and oldest complaint is the missing schematic — and the file plumbing to fix it already ships.** The Zig core contains a complete typed KiCad *schematic* model with a writer, but nothing generates one. | `faebryk/core/zig/gen/sexp/schematic.pyi`; two years of Hacker News threads | Schematic generation is an algorithm problem, not a file-format problem. It is tractable, and it is the single biggest adoption unlock for working EEs. |

### 1.3 Recommendation

**Fork, freeze, and build upward.** Concretely:

1. **Fork** atopile 0.15.9 and faebryk at the MIT-licensed core. Pin it. Put the cloud couplings — picker API, telemetry, auth, DeepPCB — behind interfaces so they can be swapped or switched off.
2. **Replace the supply-chain layer** with an Xbattery parts service: multi-source approved-vendor lists, lifecycle status, India landed cost, and an offline cache that makes builds reproducible with no network.
3. **Add the physics the tool is missing** — ampacity, isolation, creepage and clearance, thermal derating — as first-class parameters that project into KiCad netclasses and custom DRC rules.
4. **Add the layer above the PCB** — pack topology, cell taps, harness, busbars — which is where a battery company actually lives, and which no tool in the market covers.
5. **Co-generate firmware artefacts** — DBC, Modbus maps, pin-mux headers, AFE register images — from the same source of truth as the hardware. This is the highest-leverage idea in this document, and it is only available to a company that builds both the board and the firmware that runs on it.
6. **Generate the schematic**, for human review and for certification evidence.

### 1.4 What not to build

Do not rebuild the constraint solver, the graph core, the KiCad S-expression engine, the language server, or the LLM agent runtime. All five exist, work, and are MIT-licensed. Do not build an autorouter. Do not build a browser IDE.

---

## 2. Method and evidence base

This study is deliberately grounded in first-hand inspection rather than marketing material, because atopile's public documentation site was decommissioned during 2026 and its public repository is, by the vendor's own admission, stale.

### 2.1 What was examined directly

| Source | Detail |
|---|---|
| **Installed atopile 0.15.9** | `%APPDATA%\uv\tools\atopile\Lib\site-packages\{atopile,faebryk}` — 428 Python files, 133,637 non-comment lines, read directly |
| **The ANTLR grammar** | `AtoLexer.g4` and `AtoParser.g4` — the definitive statement of what the language can and cannot express |
| **The Zig core** | `faebryk/core/zig/` build files, README, and generated `.pyi` stubs for the KiCad pcb / footprint / netlist / symbol / **schematic** / fp_lib_table models |
| **A real build's artefacts** | `C:\Users\TempAdmin\atopile-demo\my_first_ato_project` — BOM, variables report, power tree, generated `.kicad_pcb` and `.kicad_pro`, gerbers, pick-and-place |
| **Package metadata** | `atopile-0.15.9.dist-info/METADATA`; PyPI release history fetched and parsed directly (171 releases) |
| **Vendor primary source** | atopile's 0.16 announcement, rendered headlessly and read verbatim |

### 2.2 What was researched externally

Public GitHub REST API (issues, discussions, branches, commits), Hacker News via the Algolia API, Hackaday, the Altium OnTrack podcast, the Y Combinator listing, the VS Code marketplace, PyPI, and competitor sites. Reddit and X/Twitter were attempted repeatedly and returned hard 403 blocks; those two sources are therefore absent from the evidence rather than negative.

### 2.3 Reasoning approach

Each section states the observation, then the evidence, then the consequence. Claims that could not be verified are marked as such. Where external research conflicted with the installed source, **the source wins**, and the discrepancy is noted.

---

## 3. atopile system analysis

### 3.1 What atopile is

atopile is a compiler. You write `.ato` files — a declarative, constraint-based domain-specific language describing modules, typed interfaces and physical constraints. The compiler parses them into a typed graph, runs a symbolic solver over the physical parameters, selects real purchasable parts that satisfy those parameters, and writes a KiCad PCB file plus a set of manufacturing and documentation artefacts. Layout remains a human activity in KiCad, optionally assisted by a cloud AI placement and routing service.

The pitch, from the project's README: *"The compiler solves constraints, picks parts, runs checks, and updates your KiCad layout."*

### 3.2 Product topology

Eight distinct pieces ship or are reachable from the 0.15.9 wheel:

| Component | Where it lives | What it does |
|---|---|---|
| **`ato` CLI** | `atopile/cli/` | `build`, `create`, `add`/`remove`/`sync`, `package publish/verify`, `auth`, `inspect`, `serve core`, `lsp`, `kicad-ipc`, `dev` |
| **Compiler** | `atopile/compiler/` | ANTLR4 lexer/parser → faebryk graph AST → type graph → linker → deferred executor |
| **faebryk core** | `faebryk/core/` | The graph, the node/trait system, and the symbolic solver |
| **Zig extension** | `pyzig`, `pyzig_sexp` | High-throughput S-expression engine and typed KiCad file models |
| **Language server** | `atopile/lsp/` (176 KB) | Completion, hover, go-to-definition, references, rename, diagnostics, formatting — with a fork-server architecture for fast restarts |
| **Core server** | `atopile/server/` | A websocket RPC server with 68 actions, driving the VS Code panels and the web app |
| **Layout server** | `atopile/layout_server/` | A standalone WebGL2 PCB viewer/editor speaking the same layout RPC |
| **Agent runtime** | `atopile/agent/` | A full LLM agent with Anthropic and OpenAI providers, 25+ tools, and five skill files |

The third-party surface: a hosted **components API** (`legacy.atopileapi.com`), a hosted **packages registry** (`packages.atopileapi.com`), a **telemetry** endpoint, **Clerk** OAuth for sign-in, and **DeepPCB** for cloud AI placement and routing.

### 3.3 Codebase map

Measured on the installed wheel. Non-comment, non-blank Python lines. The Zig core, the TypeScript frontends and the backend services are not in the wheel and are not counted.

| Area | Files | SLOC | Share |
|---|---:|---:|---:|
| `faebryk/libs` — pickers, KiCad I/O, EDA converters, JLC data, project deps | 91 | 31,519 | 23.6% |
| `faebryk/library` — the standard library of nodes, interfaces and traits | 106 | 23,961 | 17.9% |
| `faebryk/core` — graph, node/trait system, symbolic solver | 23 | 14,447 | 10.8% |
| `atopile/compiler` — parser, AST, type graph, linker (incl. ~4.3k generated) | 17 | 11,364 | 8.5% |
| `atopile/model` — projects, builds, packages, parts, cost, manufacturing, SQLite | 23 | 7,730 | 5.8% |
| `atopile/*` — build steps, config, data models, errors, logging | 18 | 7,694 | 5.8% |
| `atopile/server` — websocket RPC, layout manager, diff engine | 21 | 7,510 | 5.6% |
| `faebryk/libs` tests | 25 | 6,232 | 4.7% |
| `faebryk/exporters` — BOM, docs, KiCad transformer, pinout | 14 | 5,390 | 4.0% |
| `atopile/lsp` | 8 | 5,068 | 3.8% |
| `atopile/agent` | 23 | 3,651 | 2.7% |
| `atopile/cli` | 14 | 3,363 | 2.5% |
| `atopile/autolayout` — DeepPCB client and job lifecycle | 15 | 2,996 | 2.2% |
| everything else (telemetry, auth, kicad plugin, templates) | 30 | 2,712 | 2.0% |
| **Total** | **428** | **133,637** | |

Two single files dominate their areas and are worth knowing about: `faebryk/library/Literals.py` (336 KB) and `faebryk/library/Units.py` (126 KB) are largely generated unit and literal machinery; `core/solver/symbolic/invariants.py` (122 KB) and `core/solver/mutator.py` (119 KB) are the solver's heart.

**Consequence.** A from-scratch rebuild is a multi-year programme. A fork plus a domain layer is a one-year programme. This single table settles the build-versus-fork question.

### 3.4 The compile pipeline

The build is a dependency-ordered graph of 30 registered steps. The first 16 are the compile proper; the rest are artefact generators.

| Order | Step | Purpose |
|---|---|---|
| 1 | `resolve-dependencies` | Fetch and pin registry/git/file dependencies |
| 2 | `init-build-context` | Load `ato.yaml`, resolve the build target |
| 3 | `modify-typegraph` | Apply type-level transforms |
| 4 | `instantiate-app` | Instantiate the root module into a design graph |
| 5 | `prepare-build` | Set up output paths and caches |
| 6 | `post-instantiation-graph-check` | Verify the instance graph |
| 7 | `post-instantiation-setup` | Structural mutations, e.g. reference unification |
| 8 | `post-instantiation-design-check` | Electrical checks (ERC) |
| 9 | `load-pcb` | Read the existing board, import previously picked parts |
| 10 | `picker` | Solve parameters and select real parts |
| 11 | `prepare-nets` | Name and materialise nets |
| 12 | `post-solve-checks` | Checks that need solved values |
| 13 | `update-pcb` | Write footprints and nets into the board, preserving placement |
| 14 | `post-pcb-checks` | Board-level checks |
| 15 | `build-design` | Virtual barrier: the design is now complete |
| 16+ | artefacts | `bom`, `step`, `glb`, `3d-image`, `2d-image`, `mfg-data`, `manifest`, `variable-report`, `pinout`, `power-tree`, `stackup`, `datasheets`, `data-interface-layout`, `collect-manufacturing` |

Two aggregate targets exist: `default` (BOM, manifest, variable report, pinout, stackup, power tree, datasheets) and `all` (everything, including 3D and manufacturing data).

**Observation worth noting.** There are exactly five check stages, and only about ten checks are registered across the entire standard library. The checking framework is well-built and almost empty. That is good news: it is the right place to add Xbattery's rules.

### 3.5 The data model

Everything is a node in a typed graph. Three kinds of edge matter: composition (parent–child), connection (same net), and traits (behavioural metadata attached to a type or an instance).

- **`module`** — a design unit containing children and connections.
- **`interface`** — a connectable boundary, wired with `~`.
- **`component`** — a physical part with a footprint.
- **Traits** — `can_bridge`, `has_designator_prefix`, `is_pickable_by_type`, `has_package_requirements`, `implements_design_check` and about sixty others. Traits are how behaviour is attached without inheritance.

Parameters carry **units and tolerance**, and are solved rather than evaluated. `resistance = 10kohm +/- 5%` is a constraint on a set, not an assignment of a number.

### 3.6 The solver

`faebryk/core/solver/` is a **symbolic interval-rewriting engine**, not an SMT solver and not a numerical optimiser. It repeatedly applies algebraic rewrites — idempotent unpacking, involutory folding, associative folding, transitive subset propagation, upper and lower estimation of expressions, isolation of a variable on one side — until parameters converge to intervals or a contradiction is found.

Practical limits, read from `core/solver/utils.py`:

- A default timeout of **150 seconds** (`ATO_STIMEOUT`).
- A **maximum-iterations heuristic**, meaning solving is best-effort and can terminate incomplete.
- No objective function. You cannot ask it to *minimise* cost, area or part count — only to *satisfy*.

**Consequence.** The solver is the right tool for "pick a part that satisfies these bounds" and the wrong tool for "choose the cheapest valid BOM". Xbattery's optimisation needs — cheapest compliant BOM, smallest board, best second-source coverage — need a separate layer, which §9 proposes.

### 3.7 The language, from the grammar

Read directly from `AtoParser.g4`. This is what `.ato` can and cannot say.

**Statements available:** `import`, assignment, `~` connect, `~>` bridge, `->` retype, `pin`, `signal`, `assert`, `trait`, declaration (`name: unit`), docstring, `pass`, `for`, and block definitions with single inheritance via `from`.

**Comparison operators in `assert`:** `<`, `>`, `<=`, `>=`, `within`, `is`. There is no `!=`.

**Literal forms:** exact (`3.3V`), bilateral (`10kohm +/- 5%`), bounded (`3.0V to 3.6V`). Numbers support decimal, scientific, hex, binary and underscore separators.

**What the grammar forbids** — each of these is a real constraint on how far you can push the language:

| Missing | Grammar evidence | Why it matters to Xbattery |
|---|---|---|
| Conditionals | No `if` production | Cannot express "if cell count > 16, add a second AFE" |
| Functions or macros | No callable production | Every repeated pattern must become a module, even trivial arithmetic |
| Units in template arguments | `template_arg : name ASSIGN literal`, and `literal` is only string/boolean/number | Cannot write `new Pack<nominal_voltage=51.2V>`; templating is limited to bare numbers |
| Generics over types | `type_reference : name` only | Cannot write a `CellString<T>` parameterised by cell type |
| Import aliasing | No `as` in `import_stmt` | Name collisions across vendor packages must be resolved by renaming |
| User-defined enums | Enums come only from the Python library | Chemistry, ASIL level, insulation class cannot be declared in `.ato` |
| String interpolation or concatenation | `assignable` has no string operators | Cannot build designators, labels or net names programmatically |
| Visibility or export control | None | No way to mark a module's internals private in a shared library |
| Comprehensions, `while`, recursion | Absent | Iteration is limited to `for x in array` |

**A note on pragmas.** The five experiment pragmas — `BRIDGE_CONNECT`, `FOR_LOOP`, `TRAITS`, `MODULE_TEMPLATING`, `INSTANCE_TRAITS` — are all listed in `_RetiredExperiment` in 0.15.9, meaning they have been merged into the language and are no longer required. They are still accepted so existing files do not break. Both the shipped agent skill file and the public documentation still instruct users to write them. Harmless, but it shows how far the documentation has drifted from the code.

### 3.8 Parts selection and the supply chain

This is the weakest subsystem relative to Xbattery's needs, and the analysis is worth spelling out.

There are three ways a part can be chosen:

1. **`is_pickable_by_supplier_id`** — you give an LCSC part number. The `Supplier` enum has exactly one member: `LCSC`.
2. **`is_pickable_by_part_number`** — you give manufacturer plus MPN, and the hosted service resolves it.
3. **`is_pickable_by_type`** — parametric selection. The `Endpoint` enum has exactly three members: `RESISTORS`, `CAPACITORS`, `INDUCTORS`.

Everything else — every diode, MOSFET, LED, regulator, connector, AFE, transceiver — must be pinned by part number or vendored as a local package. A generic `LED` with no part number is symbolic: it is silently dropped from the BOM and the layout while the build still reports success.

Package size constraints go through `has_package_requirements`, whose `size` is an `SMDSize` enum. The `.package = "0402"` sugar maps `R`/`C`/`L` prefixes to imperial codes. This works for passives. It has no equivalent for anything else.

The BOM exporter warns and drops any part without an LCSC number: `logger.warning("Non-LCSC parts not supported in JLCPCB BOM")`.

Cost estimation is a hardcoded JLCPCB price model — setup fees, stencil fees, cost per solder joint, extended-part loading fees, board-size surcharges — denominated in US dollars.

**What is absent entirely:** second sources, alternates, approved-vendor lists, lifecycle or EOL status, RoHS/REACH declarations, moisture-sensitivity level, AEC-Q qualification, temperature grade, counterfeit-risk scoring, distributor lead time, minimum order quantity, or any currency other than USD.

### 3.9 Project health and strategic position

This section is the one that changes the decision, so it is evidenced heavily.

**Release timeline, parsed directly from PyPI (171 releases):**

| Version | Released |
|---|---|
| 0.15.9 | 2026-09-12 |
| 0.15.8 | 2026-08-07 |
| 0.15.7 | 2026-04-23 |
| 0.15.0 | 2026-04-04 |
| 0.14.0 | 2026-01-31 |

**Repository signals:**

- 3,949 stars, 239 forks, MIT licence, created December 2023.
- Last public push: **13 June 2026**. Two releases — 0.15.8 and 0.15.9 — shipped *after* that date.
- Last tagged GitHub Release: **v0.14.1004, 12 February 2026**.
- No `CONTRIBUTING.md`, no `ROADMAP.md`, no `CHANGELOG.md`.
- 17 genuinely open issues (the "24" in the API is 17 issues plus 7 pull requests).
- The documentation repository `atopile/docs` was **archived on 29 April 2026**. The package-registry backend repository was **archived on 10 March 2026**.
- `docs.atopile.io` is now a four-link landing page whose headline reads: *"The docs live in the editor now."*

**The vendor's own statement.** From atopile's post of 6 August 2026, quoted verbatim:

> "atopile 0.16 now runs the full IDE in your browser: app.atopile.io."

> "We are soft-deprecating the `0.15` line. Version `0.15.8` exists to keep an active project moving while you finish or plan a migration; it is not a second product line that we will maintain indefinitely. We will announce a removal date in the future."

> "The components service used by older releases was retired before a clear migration path was in place. This left some valid projects unable to pick parts; that was our mistake."

> "The compiler and graph core will remain open source... There are also closed source parts of atopile. In the past, this was primarily the backend for the parts picker, but recently we've built significantly more tooling, including the browser-based IDE and our improved agent harnesses."

> "We recently merged our open-source and closed-source code into a single repository to improve development velocity. As a result, the public repository has become stale, despite us working full-time on the project."

> "Our path to financial stability is focusing on enterprise usage and larger teams. We offer atopile with bespoke integrations, on-premise deployment, and the necessary certifications."

The same post lists what was dropped: PyPI, the VS Code and Open VSX marketplaces, Homebrew/AUR/Nix, **on-premise deployments for enterprise**, source builds and the web playground — collapsed into a single hosted environment described as *"Linux on x86-64, with glibc, AVX-512, powerful multicore machines, a single KiCad version, and 100 Gbit/s connectivity to our backend."*

**Consequences for Xbattery.**

1. The Windows-native path this machine uses is not merely unsupported — the vendor has explicitly consolidated onto Linux x86-64 with AVX-512. The wheel crash that had to be worked around on this PC (`0xC000001D`, issue #1838) is a direct symptom, and it is still open.
2. The 0.15 line, including 0.15.9, will stop working for part picking at an unannounced future date, because picking depends on their hosted service.
3. The public repository cannot be relied on as the upstream for a fork going forward; the last usable public state is what is installed here.
4. There is nonetheless a legitimate commercial route: atopile explicitly sells on-premise deployment with certifications to enterprises. That conversation is worth having in parallel with the fork, and §12 treats it as a live option rather than a fallback.

### 3.10 Telemetry and confidentiality

Telemetry is **on by default** (disabled only when `CI` is set). It reports to `telemetry.atopileapi.com` and the properties collected include the **git user email**, the normalised **git remote URL**, the current **git commit hash**, the project name and a derived project id, the CI provider, the GitHub repository owner and name, the platform, and the installation method.

For a company whose designs are its core IP, that set is not acceptable by default. It is easy to switch off — set `ATO_TELEMETRY=n`, or write `telemetry: false` into `~/.config/atopile/telemetry.yaml` — but it should be switched off deliberately and verified, and it is one more argument for a fork in which the default is inverted.

### 3.11 What atopile does genuinely well

It is important not to lose this in a gap analysis. The following are strong, and should be preserved in any fork:

- **The typed-interface model.** `I2C ~ sensor.i2c` connecting a whole bus in one statement, with type checking, is the feature users praise most. It removes an entire category of pin-level wiring error.
- **Parameters as constrained sets with units.** Tolerance-aware arithmetic and a solver that propagates intervals is real engineering, not a veneer.
- **The Zig S-expression engine.** Fast, typed, round-trip-faithful KiCad file handling — pcb, footprint, netlist, symbol, schematic and fp_lib_table — with precise error locations. This is a serious asset.
- **Layout reuse.** `.layouts.json` plus the KiCad "Pull Group" plugin lets a module's physical layout be authored once and instantiated many times, with net remapping handled automatically.
- **Build hygiene.** Placement, designators, net names and picked parts are preserved across rebuilds; `--frozen` makes CI reproducible.
- **The language server.** Completion, hover, go-to-definition, references, rename, diagnostics and formatting, over a fork-server for fast restarts.
- **The agent runtime.** A working LLM agent with a tool registry, checklists, skills and both Anthropic and OpenAI providers — already wired to build, search parts, install packages and read logs.

---

## 4. Verified defects and limitations

Everything in this section was reproduced or read directly in the installed 0.15.9 source, or observed in the artefacts of a real build on this machine. Each entry gives the evidence so it can be re-checked.

### 4.1 Isolated grounds are silently merged — the critical one

**What the code does.** `faebryk/library/has_single_electric_reference.py` defines a trait whose `connect_all_references()` method does this:

```python
all_signals = parent_node.get_children(
    direct_only=False,                       # <-- walks the ENTIRE subtree
    types=(F.ElectricSignal, F.ElectricLogic),
)
for signal in all_signals:
    signal_reference = signal.reference.get()
    if ground_only:
        signal_reference.lv.get()...connect_to(reference.lv.get())
    else:
        signal_reference...connect_to(reference)
```

It runs automatically at the `POST_INSTANTIATION_SETUP` stage, before any electrical check.

**Three things are wrong with it for a BMS.**

1. `direct_only=False` means a nested sub-module's signals are pulled into the *parent's* shared reference, even when that sub-module sits on the far side of a galvanic barrier.
2. A nested module that carries its **own** `has_single_electric_reference` trait does not get to keep its own reference. The library's own unit test asserts the opposite behaviour as correct — this is the test, verbatim from `has_single_electric_reference.py`:

```python
# child's logic reference should ALSO be unified with parent's shared reference
assert _iface_connected(app.child.get().logic.get().reference.get(), shared)
```

3. The escape hatch does not exist. The signature is `MakeChild(cls, ground_only=False, exclude: list[fabll._ChildField] = [])` — `exclude` is accepted, never stored, and never read. A grep shows it is never passed by any caller in the library. It is a dead parameter with a mutable default.

**Why it bites Xbattery specifically.** `CAN_TTL`, `DifferentialPair`, `Ethernet`, `I2C`, `HDMI`, `FilterElectricalRC` and `Addressor` all carry this trait. Any BharatBMS board with an isolated CAN transceiver, an isolated RS-485 transceiver, or an isolated HV cell-sense domain will have the isolated ground merged with primary ground in the netlist. No warning is emitted. The board will route, pass DRC, and be fabricated with the isolation barrier bridged.

**Compounding factor.** There is no concept of isolation anywhere in the library to catch it downstream. A grep for `isolat`, `galvan`, `creepage`, `barrier` or `reinforced` across `faebryk/library`, `faebryk/libs/app` and `atopile/compiler` returns only an unrelated I2C-addressing flag and two designator-prefix comments.

**Status upstream.** Open as issue #1812 since 9 April 2026, unlabelled, zero reactions.

### 4.2 No netclasses and no design rules are written to the board

**Evidence.** The `.kicad_pcb` produced by a real build on this machine contains no `net_class` entries at all. The accompanying `.kicad_pro` contains exactly one netclass — KiCad's stock `Default` — with `clearance: 0.2`, `track_width: 0.2`, `via_diameter: 0.6`. The board-level rules read `min_track_width: 0.0`, `min_clearance: 0.0`.

No `.kicad_dru` custom-rules file is generated anywhere; a grep for `kicad_dru` across the whole tree returns nothing.

**Why this matters more than it sounds.** `faebryk/library/PCBManufacturing.py` already models a great deal: `PCBLayer` with thickness, material (FR4, aluminium, polyimide, PTFE, alumina), relative permittivity and loss tangent; `has_trace_specification` with trace width, spacing, annular rings and several clearance classes; `has_drill_specification`. The JLCPCB capability database is imported and used to write a stackup into the board. **None of it is projected into the board's design rules.** The model knows the fab can only do 0.127 mm traces, and then writes a board whose minimum track width is zero.

Combined with §4.1, the practical consequence is that there is no way to say "these two nets are on opposite sides of a reinforced barrier, keep them 8 mm apart" and have anything enforce it.

### 4.3 `max_current` is decorative

`ElectricPower` declares `voltage`, `max_current` and `max_power`, and marks the latter two as **sum bus parameters** — connect three sinks to a rail and their currents sum. That is a genuinely nice foundation for a power budget.

A grep for every use of `max_current` in the codebase returns hits in exactly one file: `exporters/documentation/power_tree.py`, where it is formatted into a JSON report. Nothing asserts that a source can supply the sum of its sinks. Nothing relates it to copper geometry. Nothing relates it to component ratings.

### 4.4 No current-carrying, thermal or temperature-rise analysis at all

A search for `current_density`, `IPC-2152`, `IPC-2221`, `temperature_rise`, `ampacity` and `thermal` across the entire installed tree finds:

- `copper weight` in `libs/jlcpcb/jlcpcb_manufacturing_spec.py`, used only to look up **minimum** trace width and spacing for manufacturability.
- `trace width` in `libs/jlcpcb/jlcpcb_impedance_calculator.py`, used only to solve controlled **impedance** for signal traces.

There is no ampacity calculation, no temperature-rise model, no via current rating, no copper-pour current analysis, and no thermal model of any kind. For a company whose products move 100 A through a board, this is the largest single functional gap.

### 4.5 Documentation exporters that produce nothing

Observed on a real build of a board that contains an `ElectricPower` rail, a resistor, an LED and a capacitor:

| Artefact | Content produced |
|---|---|
| `power_tree.md` | Three lines: an empty ```` ```mermaid / graph TD / ``` ```` block |
| `default.power_tree.ato.json` | `{"title": "Power Tree", "nodes": [], "edges": [], "groups": []}` |
| `default.data_interface_tree.ato.json` | `[]` |
| `default.testpoints.json` | `[]` |

Reading `exporters/documentation/power_tree.py` explains the first two: `export_power_tree()` unconditionally writes a hardcoded empty mermaid stub, and the real work happens in `export_power_tree_json()`, whose classifier only recognises nodes it can type as converters, sources or sinks — which requires `is_source` / `is_sink` traits that nothing in the demo sets. The CLI user gets a file named "Power Tree" containing no power tree.

### 4.6 Spec-versus-actual is reported but not evaluated

`default.variables.ato.json` from the same build:

```json
{
  "name": "capacitance",
  "spec": "8-12µF",
  "actual": "9-11µF",
  "meetsSpec": null,
  "source": "picked"
}
```

`meetsSpec` is `null` on every variable in the report. The field exists; the comparison is not performed. Unconstrained parameters are reported as `{ℝ+}V` — "any positive real" — which is exactly the case a derating check would need to flag, and does not.

A related cosmetic defect: that `{ℝ+}V` string leaks into the BOM's Value column, which reads `976Ω ±1% 100mW ℝ+V` for the resistor. The LED's Value column is empty.

### 4.7 Retained parts are not re-validated against non-numeric constraints

`libs/app/keep_picked_parts.py` reloads previously picked parts from the board and reasserts them as constraints, so a numeric conflict — a capacitance that no longer fits — surfaces as a solver contradiction and fails the build. That part is well designed.

But package requirements are a **trait**, not a solver parameter. Adding or changing `.package = "C0402"` on a part that is already placed does not force a re-pick and does not raise a contradiction, because the retained part still satisfies the numeric constraints. On this machine's demo project, a capacitor declared `c_bulk.package = "C0603"` is realised in the BOM as a TDK `FG26X7R1E106KRT06` in footprint `CAP-TH_L5.5-W3.5-P5.00-D0.5` — a through-hole radial part 5.5 mm × 3.5 mm.

The practical rule is: **changing a package constraint on an already-picked part silently does nothing.** You must force a re-pick with `--no-keep-picked-parts`.

### 4.8 The language-server surface has notable holes

Registered LSP features: completion, hover, definition, type definition, references, rename, prepare-rename, diagnostics, formatting, and the document lifecycle events.

Not registered: **document symbol** (so there is no outline view or breadcrumb navigation for `.ato` files in VS Code), workspace symbol, semantic tokens, inlay hints, signature help, folding range, call hierarchy, and code lens. For files describing a 200-component board, the absence of an outline view is felt immediately.

### 4.9 Single points of cloud failure

Part picking raises this if you are not signed in:

> "Part picking on atopile 0.15.8 requires sign-in. Run `ato auth login`, or migrate to app.atopile.io (0.16+)."

In the seven months to August 2026 there were five separate service-outage issues filed — `packages.atopile.io` failing to resolve, `components.atopileapi.com` returning NXDOMAIN, a dangling CNAME breaking all picker calls, and the telemetry endpoint 404ing. Each of these stops a build.

An older issue, #201 "Working on projects while offline", records the same problem from the user's side: the build reaches out to the network to fetch part data even when there is no connectivity.

### 4.10 A note on this machine's current state

Two environment facts that affect any immediate work:

1. **Smart App Control blocked the toolchain on 27 September, and has been resolved.** Windows promoted Smart App Control to enforcement and blocked uv's unsigned interpreter. The environment was rebuilt on the signed python.org 3.14.7 and now works with Smart App Control still enabled. Full diagnosis and resolution in §14.3. The relevance to this study is that a toolchain distributed as an unsigned binary is fragile on a managed or hardened Windows estate — a consideration for how Xforge itself is packaged and deployed internally.
2. The AVX-512 wheel workaround previously applied to this install — rebuilding `pyzig` from source with `-Dcpu=baseline` for issue #1838 — is exactly the platform-matrix problem atopile cites as its motivation for abandoning multi-platform distribution. It is no longer needed here under the signed interpreter, but it is a good illustration of the maintenance burden a fork inherits.

### 4.11 Summary table of verified defects

| ID | Defect | Severity for Xbattery | Fixable in a fork? |
|---|---|---|---|
| D1 | Isolated grounds silently merged; `exclude` is a no-op | **Critical** | Yes — bounded change, ~2 days plus a barrier model |
| D2 | No netclasses or DRC rules emitted to the board | **Critical** | Yes — the manufacturing model already exists |
| D3 | No ampacity / thermal / temperature-rise model | **Critical** | Yes — new subsystem, ~3 weeks |
| D4 | `max_current` unused outside a report | High | Yes — trivial once D3 exists |
| D5 | Single supplier (LCSC), three parametric categories | **Critical** | Yes — replace the picker backend |
| D6 | Package change on a picked part silently ignored | High | Yes — re-validate traits against retained picks |
| D7 | Power tree and data-interface exporters emit empty files | Medium | Yes — small |
| D8 | `meetsSpec` never computed | Medium | Yes — small |
| D9 | No document-symbol / outline in the LSP | Medium | Yes — small |
| D10 | Cloud dependency for picking; five outages in seven months | **Critical** | Yes — local parts database |
| D11 | Telemetry on by default, sends git email and remote URL | High | Yes — invert the default |
| D12 | No schematic generation | High | Yes — writer exists, needs placement and routing algorithms |
| D13 | No assembly variants, panelisation, multi-board, harness, simulation, FMEA | High | New subsystems — see §9 |

---

## 5. Community and user research

### 5.1 How the evidence was gathered

Hacker News was searched exhaustively through the Algolia API across 2024–2026, and every substantive comment thread mentioning atopile was read. Hackaday's two articles and their comment sections, an independent critique blog, the Altium OnTrack podcast founder interview, the Y Combinator listing, LinkedIn and the live sites were also covered. Reddit and X/Twitter both returned hard 403 blocks to every access route attempted; their absence here is a tooling limitation, not a finding.

### 5.2 Ranked themes

| # | Theme | Frequency | Intensity | Representative quote |
|---|---|---|---|---|
| 1 | No visual schematic; cannot review a design at a glance | Very high, every thread 2024–2026 | High — a dealbreaker for many veteran EEs | *"Schematics convey lots of information quickly. Function, structure, constraints, implementation notes… They work."* — robomartin, HN Feb 2024 |
| 2 | Layout and routing are still manual; autorouting unsolved | Very high | High | *"I would say that schematic capture is only a small minority of the work of most circuit design. Probably 90% is creating components and layout/routing."* — IshKebab, HN Jul 2025 |
| 3 | Documentation and real examples are thin | High | Medium-high | *"I gave up hunting through your website because I never managed to find an example of what the code for a real circuit looks like."* — yodon, HN Jul 2025 |
| 4 | "Yet another DSL" | High in 2024, tapering | Medium-high | *"I absolutely hate it when people invent their own weird programming language instead of using a well defined existing one… Why not just use Python?"* — TobiasJacob, HN Feb 2024 |
| 5 | Parts picker and library are thin and JLCPCB-centric | High, steady | Medium | *"Having to duplicate the library parts just to work with atopile is a significant obstacle for getting started."* — paulvdh, Hackaday Feb 2024 |
| 6 | Vendor lock-in / cloud pivot / sign-in required | New, Aug–Sep 2026 | **Very high** | *"Atopile is ditching their cli. They're going the wrong direction."* — thedougd, HN Sep 2026 |
| 7 | No analog, RF, high-power or simulation path | Medium-high, from specialists | High among those who raise it | *"This product would not work at all for any analog or power designs — EEs like to visualize current flow and a schematic is the best way to do that."* — tubetime, HN Feb 2024 |
| 8 | Unproven for production teams, large or regulated designs | Medium but deep | High | *"I shudder to think what it would be like to try to understand and debug a PCBA for a 20 layer board that was just a bunch of code."* — tcherasaro, HN Feb 2024 |
| 9 | Not novel — reinvents Verilog / SKiDL / netlists | Medium, recurring | Medium | *"The ato language works well for specifying parts and parameters, but is very basic for defining connectivity. This means that the designer will have minimal control of how the final schematics will turn out."* — liu3hao, HN Feb 2026 |
| 10 | Wish for hybrid GUI plus code with round-trip sync | Medium, constructive | Medium | *"Side-by-side schematic symbol view / code view that are actively synced to one another in real-time."* — JRKrause, HN Feb 2024 |

### 5.3 The GitHub signal

Engagement on issues is uniformly thin — the highest-reacted issue in the project's history has five reactions — so the useful signal is **repetition of a theme**, not reaction counts, plus the Discussions tab.

**The single highest-engagement item in the entire project is a Discussion, not an issue:** #881, *"Steps Towards Auto-Layout"*, with 35 reactions. The team's stated strategy there: *"Our strategy is to eat layout task by task, until the remaining layout is tractable for generative tools to complete the remainder of the design."*

Themes by repetition across all 343 issues ever filed:

| Theme | Recurrences | Notable |
|---|---|---|
| Windows platform friction | ~10 distinct bugs | The AVX-512 native crash was filed three separate times (#1821, #1825, #1838); #1838 remains open |
| Hosted-service outages | 5 in 7 months | #1830, #1829, #1831, #1832, #1744 |
| Layout reuse breaking under refactors | 3 | #237, #227, #894 — renaming or replacing a module orphans its saved placement |
| KiCad version compatibility | 3 | #1822: a board saved by KiCad 10 can no longer be read by atopile 0.15.7 |
| Multi-supplier sourcing | 1, closed without the feature | #1271: *"Currently only sourcing from EasyEDA (LCSC). Might want to add other suppliers…"* |
| SPICE simulation | 1 Discussion, 0 replies | #1815 — but a `feature/ngspice` branch exists |
| Thermal / high-current / autorouting | **0 issues** | The topic is absent from the tracker entirely |

The branch list is a better roadmap than anything written down: `feature/ngspice`, `feature/multiboard`, `feature/multi-board-project-support`, `fix-thermal-via-net`, `feature/deeppcb`, `feature/pinout_generation`, `feature/jlcpcb_stackup_importer`, `feature/llm_chat`.

### 5.4 What users praise — keep all of this

1. **Plain text and git.** The most-liked idea by a distance. *"The state of electronics tooling has long been extremely bad… And multiple people working on the same design and merging their changes? Forget about it!"* — michaelt, HN.
2. **Typed interfaces.** Connecting an entire I2C or power bus in one type-checked statement.
3. **The constraint solver.** *"Get even a basic equation solver in there and I'll be a user! Have it handle units properly and I'll be a happy user. Have it be able to handle both worst-case and RSS tolerance stackups and I'll be in love."* — addaon, HN. Note the last clause: **tolerance stack-up analysis is an explicit community wish that still does not exist.**
4. **Package reuse**, npm-style.
5. **The AI-agent workflow.** *"I did some vibe hardware design using atopile recently — it's surprisingly good."* — iamflimflam1, HN Jul 2025.
6. **Founder engagement.** Consistently praised, across two years of threads.

### 5.5 Reading the community evidence for Xbattery

Three conclusions follow directly.

- **The schematic is the adoption gate.** Every EE who evaluated the tool and walked away named the same reason. Any internal platform that expects senior engineers to review a 51.2 V BMS design must produce a reviewable schematic. It is not a nice-to-have; it is the price of entry with experienced staff and with certification bodies.
- **The criticisms that matter are exactly Xbattery's requirements.** "No analog or power", "no simulation", "unproven for regulated designs", "single supplier" — the community's objections and Xbattery's needs are the same list. That is a strong signal that the gap is real and worth building into.
- **The praise identifies what to preserve.** Plain text, typed interfaces, the solver, package reuse, the agent. These are the parts of the fork to protect and extend, not re-litigate.

---

## 6. Competitive landscape

The purpose of this section is narrow: to find capabilities that exist *somewhere* in the market, so that the novel-feature list in §9 is genuinely novel and the roadmap does not rebuild something that can be bought.

### 6.1 Direct code-first competitors

| Tool | Approach | Killer capability atopile lacks | Licence / model | Status Sep 2026 |
|---|---|---|---|---|
| **JITX** (jitx.com) | Requirements, stackups and manufacturing rules as code. **Migrated off Stanza to pure Python in Q4 2025.** Compiles to schematic plus board, with its own topological autorouter. | **Signal-integrity-aware constraint-*solved* routing** — impedance, skew and loss are routing targets the solver satisfies, not DRC checks applied afterwards. Plus a closed loop with Ansys HFSS. | Proprietary; public self-serve pricing was removed in 2026 in favour of enterprise/demo sales | Active, YC and Sequoia backed |
| **tscircuit** (tscircuit.com) | React/TypeScript components describe schematic and PCB simultaneously; live browser re-render on every save. | Unified schematic + PCB + 3D live preview in the browser, zero install; TSX is a language every code model already knows. | MIT, fully open source | Active, daily commits |
| **Zener / Diode Computers** | `.zen` files in Starlark; the `pcb` CLI compiles to a KiCad project. | A **curated registry of ~250 production-validated reference designs used deliberately to ground LLM generation**, plus testbench-style grading ("≥22 µF between power and ground") instead of exact-match checks. Anthropic is a named partner. | MIT for the tool; the company monetises as a design consultancy | Early but fast-moving; cites atopile as prior art |
| **SKiDL** | Python package producing netlists only. | Nothing atopile lacks; it is strictly lower level. Worth knowing as a fallback if a DSL is rejected internally. | Open source | Active; KiCad 10 support added |

### 6.2 AI copilots and chat-driven EDA

| Tool | What it adds | Relevance to Xbattery |
|---|---|---|
| **Flux.ai** | $27M Series B, March 2026. Browser EDA with an "AI Circuit Co-Designer". **Real-time multiplayer editing** and **automatic footprint generation from datasheet PDFs**. | The datasheet-PDF-to-footprint vision pipeline is a capability atopile has no equivalent for, and one Xbattery would use constantly when vendoring AFEs and transceivers. |
| **Celus** | Natural-language or block-diagram requirements to matched components to schematic. Partnered with Siemens EDA. | Sales-gated, no public pricing. Its block-level architecture-first UX is a good model for the requirement-capture front end proposed in §9.7. |
| **Circuit Mind** | "Architecture to schematic and BOM in 60s", explores very large BOM option spaces for cost and availability. | The BOM-optimisation-as-search idea is directly applicable and is *not* something atopile's satisfy-only solver can do. |

### 6.3 AI autorouting as a service

| Tool | Notes | The one thing that matters here |
|---|---|---|
| **Quilter** | Physics-driven reinforcement learning, ~100 candidate layouts in parallel, Simbeor field solver for impedance. $40M raised. Integrates with Altium, Allegro and Xpedition file formats. | **It is the only autorouting vendor confirmed to offer self-hosted / air-gapped deployment**, explicitly for aerospace and defence customers who cannot send designs to a cloud. If Xbattery ever needs AI layout without shipping IP offsite, this is the only current option. |
| **DeepPCB** (InstaDeep, now a BioNTech subsidiary) | RL trained by self-play; native KiCad support; credit-based pricing at 0.5 credit per minute. | Already integrated into atopile as a full job-lifecycle subsystem — submit, poll, multiple candidates, preview, apply-as-diff onto the `.kicad_pcb`, with jobs persisted to `~/.atopile/autolayout/jobs.json`. Cloud-only, token-authenticated. |

### 6.4 The incumbents' AI features

| Suite | Native capability atopile lacks |
|---|---|
| **Cadence Allegro X AI** | Generative placement and routing **coupled to the Celsius thermal solver** in the same platform. Self-hosted deployment was still not shipped as of September 2026. |
| **Siemens Xpedition (2604, Apr 2026)** | **Multi-board system-level interface verification** — checking I/O, power and ground consistency across the boards of one system. Also AI datasheet analysis and variant management. |
| **Altium 365** | **Component lifecycle and obsolescence risk analytics** across a whole BOM, following the Part Analytics acquisition. Assisted routing only; not generative. |
| **KiCad 10** (Mar 2026) | Design **variants**, pin and gate swap, a graphical DRC rule editor, time-domain tuning, and ngspice simulation integrated in Eeschema. Note that atopile 0.15.9 **cannot read a board that KiCad 10 has saved** (issue #1822) — this machine is pinned to KiCad 9 for that reason. |

### 6.5 Domains with no tooling at all

This is the most commercially interesting part of the survey.

- **BMS-specific design automation does not exist.** What the market calls "BMS tooling" — Ansys, CADFEM — is algorithm and firmware modelling: state-of-charge estimation, cell-balancing algorithms, ISO 26262 code generation. Nobody offers "describe your pack topology and cell count, get a BMS board". The whitespace is total.
- **Busbar-as-code does not exist.** Every busbar tool is a CAD plugin or an FEA package (EAE for Revit, CENOS, INTEGRATED, EMWorks). Nobody has made busbars a first-class object in a design language.
- **Harness-as-code exists but is disconnected.** WireViz is the real analogue — GPL, YAML in, SVG and BOM out, version-control friendly, actively maintained. It has no integration with any PCB tool, including atopile.
- **Thermal and current-density in the design loop** is available from Ansys (SIwave plus Icepak), Cadence (Celsius) and Siemens (Flotherm, FLOEFD SmartPCB) — all commercial and all outside the code-driven world. On the open side the components exist but are unassembled: ngspice does electro-thermal at circuit level, ElmerFEM does FEM heat transfer, OpenEMS with Antmicro's gerber2ems does full-wave EM from Gerbers.

### 6.6 Capabilities that exist in the market but not in atopile

Ranked by relevance to Xbattery:

1. Thermal and current-density analysis in the design loop (Cadence, Siemens, Ansys; open pieces exist).
2. Self-hosted / air-gapped AI layout (Quilter only).
3. Component lifecycle and obsolescence risk analytics across a BOM (Altium 365).
4. Multi-board system-level interface verification (Siemens Xpedition 2604).
5. Datasheet-PDF to footprint and symbol generation by vision model (Flux, Xpedition Standard).
6. A curated, physically validated reference-design registry used to ground AI generation (Diode).
7. Simulation in the compile loop with results feeding the constraint solver (JITX to HFSS).
8. Signal-integrity-aware constraint-solved routing (JITX).
9. BOM optimisation as a search over cost and availability (Circuit Mind).
10. Assembly variants and design variants (KiCad 10, Altium, Xpedition — and notably not atopile).

And two that exist nowhere, which is where Xbattery's differentiated value sits: **BMS-specific design automation** and **busbar-as-code**.

---

## 7. Consolidated gap matrix

Legend — **Y** present and usable, **P** partial, **N** absent.

### 7.1 Core design capability

| Capability | atopile 0.15.9 | Priority for Xbattery | Feasibility in a fork |
|---|:--:|---|---|
| Declarative circuit DSL with typed interfaces | Y | Keep | — |
| Constraint solving over physical parameters with tolerance | Y | Keep | — |
| Parametric part selection | P — R, L, C only | **P0** | Medium — new picker backend |
| Part selection by MPN or supplier ID | Y | Keep | — |
| Hierarchical modules and reuse | Y | Keep | — |
| Arrays and `for` iteration | Y | Keep | — |
| Conditional structure (if / when) | N | **P1** | Medium — language change |
| Templating with physical quantities | N — literals only | **P1** | Low — grammar change |
| Schematic generation | N | **P0** | Medium — writer exists, placement/routing needed |
| Schematic ingestion (KiCad, Altium) | Y | P2 | — |
| Netlist diff between revisions | P — PCB geometry diff only | **P1** | Low |
| Assembly variants / DNP | N | **P0** | Medium |
| Multi-board / system design | N | **P1** | High |
| Panelisation | N | P2 | Low — KiKit exists |
| Simulation (SPICE) | N | **P1** | Medium — ngspice, branch exists upstream |
| Tolerance stack-up analysis (worst case and RSS) | N | **P1** | Medium — solver has the primitives |

### 7.2 Physical and safety

| Capability | atopile 0.15.9 | Priority | Feasibility |
|---|:--:|---|---|
| Netclass generation into the board | N | **P0** | Low |
| Custom DRC rule generation (`.kicad_dru`) | N | **P0** | Low |
| Ampacity / trace width from current | N | **P0** | Medium |
| Copper weight as a design parameter | P — DFM lookup only | **P0** | Low |
| Temperature rise / thermal model | N | **P0** | Medium-high |
| Via current rating | N | **P0** | Low |
| Isolation barrier as a first-class object | N | **P0** | Medium |
| Creepage and clearance rules | N | **P0** | Medium |
| Working-voltage propagation across the graph | N | **P0** | Medium |
| Component derating rules (voltage, power, temperature) | N | **P0** | Low |
| Fuse / protection coordination | N | **P1** | Medium |
| Controlled impedance | P — JLC calculator only | P2 | — |
| EMC / ESD / surge structural checks | N | **P1** | Medium |
| Functional safety artefacts (FMEA, FMEDA) | N | **P1** | High — novel |

### 7.3 Supply chain and manufacturing

| Capability | atopile 0.15.9 | Priority | Feasibility |
|---|:--:|---|---|
| Multi-supplier sourcing | N — LCSC only | **P0** | Medium |
| Approved-vendor list with second sources | N | **P0** | Low |
| Lifecycle / EOL / NRND status | N | **P0** | Low — data is purchasable |
| Stock and lead-time awareness in CI | N | **P0** | Low |
| India landed cost (HSN, duty, GST, freight, INR) | N | **P0** | Low |
| AEC-Q / temperature grade / MSL filters | N | **P1** | Low |
| RoHS / REACH / conflict-minerals declarations | N | **P1** | Low |
| Cost model | P — hardcoded JLCPCB USD | **P1** | Low |
| Offline / air-gapped builds | N | **P0** | Medium |
| Manufacturing outputs (Gerber, P&P, STEP, GLB, DXF) | Y | Keep | — |

### 7.4 Process, review and collaboration

| Capability | atopile 0.15.9 | Priority | Feasibility |
|---|:--:|---|---|
| Plain-text, git-native source | Y | Keep | — |
| Build reproducibility (`--frozen`) | Y | Keep | — |
| Language server | P — no outline/symbols | **P1** | Low |
| LLM agent runtime | Y | Keep and extend | — |
| Design review artefacts for humans | P | **P0** | Medium |
| Requirement-to-test traceability | N | **P1** | Medium |
| Revision / ECN / change-order management | N | **P1** | Medium |
| Hardware "unit tests" | N | **P0** | Medium |
| Telemetry off by default | N | **P0** | Trivial |
| On-premise / self-hosted | N in 0.16 | **P0** | It is the fork |

---

## 8. Fit assessment for Xbattery

### 8.1 What Xbattery builds, and what that implies

From public sources: Xbattery is a Hyderabad deep-tech company founded in 2024, based at T-Hub, with $2.3M in seed funding. Products are **BharatBMS** — described as India's first indigenously developed unified BMS, with variants at 51.2 V, 72 V and 110 V for energy storage plus high-voltage BMS for EVs — and the **XB-5K**, a 5 kWh LFP home and office energy-storage system, 37 kg, scalable to 15 kWh.

Four implications follow, and they shape everything in §9:

1. **You ship a family, not a board.** 51.2 V, 72 V, 110 V and an EV high-voltage line are the same architecture at different cell counts and isolation classes. This is precisely the case parametric design was invented for, and it is the strongest argument for adopting a code-driven flow at all. One `BharatBMS` module with `cell_count`, `chemistry` and `isolation_class` as parameters should generate all four.
2. **You live on both sides of the isolation barrier.** Every product has an HV cell-sense domain and an LV logic/comms domain. The tool's single most dangerous defect (§4.1) sits exactly there.
3. **You move real current.** A 5 kWh LFP pack at 51.2 V is roughly 100 Ah. Contactors, shunts, MOSFET arrays, precharge and busbars are the core of the board, and the tool has no model of current at all.
4. **You write the firmware too.** The internal work on this machine — LuxPower and Deye CAN protocol reverse-engineering, DBC authoring, BQ76952 register maps, an 800 V BMU power and sleep architecture on an NXP FS26 platform — shows a team that owns hardware and firmware together. That is the basis of the highest-value idea in this document.

### 8.2 What breaks if Xbattery adopts atopile as-is

| Xbattery need | What happens today |
|---|---|
| Isolated CAN to the inverter (LuxPower, Deye) | Isolated ground silently merged with primary ground. Board is fabricated with the barrier bridged. |
| 16S / 24S / 32S cell-tap front end | Expressible with arrays and `for`, but no cell-tap fusing, RC filtering or tap-ordering checks exist. Every AFE must be vendored by hand — no BQ769x2 or NXP MC3377x package exists in the registry. |
| 100 A power path | No trace-width calculation, no copper-weight parameter, no temperature rise, no via current rating. The generated board has `min_track_width: 0.0`. |
| 110 V and 800 V clearance | No creepage or clearance concept. No working-voltage propagation. No netclass or DRC output. |
| Production BOM for India | LCSC-only. No second source, no lifecycle status, no INR, no HSN, no duty. Non-LCSC parts are dropped from the BOM with a warning. |
| Certification evidence for IEC 62619, UL 1973, AIS-156 | Nothing. No isolation table, no clearance report, no traceability matrix. |
| Design review by a senior EE | No schematic. |
| Reproducible builds for audit | Part picking requires a live connection to a vendor service that is being retired. |
| IP confidentiality | Telemetry on by default sends git email, remote URL and commit hash; 0.16 puts the whole design on a vendor's server. |

### 8.3 The honest counter-case

It is worth stating the argument against this whole programme, because it should be beaten on merit rather than ignored.

- **KiCad 9 alone is free and works.** A three-person hardware team can ship BharatBMS variants with KiCad, a spreadsheet BOM and discipline. Everything proposed here is overhead until the variant count and the certification burden make manual work the bottleneck.
- **A DSL is a hiring and onboarding cost.** Every new EE must learn it. The community's "yet another language" objection is not unreasonable.
- **Three engineers for twelve months is a material fraction of a $2.3M seed.**

The counter-argument, which is why the recommendation stands: Xbattery's differentiator is claimed to be an *indigenous, unified* BMS platform spanning 51.2 V to 800 V. "Unified" across a voltage range of 16× is a claim about architecture reuse, and architecture reuse is exactly what breaks down when four product lines are maintained as four KiCad projects. The tool is not overhead against the first board; it is leverage against the fourth, and insurance against the certification audit on the second.

The recommended de-risking is in the roadmap: **Phase 0 delivers value in six weeks using the existing KiCad flow**, with no DSL adoption required, and the decision to go further is taken with evidence.

---

## 9. Novel feature design

This section is the substance of the proposal. Features are grouped into seven tiers. Tiers A–C are the ones that make the platform viable for Xbattery; D–F make it better than anything on the market; G is deliberately speculative and labelled as such.

Throughout, the working name **Xforge** is used for the forked platform. It is a placeholder.

Each feature states: **what it is**, **why Xbattery specifically needs it**, **how it is built** against the forked architecture, and a rough **effort** in engineer-weeks.

> **A standing caveat on numeric constants.** Several features below depend on values from IEC 60664-1, IEC 62368-1 and IPC-2152. Those standards are paywalled, and independent secondary sources disagree by up to about 25% on creepage and clearance values at the same operating point. **Buy IEC 60664-1:2020+AMD1, IEC 62368-1:2023 and IPC-2152 once, extract the tables verbatim, and encode them as named constants that cite table, row and column in a comment.** Do not ship any number in this document as a hard gate. The IPC-2221 formula is the exception — it is a widely reproduced empirical fit and is safe to implement directly.

### Tier A — the safety and physics compiler

This tier turns Xforge from a netlist generator into something that can say "this board cannot carry 100 A" before the board is fabricated.

#### A1. Current as a first-class, propagated quantity

**What.** Extend the graph so that every `Electrical` node carries a solved current, not just every `ElectricPower` interface. Current propagates by Kirchhoff's current law across the connection graph, using the existing sum-bus-parameter mechanism that `ElectricPower.max_current` already demonstrates.

**Why.** `max_current` today aggregates and is then printed in a report. Nothing checks that a source can supply its sinks, and nothing connects it to copper. For a 100 A LFP pack this is the whole ballgame.

**How.** `ElectricPower` already marks `max_current` and `max_power` with `is_sum_bus_parameter`; that machinery is the hook. Add `nominal_current`, `peak_current` and `fault_current` alongside `max_current`, register a `post_solve` design check that asserts source capability ≥ aggregated sink demand on every rail, and make the fault-current figure available to the protection-coordination check (A6).

**Effort.** 3 weeks.

#### A2. Ampacity check and automatic netclass generation

**What.** Given the solved current on a net, the target temperature rise, the copper weight and the layer, compute the minimum conductor cross-section, convert it to a minimum track width, and write it into the board as a **KiCad netclass** plus a **`.kicad_dru` custom rule**. Fail the build if the routed geometry is narrower.

**Why.** This is the single highest-value missing check, and it closes the loop between the electrical model and the physical board — the thing atopile claims to do and does not.

**How.** Three parts, in increasing order of difficulty:

1. **The maths.** IPC-2221's closed-form fit is public and consistently reproduced:
   `I = k · ΔT^0.44 · A^0.725`, with `A` in mil², `ΔT` in °C, `k = 0.048` external and `k = 0.024` internal. Inverted for the checker: `A_required = (I / (k · ΔT^0.44))^(1/0.725)`.
   IPC-2152 is chart-based and has no public closed form; treat digitising it as a separate data-acquisition task, and ship IPC-2221 first with a documented conservatism note. Note that IPC-2152 generally yields *narrower* traces than IPC-2221 because the older standard's 2:1 internal/external penalty is pessimistic for real multilayer boards with adjacent pours.
2. **The netclass writer.** `faebryk/libs/net_naming.py` already assigns structured names, and the `.kicad_pro` already carries a `net_settings.classes` array and `netclass_patterns`. Emit one netclass per current band with the computed `track_width`, `clearance` and `via_diameter`, and assign nets by pattern.
3. **The DRU writer.** Emit a `.kicad_dru` with per-net-class rules, including the isolation keep-outs from A4.

Add via ampacity on the same basis: model the barrel as a flat conductor of cross-section `π × drill_diameter × plating_thickness`, and apply the same relation. A via landing on a plane is commonly credited with about 1.2× the current of an isolated via; treat that as a configurable, documented rule of thumb, not a standard value.

**Effort.** 4 weeks for IPC-2221 plus netclass and DRU output. A further 3 weeks if IPC-2152 chart data is digitised.

**Sketch of the intended surface:**

```ato
import ElectricPower
from "xforge/physical" import CopperWeight, ThermalBudget

module PackPowerPath:
    pack = new ElectricPower
    pack.voltage = 51.2V +/- 20%
    pack.nominal_current = 100A
    pack.peak_current = 200A          # 10 s discharge burst

    trait has_thermal_budget<max_rise=20celsius>
    trait has_copper_weight<outer=2oz, inner=1oz>
    # -> compiler computes minimum track width, writes netclass PWR_100A,
    #    emits a .kicad_dru rule, and fails the build if the router
    #    produces anything narrower.
```

#### A3. Working voltage propagation

**What.** Every net acquires a **working voltage** — the highest steady-state potential difference it sees relative to every other net it is not connected to — derived from the solved voltages of the rails it touches. This is the input every insulation rule needs.

**Why.** Creepage and clearance are functions of working voltage between *pairs* of nets, not of a net in isolation. Without this, no insulation rule can be automated.

**How.** After the solver converges, compute pairwise potential differences across the net graph. This is O(n²) in nets but n is small (hundreds), and it only needs recomputing when voltages change. Store the result as an annotation consumed by A4 and by the schematic generator.

**Effort.** 2 weeks.

#### A4. Isolation barriers as first-class objects

**What.** A declarable `IsolationBarrier` that separates two power domains, carrying a working voltage, an insulation class (functional, basic, supplementary, double, reinforced), a pollution degree, a laminate material group (CTI), an overvoltage category and a deployment altitude. It does four things: it **blocks** reference unification across itself, it **computes** the required creepage and clearance, it **emits** keep-out geometry and DRC rules onto every copper layer, and it **reports** an isolation table for the certification file.

**Why.** This is the direct fix for the critical defect in §4.1 and the enabler for every HV product Xbattery ships. Every BharatBMS variant has at least one barrier; the 800 V EV line has several.

**How.**

1. **Fix the merge.** Rewrite `has_single_electric_reference.connect_all_references()` so the subtree walk stops at any node that declares its own reference domain or sits behind a barrier, and so `exclude` actually excludes. Add a regression test that is the inverse of the one currently in the file.
2. **Model the barrier.** A node type with the six parameters above, plus two `domain` handles. Nets reachable only through one handle belong to that domain.
3. **Check it.** A `post_instantiation_design_check` that fails if any net is reachable from both domains other than through a declared crossing component (optocoupler, digital isolator, isolated DC-DC, capacitive or magnetic coupler, Y-capacitor).
4. **Enforce it physically.** A `post_pcb_check` that measures the actual copper-to-copper path on every layer and compares it against the looked-up requirement, plus a DRU rule so KiCad enforces it interactively.
5. **Gate the conformal-coating shortcut.** A "coated" boolean must never reduce the pollution degree. Only a named, qualified coating system with a certificate reference may justify a PD2→PD1 reduction, and the reference must be recorded in the design.

**Effort.** 5 weeks, plus the standards purchase.

```ato
from "xforge/safety" import IsolationBarrier, InsulationClass, PollutionDegree

module BharatBMS_HV:
    hv_domain = new ElectricPower     # 800 V pack
    lv_domain = new ElectricPower     # 12 V logic

    barrier = new IsolationBarrier
    barrier.working_voltage = 800V
    barrier.insulation = InsulationClass.REINFORCED
    barrier.pollution_degree = PollutionDegree.PD2
    barrier.material_group = "IIIa"     # verify against the laminate datasheet
    barrier.altitude = 500m             # Hyderabad
    barrier.primary ~ hv_domain
    barrier.secondary ~ lv_domain
    # -> required creepage/clearance computed, keep-out emitted on all layers,
    #    reference unification blocked, isolation table written to the cert pack.
```

#### A5. Component derating rules

**What.** A declarative derating policy applied automatically to every picked part: capacitor voltage derating by dielectric and temperature, resistor power derating, MOSFET V_DS and safe-operating-area margin, inductor saturation current, electrolytic ripple current and lifetime.

**Why.** Derating policy is currently tribal knowledge held in a spreadsheet. Encoding it means the picker cannot choose a part that violates it, and the policy becomes an auditable artefact for certification.

**How.** A policy file (`derating.yaml`) maps component class and application class to a margin. The picker applies it as an additional solver constraint before querying, so violations are impossible rather than reported. Class II ceramics need special handling — DC-bias capacitance loss is large and is why a nominal 10 µF X7R at rated voltage is often 3 µF in circuit — so the capacitance constraint should be evaluated at the applied DC bias, not at zero bias.

**Effort.** 3 weeks.

#### A6. Protection coordination and the BMS safety-path checks

**What.** A family of BMS-specific structural checks, each expressed as a graph pattern over the design:

| Check | Criterion |
|---|---|
| Cell-tap fusing | Every AFE cell-sense net has exactly one fuse or PTC between the cell terminal and the AFE pin, rated below the AFE's absolute maximum input current and above the balancing current |
| Cell-tap filtering | Every cell-sense net has a series R and a shunt C present, non-zero, within the AFE vendor's stated maximum distance of the pin |
| Kelvin sensing | The current-sense net originates at the shunt's dedicated sense pad, not as a tap off the force trace |
| Precharge sizing | `3RC ≤ target precharge time`, and the resistor's pulse rating exceeds `½CV²` divided by the worst-case re-precharge interval |
| Contactor flyback | A clamp element exists across every inductive coil, or the contactor's datasheet confirms an internal one |
| Reverse polarity | Every external DC port terminates in a FET-based protection stage, not a bare series diode, above a configurable current threshold |
| ADC clamp coordination | Worst-case fault current into the clamp, computed from the fault voltage and the series resistance, stays inside the clamp's and the ADC's continuous ratings |
| Independent secondary protection | A second sense→decide→actuate path exists that shares no node, no power rail and no clock with the primary path |
| Watchdog present | A watchdog element supervises the safety-relevant MCU loop, with a timeout bounded below the maximum allowable fault-response latency |

**Why.** These are the checks a BMS reviewer performs by eye today, and they are exactly the ones that a code-driven flow can perform every commit. The independent-secondary-path check in particular maps onto ISO 26262 ASIL decomposition and onto the two-fault-tolerance expectation for grid-connected storage in India.

**How.** Each is a `post_instantiation_design_check` or `post_solve_check` registered against a trait. The graph query API already exists — this is pattern matching over `get_children` and the connection edges. The independent-path check is the only hard one: it needs a reachability analysis over three tagged element roles with shared-resource detection, which is a graph colouring problem on a few hundred nodes.

**Effort.** 6 weeks for the set, and this is the piece that most directly encodes Xbattery's own engineering knowledge.

### Tier B — supply chain for an Indian production company

#### B1. Multi-source parts service with approved-vendor lists

**What.** Replace the single hosted LCSC picker with an Xbattery-owned parts service. Every part has an AVL of at least two approved sources with distributor part numbers, and the picker will not select a part with fewer than the policy minimum. Sources include Mouser, Digi-Key, Arrow, element14 India and local distributors alongside LCSC.

**Why.** LCSC is fine for prototypes and wrong for production. The current BOM exporter silently drops any part without an LCSC number.

**How.** The picker is already behind an interface — `libs/picker/api/api.py` has `fetch_part_by_lcsc`, `fetch_part_by_mfr`, `query_parts` and `fetch_parts_multiple`. Reimplement that interface against a local PostgreSQL parts database, populated by nightly pulls from distributor APIs and by manual AVL entries. Extend the `Supplier` enum beyond `LCSC`. Extend the parametric `Endpoint` enum beyond resistors, capacitors and inductors — diodes, MOSFETs, LEDs, connectors and crystals are all parametrically selectable in principle and are not today.

**Effort.** 6 weeks including the data pipeline.

#### B2. Lifecycle, compliance and risk attributes on every part

**What.** Each part carries lifecycle status (active / NRND / EOL with last-time-buy date), RoHS and REACH declarations, moisture sensitivity level, AEC-Q qualification and grade, operating temperature range, and a counterfeit-risk flag derived from source authorisation.

**Why.** A BMS certified to IEC 62619 with a part that goes end-of-life mid-production is a recertification event. Catching it in CI is worth more than catching it in procurement.

**How.** Attributes on the parts database, exposed as solver-visible constraints so a policy such as "every part in a safety-path module must be AEC-Q100 Grade 1 and active" is enforced at compile time. Add a CI check that fails when any BOM line's stock falls below the planned build quantity or its lifecycle status changes.

**Effort.** 3 weeks on top of B1.

#### B3. India landed-cost model

**What.** Replace the hardcoded JLCPCB dollar model with a landed-cost model in INR: unit price at quantity, HSN code, basic customs duty, IGST, freight, and an assembly cost model that can target multiple fabs rather than only JLCPCB.

**Why.** Board cost decisions made in USD ex-works are wrong by a large margin for an Indian manufacturer, and BOM cost is a live constraint on a 5 kWh residential product competing on price.

**How.** `atopile/model/cost_estimation.py` is a clean dataclass model of JLCPCB's pricing — a good template to generalise. Parameterise the fab, add a duty and tax layer keyed on HSN, and denominate in INR with a configurable FX rate captured per build for auditability.

**Effort.** 3 weeks.

#### B4. Offline and reproducible builds

**What.** A content-addressed local cache of every part record, footprint, symbol and 3D model used by a design, committed alongside the project or stored in an internal artefact store. Builds run with no network. A build from a git tag two years later produces byte-identical outputs.

**Why.** Certification and field-failure investigation both require rebuilding an exact historical design. atopile today cannot do this: picking calls a live service that is being retired, and five outages in seven months blocked builds.

**How.** The `build/cache/parts` directory already exists as a partial cache. Formalise it: hash every external input, vendor it into the repository or an internal store, and make the network path opt-in rather than default. This is also the single change that most reduces dependence on the upstream vendor.

**Effort.** 3 weeks.

### Tier C — hardware and firmware from one source of truth

This tier is the strategic differentiator, and it is available to Xbattery in a way it is not available to atopile, JITX or anyone else, because Xbattery writes the firmware that runs on the board it designs.

#### C1. Communications interface co-generation — DBC, Modbus and firmware codecs

**What.** Declare the CAN and Modbus interface **once**, in the design, alongside the transceiver that carries it. From that single declaration generate: the `.dbc` file, the Modbus register map, the C encode and decode functions, the documentation table for the integration manual, and a set of test vectors.

**Why.** This is the highest-leverage idea in this document. The team already reverse-engineers inverter protocols — LuxPower SNA5000 and Deye SUN-3.6K — hand-writes DBC files, and hand-maintains Modbus maps. Today the CAN ID in the DBC, the `#define` in the firmware, the row in the integration manual and the transceiver on the schematic are four separate artefacts that drift. Making them one artefact eliminates an entire class of field bug, and it is exactly the kind of cross-domain consistency that a graph-based design database is good at.

**How.**

```ato
from "xforge/comms" import CANInterface, CANMessage, CANSignal, Endianness

module InverterLink:
    can = new CANInterface
    can.bitrate = 500kbps
    can.addressing = "extended"          # 29-bit, as used by the pack protocols

    pack_status = new CANMessage
    pack_status.id = 0x1801A1F0
    pack_status.cycle_time = 100ms
    pack_status.byte_order = Endianness.BIG

    soc = new CANSignal
    soc.parent = pack_status
    soc.start_bit = 0
    soc.length = 16
    soc.scale = 0.1
    soc.unit = "%"
    soc.range = 0 to 100
```

Generators are pure functions over the resolved graph, added as new build targets alongside `bom` and `pinout`:

| New build target | Output |
|---|---|
| `dbc` | A `cantools`-parseable `.dbc` |
| `modbus-map` | Register map as CSV, JSON and Markdown |
| `comms-firmware` | `can_ids.h`, pack and unpack functions, a CRC table |
| `comms-doc` | The integration-manual chapter |
| `comms-tests` | Test vectors plus a `python-can` replay script |

The team already has `cantools` and `python-can` installed on the bench machine, so the verification loop is one script away.

**Effort.** 5 weeks, and it pays back on the first inverter integration.

#### C2. Pin-mux-aware MCU allocation

**What.** Connect a peripheral interface to an MCU at the *interface* level — `mcu.can ~ transceiver.can` — and let the compiler solve the pin assignment against the MCU's alternate-function table, then emit the schematic nets, an STM32CubeMX `.ioc`, a Zephyr devicetree overlay and a `pin_mux.h`.

**Why.** Pin assignment on an STM32 with three CAN peripherals, two SPI buses and an AFE is a constraint satisfaction problem that engineers solve by hand with a spreadsheet, and get wrong. The solver in faebryk is an interval solver and not ideal for this, but the problem is small enough for a straightforward backtracking search.

**How.** Vendor pin-mux tables as data (they are published in every reference manual and are extractable from CubeMX's own database). Add a `has_pin_mux` trait carrying the alternate-function table. Solve with backtracking, seeded by user-pinned assignments and by layout hints such as "keep CAN pins on the connector side".

**Effort.** 5 weeks for one MCU family — STM32, given the team's existing CubeIDE and CubeMX toolchain and the STM32C09x work already done.

#### C3. AFE configuration co-generation

**What.** Declare the analogue front end's configuration in the design — cell count, protection thresholds, balancing parameters, ADC settings — and generate the register image, the firmware constants, and a datasheet-derived check that every threshold is inside the device's legal range and consistent with the cell's safety envelope.

**Why.** The team has already decompiled a competitor's BMS firmware and identified a BQ76952 front end. Configuring an AFE is currently a spreadsheet plus a vendor GUI plus hand-written constants. The thresholds are safety parameters and belong under the same review and version control as the schematic.

**How.** A device-description file per AFE — register map, field ranges, encoding — plus a generator producing the EEPROM or OTP image and a C header. Add a check that couples the AFE's overvoltage and undervoltage thresholds to the declared cell chemistry's safe operating window, so an LFP pack cannot be configured with NMC thresholds.

**Effort.** 4 weeks for the first device family, 1 week per additional device.

#### C4. Test-point and bring-up artefact generation

**What.** From the declared test points and the comms definition, generate the bring-up checklist, the bed-of-nails fixture netlist, the ICT coverage report, and the production test script.

**Why.** Every board Xbattery builds needs a bring-up procedure and a production test. Both are currently written by hand after the fact, and neither is checked against the design.

**How.** `TestPoint` already exists in the library and a `testpoints.json` artefact is already emitted, though it was empty in the demo build. Extend it with an accessibility check — is every net that the test plan needs actually probeable — and generate the fixture netlist from the pad coordinates in the board.

**Effort.** 3 weeks.

### Tier D — above the PCB

No tool in the market covers this layer. It is where a battery company's real product lives.

#### D1. Pack topology as a first-class object

**What.** A `BatteryPack` type parameterised by series and parallel count, cell model and chemistry, which generates the cell-tap network, the balancing resistor network, the temperature-sensor placement map, the busbar current map, and the electrical model the rest of the design solves against.

**Why.** This is the single feature that makes "one BharatBMS, four voltages" real. Today the 51.2 V, 72 V and 110 V variants are three designs; with this they are three parameter sets.

**How.**

```ato
from "xforge/pack" import BatteryPack, Cell, Chemistry

module XB5K:
    pack = new BatteryPack
    pack.series = 16
    pack.parallel = 1
    pack.cell = new Cell
    pack.cell.chemistry = Chemistry.LFP
    pack.cell.nominal_voltage = 3.2V
    pack.cell.capacity = 100Ah
    pack.cell.max_charge_current = 100A
    pack.cell.max_discharge_current = 200A
    # derived and checkable:
    #   pack.nominal_voltage = 51.2V
    #   pack.energy = 5.12kWh
    #   pack voltage window drives every insulation rule
    #   cell-tap count drives AFE selection and daisy-chain depth
```

The AFE selection then becomes a solver problem: 16 cells needs one BQ76952 or one ADBMS device; 32 needs two in a daisy chain with the isolation that implies. Thermistor count and placement come from a declared policy — for instance, one per four cells plus one on each busbar joint.

**Effort.** 6 weeks.

#### D2. Busbar and high-current interconnect as code

**What.** Busbars, bolted joints and cell interconnects modelled as conductors with a cross-section, a material, a length and a current, checked for current density and temperature rise, and exported as DXF or STEP for fabrication.

**Why.** No tool in the market does this. Busbars are a significant cost and the dominant thermal risk in a 100 A pack, and today they are drawn in mechanical CAD with no link to the electrical model.

**How.** A `Busbar` node with geometry, using the same ampacity machinery as A2. Current density against a configurable limit — industry convention is roughly 1.5–2.0 A/mm² for naturally convected copper, tightening in an enclosed box — and a bolted-joint model with contact resistance. Export geometry for the fabricator and feed the resistance back into the pack's electrical model so the solver sees the real IR drop.

**Effort.** 5 weeks.

#### D3. Harness as code, integrated with the board

**What.** Connectors, wires, crimps and labels declared in the same project as the PCB, with wire gauge derived from the current the harness carries, and outputs comprising a wiring diagram, a cut list, a crimp specification and printable labels.

**Why.** Every pack has a harness, and today it lives in a drawing that drifts from the board. Connector mating errors and undersized wires are field-failure causes.

**How.** WireViz already solves the rendering and BOM half of this, is GPL and actively maintained, and takes YAML. The integration is to emit WireViz YAML from the Xforge graph rather than to rebuild it — checking connector mating, gender and pin count against the board's connectors, and sizing wire from the propagated current of A1.

**Effort.** 4 weeks.

### Tier E — verification and certification evidence

#### E1. Hardware unit tests

**What.** A `test` block in the language that runs assertions against the fully solved design graph, executed by `xforge test` in CI.

**Why.** The community explicitly asked for this — *"I'd like to run simulation tests on modules to verify it will work as intended. Better if it run via pytest."* More importantly, it is how design rules that are specific to one product, rather than general to the domain, get captured and kept.

**How.** The check framework already exists with five stages. A `test` block is sugar for registering an anonymous check. Report in JUnit XML so any CI system consumes it.

```ato
test "pack stays inside the LFP window at full charge":
    assert pack.max_cell_voltage <= 3.65V
    assert bms.overvoltage_threshold within 3.60V to 3.75V
    assert bms.overvoltage_threshold > pack.max_cell_voltage

test "contactor drive survives coil collapse":
    assert contactor_driver.clamp_present is True
    assert contactor_driver.mosfet.vds_max >= contactor.coil_flyback_voltage * 1.5
```

**Effort.** 3 weeks.

#### E2. Automated FMEDA from the design graph

**What.** Enumerate single-point faults over the graph — every component open, every component shorted, every net open, every net shorted to an adjacent net — propagate each through the declared protection architecture, and classify the outcome as detected, latent or dangerous. Produce the diagnostic coverage figure and a first-draft FMEDA table.

**Why.** This is the most ambitious feature in the document and the most valuable. FMEDA is mandatory for ISO 26262 work and expected for UL 1973 and IEC 62619 submissions, and it is currently weeks of spreadsheet labour repeated every design change. It is exactly the kind of exhaustive, mechanical analysis a machine-readable design should enable, and no EDA vendor offers it from a design database.

**How.** Build it incrementally and honestly:

1. **Fault enumeration** over the graph is straightforward — it is a list of components and nets.
2. **Propagation** is the hard part. Full propagation requires simulation; the tractable version is *structural*: for each fault, ask whether the declared protection path still reaches its actuator. That answers "does the pack still disconnect" without simulating anything, and it catches the class of error that matters most — a single fault that disables both the primary and secondary protection paths.
3. **Classification and coverage** follow from the structural result plus per-component failure-rate data from FIDES or SN 29500.
4. **Output** is a reviewable FMEDA table with the derived SPFM, LFM and PMHF figures, clearly marked as a first draft requiring engineering review. **It must never be presented as a certified artefact produced without human judgement.**

**Effort.** 10 weeks for the structural version. Treat the simulation-backed version as a later phase.

#### E3. Certification evidence pack

**What.** A build target that produces the document set a certification body asks for: the isolation table with computed creepage and clearance per barrier, the component derating report, the BOM with supplier certificates attached, the requirement-to-test traceability matrix, the FMEDA draft, and the schematic.

**Why.** IEC 62619, UL 1973 and AIS-156 submissions are each a document assembly exercise done under time pressure. Generating the bulk of it from the design, every build, turns a multi-week scramble into a review.

**How.** A new build target composing the outputs of A2, A4, A5, E1 and E2, rendered to a single self-contained HTML plus PDF. Traceability comes from linking each requirement identifier to the assertions and tests that discharge it, with an orphan check in both directions — no requirement without a test, no test without a requirement.

**Effort.** 4 weeks once its dependencies exist.

#### E4. Semantic design diff

**What.** A reviewable diff between two revisions at the level of nets, components and parameters — "R17 changed from 10 kΩ ±1% to 4.7 kΩ ±1%; net `CELL_TAP_7` gained a connection to `TP12`; the isolation barrier's required creepage increased from 5.5 mm to 6.3 mm because the working voltage rose" — rather than a text diff of `.ato` files or a geometric diff of boards.

**Why.** Text diffs of a DSL do not tell a reviewer what changed electrically. This is the artefact that makes design review by pull request actually work, which is the whole premise of code-driven hardware.

**How.** `atopile/server/domains/diff_engine.py` already diffs PCB geometry with a match-and-classify structure. Extend the same pattern to the resolved graph, and render as HTML for attachment to a pull request.

**Effort.** 4 weeks.

### Tier F — the human interface

#### F1. Schematic generation

**What.** Generate a readable, hierarchical `.kicad_sch` from the design graph: one sheet per module, symbols placed by a force-directed or layered algorithm, orthogonal wire routing, power symbols for rails, hierarchical sheet pins for inter-module connections, and off-sheet labels for long nets.

**Why.** It is the community's single loudest complaint across two years. It is the gate on adoption by senior engineers. It is required by certification reviewers. And atopile's own community thread on the subject concluded the team would "eat layout task by task" — they have not eaten this one.

**How.** The file format problem is **already solved**: the Zig core ships a complete typed KiCad schematic model — `Symbol`, `SymbolInstance`, `SymbolPin`, `Wire`, `Junction`, `Label`, `GlobalLabel`, `Sheet`, `SheetPin`, `Property` — with a writer. What is missing is the algorithm. Build it in three stages:

1. **Stage 1 — hierarchical block diagram.** One box per module, ports for interfaces, orthogonal routing between them. Not a schematic, but immediately useful for review, and cheap. This alone answers most of the "I can't see my design" complaint.
2. **Stage 2 — flat schematic per module.** Symbols from the vendored `.kicad_sym` files that the picker already downloads, placed by a layered algorithm with power rails at the top and grounds at the bottom, nets shorter than a threshold drawn as wires and longer ones as labels.
3. **Stage 3 — conventional layout heuristics.** Signal flow left to right, feedback paths routed below, decoupling grouped near its device. This is where a schematic becomes something an engineer wants to read rather than tolerates.

**Effort.** 3 weeks for stage 1, 8 weeks for stage 2, and stage 3 is open-ended. Stage 1 is the best effort-to-value ratio in this entire document.

#### F2. Language ergonomics

**What.** Close the grammar gaps identified in §3.7 that actually bite: physical quantities in template arguments, conditional structure, import aliasing, and user-defined enums.

**Why.** `new BatteryPack<series=16, nominal_voltage=51.2V>` is the natural way to write a product family, and the grammar forbids it because template arguments are restricted to bare literals.

**How.** The grammar is a 6 KB ANTLR file and the visitor is well structured. Changing `template_arg` to accept `literal_physical` is a small, contained change. Conditionals are larger and should be resisted until there is a concrete need — a declarative language that grows an `if` tends to keep growing.

**Effort.** 4 weeks for the contained subset.

#### F3. Language-server completeness

**What.** Add document symbol, workspace symbol, semantic tokens, inlay hints for solved parameter values, and folding ranges.

**Why.** Inlay hints showing the *solved* value next to the declared constraint — `r_shunt.resistance = 100uohm +/- 1%  ⟨picked: 100 µΩ ±0.5%, 3 W⟩` — turns the editor into the primary review surface. The missing document-symbol provider means there is no outline view today, which is felt immediately on any real board.

**Effort.** 3 weeks.

### Tier G — frontier features

These are speculative by design, as the brief requested. Each is labelled with an honest assessment of whether it is currently possible.

#### G1. Bench-in-the-loop verification — *possible today*

The design declares the CAN messages it will emit (C1) and the test points it exposes (C4). CI then runs the generated test vectors against a **real board** on the PCAN and RS-485 bench that already exists on this machine, and asserts that the frames the hardware produces match the DBC the design generated. A design change that breaks the inverter protocol fails the build, on hardware, before anyone opens PCAN-View.

This is genuinely unusual — hardware-in-the-loop as a compiler check, closing the loop between the design database and the physical article. It requires a dedicated bench PC as a CI runner and about 4 weeks of work, and every piece of it already exists in the building.

#### G2. Fleet-informed derating — *possible, needs the data pipeline*

BharatBMS has remote diagnostics. Field telemetry gives measured cell imbalance, measured temperature rise at known currents, and observed failure rates by component and by batch. Feed that back as the *default* derating and thermal-budget constants in the design rules, so the next revision is designed against what the fleet actually experiences rather than against a datasheet's nominal. Over three product generations this becomes a proprietary reliability model that no EDA vendor can replicate, because the data is Xbattery's.

#### G3. Formal verification of the protection state machine — *possible, well-bounded*

The BMS protection logic is a finite state machine of modest size. Express the safety requirements in linear temporal logic — "it is always the case that a cell voltage above the threshold for longer than the debounce leads to contactor open within the fault-response time" — and model-check the firmware's state machine against the cell's declared safe operating envelope using an existing checker such as NuSMV or TLA+. The novelty is that the envelope comes from the *same* declaration that drives the AFE configuration and the hardware thresholds, so the proof is about the shipped system rather than about a separate model.

#### G4. Topology synthesis, not just parameter selection — *research*

Today you describe a topology and the solver fills in values. The next step is to describe a *requirement* — "51.2 V, 100 A continuous, 16S, IEC 62619, reinforced isolation to a 12 V CAN interface, under ₹4,500 BOM" — and have the system search a space of known-good topology fragments for a satisfying architecture. This is closer to Diode's validated-registry approach than to a solver, and the honest framing is that it is a retrieval-and-assembly problem over a curated library of Xbattery's own proven blocks, not a synthesis-from-first-principles problem. It becomes feasible only once Xbattery has a decent library of validated blocks, which is an argument for building that library deliberately from day one.

#### G5. Thermal co-simulation in the compile loop — *possible with open components, significant work*

Nothing open assembles this today, but the pieces exist: ElmerFEM for FEM heat transfer, ngspice for circuit-level electro-thermal coupling, and Antmicro's gerber2ems for geometry extraction from Gerbers. A build target that extracts copper geometry, applies the solved per-net currents as heat sources, solves the steady-state temperature field, and feeds the resulting local temperatures back into the derating checks would be the first open, code-driven electro-thermal loop in the industry. Cadence and Siemens sell exactly this and nobody gives it away.

Realistically this is a 6-month project on its own and should be scheduled only after Tiers A–C are delivering value. It is listed because it is the natural end state of taking current seriously as a first-class quantity.

### 9.1 Feature summary

| Tier | Feature | Effort (wk) | Priority | Exists anywhere in market? |
|---|---|---:|---|---|
| A1 | Current as a propagated quantity | 3 | P0 | Partially, in incumbents |
| A2 | Ampacity check, netclass and DRU generation | 4–7 | **P0** | No, not from a design language |
| A3 | Working voltage propagation | 2 | P0 | No |
| A4 | Isolation barriers as first-class objects | 5 | **P0** | No |
| A5 | Component derating rules | 3 | P0 | Partially, in incumbents |
| A6 | BMS protection-path checks | 6 | **P0** | **No — nowhere** |
| B1 | Multi-source parts service with AVL | 6 | **P0** | Yes (Altium, Siemens) |
| B2 | Lifecycle and compliance attributes | 3 | P0 | Yes (Altium) |
| B3 | India landed-cost model | 3 | P1 | No |
| B4 | Offline reproducible builds | 3 | **P0** | Partially |
| C1 | DBC / Modbus / firmware co-generation | 5 | **P0** | **No — nowhere** |
| C2 | Pin-mux-aware MCU allocation | 5 | P1 | Partially (CubeMX, standalone) |
| C3 | AFE configuration co-generation | 4 | P1 | **No — nowhere** |
| C4 | Test-point and bring-up artefacts | 3 | P1 | Partially |
| D1 | Pack topology as a first-class object | 6 | **P0** | **No — nowhere** |
| D2 | Busbar as code | 5 | P1 | **No — nowhere** |
| D3 | Harness as code, board-integrated | 4 | P2 | Partially (WireViz, disconnected) |
| E1 | Hardware unit tests | 3 | P0 | No |
| E2 | Automated FMEDA | 10 | P1 | **No — nowhere** |
| E3 | Certification evidence pack | 4 | P1 | **No — nowhere** |
| E4 | Semantic design diff | 4 | P1 | Partially (Altium) |
| F1 | Schematic generation (stage 1 / stage 2) | 3 / 8 | **P0** | Yes (everyone else) |
| F2 | Language ergonomics | 4 | P1 | — |
| F3 | Language-server completeness | 3 | P1 | — |
| G1 | Bench-in-the-loop CI | 4 | P2 | **No — nowhere** |
| G2 | Fleet-informed derating | — | P3 | **No — nowhere** |
| G3 | Formal protection-FSM verification | — | P3 | No |
| G4 | Topology synthesis | — | P3 | Emerging (Diode) |
| G5 | Thermal co-simulation | ~26 | P3 | Yes, commercial only |

Nine of these features exist nowhere in the market. Six of those nine are specific to battery systems. That is the defensible position.

---

## 10. Platform architecture

### 10.1 The build-versus-fork decision, stated plainly

| Option | Cost | Verdict |
|---|---|---|
| **Adopt atopile 0.16 as-is** | Low | **Rejected.** Designs live on a vendor server; no HV, current or isolation model; single-supplier BOM; no offline build; the local CLI is being retired. |
| **Build from scratch** | 133,637 SLOC of prior art to re-create before writing the first Xbattery-specific line | **Rejected.** The compiler, solver, graph and KiCad engine are years of work and are already MIT-licensed. |
| **Buy atopile Enterprise** | Unknown; the vendor explicitly offers "bespoke integrations, on-premise deployment, and the necessary certifications" | **Pursue in parallel.** Worth a conversation, but it does not deliver the battery-domain layer, which is where the value is. Treat it as a possible accelerator, not a plan. |
| **Fork 0.15.9 and build the domain layer** | 3 engineers, 12 months | **Recommended.** |

One legal note that should be confirmed with counsel rather than taken from this document: atopile is MIT-licensed, which permits forking, modification and private commercial use without publishing changes. The Zig core, the standard library and the compiler all carry that licence in the installed tree. Confirm that every vendored dependency in the fork is compatible — KiCad itself is GPL, but Xforge invokes `kicad-cli` as a separate process and writes its file formats, which is the same posture atopile already takes.

### 10.2 Layered architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  L6  INTERFACES                                                       │
│      VS Code extension · CLI · review web UI · CI integration        │
├──────────────────────────────────────────────────────────────────────┤
│  L5  GENERATORS                                          [XB-BUILT]  │
│      schematic · DBC/Modbus · firmware headers · AFE image           │
│      cert pack · FMEDA · harness (WireViz) · busbar DXF · BOM        │
├──────────────────────────────────────────────────────────────────────┤
│  L4  RULE ENGINE                                         [XB-BUILT]  │
│      ampacity · creepage/clearance · derating · protection paths     │
│      cell-tap topology · Kelvin sensing · precharge · watchdog       │
│      ── standards tables as versioned, cited data ──                 │
├──────────────────────────────────────────────────────────────────────┤
│  L3  DOMAIN LIBRARY                                      [XB-BUILT]  │
│      BatteryPack · Cell · IsolationBarrier · Busbar · Harness        │
│      AFE wrappers (BQ769x2, ADBMS68xx, MC3377x) · contactor          │
│      precharge · shunt · isolated CAN/RS-485 · gate driver           │
├──────────────────────────────────────────────────────────────────────┤
│  L2  SUPPLY CHAIN                                        [XB-BUILT]  │
│      parts DB (PostgreSQL) · AVL · lifecycle · landed cost (INR)     │
│      offline content-addressed cache                                 │
├──────────────────────────────────────────────────────────────────────┤
│  L1  FORKED CORE                                    [FORKED, FROZEN] │
│      ato compiler · faebryk graph · symbolic solver · trait system   │
│      KiCad Zig engine (pcb/sch/netlist/symbol) · LSP · agent runtime │
│      build-step muster · exporters                                   │
└──────────────────────────────────────────────────────────────────────┘
```

**The governing rule: changes to L1 are minimised and tracked.** Every modification to the forked core is a patch in a series, documented with its rationale, so that a future rebase onto upstream — should the public repository become current again — is tractable. Everything Xbattery-specific goes in L2 and above, using the extension points the core already provides: the trait system, the design-check registry and the build-step muster.

### 10.3 The extension points the core already gives you

This is why a fork is cheap. Four mechanisms already exist and are exactly what the domain layer needs:

| Mechanism | Where | What it buys |
|---|---|---|
| **Trait system** | `fabll.Traits` | Attach `has_working_voltage`, `has_ampacity_requirement`, `is_isolation_barrier` to any node without touching the core types |
| **Design-check registry** | `implements_design_check`, five stages from `POST_INSTANTIATION_GRAPH_CHECK` to `POST_PCB` | Every Tier A rule is a decorated method. The framework exists and is almost empty — about ten checks across the whole standard library |
| **Build-step muster** | `@muster.register(name, dependencies=[...], produces_artifact=True)` | Every Tier C and E generator is a new target. No core change |
| **Picker interface** | `libs/picker/api/api.py` | Swap the parts backend behind a stable method surface |

### 10.4 Changes required inside the forked core

Short list, and deliberately so:

1. **Fix `has_single_electric_reference`** — stop the subtree walk at domain boundaries, implement `exclude`, invert the misleading unit test. (§4.1)
2. **Emit netclasses and a `.kicad_dru`** from the KiCad transformer. (§4.2)
3. **Invert the telemetry default** to off, and remove the git-email and remote-URL properties outright. (§3.10)
4. **Make the network optional** in the picker path, with a local cache as the default resolution source. (§4.9)
5. **Re-validate trait constraints against retained picks**, so a package change forces a re-pick. (§4.7)
6. **Compute `meetsSpec`** in the variable report. (§4.6)
7. **Grammar: allow physical quantities in template arguments.** (§3.7)
8. **Add the missing LSP providers.** (§4.8)

Items 1, 3 and 6 are each a day or less. Item 2 is the highest-value core change in the list.

### 10.5 Data that must be acquired, not written

Worth separating from engineering effort, because it is procurement and it has a lead time:

| Data | Source | Note |
|---|---|---|
| IEC 60664-1:2020+AMD1, IEC 62368-1:2023 | Purchase | Creepage and clearance tables. Secondary sources disagree by up to 25%; the tables must come from the standard |
| IPC-2152 | Purchase and digitise | Chart-based, no public formula. IPC-2221 ships first as a documented-conservative interim |
| Component failure rates | FIDES or SN 29500 | Needed for FMEDA (E2) |
| MCU pin-mux tables | Extractable from vendor tools and reference manuals | Needed for C2 |
| AFE register maps | Vendor datasheets | Needed for C3 |
| Distributor catalogues | Mouser, Digi-Key, Arrow, element14 APIs | Needed for B1; all have public APIs |
| HSN codes and duty rates | CBIC | Needed for B3 |
| Laminate CTI / material group | Laminate datasheets per fab | Must be per-laminate, not a constant |

---

## 11. Phased implementation roadmap

Three engineers assumed: one compiler engineer, one hardware engineer who can code, one full-stack. Twelve months. Each phase ends with something usable, and the programme can be stopped at the end of any phase with the value delivered so far intact.

### Phase 0 — Prove the value without adopting anything (weeks 1–6)

**Goal: demonstrate the rule engine on an existing KiCad design, with no DSL, no fork and no migration.** This is the de-risking phase, and it is deliberately first.

| Week | Deliverable |
|---|---|
| 1–2 | A standalone checker that reads an existing BharatBMS `.kicad_pcb` and `.kicad_sch` and extracts nets, components and geometry. The Zig engine already parses all of these; use it as a library. |
| 3–4 | IPC-2221 ampacity check and a clearance measurement between declared HV and LV net groups, driven by a small YAML file naming the domains. Output: an HTML report listing every violation with net names and locations. |
| 5–6 | Run it against every board Xbattery has shipped. Present the findings. |

**Success criterion: the checker finds at least one real issue in a shipped board.** If it finds nothing, the physics rules are less valuable than argued here and the programme should be rescoped around Tier C instead. If it finds something, the case for Phases 1–4 is made with internal evidence rather than with this document.

**This phase costs one engineer six weeks and requires no commitment to anything.**

### Phase 1 — Fork, harden, and make it trustworthy (months 2–4)

| Deliverable | Reference |
|---|---|
| Fork 0.15.9, pin it, set up an internal build, CI and a patch series | §10.2 |
| Fix the isolated-ground merge; add regression tests | §4.1 / A4 |
| Telemetry off, git properties removed | §3.10 |
| Local parts database with an offline cache; builds run with no network | B4 |
| Multi-source AVL with lifecycle status | B1, B2 |
| Netclass and `.kicad_dru` emission from the transformer | §4.2 / A2 |
| Current propagation and the ampacity check, promoted from Phase 0 | A1, A2 |
| Hardware unit tests (`xforge test`) with JUnit output | E1 |
| **Schematic generation stage 1 — hierarchical block diagram** | F1 |
| Miscellaneous core fixes: `meetsSpec`, package re-validation, LSP providers | §10.4 |

**End state:** a fork that builds offline, sources from real distributors, checks current-carrying capacity, and produces a block diagram an engineer can review. One real board is ported to it in parallel as the proving case.

### Phase 2 — The safety compiler (months 5–7)

| Deliverable | Reference |
|---|---|
| Working voltage propagation | A3 |
| Isolation barriers, with creepage and clearance from purchased standards | A4 |
| Component derating policy enforced in the picker | A5 |
| The BMS protection-path check family | A6 |
| Semantic design diff, rendered for pull-request review | E4 |
| India landed-cost model | B3 |

**End state:** the platform can reject a design that violates Xbattery's own safety rules, and a reviewer can see exactly what changed between revisions. This is the phase that makes the tool load-bearing rather than advisory.

### Phase 3 — Hardware and firmware from one source (months 8–10)

| Deliverable | Reference |
|---|---|
| CAN/DBC, Modbus and firmware codec co-generation | C1 |
| AFE configuration co-generation for the first device family | C3 |
| Pack topology as a first-class object; generate the 51.2 V, 72 V and 110 V variants from one source | D1 |
| Test-point and bring-up artefact generation | C4 |
| **Bench-in-the-loop CI on the existing PCAN and RS-485 rig** | G1 |
| Pin-mux-aware MCU allocation (STM32) | C2 |

**End state:** the highest-leverage claim in this document is real — one declaration produces the transceiver on the board, the `.dbc`, the firmware codec, the integration-manual table and the hardware test that proves they agree.

### Phase 4 — Certification and the layer above the PCB (months 11–12+)

| Deliverable | Reference |
|---|---|
| Certification evidence pack | E3 |
| Structural FMEDA | E2 |
| Busbar as code | D2 |
| Harness as code, via WireViz | D3 |
| **Schematic generation stage 2 — full flat schematic per module** | F1 |
| Language ergonomics: physical quantities in templates | F2 |

**Deferred beyond twelve months:** thermal co-simulation (G5), formal FSM verification (G3), topology synthesis (G4), fleet-informed derating (G2 — it needs field data volume more than it needs engineering).

### 11.1 Milestones that matter

| When | Milestone | Why it is the right checkpoint |
|---|---|---|
| Week 6 | The checker finds a real defect in a shipped board | Go / no-go on the whole programme, decided with evidence |
| Month 4 | One real BharatBMS board builds end to end, offline, from source | Proves the fork is viable in production |
| Month 7 | A design that bridges an isolation barrier fails the build | Proves the safety compiler works |
| Month 10 | A protocol change propagates to board, firmware, docs and hardware test in one commit | Proves the differentiator |
| Month 12 | A certification pack is generated for a real submission | Proves the business case |

### 11.2 Sequencing rationale

Three principles drove this ordering, and each is worth stating because a reader may reasonably want a different order:

- **Trust before features.** Offline builds and a local parts database come first because a tool that stops working when a vendor's DNS breaks will not be trusted with a production design, and nothing built on top of it will matter.
- **Physics before polish.** The ampacity and isolation checks precede schematic generation stage 2 because they prevent a class of defect that costs money, while the schematic improves a workflow. Stage 1 of the schematic is pulled into Phase 1 anyway because it is cheap and it buys engineer goodwill.
- **The differentiator third, not first.** Firmware co-generation is the most valuable idea here, and it is deliberately scheduled after the platform is trusted and safe. Building it first would produce an impressive demo on a foundation nobody relies on.

---

## 12. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **The fork becomes an orphan** — upstream diverges permanently and the fork accumulates unmaintained code | High | Medium | Accept it explicitly. 134k SLOC is maintainable by one engineer at steady state given it is frozen, not evolving. Keep L1 changes to a documented patch series. Budget one engineer-month a year for KiCad file-format tracking. |
| **Standards numbers are wrong** — a hard gate built on a secondary source blocks a valid design or, worse, passes an invalid one | **High if unmitigated** | **High** | Buy the standards. Encode every constant with a citation to table, row and column. Until then, run the rules in **advisory mode only** — report, never block. This is a firm recommendation, not a suggestion. |
| **Team rejects the DSL** | Medium | High | Phase 0 requires no DSL at all. Phase 1's block diagram gives immediate visible payback. Port one board, not all of them. If after Phase 1 the team is not using it, stop — the Phase 0 checker still has standalone value. |
| **KiCad version drift** — atopile 0.15.9 already cannot read KiCad 10 boards | **Certain** | Medium | Pin KiCad 9 for now, as this machine already does. Budget the file-format update as recurring maintenance; the Zig models are typed and the change is mechanical. |
| **Three engineers is optimistic** | Medium | Medium | The phases are independently valuable and independently stoppable. Phase 0 plus Phase 1 is one engineer for four months and delivers most of the safety value. |
| **atopile's licence or availability changes** | Low (MIT is irrevocable for the code already obtained) | Low | Archive the 0.15.9 source and every dependency wheel to internal storage now, this week. The public repository is already stale, and the last usable public state is the one installed on this machine. |
| **FMEDA output is treated as certified** | Medium | **High** | Hard-label every generated FMEDA as a draft requiring engineering review, in the artefact itself, not only in documentation. Never let it be submitted without a signed review. |
| **Key-person dependency on the compiler engineer** | Medium | High | Require a design note per L1 patch. Pair on the solver work. The domain layer in L2–L5 is ordinary Python and is broadly maintainable. |
| **Unsigned binaries blocked by Windows code-integrity policy** — happened to atopile itself on 27 Sep 2026 | Certain; already occurred once | Low if anticipated, high if it stops a release | Ship Xforge's interpreter and any compiled extension from a signed source, and pin the interpreter explicitly rather than letting the installer choose. Resolved instance in §14.3. |

---

## 13. Xbattery design-system integration

The design system has not yet been provided. This section states precisely what is needed and how it will be applied, so that integration is a mechanical step when the assets arrive.

### 13.1 Surfaces that will carry the design system

| Surface | Technology | What the design system governs |
|---|---|---|
| Review web UI | React or plain HTML, served locally | Colour, type, spacing, components, iconography, dark mode |
| Generated HTML reports — cert pack, FMEDA, ampacity, isolation, diff | Self-contained HTML with inline CSS | Same tokens, print stylesheet, letterhead and document furniture |
| VS Code extension panels | Webview | Must reconcile Xbattery tokens with VS Code's theme variables |
| Schematic output | KiCad `.kicad_sch` | Title block, sheet borders, revision table, approval block, logo |
| PCB silkscreen and fab drawings | KiCad | Logo placement, designator conventions, revision marking |
| CLI | ANSI terminal | Accent colour, status glyphs, log-level colouring |
| PDF deliverables | Rendered from HTML | Cover page, headers and footers, document control block |

### 13.2 What is needed from Xbattery

1. **Tokens** — colour ramps including semantic colours for pass, warn, fail and info; a type scale with families and weights; a spacing scale; radii; elevation. Ideally as JSON or CSS custom properties; a Figma file is workable.
2. **Logo assets** — SVG for the web, monochrome line art for silkscreen, and a variant that survives 1:1 at fab resolution.
3. **Document templates** — the approved title block, revision table, approval block and document-numbering scheme, since these appear on every generated schematic and certification document.
4. **Voice and terminology** — the house terms for pack, module, string, BMU, BMS and slave, so generated documentation matches the rest of Xbattery's output.
5. **Accessibility target** — whether WCAG AA contrast is required; it affects the semantic colour ramp.

### 13.3 How it will be applied

- A single **token source of truth** in the repository as JSON, from which CSS custom properties, a Python constants module for report generation, and KiCad title-block templates are all generated. One place to change, every surface follows.
- **Dark mode from the start**, defined as a token override rather than a second stylesheet. Engineers work in dark editors.
- **Self-contained output.** Every generated report embeds its CSS and images, so it opens identically on any machine and can be attached to an email or a certification submission without a dependency. This matches the delivery convention already used for Xbattery hardware documentation.
- **Print fidelity.** Certification documents are printed and bound. Page breaks, table repetition across pages and margin rules get explicit attention rather than being left to the browser.

Until the assets arrive, all generated surfaces will use a neutral token set with the same variable names, so the switch is a token-file replacement and not a rewrite.

---

## 14. Appendices

### 14.1 Where everything lives on this machine

| Item | Path |
|---|---|
| atopile tool environment | `%APPDATA%\uv\tools\atopile` |
| atopile source | `%APPDATA%\uv\tools\atopile\Lib\site-packages\atopile` |
| faebryk source | `%APPDATA%\uv\tools\atopile\Lib\site-packages\faebryk` |
| Zig KiCad model stubs | `…\faebryk\core\zig\gen\sexp\*.pyi` |
| Demo project and build artefacts | `C:\Users\TempAdmin\atopile-demo\my_first_ato_project` |
| Auth session | `%LOCALAPPDATA%\atopile\atopile\clerk_oauth_session.json` |
| Telemetry config | `~/.config/atopile/telemetry.yaml` |
| Autolayout job store | `~/.atopile/autolayout/jobs.json` |
| KiCad 9 (the version to use) | `%LOCALAPPDATA%\Programs\KiCad\9.0` |

### 14.2 Useful commands

```bash
# Version and config
ato --version
ato export-config-schema --pretty      # full ato.yaml JSON schema
ato dump-config --format json          # the resolved project config

# Build
ato --non-interactive build -v         # plain log lines, no live display
ato build -t all -v                    # every artefact including gerbers and STEP
ato build --frozen                     # CI: fail rather than re-resolve
ato build --no-keep-picked-parts       # force a re-pick (needed after a package change)

# Turn off telemetry
setx ATO_TELEMETRY n
# or write  telemetry: false  into ~/.config/atopile/telemetry.yaml

# Solver diagnostics
setx ATO_STIMEOUT 600                  # default is 150 s
```

### 14.3 Environment issue encountered and resolved

On 27 September the toolchain on this machine stopped working: `ato` failed with `uv trampoline failed to spawn Python child process (os error 4551)`. It had worked on 25 September.

**Diagnosis.** CodeIntegrity event 3077 named exactly one blocked file — `%APPDATA%\uv\tools\atopile\Scripts\python.exe` — under the policy `VerifiedAndReputableDesktop`, which is **Smart App Control**. Windows had promoted Smart App Control from evaluation to enforcement in the intervening two days. The interpreter uv installs is an `astral-sh/python-build-standalone` build and is unsigned, so enforcement blocked it. The machine is neither Azure AD nor domain joined, so no management policy was involved.

**The insight that avoided a bad fix.** The obvious remedy is to turn Smart App Control off, but that is irreversible without reinstalling Windows and is a system-wide security downgrade. Testing showed it was unnecessary: unsigned `.pyd` extension modules load without complaint under the PSF-signed system Python, so **Smart App Control gates the executable, not the DLLs it loads.** A signed interpreter is therefore sufficient.

**Resolution.**

1. Installed official python.org **3.14.7** — Authenticode-signed by the Python Software Foundation, signature verified before execution — per-user with `/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0`, so nothing on `PATH` changed.
2. Removed `%APPDATA%\uv\tools\atopile` (uv probes the existing interpreter before reinstalling, so it cannot repair a blocked environment in place), then reinstalled with `uv tool install --force --python "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" atopile`.
3. Restored the `zz_atopile_file_session.pth` keyring workaround. The stored sign-in survived, as it lives outside the tool environment.

**Outcome.** `ato build -t all -v` completes in about 15 seconds and produces every artefact including gerbers, STEP and GLB. Smart App Control remains **enabled**, and no further CodeIntegrity blocks are logged.

Two notes for the future. First, any reinstall must pass `--python` pointing at the signed interpreter, or uv will select its own unsigned build and the block returns. Second, the AVX-512 workaround previously needed on this machine — a `pyzig` rebuild with `-Dcpu=baseline` for issue #1838 — is no longer required under this interpreter; the stock wheels run correctly. The rebuilt binaries are retained at `atopile-demo\tools\pyzig-baseline-backup` in case a heavier design reintroduces the fault.

### 14.4 Verification log

Claims in this document that were checked by direct observation rather than by reading documentation:

| Claim | How verified |
|---|---|
| 133,637 SLOC across 428 files | Walked the installed tree and counted non-comment, non-blank lines |
| Only R, L and C are parametrically pickable | Read the `Endpoint` enum in `Pickable.py` |
| LCSC is the only supplier | Read the `Supplier` enum in `Pickable.py` |
| No netclasses or DRC rules in output | Parsed the demo's `.kicad_pcb` and `.kicad_pro` |
| Power-tree and data-interface exporters emit empty files | Read the artefacts from a real build |
| `meetsSpec` is always null | Read `default.variables.ato.json` |
| Package constraint ignored on a retained pick | Compared the declared `C0603` against the picked through-hole TDK part in the BOM |
| Isolated grounds merged; `exclude` ignored | Read `has_single_electric_reference.py` in full, including its unit tests; grepped for callers |
| No thermal, ampacity or creepage concept | Grepped the whole tree for fifteen related terms |
| Zig core contains a KiCad schematic writer | Read `gen/sexp/schematic.pyi` and the Zig README |
| Pragmas are retired in 0.15.9 | Read `_RetiredExperiment` in `ast_visitor.py` |
| Telemetry on by default, collects git email | Read `telemetry/config.py` and `telemetry/properties.py` |
| Release timeline | Fetched and parsed the PyPI JSON API — 171 releases |
| The 0.16 pivot and its wording | Rendered the vendor's blog post headlessly and read it verbatim |
| Smart App Control is blocking the toolchain | Queried `Win32_DeviceGuard` and the CI policy registry key |

### 14.5 Sources

**Primary — atopile**
- Repository: https://github.com/atopile/atopile
- 0.16 announcement: https://atopile.io/blog/atopile-v16
- PyPI: https://pypi.org/pypi/atopile/json
- Packages monorepo: https://github.com/atopile/packages
- VS Code extension: https://marketplace.visualstudio.com/items?itemName=atopile.atopile
- Auto-layout discussion (#881): https://github.com/atopile/atopile/discussions/881
- Isolation-barrier bug (#1812): https://github.com/atopile/atopile/issues/1812
- AVX-512 wheel crash (#1838): https://github.com/atopile/atopile/issues/1838
- KiCad 10 incompatibility (#1822): https://github.com/atopile/atopile/issues/1822
- Multi-supplier request (#1271): https://github.com/atopile/atopile/issues/1271
- Offline builds (#201): https://github.com/atopile/atopile/issues/201

**Community**
- Show HN, Feb 2024: https://news.ycombinator.com/item?id=39263854
- HN, Jul 2025: https://news.ycombinator.com/item?id=44548449
- HN on the 2026 pivot: https://news.ycombinator.com/item?id=49700663
- Hackaday, Feb 2024: https://hackaday.com/2024/02/06/atopile-wants-you-to-code-schematics/
- Independent critique: http://pomogaev.ca/yc_critic/
- Altium OnTrack founder interview: https://podcast.altium.com/e/code-based-pcb-design-with-ai-inside-atopile/

**Competitors**
- JITX: https://www.jitx.com/ · https://blog.jitx.com/jitx-corporate-blog/whats-new-in-jitx-2025
- tscircuit: https://tscircuit.com/
- Zener / Diode: https://zener.diode.computer/ · https://github.com/diodeinc/pcb
- Flux: https://www.flux.ai/
- Quilter: https://www.quilter.ai/pricing
- DeepPCB: https://deeppcb.ai/pricing/
- Celus: https://www.celus.io/
- WireViz: https://github.com/wireviz
- KiCad: https://www.kicad.org/

**Standards and domain — all secondary; verify against the standards before use**
- IPC-2221 vs IPC-2152: https://tracewidthcalculator.com/blog/ipc-2221-vs-ipc-2152-pcb-standards · https://blog.ansi.org/ansi/ipc-2152-current-carrying-capacity-in-pcbs/
- Creepage and clearance: https://www.protoexpress.com/blog/importance-pcb-line-spacing-creepage-clearance/ · https://www.batterydesign.net/creepage-and-clearance-calculator/ · https://www.powerelectronictips.com/faq-on-creepage-and-clearance-part-2/
- Pollution degree: https://www.ni.com/en/support/documentation/supplemental/22/pollution-degree-rating-for-electrical-equipment.html
- Conformal coating and insulation: https://lorit-consultancy.com/en/2024/04/iec-60664-the-fountain-of-knowledge/
- Kelvin sensing: https://www.analog.com/en/resources/analog-dialogue/articles/optimize-high-current-sensing-accuracy.html
- Precharge sizing: https://www.batterydesign.net/pre-charge-resistor/
- Cell-tap protection: https://www.orionbms.com/manuals/pdf/orionbms2_wiring_manual.pdf

**Xbattery**
- https://xbattery.energy/
- https://www.pv-magazine-india.com/2026/02/25/xbattery-launches-5-kwh-scalable-energy-storage-system-for-residential-small-office-use/
- https://www.saurenergy.com/solar-energy-news/xbattery-secures-23m-seed-funding-to-build-high-voltage-bms-for-evs-and-bess-10500271

---

*Done by Harsh Thakur · 27 September 2026*
