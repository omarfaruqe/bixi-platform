"""Small, dependency-free HTTP helpers: retries, atomic file writes, SHA-256 checksums."""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import certifi

LOGGER = logging.getLogger(__name__)
USER_AGENT = "bixi-platform/0.1 (data science portfolio project)"
RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_CHUNK_BYTES = 1 << 20

T = TypeVar("T")


class DownloadError(RuntimeError):
    """A download failed after all retries (or failed in a way retrying cannot fix)."""


@dataclass(frozen=True)
class FileInfo:
    size_bytes: int
    sha256: str


# def _open(url: str, timeout: float):
#     request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
#     return urllib.request.urlopen(request, timeout=timeout)

def _open(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def _with_retries(action: Callable[[], T], url: str, retries: int, backoff: float) -> T:
    for attempt in range(1, retries + 1):
        try:
            return action()
        except urllib.error.HTTPError as error:  # must come before URLError (its parent)
            if error.code not in RETRYABLE_HTTP_CODES or attempt == retries:
                raise DownloadError(f"HTTP {error.code} for {url}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == retries:
                raise DownloadError(f"Could not reach {url}: {error}") from error
        wait = backoff * 2 ** (attempt - 1)
        LOGGER.warning(
            "Attempt %d/%d failed for %s; retrying in %.0fs", attempt, retries, url, wait
        )
        time.sleep(wait)
    raise DownloadError(f"No attempts were made for {url}")  # retries < 1


def download_file(
    url: str, dest: Path, *, timeout: float = 120, retries: int = 3, backoff: float = 2.0
) -> FileInfo:
    """Stream ``url`` to ``dest`` via a temporary ``.part`` file, so a failed download never
    leaves a half-written file under the final name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    def action() -> FileInfo:
        digest = hashlib.sha256()
        size = 0
        with _open(url, timeout) as response, part.open("wb") as handle:
            while chunk := response.read(_CHUNK_BYTES):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        return FileInfo(size, digest.hexdigest())

    try:
        info = _with_retries(action, url, retries, backoff)
    except DownloadError:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    return info


def fetch_json(url: str, *, timeout: float = 30, retries: int = 3, backoff: float = 2.0) -> Any:
    def action() -> Any:
        with _open(url, timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        return _with_retries(action, url, retries, backoff)
    except json.JSONDecodeError as error:
        raise DownloadError(f"{url} did not return valid JSON") from error
