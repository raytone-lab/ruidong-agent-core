from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol

from .events import StandardEvent


class StreamParserSession(Protocol):
    def feed(self, raw_chunk: Any) -> Iterable[StandardEvent]: ...

    def finalize(self) -> Iterable[StandardEvent]: ...

    def finalize_on_error(self) -> Iterable[StandardEvent]: ...


class Transport(Protocol):
    async def stream(
        self,
        request_body: dict[str, Any],
        *,
        api_key: str,
        base_url: str,
        timeout: float,
    ) -> AsyncIterator[Any]: ...
