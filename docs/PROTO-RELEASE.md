# Proto Release

## Package Shape

`rd-agent-proto` is the release unit for the Agent Runtime wire contract. It
ships:

- checked-in `.proto` files under `rd_agent_proto/proto`;
- generated Python protobuf bindings under the `ruidong.agent.v1` package;
- Python converters between `rd-agent-contracts` dataclasses and protobuf
  messages.

The package version is currently `0.1.0`.

## Generation

Regenerate Python bindings after changing `proto/ruidong/agent/v1/*.proto`:

```bash
uv run python tools/scripts/generate_proto_python.py
uv run python tools/scripts/verify_protocol.py
```

`verify_protocol.py` fails if generated files are stale.

## Build

```bash
uv build --wheel packages/rd-agent-proto
uv run --no-sync python tools/scripts/verify_wheel_install.py rd-agent-proto --dist-dir dist
```

The release workflow builds `rd-agent-proto` with the rest of the workspace
packages and supports tags like:

```text
rd-agent-proto-v0.1.0
```

## Buf Module Path

The repository keeps `buf.yaml` and `buf.gen.yaml` checked in. The current CI
gate verifies these files and the generated Python artifacts. Native Buf
registry publication can be enabled once a remote module namespace is selected.

