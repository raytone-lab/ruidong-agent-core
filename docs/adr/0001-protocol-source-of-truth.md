# ADR 0001: Protocol Source of Truth

## Status

Accepted.

## Context

The repository already has useful contract assets:

- Python dataclasses and ports in `rd-agent-contracts`;
- event payload docs in `docs/EVENT-PAYLOAD-SCHEMA.md`;
- adapter standard events in `rd-llm-adapter`;
- replayable golden traces in `traces/golden`;
- executable conformance checks in `rd-agent-core`.

The gap is that these assets do not by themselves provide a language-neutral
wire contract for non-Python consumers or generated bindings.

## Decision

Use a layered contract model:

1. `proto/ruidong/agent/v1/` is the language-neutral wire data contract.
2. `rd-agent-contracts` remains the Python SDK contract package and owns host
   behavior ports.
3. `rd-agent-core.conformance`, reference host tests, and golden trace checks
   verify behavior that cannot be expressed fully in protobuf.
4. `tools/scripts/verify_governance.py` checks that protocol docs, proto event
   names, Python event enums, and package versions stay aligned.

## Consequences

- Event and data shape changes must update both Python contract code and proto
  files until code generation becomes the implementation path.
- Host behavior contracts remain Python Protocols and conformance checks.
- Multi-language consumers can pin proto files by repository tag.
- The repository can later split `proto/` into a dedicated protocol repository
  without changing the runtime package boundaries first.

