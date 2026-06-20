"""Supabase connection and low-level query helpers."""

from __future__ import annotations

from typing import Any

import streamlit as st


class SupabaseConnectionError(RuntimeError):
    pass


def _read_secret(name: str) -> str:
    try:
        value = st.secrets.get(name)
    except Exception as exc:
        raise SupabaseConnectionError(f"Streamlit secret {name} is not configured") from exc
    if not value:
        raise SupabaseConnectionError(f"Streamlit secret {name} is not configured")
    return str(value)


@st.cache_resource(show_spinner=False)
def get_supabase_client(user_id: str):
    """Create one server-side client; credentials never appear in source code."""
    try:
        from supabase import ClientOptions, create_client
        options = ClientOptions(headers={"x-user-id": user_id})
        return create_client(_read_secret("SUPABASE_URL"), _read_secret("SUPABASE_ANON_KEY"), options=options)
    except SupabaseConnectionError:
        raise
    except Exception as exc:
        raise SupabaseConnectionError(f"Could not connect to Supabase: {exc}") from exc


class SupabaseGateway:
    """Thin injectable wrapper around PostgREST and Supabase Storage."""

    def __init__(self, client):
        self.client = client

    @staticmethod
    def _filters(query, filters: dict[str, Any] | None):
        for column, value in (filters or {}).items():
            query = query.eq(column, value)
        return query

    def select(self, table: str, filters=None, columns: str = "*", order: str | None = None,
               desc: bool = False, limit: int | None = None) -> list[dict]:
        try:
            query = self._filters(self.client.table(table).select(columns), filters)
            if order:
                query = query.order(order, desc=desc)
            if limit:
                query = query.limit(limit)
            return query.execute().data or []
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not read {table}: {exc}") from exc

    def insert(self, table: str, rows: list[dict] | dict) -> list[dict]:
        if not rows:
            return []
        try:
            return self.client.table(table).insert(rows).execute().data or []
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not insert into {table}: {exc}") from exc

    def upsert(self, table: str, rows: list[dict] | dict, on_conflict: str) -> list[dict]:
        try:
            return self.client.table(table).upsert(rows, on_conflict=on_conflict).execute().data or []
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not upsert {table}: {exc}") from exc

    def update(self, table: str, values: dict, filters: dict) -> list[dict]:
        try:
            query = self._filters(self.client.table(table).update(values), filters)
            return query.execute().data or []
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not update {table}: {exc}") from exc

    def delete(self, table: str, filters: dict) -> list[dict]:
        try:
            query = self._filters(self.client.table(table).delete(), filters)
            return query.execute().data or []
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not delete from {table}: {exc}") from exc

    def replace_user_rows(self, table: str, user_id: str, rows: list[dict]) -> None:
        self.delete(table, {"user_id": user_id})
        if rows:
            self.insert(table, rows)

    def upload_private_file(self, bucket: str, path: str, contents: bytes, content_type: str) -> str:
        try:
            self.client.storage.from_(bucket).upload(
                path=path, file=contents,
                file_options={"content-type": content_type, "upsert": "false"},
            )
            return path
        except Exception as exc:
            raise SupabaseConnectionError(f"Could not upload file: {exc}") from exc
