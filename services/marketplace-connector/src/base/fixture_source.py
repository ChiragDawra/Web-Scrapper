"""The recorded-fixture read path shared by the Sprint 4 connectors.

`fetch_raw()` is a stub over recorded responses until `INPUTS_NEEDED.md` item 1
is answered (official API vs. data provider vs. HTML). That stub is identical
for every marketplace — read the JSON files in a directory, unwrap whatever
envelope each was saved in, yield one raw item at a time — and only the envelope
keys differ, which is why they are passed in from each `selectors.py` rather
than known here.

Yielded as a generator, not a list, for the same two reasons `SERVICE_INTERFACES.md`
§1's poll loop wants: a bad item can be skipped while the batch keeps pulling
(Task 2.5), and a live implementation returning a paged cursor is a drop-in
replacement for this one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path as FilePath
from typing import Any

from src.base.raw_mapping import Path, select

__all__ = ["iter_fixture_items", "unwrap_items"]


def unwrap_items(payload: Any, item_list_paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """Yield the item objects out of one recorded response.

    The known envelopes are tried in order, then a bare array, then a bare
    object. All four are accepted so a recording never has to be reshaped by
    hand before it can be replayed — a hand-cut fixture of a single awkward
    listing is the fastest way to pin a parsing bug, and it should not need a
    wrapper to be replayable.
    """
    for path in item_list_paths:
        items = select(payload, path)
        if isinstance(items, list):
            yield from (item for item in items if isinstance(item, dict))
            return

    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        yield payload


def iter_fixture_items(
    fixture_dir: FilePath, item_list_paths: Iterable[Path]
) -> Iterator[dict[str, Any]]:
    """Every raw item in every recording under `fixture_dir`, oldest filename first."""
    item_list_paths = tuple(item_list_paths)
    for path in sorted(fixture_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        yield from unwrap_items(payload, item_list_paths)
