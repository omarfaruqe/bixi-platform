"""BIXI live station feed (GBFS): station locations and capacities.

Important: this is a *current snapshot*, not history. Capacity values describe the network as
it is today, so they are an assumption when applied to 2023-2025 (stations get resized or moved).
The station_status feed is a single moment in time and cannot reconstruct past inventory.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bixi.download import manifest
from bixi.download.http import DownloadError, fetch_json

LOGGER = logging.getLogger(__name__)

GBFS_DISCOVERY_URL = "https://gbfs.velobixi.com/gbfs/2-2/gbfs.json"
WANTED_FEEDS = ("station_information", "station_status", "system_information")


def extract_feed_urls(
    discovery: dict[str, Any], wanted: Iterable[str] = WANTED_FEEDS, language: str = "en"
) -> dict[str, str]:
    """Return ``{feed_name: url}`` from a GBFS discovery document (v2.x per-language or v3)."""
    data = discovery.get("data", {})
    feeds = data.get("feeds")
    if feeds is None:  # GBFS 2.x nests feeds under a language code
        per_language = data.get(language) or next(iter(data.values()), {})
        feeds = per_language.get("feeds", [])
    wanted = set(wanted)
    return {feed["name"]: feed["url"] for feed in feeds if feed.get("name") in wanted}


def download_gbfs(raw_dir: Path) -> dict[str, Path]:
    discovery = fetch_json(GBFS_DISCOVERY_URL)
    urls = extract_feed_urls(discovery)
    if "station_information" not in urls:
        raise DownloadError(f"No station_information feed listed in {GBFS_DISCOVERY_URL}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    saved: dict[str, Path] = {}
    for name in WANTED_FEEDS:
        if name not in urls:
            LOGGER.warning("GBFS feed %s not offered; skipping", name)
            continue
        payload = fetch_json(urls[name])
        path = raw_dir / "gbfs" / f"{name}_{stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        manifest.record(raw_dir, f"gbfs_{name}", url=urls[name], path=str(path))
        LOGGER.info("saved %s", path)
        saved[name] = path
    return saved
