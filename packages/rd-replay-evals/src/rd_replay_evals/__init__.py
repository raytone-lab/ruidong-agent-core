"""rd-replay-evals — 录制现有 monolith 事件流为 golden trace，replay 验证 engine 行为不变。"""

from .dumper import EventRow, dump_event_rows
from .mocks import MockLLMProvider, MockToolExecutor
from .recorder import RecordingEventSink, finalize_to_trace
from .trace_format import GoldenTrace, TraceMeta, read_trace, write_trace

__version__ = "1.0.0"

__all__ = [
    "EventRow",
    "GoldenTrace",
    "MockLLMProvider",
    "MockToolExecutor",
    "RecordingEventSink",
    "TraceMeta",
    "dump_event_rows",
    "finalize_to_trace",
    "read_trace",
    "write_trace",
]
