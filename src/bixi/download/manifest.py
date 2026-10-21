"""A manifest of everything downloaded (URL, checksum, time) for reproducibility."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"


def record(raw_dir: Path, key: str, **fields: Any) -> None:
    """Add or replace one entry in ``<raw_dir>/manifest.json``."""
    path = raw_dir / MANIFEST_NAME
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    entries[key] = {**fields, "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
