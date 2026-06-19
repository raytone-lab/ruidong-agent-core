# rd-agent-proto v0.1.0

Initial protocol release unit for Agent Runtime wire contracts.

## Contents

- `proto/ruidong/agent/v1/events.proto`
- `proto/ruidong/agent/v1/transcript.proto`
- `proto/ruidong/agent/v1/runtime.proto`
- generated Python protobuf bindings under `ruidong.agent.v1`
- Python dataclass/protobuf converters in `rd_agent_proto`
- protocol examples for happy path and invalid tool call rejection
- golden trace protobuf roundtrip verification

## Verification

```bash
uv run python tools/scripts/verify_protocol.py
uv build --wheel packages/rd-agent-proto
uv run --no-sync python tools/scripts/verify_wheel_install.py rd-agent-proto --dist-dir dist
```

