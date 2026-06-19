# Agent Instructions

Use this file when an automated coding agent works in this repository.

## Repository Shape

- `packages/rd-agent-contracts` owns public data contracts, host ports, ids,
  usage, event envelope, run persistence, continuation, subagent, workspace,
  and trace types.
- `packages/rd-agent-proto` owns generated Python protobuf bindings and
  conversion helpers for the checked-in `proto/ruidong/agent/v1` files.
- `packages/rd-llm-adapter` owns provider request builders, stream parser
  sessions, transports, fixture replay, and adapter registries.
- `packages/rd-agent-core` owns the host-neutral turn/run kernels, runner
  facades, tool policy, model profiles, continuation/subagent runners,
  conformance helpers, and testing harness.
- `packages/rd-llm-gateway` is a Phase A historical package. Do not use it as
  the recommended runtime boundary for new integrations.
- `examples/reference_host` is executable documentation for host ports. Its
  SQLite schema is not a stable product schema.

## Non-Negotiable Boundaries

- Do not import SaaS application modules, ORMs, web frameworks, Redis, S3, UI
  models, or billing systems into `rd-agent-core`.
- Do not execute invalid or partial tool calls. Only complete tool calls may
  reach `ToolExecutorPort`.
- Keep raw provider chunks below `rd-llm-adapter`; core consumes standard
  events only.
- Treat `AgentEvent` plus its per-run `seq` as the event-log truth for replay,
  UI projection, audit, and billing.

## Verification

Run the local gate before handing off substantial changes:

```bash
uv run python tools/scripts/release_gate.py --no-coverage
```

Run the full release gate before a release:

```bash
uv run python tools/scripts/release_gate.py
```

If you change public docs, protocol files, event types, package versions, or
governance files, also run:

```bash
uv run python tools/scripts/verify_governance.py
uv run python tools/scripts/verify_protocol.py
```
