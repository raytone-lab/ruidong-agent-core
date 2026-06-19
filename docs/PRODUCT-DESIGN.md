# Product Design

## Product Thesis

`ruidong-agent-core` is an Agent Runtime SDK and protocol workspace. Its product
job is to let a host application run agent workflows without inheriting
CodeSphere-specific database models, UI assumptions, provider chunk formats, or
tool execution rules.

The product is not a complete SaaS. It is the reusable runtime layer under a
SaaS, CLI, desktop host, worker, or future hosted PaaS.

## Users

| User | Job to be done | Product surface |
| --- | --- | --- |
| Host engineer | Embed a bounded, testable agent loop into a product | `rd-agent-core`, `rd_agent_core.testing`, `examples/reference_host` |
| Platform engineer | Standardize events, lifecycle, continuation, and replay | `rd-agent-contracts`, `rd-agent-proto`, `rd-replay-evals`, protocol docs |
| Model integration engineer | Add or validate provider stream protocols | `rd-llm-adapter`, fixture validator, adapter registry |
| Product maintainer | Release SDK packages with confidence | release gate, release notes, governance docs |

## Product Surfaces

### Runtime SDK

The runtime SDK is centered on:

- `RunKernel` and `TurnKernel` for deterministic run/turn control flow;
- `AgentRunner`, `ContinuationRunner`, and `SubagentRunner` for lifecycle glue;
- `CoreToolPolicy` and `ToolSafetyPolicy` for tool execution boundaries;
- `ModelProfile` and `ProviderLock` for model/protocol compatibility.

Evidence:

- `packages/rd-agent-core/src/rd_agent_core/run.py`
- `packages/rd-agent-core/src/rd_agent_core/turn.py`
- `packages/rd-agent-core/src/rd_agent_core/runner.py`
- `packages/rd-agent-core/src/rd_agent_core/continuation_runner.py`
- `packages/rd-agent-core/src/rd_agent_core/subagent_runner.py`
- `packages/rd-agent-core/src/rd_agent_core/model_profile.py`

### Contract SDK

The contract SDK gives hosts a shared vocabulary for event logs, run
persistence, tools, usage, continuation, subagent tasks, workspace isolation,
and trace identity.

Evidence:

- `packages/rd-agent-contracts/src/rd_agent_contracts/events.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/event_log.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/run_persistence.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/tool_execution.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/continuation_queue.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/subagent.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/workspace.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/trace.py`

### Protocol SDK

The protocol SDK publishes the language-neutral wire contract and generated
Python protobuf bindings without changing runtime behavior.

Evidence:

- `proto/ruidong/agent/v1/events.proto`
- `proto/ruidong/agent/v1/transcript.proto`
- `proto/ruidong/agent/v1/runtime.proto`
- `packages/rd-agent-proto/src/rd_agent_proto/converters.py`
- `packages/rd-agent-proto/tests/test_protocol_roundtrip.py`

### Provider Adapter SDK

The adapter layer turns provider-specific streaming protocols into standard
runtime events. Core must not parse raw provider chunks.

Evidence:

- `packages/rd-llm-adapter/src/rd_llm_adapter/events.py`
- `packages/rd-llm-adapter/src/rd_llm_adapter/openai_compat.py`
- `packages/rd-llm-adapter/src/rd_llm_adapter/anthropic_native.py`
- `packages/rd-llm-adapter/src/rd_llm_adapter/registry.py`
- `packages/rd-llm-adapter/scripts/validate_model_adapter_fixtures.py`

### Test and Certification Surface

Host teams should be able to prove integration correctness without a real
provider, production database, or production queue.

Evidence:

- `packages/rd-agent-core/src/rd_agent_core/testing.py`
- `packages/rd-agent-core/src/rd_agent_core/conformance.py`
- `examples/reference_host/sqlite_reference_host.py`
- `examples/reference_host/tests/test_sqlite_reference_host.py`

## Non-Goals

- No user, tenant, or product permission model in core.
- No SaaS ORM, FastAPI, Redis, S3, billing, UI projection, or artifact pipeline
  in runtime packages.
- No provider API key management or production routing inside core.
- No guarantee that example SQLite tables are stable product schemas.
- No direct execution of partial or invalid tool calls.

## Product Quality Bar

The repository is acceptable only when these are true:

- Public package boundaries are documented in [ARCHITECTURE.md](ARCHITECTURE.md).
- Protocol and event contracts are documented in
  [PROTOCOL-CONTRACT.md](PROTOCOL-CONTRACT.md) and
  [EVENT-PAYLOAD-SCHEMA.md](EVENT-PAYLOAD-SCHEMA.md).
- Host integration has an executable reference implementation.
- Release gates verify lint, tests, documentation governance, golden traces,
  typing markers, reference host examples, and syntax compilation.
- Versioned release notes exist for released SDK packages.

## Current Product State

The current recommended integration path is:

1. Implement the host ports from `rd-agent-contracts`.
2. Use `rd-llm-adapter` to normalize provider streams.
3. Use `rd-agent-core` as the host-neutral runtime.
4. Use `rd_agent_core.testing` and `rd_agent_core.conformance` to certify the
   host integration.

The Phase A `rd-llm-gateway` package remains in the workspace for compatibility
and release coverage, but it is not the recommended boundary for new runtime
integrations.
