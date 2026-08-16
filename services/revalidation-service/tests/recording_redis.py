"""A `Redis` stand-in that records what would have been published.

Same helper as the connector's, for the same reason: the assertions are about
the events reaching the stream, and none of them needs a server. Used with the
real `EventPublisher`, so envelope and payload schema validation still runs
before anything is recorded — which is what makes "no event published" a
meaningful assertion here rather than a mock that agreed with itself.
"""

from __future__ import annotations

import json
from typing import Any

from libs.event_bus.publisher import ENVELOPE_FIELD

__all__ = ["RecordingRedis"]


class RecordingRedis:
    """Captures `XADD` calls in order. A stand-in, not a mock: it records and nothing else."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> bytes:
        self.entries.append((name, fields))
        return f"{len(self.entries)}-0".encode()

    def envelopes(self) -> list[dict[str, Any]]:
        """The recorded entries decoded back into envelope dicts."""
        return [json.loads(fields[ENVELOPE_FIELD]) for _, fields in self.entries]
