# Glossary

This glossary defines the terms used across product, architecture, protocol,
runtime, and host-integration documents. Each term points to code or executable
documentation that makes the term concrete.

| Term | Meaning | Evidence |
| --- | --- | --- |
| Agent Runtime SDK | The reusable runtime layer that hosts embed to run bounded agent workflows | `packages/rd-agent-core/src/rd_agent_core/` |
| Host | The product application that owns users, tenants, persistence, queues, permissions, tools, UI projection, billing, and artifacts | `docs/HOST-INTEGRATION-CONTRACT.md` |
| Contract SDK | The Python contract package containing data models and host ports | `packages/rd-agent-contracts/src/rd_agent_contracts/` |
| Protocol SDK | The protobuf distribution package containing generated Python bindings and converters | `packages/rd-agent-proto/src/rd_agent_proto/` |
| Port | A host-implemented Protocol boundary such as `EventLogPort`, `RunPersistencePort`, or `ToolExecutorPort` | `packages/rd-agent-contracts/src/rd_agent_contracts/event_log.py`, `packages/rd-agent-contracts/src/rd_agent_contracts/run_persistence.py` |
| AgentEvent | The append-only event-log envelope used for replay, UI projection, audit, and billing | `packages/rd-agent-contracts/src/rd_agent_contracts/events.py` |
| EventLogPort | The append-only event-log behavior contract with per-run sequence and idempotency semantics | `packages/rd-agent-contracts/src/rd_agent_contracts/event_log.py` |
| Turn | One model interaction plus optional tool execution inside a run | `packages/rd-agent-core/src/rd_agent_core/turn.py` |
| Run | A bounded multi-turn execution slice with lifecycle state and stop reason | `packages/rd-agent-core/src/rd_agent_core/run.py`, `packages/rd-agent-contracts/src/rd_agent_contracts/run_persistence.py` |
| Continuation | A follow-up run created when a bounded run needs to resume from persisted engine state | `packages/rd-agent-core/src/rd_agent_core/continuation_runner.py`, `packages/rd-agent-contracts/src/rd_agent_contracts/continuation_queue.py` |
| Subagent | A delegated agent task with its own profile, run record, workspace policy, and outcome | `packages/rd-agent-core/src/rd_agent_core/subagent_runner.py`, `packages/rd-agent-contracts/src/rd_agent_contracts/subagent.py` |
| Adapter | Provider-facing code that converts raw provider protocols into standard runtime events | `packages/rd-llm-adapter/src/rd_llm_adapter/` |
| StandardEvent | Provider-neutral stream events consumed by core | `packages/rd-llm-adapter/src/rd_llm_adapter/events.py` |
| ModelProfile | Runtime description of model capabilities and protocol limits | `packages/rd-agent-core/src/rd_agent_core/model_profile.py` |
| ProviderLock | Compatibility guard for keeping a transcript on a compatible provider/tool/reasoning protocol | `packages/rd-agent-contracts/src/rd_agent_contracts/provider_lock.py` |
| Golden Trace | JSONL event trace used to validate replay self-consistency | `traces/golden/`, `packages/rd-replay-evals/src/rd_replay_evals/trace_format.py` |
| Reference Host | Executable SQLite example for host ports and continuation semantics | `examples/reference_host/sqlite_reference_host.py` |
| Protocol Wire Contract | Language-neutral data contract under `proto/ruidong/agent/v1/` | `proto/README.md` |
