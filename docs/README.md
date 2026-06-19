# Documentation Index

This directory is the public product, architecture, protocol, and release
documentation for `ruidong-agent-core`. Every normative document in this index
is either verified by tests or backed by source files listed in its evidence
section.

## Product and Architecture

- [PRODUCT-DESIGN.md](PRODUCT-DESIGN.md): product positioning, personas,
  product surfaces, non-goals, and acceptance criteria.
- [ARCHITECTURE.md](ARCHITECTURE.md): package boundaries, dependency direction,
  runtime data flow, and evidence links into code.
- [SDK-OVERVIEW.md](SDK-OVERVIEW.md): SDK capability overview and integration
  routes.
- [agent-core-abstraction.md](agent-core-abstraction.md): historical core
  abstraction boundary and SaaS integration notes.

## Protocol and Contracts

- [PROTOCOL-CONTRACT.md](PROTOCOL-CONTRACT.md): machine-readable and
  behavior-contract strategy, schema versions, proto files, and verification.
- [PROTO-RELEASE.md](PROTO-RELEASE.md): `rd-agent-proto` package shape,
  generation, build, and release process.
- [MULTILANGUAGE-CONSUMPTION.md](MULTILANGUAGE-CONSUMPTION.md): current and
  planned Go/TypeScript/Python consumption paths.
- [EVENT-PAYLOAD-SCHEMA.md](EVENT-PAYLOAD-SCHEMA.md): core event payload
  schema for the current `AgentEvent` stream.
- [HOST-INTEGRATION-CONTRACT.md](HOST-INTEGRATION-CONTRACT.md): host/runtime
  responsibility split and minimum integration order.
- [API-REFERENCE.md](API-REFERENCE.md): public Python API reference.
- [API-STABILITY.md](API-STABILITY.md): compatibility and deprecation policy.

## Operations

- [QUICKSTART.md](QUICKSTART.md): installation, harness smoke, host integration
  sequence, and release validation.
- [REPOSITORY-GOVERNANCE.md](REPOSITORY-GOVERNANCE.md): ownership, release
  gates, branch hygiene, documentation rules, and verification policy.
- [GLOSSARY.md](GLOSSARY.md): shared runtime, protocol, host, adapter, and
  replay terminology.
- [releases/README.md](releases/README.md): versioned release notes.

## ADRs

- [adr/0001-protocol-source-of-truth.md](adr/0001-protocol-source-of-truth.md):
  decision record for the protocol source-of-truth model.

## Historical Audits

- [AUDIT-phase-b-2026-05-29.md](AUDIT-phase-b-2026-05-29.md)
- [AUDIT-round3-2026-06-01.md](AUDIT-round3-2026-06-01.md)
- [REVIEW-p1-fix-2026-05-30.md](REVIEW-p1-fix-2026-05-30.md)
- [MODEL-ADAPTER.md](MODEL-ADAPTER.md)
