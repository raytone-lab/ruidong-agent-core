# Multi-Language Consumption

## Current State

The repository is prepared for multi-language consumption through protobuf, but
only Python bindings are generated and tested in this repository today.

Current supported path:

- Python runtime: `rd-agent-contracts`, `rd-agent-proto`, `rd-agent-core`.
- Language-neutral contract: `proto/ruidong/agent/v1/*.proto`.
- Go package option: `github.com/shinelee211-arch/ruidong-agent-core/gen/go/ruidong/agent/v1;agentv1`.
- Generation config: `buf.gen.yaml`.

## Consumer Contract

Consumers should pin a release tag, not an arbitrary branch:

```text
rd-agent-proto-v0.1.0
```

A consumer must treat these as stable inputs:

- `AgentEvent` envelope;
- event type strings;
- transcript blocks;
- usage;
- tool definitions and execution result shapes;
- trace context.

Behavioral contracts such as event idempotency, run lifecycle transitions, and
tool execution policy remain host/SDK behavior and are verified through
conformance tests rather than protobuf alone.

## Planned Binding Targets

The checked-in Buf generation config can be extended for Go and TypeScript when
real consumers appear. Do not split a dedicated `ruidong-agent-proto` repository
until at least two external consumers need pinned Go/TypeScript/Python bindings.

Recommended future generated paths:

```text
gen/go/ruidong/agent/v1
gen/ts/ruidong/agent/v1
packages/rd-agent-proto/src/ruidong/agent/v1
```

## Verification

Current repository verification:

```bash
uv run python tools/scripts/verify_protocol.py
uv run python tools/scripts/release_gate.py
```

External consumers should add their own generated-code compilation or import
smoke tests after adopting the proto files.
