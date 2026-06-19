# Protocol Files

This directory contains the language-neutral Agent Runtime wire data contract.
The current files are intentionally small and mirror the stable public Python
contracts that already exist in `rd-agent-contracts` and `rd-agent-core`.

## Files

- `ruidong/agent/v1/events.proto`: event envelope and runtime event names.
- `ruidong/agent/v1/transcript.proto`: transcript blocks and usage.
- `ruidong/agent/v1/runtime.proto`: tools, run summaries, and trace identity.

## Policy

- Additive fields are preferred.
- Removing fields or changing semantics requires a schema-version decision and
  release migration note.
- Host behavior ports remain in `rd-agent-contracts` and are verified through
  conformance tests.
- Run `uv run python tools/scripts/generate_proto_python.py` and
  `uv run python tools/scripts/verify_protocol.py` after changing proto files.
