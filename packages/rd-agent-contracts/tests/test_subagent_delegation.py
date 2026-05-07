from __future__ import annotations

from rd_agent_contracts import (
    SubagentDelegationContext,
    decide_subagent_delegation,
)


def test_subagent_delegation_uses_recent_history_for_short_followups():
    decision = decide_subagent_delegation(
        SubagentDelegationContext(
            instruction="确认",
            session_messages=[
                {
                    "role": "user",
                    "content": (
                        "帮我做一个设备检修助手智能体，包含前后端设计及文档PDF上传，"
                        "封装好API接口"
                    ),
                }
            ],
            available_tool_names={"create_subagent_task"},
        )
    )

    assert decision.required is True
    assert decision.reason == "任务同时包含前端和后端/API工作流"


def test_open_subagent_tasks_keep_delegation_gate_closed():
    decision = decide_subagent_delegation(
        SubagentDelegationContext(
            instruction="继续",
            available_tool_names={"create_subagent_task"},
            has_open_subagent_tasks=True,
        )
    )

    assert decision.required is True
    assert (
        decision.reason
        == "已有子 Agent 任务尚未完成，root orchestrator 需要等待或检查子任务状态"
    )


def test_satisfied_subagent_tasks_do_not_force_more_delegation():
    decision = decide_subagent_delegation(
        SubagentDelegationContext(
            instruction="做一个前后端系统",
            available_tool_names={"create_subagent_task"},
            has_satisfied_subagent_tasks=True,
        )
    )

    assert decision.required is False
    assert decision.reason is None


def test_product_backend_database_continuation_requires_delegation():
    decision = decide_subagent_delegation(
        SubagentDelegationContext(
            instruction="执行吧",
            session_messages=[
                {
                    "role": "user",
                    "content": (
                        '设计"仓管家"WMS仓储系统。适用：电商仓库。模块：库存总览大屏、'
                        "出入库操作、库位管理、盘点任务、预警中心。要求：操作高效优先、"
                        "支持PDA扫码、大字体大按钮、状态颜色编码清晰[appGenerate][应用系统]"
                    ),
                },
                {"role": "user", "content": "要有后端和数据库"},
            ],
            available_tool_names={"create_subagent_task"},
        )
    )

    assert decision.required is True
    assert decision.reason == "任务要求后端/数据库且属于产品级应用生成"


def test_simple_followup_does_not_use_history_for_specific_edit():
    decision = decide_subagent_delegation(
        SubagentDelegationContext(
            instruction="把标题改成 Raytone",
            session_messages=[
                {"role": "user", "content": "之前做一个包含前后端和API的系统"}
            ],
            file_count=100,
            available_tool_names={"create_subagent_task"},
        )
    )

    assert decision.required is False
    assert decision.reason is None


def test_subagent_delegation_requires_orchestrator_and_tool():
    assert (
        decide_subagent_delegation(
            SubagentDelegationContext(
                instruction="请并行处理",
                agent_kind="subagent",
                available_tool_names={"create_subagent_task"},
            )
        ).required
        is False
    )
    assert (
        decide_subagent_delegation(
            SubagentDelegationContext(
                instruction="请并行处理",
                available_tool_names={"write_file"},
            )
        ).required
        is False
    )
