"""OpenAI-compatible adapter（覆盖 OpenAI / OpenRouter / 自建 OpenAI 兼容网关）。

Phase A 只做 chunk 解析层；Provider httpx 调用在 Task 19 加。
"""
from __future__ import annotations

import json
from typing import Any

from ..normalizer import StreamNormalizer
from ..types import StreamChunk


def parse_openai_sse_chunk(
    raw: dict[str, Any],
    normalizer: StreamNormalizer,
) -> list[StreamChunk]:
    """解析一个 OpenAI SSE chunk，输出归一化 StreamChunk 列表。

    一个 raw chunk 可能产出多个归一化 chunk（如 delta.content + delta.tool_calls）。
    """
    out: list[StreamChunk] = []
    choices = raw.get("choices") or []
    if not choices:
        # 末尾的 usage chunk
        if "usage" in raw:
            out.append(normalizer.usage(_remap_openai_usage(raw["usage"])))
        return out

    choice = choices[0]
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    # text content
    if delta.get("content"):
        out.append(normalizer.text_delta(delta["content"], raw=raw))

    # tool_calls
    for tc in delta.get("tool_calls") or []:
        tool_use_id = tc.get("id") or ""
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = fn.get("arguments") or ""
        if finish_reason == "length":
            out.append(
                normalizer.tool_use_partial(tool_use_id, name, args, raw=raw)
            )
        else:
            try:
                if args:
                    json.loads(args)
                out.append(
                    normalizer.tool_use_complete(
                        tool_use_id, name, args, raw=raw
                    )
                )
            except json.JSONDecodeError:
                out.append(
                    normalizer.tool_use_invalid(
                        tool_use_id, name, args, raw_chunk=raw
                    )
                )

    # usage（OpenAI 通常在最后一个 chunk）
    if "usage" in raw:
        out.append(normalizer.usage(_remap_openai_usage(raw["usage"])))

    return out


def _remap_openai_usage(u: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 字段名映射到 contracts.Usage。"""
    return {
        "input_tokens": u.get("prompt_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),
    }
