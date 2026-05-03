"""rd-agent-contracts — Agent Runtime PaaS 跨包共享协议。

包含：
- ID 类型与生成器
- Message / ToolCall / ToolResult / AgentEvent 等 dataclass
- 横切 ports protocol（EventSink / Meter / BudgetGate / PolicyGate /
  CancellationToken / BlobWriter / Clock / IdGenerator）
- schema_version = "1.0.0"
"""

from .blob import BlobRef
from .budget import BudgetEnvelope
from .clock import Clock, FrozenClock, SystemClock
from .enums import StopReason, ToolCallStatus
from .events import AgentEvent
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
from .transcript_blocks import (
    InvalidToolCall,
    ProviderState,
    ReasoningBlock,
    StandardContentBlock,
    TextBlock,
    ToolUseBlock,
)
from .usage import Usage, normalize_usage

__version__ = "1.0.0"
SCHEMA_VERSION = "1.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "ActionId",
    "AgentEvent",
    "BlobRef",
    "BlobWriter",
    "BudgetEnvelope",
    "BudgetGate",
    "CancellationToken",
    "Clock",
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
    "RunId",
    "SessionId",
    "StandardContentBlock",
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
    "normalize_usage",
]
