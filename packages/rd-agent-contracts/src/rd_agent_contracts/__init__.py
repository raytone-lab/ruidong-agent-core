"""rd-agent-contracts — Agent Runtime PaaS 跨包共享协议。

包含：
- ID 类型与生成器
- Message / ToolCall / ToolResult / AgentEvent 等 dataclass
- EventDraft / EventLogPort append-only 事件日志契约
- AgentRun lifecycle 持久化数据与 port
- ContinuationQueuePort 自动续跑队列契约
- 横切 ports protocol（EventSink / Meter / BudgetGate / PolicyGate /
  CancellationToken / BlobWriter / Clock / IdGenerator）
- __version__：包发版号（跟 pyproject.toml 同步）
- SCHEMA_VERSION：data contract schema 版本，仅在 contract 字段/类型有 breaking change 时 bump
"""

from .blob import BlobRef
from .budget import BudgetEnvelope
from .clock import Clock, FrozenClock, SystemClock
from .continuation_queue import (
    ContinuationJobRecord,
    ContinuationJobSpec,
    ContinuationJobStatus,
    ContinuationQueuePort,
)
from .enums import StopReason, ToolCallStatus
from .event_log import EventLogPort
from .events import AgentEvent, EventDraft
from .ids import (
    ActionId,
    IdGenerator,
    MessageId,
    RunId,
    SessionId,
    ToolUseId,
    TurnId,
    UuidIdGenerator,
)
from .messages import Message, Role, ToolCall, ToolResult
from .ports import (
    BlobWriter,
    BudgetGate,
    CancellationToken,
    EventSink,
    Meter,
    PolicyGate,
)
from .provider_lock import ProviderLock
from .run_persistence import (
    AgentKind,
    RunBudget,
    RunCompletion,
    RunFailure,
    RunPersistencePort,
    RunRecord,
    RunResultMetadata,
    RunScope,
    RunStatus,
)
from .run_policy import (
    CONTINUABLE_STOP_REASONS,
    NEEDS_ATTENTION_STOP_REASONS,
    TERMINAL_WAIT_REASONS,
    completion_status_for_stop_reason,
    is_continuable_stop_reason,
    is_terminal_wait_stop_reason,
    needs_attention_for_stop_reason,
    should_auto_continue_run,
)
from .transcript_blocks import (
    InvalidToolCall,
    ProviderState,
    ReasoningBlock,
    StandardContentBlock,
    StandardToolCall,
    TextBlock,
    ToolUseBlock,
)
from .usage import Usage, normalize_usage

__version__ = "1.4.0"
SCHEMA_VERSION = "1.2.0"

__all__ = [
    "SCHEMA_VERSION",
    "ActionId",
    "AgentKind",
    "AgentEvent",
    "BlobRef",
    "BlobWriter",
    "BudgetEnvelope",
    "BudgetGate",
    "CancellationToken",
    "Clock",
    "ContinuationJobRecord",
    "ContinuationJobSpec",
    "ContinuationJobStatus",
    "ContinuationQueuePort",
    "EventDraft",
    "EventLogPort",
    "EventSink",
    "FrozenClock",
    "IdGenerator",
    "InvalidToolCall",
    "Message",
    "MessageId",
    "Meter",
    "PolicyGate",
    "ProviderLock",
    "ProviderState",
    "ReasoningBlock",
    "Role",
    "RunBudget",
    "RunCompletion",
    "RunFailure",
    "RunId",
    "RunPersistencePort",
    "RunRecord",
    "RunResultMetadata",
    "RunScope",
    "RunStatus",
    "SessionId",
    "StandardContentBlock",
    "StandardToolCall",
    "StopReason",
    "SystemClock",
    "TextBlock",
    "ToolCall",
    "ToolCallStatus",
    "ToolResult",
    "ToolUseBlock",
    "ToolUseId",
    "TurnId",
    "Usage",
    "UuidIdGenerator",
    "CONTINUABLE_STOP_REASONS",
    "NEEDS_ATTENTION_STOP_REASONS",
    "TERMINAL_WAIT_REASONS",
    "completion_status_for_stop_reason",
    "is_continuable_stop_reason",
    "is_terminal_wait_stop_reason",
    "needs_attention_for_stop_reason",
    "normalize_usage",
    "should_auto_continue_run",
]
