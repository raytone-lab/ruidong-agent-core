from __future__ import annotations

from pathlib import Path

from rd_agent_proto import agent_event_from_proto, agent_event_to_proto
from rd_replay_evals.trace_format import read_trace
from ruidong.agent.v1 import events_pb2

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_golden_traces_roundtrip_through_protobuf() -> None:
    traces = sorted((REPO_ROOT / "traces" / "golden").glob("*.jsonl"))
    assert traces

    for path in traces:
        with path.open(encoding="utf-8") as fp:
            trace = read_trace(fp)
        for event in trace.events:
            payload = agent_event_to_proto(event).SerializeToString()
            parsed = events_pb2.AgentEvent()
            parsed.ParseFromString(payload)
            assert agent_event_from_proto(parsed) == event

