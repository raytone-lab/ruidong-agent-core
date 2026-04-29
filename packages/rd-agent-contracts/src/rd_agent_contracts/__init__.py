"""rd-agent-contracts — Agent Runtime PaaS 跨包共享协议。

包含：
- ID 类型与生成器
- Message / ToolCall / ToolResult / AgentEvent 等 dataclass
- 横切 ports protocol（EventSink / Meter / BudgetGate / PolicyGate / CancellationToken / BlobWriter / Clock / IdGenerator）
- schema_version = "1.0.0"
"""

__version__ = "1.0.0"
SCHEMA_VERSION = "1.0.0"
