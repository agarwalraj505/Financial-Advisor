"""Single-user password gate with a clean path to OIDC or Supabase Auth later."""

from __future__ import annotations

import hmac

import streamlit as st

from ui_components import render_alert, render_page_header


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def require_authentication() -> str | None:
    """Render the MVP password gate and return a stable app-scoped user ID."""
    expected = _secret("APP_PASSWORD")
    if not expected:
        render_alert("APP_PASSWORD is not configured. Add it in Streamlit Community Cloud secrets.", "danger")
        st.code('APP_PASSWORD = "use-a-long-random-password"')
        return None
    if st.session_state.get("authenticated"):
        return "default_user"
    render_page_header("Financial Hub", "Private access to your market-aware wealth manager.", "Secure sign-in")
    render_alert("Your portfolio remains private in Supabase. This app has no broker connection and cannot place trades.", "info")
    entered = st.text_input("Password", type="password", key="login_password")
    if st.button("Sign in", type="primary"):
        if hmac.compare_digest(str(entered), str(expected)):
            st.session_state.authenticated = True
            st.session_state.pop("login_password", None)
            st.rerun()
        else:
            render_alert("Incorrect password.", "danger")
    return None


def logout_button() -> None:
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()
