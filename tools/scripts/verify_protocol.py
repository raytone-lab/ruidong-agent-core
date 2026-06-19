from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from rd_agent_contracts import SCHEMA_VERSION, AgentEvent
from rd_agent_proto import agent_event_from_proto, agent_event_to_proto
from ruidong.agent.v1 import events_pb2

GENERATED_FILES = (
    "ruidong/agent/v1/events_pb2.py",
    "ruidong/agent/v1/runtime_pb2.py",
    "ruidong/agent/v1/transcript_pb2.py",
)
PROTO_FILES = (
    "proto/ruidong/agent/v1/events.proto",
    "proto/ruidong/agent/v1/runtime.proto",
    "proto/ruidong/agent/v1/transcript.proto",
)
GO_PACKAGE = (
    'option go_package = "github.com/shinelee211-arch/ruidong-agent-core/'
    'gen/go/ruidong/agent/v1;agentv1";'
)


class ProtocolVerificationError(AssertionError):
    """Raised when protocol artifacts do not match the current contract."""


def verify(repo_root: Path) -> None:
    repo_root = repo_root.resolve()
    _verify_buf_config(repo_root)
    _verify_proto_language_options(repo_root)
    _verify_generated_python_is_current(repo_root)
    _verify_protocol_examples(repo_root)
    _verify_golden_traces_roundtrip(repo_root)


def _verify_buf_config(repo_root: Path) -> None:
    buf_yaml = (repo_root / "buf.yaml").read_text(encoding="utf-8")
    buf_gen = (repo_root / "buf.gen.yaml").read_text(encoding="utf-8")
    required = ("version: v2", "path: proto", "STANDARD", "FILE")
    for item in required:
        if item not in buf_yaml:
            raise ProtocolVerificationError(f"buf.yaml missing {item!r}")
    if "buf.build/protocolbuffers/python" not in buf_gen:
        raise ProtocolVerificationError("buf.gen.yaml must configure Python generation")
    if "packages/rd-agent-proto/src" not in buf_gen:
        raise ProtocolVerificationError("buf.gen.yaml must generate into rd-agent-proto")


def _verify_proto_language_options(repo_root: Path) -> None:
    for relative in PROTO_FILES:
        content = (repo_root / relative).read_text(encoding="utf-8")
        if "package ruidong.agent.v1;" not in content:
            raise ProtocolVerificationError(f"{relative} must use package ruidong.agent.v1")
        if GO_PACKAGE not in content:
            raise ProtocolVerificationError(f"{relative} missing Go generation package option")


def _verify_generated_python_is_current(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="rd-proto-gen-") as temp_dir:
        temp_out = Path(temp_dir)
        _generate_bindings(repo_root=repo_root, out_dir=temp_out)
        for relative in GENERATED_FILES:
            expected = (temp_out / relative).read_text(encoding="utf-8")
            actual_path = repo_root / "packages" / "rd-agent-proto" / "src" / relative
            if not actual_path.is_file():
                raise ProtocolVerificationError(f"missing generated file: {relative}")
            actual = actual_path.read_text(encoding="utf-8")
            if actual != expected:
                raise ProtocolVerificationError(
                    f"generated protobuf file is stale: {actual_path.relative_to(repo_root)}"
                )


def _verify_protocol_examples(repo_root: Path) -> None:
    example_dir = repo_root / "examples" / "protocol"
    examples = sorted(example_dir.glob("*.json"))
    if not examples:
        raise ProtocolVerificationError("protocol examples are required")
    names = {path.name for path in examples}
    for required in ("happy_path.json", "reject_invalid_tool_call.json"):
        if required not in names:
            raise ProtocolVerificationError(f"missing protocol example {required}")
    for path in examples:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ProtocolVerificationError(
                f"{path.relative_to(repo_root)} schema_version must be {SCHEMA_VERSION}"
            )
        events = [AgentEvent(**item) for item in payload.get("events", [])]
        if not events:
            raise ProtocolVerificationError(f"{path.relative_to(repo_root)} has no events")
        _assert_monotonic(events, path=path, repo_root=repo_root)
        for event in events:
            _assert_event_roundtrip(event)
        if path.name.startswith("reject_"):
            event_types = {event.event_type for event in events}
            if "tool_call_invalid" not in event_types:
                raise ProtocolVerificationError(
                    f"{path.relative_to(repo_root)} must include tool_call_invalid"
                )
            if event_types & {"tool_started", "tool_completed"}:
                raise ProtocolVerificationError(
                    f"{path.relative_to(repo_root)} must not execute invalid tools"
                )


def _verify_golden_traces_roundtrip(repo_root: Path) -> None:
    from rd_replay_evals.trace_format import read_trace

    traces = sorted((repo_root / "traces" / "golden").glob("*.jsonl"))
    if not traces:
        raise ProtocolVerificationError("golden traces are required")
    for path in traces:
        with path.open(encoding="utf-8") as fp:
            trace = read_trace(fp)
        for event in trace.events:
            parsed = events_pb2.AgentEvent()
            parsed.ParseFromString(agent_event_to_proto(event).SerializeToString())
            _assert_same_event(event, agent_event_from_proto(parsed))


def _assert_monotonic(events: list[AgentEvent], *, path: Path, repo_root: Path) -> None:
    seqs = [event.seq for event in events]
    if seqs != sorted(seqs):
        raise ProtocolVerificationError(
            f"{path.relative_to(repo_root)} events must be seq sorted: {seqs}"
        )


def _assert_event_roundtrip(event: AgentEvent) -> None:
    _assert_same_event(event, agent_event_from_proto(agent_event_to_proto(event)))


def _assert_same_event(expected: AgentEvent, actual: AgentEvent) -> None:
    if _normalize(asdict(expected)) != _normalize(asdict(actual)):
        raise ProtocolVerificationError(
            "AgentEvent proto roundtrip mismatch: "
            f"expected={expected.to_dict()} actual={actual.to_dict()}"
        )


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _generate_bindings(*, repo_root: Path, out_dir: Path) -> None:
    script = repo_root / "tools" / "scripts" / "generate_proto_python.py"
    spec = importlib.util.spec_from_file_location("generate_proto_python_for_verify", script)
    if spec is None or spec.loader is None:
        raise ProtocolVerificationError("could not load generate_proto_python.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.generate(repo_root=repo_root, out_dir=out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args(argv)
    verify(args.repo_root)
    buf_path = shutil.which("buf")
    if buf_path:
        subprocess.run([buf_path, "lint"], cwd=args.repo_root, check=True)
        print(f"Buf lint passed with {buf_path}.")
    else:
        print("Buf is not installed; verified checked-in Buf config and protobuf artifacts.")
    print("Protocol verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
