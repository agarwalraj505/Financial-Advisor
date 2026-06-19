"""Shared provider result/status types and safe Streamlit-secret access."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


@dataclass
class ProviderResult:
    success: bool
    provider: str
    data: dict[str, Any] = field(default_factory=dict)
    confidence: str = "Low"
    error: str = ""
    status_code: int | None = None
    fetched_at: str = field(default_factory=utc_now)


class BaseProvider:
    name = "Base"
    purpose = ""
    key_name = ""
    key_required = False

    def __init__(self):
        self.last_success = ""
        self.last_error = ""

    @property
    def api_key(self) -> str:
        return read_secret(self.key_name) if self.key_name else ""

    @property
    def enabled(self) -> bool:
        return not self.key_required or bool(self.api_key)

    def success(self, data: dict, confidence: str = "Medium") -> ProviderResult:
        self.last_success, self.last_error = utc_now(), ""
        return ProviderResult(True, self.name, data, confidence, fetched_at=self.last_success)

    def failure(self, error: str, status_code: int | None = None) -> ProviderResult:
        self.last_error = error
        return ProviderResult(False, self.name, error=error, status_code=status_code)

    def status_row(self, key_label: str) -> dict:
        status = "Enabled" if self.enabled else "Disabled"
        return {"Provider": self.name, "Purpose": self.purpose, "Key required?": key_label,
                "Status": status, "Last success": self.last_success, "Last error": self.last_error}
