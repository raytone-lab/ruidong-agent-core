from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any


class OpenAICompatTransport:
    """OpenAI Chat Completions compatible streaming transport."""

    async def stream(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
        timeout: float,
    ) -> AsyncIterator[Any]:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        try:
            stream = await client.chat.completions.create(**request_body)
            async for chunk in stream:
                yield chunk
        finally:
            close_client = getattr(client, "close", None)
            if close_client is not None:
                maybe_awaitable = close_client()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
