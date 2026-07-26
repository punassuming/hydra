"""Human- and machine-readable CLI output."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from typing import Any

import yaml


def write_document(value: Any, output: str = "yaml") -> None:
    if output == "json":
        print(json.dumps(value, indent=2, default=str))
    else:
        print(yaml.safe_dump(value, sort_keys=False).rstrip())


def write_table(rows: Iterable[dict[str, Any]], columns: Sequence[tuple[str, str]]) -> None:
    materialized = list(rows)
    values = [[_cell(row.get(key)) for _, key in columns] for row in materialized]
    headings = [heading for heading, _ in columns]
    widths = [len(heading) for heading in headings]
    for row in values:
        widths = [max(width, len(value)) for width, value in zip(widths, row, strict=True)]
    print("  ".join(heading.ljust(width) for heading, width in zip(headings, widths, strict=True)))
    for row in values:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)).rstrip())


def write_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple)):
        return ",".join(map(str, value)) or "-"
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)
