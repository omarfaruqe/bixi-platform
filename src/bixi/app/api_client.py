"""Thin client for the forecast API (bixi.api). The dashboard never reads the database directly.

BIXI_API_URL points at the API: http://localhost:8000 when developing, http://api:8000 inside the
Docker network on the server.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

TIMEOUT = httpx.Timeout(10.0)


class ApiUnavailable(RuntimeError):
    """The API could not be reached (status None) or returned an error status."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def no_active_run(self) -> bool:
        """The API is up but no forecast run has been published (HTTP 503)."""
        return self.status == 503


def base_url() -> str:
    return os.getenv("BIXI_API_URL", "http://localhost:8000").rstrip("/")


@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def get(path: str, params: tuple[tuple[str, str], ...] = ()) -> dict | list:
    """GET ``path`` with query ``params`` (a tuple so the call is cacheable)."""
    try:
        response = httpx.get(f"{base_url()}{path}", params=dict(params), timeout=TIMEOUT)
    except httpx.HTTPError as error:
        raise ApiUnavailable(str(error)) from error
    if response.status_code >= 400:
        raise ApiUnavailable(
            f"{response.status_code}: {response.text[:200]}", status=response.status_code
        )
    return response.json()
