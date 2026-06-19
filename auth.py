"""Single-user password gate with a clean path to OIDC or Supabase Auth later."""

from __future__ import annotations

import hmac

import streamlit as st


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def require_authentication() -> str | None:
    """Render the MVP password gate and return a stable app-scoped user ID."""
    expected = _secret("APP_PASSWORD")
    if not expected:
        st.error("APP_PASSWORD is not configured. Add it in Streamlit Community Cloud secrets.")
        st.code('APP_PASSWORD = "use-a-long-random-password"')
        return None
    if st.session_state.get("authenticated"):
        return "default_user"
    st.title("Market-Aware Wealth Manager")
    st.caption("Enter the private app password to continue.")
    entered = st.text_input("Password", type="password", key="login_password")
    if st.button("Sign in", type="primary"):
        if hmac.compare_digest(str(entered), str(expected)):
            st.session_state.authenticated = True
            st.session_state.pop("login_password", None)
            st.rerun()
        else:
            st.error("Incorrect password.")
    return None


def logout_button() -> None:
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()
