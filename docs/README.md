# Documentation

| Document | What it is |
|---|---|
| [`platform-study/atopile-analysis.md`](platform-study/atopile-analysis.md) | The study that led to this repo. Reverse-engineering of atopile 0.15.9, feature-gap analysis against Xbattery's needs, competitive landscape, and the build plan. 14 sections. |
| [`standards.md`](standards.md) | Where every constant in the rule engine comes from, evidence tiers, and which rules are allowed to gate a build. **Read this before adding a numeric rule.** |
| [`BJB-RevC-findings.md`](BJB-RevC-findings.md) | First real run against a live design. Root cause of the 13 errors on BJB RevC. |
| [`comms.md`](comms.md) | `xforge.comms`: one YAML spec generates the DBC, the register map and the firmware pack/unpack code, so they can't drift apart. Spec format, a worked example, and what the CLI wiring should look like. |

## Why this repo exists

The short version, from the platform study:

> atopile is a genuinely good idea executed to about 60% of what Xbattery needs,
> and as of August 2026 its owners moved the product to a closed, browser-hosted,
> cloud-only environment and soft-deprecated the locally installable version.
> Everything Xbattery actually needs on top of it — the high-voltage,
> high-current, isolation, functional-safety, multi-source supply-chain and
> firmware co-generation layer — does not exist in atopile, and does not exist in
> any competitor either.

The original plan was a twelve-month, three-engineer programme built on a fork of
atopile's MIT-licensed core. That was replanned to **eight weeks, two people**,
and the fork was deferred. The reasoning: a fork's value is in *authoring*
designs, and the designs already exist. The bottleneck is *verification*. So the
verification layer got built first — as standalone tools that read the files the
team already produces.

Those tools are layers L4 and L5 of the architecture in §10 of the study, so
nothing here is wasted if the fork happens later.

## Rendering the study

The markdown is the source. To produce the single-file HTML (images embedded,
opens identically anywhere):

```bash
cd docs/platform-study
pip install markdown
python _tools/render_doc.py
```

Output is `XbatteryEDAPlatform.html`, which is gitignored — regenerate it rather
than committing a build artifact.
