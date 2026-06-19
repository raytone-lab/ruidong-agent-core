# Protocol Contract

## Purpose

This document defines how protocol truth is managed for the Agent Runtime. It
bridges three layers:

1. **Wire data contract**: files under `proto/ruidong/agent/v1/`.
2. **Protocol SDK**: generated Python protobuf bindings and converters in
   `rd-agent-proto`.
3. **Python contract SDK**: dataclasses and ports in `rd-agent-contracts`.
4. **Behavior contract**: conformance checks, golden traces, and reference host
   tests.

The current Python schema version is `SCHEMA_VERSION = "1.2.0"`.

## What Belongs in Proto

The proto files define stable, language-neutral data shapes:

- `AgentEvent` envelope;
- core event type names;
- transcript content blocks;
- tool definitions, tool execution requests, and tool execution results;
- usage;
- run lifecycle summaries;
- trace identity.

Proto files do not define database tables, queue transactions, permission
models, product UI projections, or provider credentials.

Files:

- `proto/README.md`
- `proto/ruidong/agent/v1/events.proto`
- `proto/ruidong/agent/v1/transcript.proto`
- `proto/ruidong/agent/v1/runtime.proto`
- `buf.yaml`
- `buf.gen.yaml`

Generated Python bindings live under `packages/rd-agent-proto/src/ruidong`.
Converters between Python dataclasses and protobuf messages live in
`packages/rd-agent-proto/src/rd_agent_proto/converters.py`.

## What Stays in Python Contracts

Python contracts keep ergonomic SDK types and behavior protocols:

- `EventLogPort`
- `RunPersistencePort`
- `ToolExecutorPort`
- `ContinuationQueuePort`
- `SubagentTaskPort`
- `SubagentRunPort`
- `TimelineReadPort`
- `SubagentWorkspacePort`

These are host behavior contracts. They are verified by conformance checks and
reference implementations instead of protobuf alone.

Evidence:

- `packages/rd-agent-contracts/src/rd_agent_contracts/event_log.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/run_persistence.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/tool_execution.py`
- `packages/rd-agent-contracts/src/rd_agent_contracts/continuation_queue.py`
- `packages/rd-agent-core/src/rd_agent_core/conformance.py`
- `examples/reference_host/sqlite_reference_host.py`

## Event Types

The canonical runtime event strings are defined by
`rd_agent_core.events.CoreEventType` and mirrored by
`proto/ruidong/agent/v1/events.proto`.

Current event strings:

- `turn_started`
- `text_delta`
- `reasoning_delta`
- `tool_call_started`
- `tool_call_delta`
- `tool_call_completed`
- `tool_call_invalid`
- `usage_update`
- `tool_started`
- `tool_completed`
- `tool_failed`
- `turn_paused`
- `turn_completed`

Adding an event requires all of the following:

1. Add the enum value to `CoreEventType`.
2. Add or update payload documentation in `docs/EVENT-PAYLOAD-SCHEMA.md`.
3. Mirror the enum in `proto/ruidong/agent/v1/events.proto`.
4. Add runtime tests for event production.
5. Run `uv run python tools/scripts/verify_governance.py`.

## Standard Adapter Events

Provider adapters normalize raw provider chunks into these standard events:

- `TextDelta`
- `ReasoningDelta`
- `ToolCallStart`
- `ToolCallIdDelta`
- `ToolCallNameDelta`
- `ToolCallArgsDelta`
- `ToolCallEnd`
- `UsageUpdate`
- `TurnDone`

Evidence:

- `packages/rd-llm-adapter/src/rd_llm_adapter/events.py`
- `packages/rd-agent-core/src/rd_agent_core/turn.py`

## Compatibility Rules

- Event payloads may add fields when old consumers can ignore them.
- Existing fields should not be removed or change meaning without a schema
  version decision and migration note.
- Hosts must tolerate unknown event payload fields.
- `event_type` remains the primary dispatch field for UI, billing, audit, and
  replay.
- Provider-specific raw chunks must stay below `rd-llm-adapter`.
- Generated multi-language bindings should pin a release tag or proto package
  version.

## Verification

Protocol documentation is verified by:

```bash
uv run python tools/scripts/verify_governance.py
```

That script checks:

- every `CoreEventType` value appears in `docs/PROTOCOL-CONTRACT.md`;
- every event enum appears in `proto/ruidong/agent/v1/events.proto`;
- standard adapter event classes are documented;
- checked-in generated Python protobuf bindings match the current proto files;
- protocol examples and golden traces roundtrip through protobuf serialization;
- required protocol and governance files exist;
- markdown links in repository documentation resolve to existing files.
