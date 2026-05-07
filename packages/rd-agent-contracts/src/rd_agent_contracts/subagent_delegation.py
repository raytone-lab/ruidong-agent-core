"""Host-neutral subagent delegation policy."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubagentDelegationContext:
    instruction: str
    session_messages: list[Mapping[str, Any]] = field(default_factory=list)
    file_count: int = 0
    available_tool_names: set[str] = field(default_factory=set)
    agent_kind: str = "orchestrator"
    has_open_subagent_tasks: bool = False
    has_satisfied_subagent_tasks: bool = False


@dataclass(frozen=True)
class SubagentDelegationDecision:
    required: bool
    reason: str | None = None


_SHORT_CONTINUATION_WORDS = {
    "继续",
    "确认",
    "执行",
    "开始",
    "可以",
    "好的",
    "好",
    "yes",
    "ok",
    "go",
}

_EXPLICIT_SUBAGENT_TERMS = (
    "subagent",
    "sub-agent",
    "子agent",
    "子 agent",
    "多agent",
    "多 agent",
    "multi-agent",
    "并行",
)

_FRONTEND_TERMS = (
    "前端",
    "前后端",
    "frontend",
    "front-end",
    "react",
    "vue",
    "页面",
    "界面",
)

_BACKEND_TERMS = (
    "后端",
    "backend",
    "back-end",
    "fastapi",
    "django",
    "api",
    "接口",
    "数据库",
    "postgres",
    "postgresql",
    "mysql",
    "服务端",
)

_COMPLEX_PRODUCT_TERMS = (
    "完整",
    "系统",
    "平台",
    "应用",
    "智能体",
    "助手",
    "上传",
    "pdf",
    "文档",
    "检索",
    "问答",
    "认证",
    "权限",
    "测试",
    "部署",
)

_PRODUCT_GENERATION_TERMS = (
    "[appgenerate]",
    "appgenerate",
    "设计",
    "生成",
    "创建",
    "搭建",
    "构建",
    "开发",
    "做一个",
    "实现一个",
    "应用系统",
    "管理系统",
)

_PRODUCT_SCOPE_TERMS = (
    "系统",
    "平台",
    "应用",
    "项目",
    "模块",
    "大屏",
    "wms",
    "crm",
    "erp",
)

_DATABASE_TERMS = (
    "数据库",
    "db",
    "sqlite",
    "postgres",
    "postgresql",
    "mysql",
    "schema",
)


def decide_subagent_delegation(
    context: SubagentDelegationContext,
) -> SubagentDelegationDecision:
    if context.agent_kind != "orchestrator":
        return SubagentDelegationDecision(required=False)
    if "create_subagent_task" not in context.available_tool_names:
        return SubagentDelegationDecision(required=False)
    if context.has_open_subagent_tasks:
        return SubagentDelegationDecision(
            required=True,
            reason="已有子 Agent 任务尚未完成，root orchestrator 需要等待或检查子任务状态",
        )
    if context.has_satisfied_subagent_tasks:
        return SubagentDelegationDecision(required=False)

    current_instruction = " ".join(str(context.instruction or "").split())
    if not current_instruction:
        return SubagentDelegationDecision(required=False)

    should_use_history = (
        len(current_instruction) <= 12
        or current_instruction.lower() in _SHORT_CONTINUATION_WORDS
    )
    signal_text = current_instruction
    if should_use_history:
        recent_user_texts = [
            _message_text(message)
            for message in context.session_messages[-10:]
            if message.get("role") == "user"
        ]
        signal_text = "\n".join([*recent_user_texts, current_instruction])

    if _contains_any(signal_text, _EXPLICIT_SUBAGENT_TERMS):
        return SubagentDelegationDecision(
            required=True,
            reason="用户明确要求子 Agent、多 Agent或并行任务",
        )
    has_frontend = _contains_any(signal_text, _FRONTEND_TERMS)
    has_backend = _contains_any(signal_text, _BACKEND_TERMS)
    if has_frontend and has_backend:
        return SubagentDelegationDecision(
            required=True,
            reason="任务同时包含前端和后端/API工作流",
        )

    has_database = _contains_any(signal_text, _DATABASE_TERMS)
    has_product_generation = _contains_any(signal_text, _PRODUCT_GENERATION_TERMS)
    has_product_scope = _contains_any(signal_text, _PRODUCT_SCOPE_TERMS)
    if has_backend and has_database and has_product_generation and has_product_scope:
        return SubagentDelegationDecision(
            required=True,
            reason="任务要求后端/数据库且属于产品级应用生成",
        )

    complex_score = sum(
        1 for term in _COMPLEX_PRODUCT_TERMS if term.lower() in signal_text.lower()
    )
    if has_backend and complex_score >= 3:
        return SubagentDelegationDecision(
            required=True,
            reason="任务包含后端/API及多个产品级复杂能力",
        )
    if context.file_count >= 80 and has_backend and complex_score >= 2:
        return SubagentDelegationDecision(
            required=True,
            reason="现有项目较大且任务涉及后端/API复杂改动",
        )
    return SubagentDelegationDecision(required=False)


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)
