"""Reusable, escaped premium UI components and consistent Plotly helpers."""

from __future__ import annotations

from html import escape
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from styles import DESIGN_TOKENS


TONES = {"neutral", "info", "positive", "success", "warning", "negative", "danger"}
VALID_TOAST_ICONS = {"✅", "⚠️", "❌", "ℹ️", "🔄", "💾", "📈", "📰", "🧠"}


def safe_toast(message: str, icon: str | None = "✅"):
    """Show a Streamlit toast without allowing invalid icon values to crash the app."""
    try:
        if icon in VALID_TOAST_ICONS:
            st.toast(message, icon=icon)
        else:
            st.toast(message)
    except Exception:
        st.success(message)


def set_flash_success(message: str) -> None:
    """Persist a success message across the next st.rerun()."""
    st.session_state["flash_success"] = str(message)


def render_flash_message() -> None:
    """Render and consume a success message saved before a rerun."""
    message = st.session_state.pop("flash_success", None)
    if message:
        st.success(message)


def _tone(tone: str) -> str:
    tone = str(tone or "neutral").lower()
    return tone if tone in TONES else "neutral"


def _pill_class(tone: str) -> str:
    return {"positive": "success", "negative": "danger"}.get(_tone(tone), _tone(tone))


def _render(html: str) -> str:
    st.markdown(html, unsafe_allow_html=True)
    return html


def render_page_header(title, subtitle, status=None):
    status_html = render_status_pill(status, "info", render=False) if status else ""
    return _render(f'<div class="page-header"><div><div class="page-eyebrow">Financial Hub</div>'
                   f'<h1 class="page-title">{escape(str(title))}</h1><p class="page-subtitle">{escape(str(subtitle))}</p>'
                   f'</div>{status_html}</div>')


def render_hero_summary(title, value, delta=None, caption=None):
    tone = "positive" if str(delta or "").strip().startswith("+") else "negative" if str(delta or "").strip().startswith("-") else "info"
    delta_html = f'<div class="hero-delta tone-{tone}">{escape(str(delta))}</div>' if delta is not None else ""
    caption_html = f'<div class="hero-caption">{escape(str(caption))}</div>' if caption else ""
    return _render(f'<div class="hero-card"><div class="hero-label">Live overview</div><div class="hero-title">{escape(str(title))}</div>'
                   f'<div class="hero-value">{escape(str(value))}</div>{delta_html}{caption_html}</div>')


def render_metric_card(label, value, delta=None, tone="neutral"):
    tone = _tone(tone)
    delta_html = f'<div class="metric-delta tone-{tone}">{escape(str(delta))}</div>' if delta is not None else ""
    return _render(f'<div class="metric-card"><div class="metric-label">{escape(str(label))}</div>'
                   f'<div class="metric-value">{escape(str(value))}</div>{delta_html}</div>')


def render_status_pill(label, tone="neutral", render=True):
    css_tone = _pill_class(tone)
    html = f'<span class="status-pill {css_tone}-pill">{escape(str(label))}</span>'
    return _render(html) if render else html


def render_section_card(title, body=None):
    body_html = f'<div class="section-body">{escape(str(body))}</div>' if body else ""
    return _render(f'<div class="section-card"><div class="section-title">{escape(str(title))}</div>{body_html}</div>')


def render_alert(message, tone="info"):
    tone = _pill_class(tone)
    if tone not in {"info", "success", "warning", "danger"}: tone = "info"
    return _render(f'<div class="premium-alert alert-{tone}">{escape(str(message))}</div>')


def render_flow_steps(steps):
    cards = []
    for index, step in enumerate(steps, 1):
        item = step if isinstance(step, dict) else {"label": str(step), "status": "Pending"}
        status = str(item.get("status", "Pending")); tone = {"Done": "success", "Running": "info", "Warning": "warning", "Failed": "danger"}.get(status, "neutral")
        cards.append(f'<div class="flow-step-card"><div class="flow-number">Step {index}</div>'
                     f'<div class="flow-name">{escape(str(item.get("label", "")))}</div>'
                     f'{render_status_pill(status, tone, render=False)}</div>')
    return _render('<div class="flow-grid">' + "".join(cards) + "</div>")


def render_empty_state(title, message, action_label=None):
    action = f'<div class="hero-caption">{escape(str(action_label))}</div>' if action_label else ""
    return _render(f'<div class="empty-state"><div class="empty-state-title">{escape(str(title))}</div>'
                   f'<div class="empty-state-message">{escape(str(message))}</div>{action}</div>')


def render_data_quality_badge(confidence):
    label = str(confidence or "Missing")
    lower = label.lower()
    tone = "success" if any(term in lower for term in ("high", "live", "ready")) else "warning" if any(term in lower for term in ("medium", "fallback", "review")) else "danger" if any(term in lower for term in ("low", "missing")) else "neutral"
    return render_status_pill(label, tone)


def render_recommendation_card(action=None, instrument=None, reason=None, score=None, confidence=None, **fields):
    action = action or "Review"; instrument = instrument or "Unnamed asset"; reason = reason or "No reason supplied."
    details = []
    for label, key in (("ISIN", "isin"), ("Quantity", "quantity"), ("Est. value", "estimated_value"), ("Fee", "fee_issue")):
        value = fields.get(key)
        if value not in (None, ""): details.append(f"{label}: {escape(str(value))}")
    score_text = "—" if score in (None, "") else escape(str(score))
    return _render(f'<div class="recommendation-card"><div class="recommendation-head"><div>'
                   f'{render_status_pill(action, "info", render=False)} <span class="recommendation-instrument">{escape(str(instrument))}</span></div>'
                   f'<div>{render_status_pill(f"Score {score_text}", "neutral", render=False)} '
                   f'{render_status_pill(confidence or "Unknown confidence", "warning", render=False)}</div></div>'
                   f'<div class="recommendation-reason">{escape(str(reason))}</div>'
                   f'<div class="news-meta">{" · ".join(details)}</div></div>')


def render_news_card(title, source, published_at, sentiment, url):
    parsed = urlparse(str(url or "")); safe_url = str(url) if parsed.scheme in {"http", "https"} else "#"
    return _render(f'<div class="news-card"><a href="{escape(safe_url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                   f'{escape(str(title or "Untitled headline"))}</a><div class="news-meta"><span>{escape(str(source or "Unknown source"))}</span>'
                   f'<span>{escape(str(published_at or "Time unavailable"))}</span>{render_status_pill(sentiment or "Neutral", "info", render=False)}</div></div>')


def render_strategy_summary_card(strategy):
    strategy = strategy or {}
    return _render(f'<div class="strategy-card section-card"><div class="hero-label">Current strategy</div>'
                   f'<div class="section-title">{escape(str(strategy.get("strategy_name", "Strategy not generated")))}</div>'
                   f'<div class="section-body">{escape(str(strategy.get("reasoning", "Refresh market evidence to generate reasoning.")))}</div>'
                   f'<div class="news-meta">{render_status_pill(strategy.get("market_regime", "Neutral"), "info", render=False)}'
                   f'{render_status_pill(strategy.get("confidence", "Low"), "warning", render=False)}</div></div>')


def render_rebalance_summary(recommendations):
    frame = recommendations if isinstance(recommendations, pd.DataFrame) else pd.DataFrame(recommendations or [])
    actions = frame.get("Action", pd.Series(dtype=str)).astype(str)
    buys = int(actions.str.contains("Buy|add", case=False, regex=True).sum())
    sells = int(actions.str.contains("Sell|reduce", case=False, regex=True).sum())
    reviews = int(actions.str.contains("No trade|review", case=False, regex=True).sum())
    return _render(f'<div class="section-card"><div class="section-title">Executive summary</div><div class="news-meta">'
                   f'{render_status_pill(f"{buys} buy/add", "success", render=False)}'
                   f'{render_status_pill(f"{sells} sell/reduce", "danger", render=False)}'
                   f'{render_status_pill(f"{reviews} review/defer", "warning", render=False)}</div></div>')


# Concise public names used by page code and future UI extensions.
def page_header(title, subtitle, badges=None):
    status = badges[0] if isinstance(badges, (list, tuple)) and badges else badges
    return render_page_header(title, subtitle, status)


def metric_card(label, value, delta=None, tone="neutral"):
    return render_metric_card(label, value, delta, tone)


def status_pill(text, tone="neutral"):
    return render_status_pill(text, tone)


def action_card(title, description, button_label=None):
    action = f'<div class="hero-caption">{escape(str(button_label))}</div>' if button_label else ""
    return _render(f'<div class="section-card"><div class="section-title">{escape(str(title))}</div>'
                   f'<div class="section-body">{escape(str(description))}</div>{action}</div>')


def section_card(title, subtitle=None):
    return render_section_card(title, subtitle)


def alert_card(message, tone="info"):
    return render_alert(message, tone)


def progress_step(label, status):
    return render_flow_steps([{"label": label, "status": status}])


def data_quality_badge(status):
    return render_data_quality_badge(status)


def news_card(title, source, published_at, sentiment, url):
    return render_news_card(title, source, published_at, sentiment, url)


def recommendation_card(action=None, instrument=None, reason=None, score=None, confidence=None, **fields):
    return render_recommendation_card(action, instrument, reason, score, confidence, **fields)


def style_figure(figure, height=390, showlegend=True):
    figure.update_layout(
        height=height, margin=dict(l=18, r=18, t=48, b=18), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter, -apple-system, BlinkMacSystemFont, Segoe UI", color=DESIGN_TOKENS["ink"]),
        title_font=dict(size=16), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        showlegend=showlegend, hoverlabel=dict(bgcolor="#FFFFFF", font_color=DESIGN_TOKENS["ink"]),
    )
    figure.update_xaxes(showgrid=False, zeroline=False)
    figure.update_yaxes(gridcolor="rgba(100,116,139,.12)", zeroline=False)
    return figure


def create_portfolio_value_chart(frame):
    frame = frame if frame is not None else pd.DataFrame()
    figure = px.line(frame, x="date", y="portfolio_value_eur", title="Portfolio value", markers=False)
    figure.update_traces(line=dict(color=DESIGN_TOKENS["primary"], width=3), fill="tozeroy", fillcolor="rgba(23,107,135,.08)")
    return style_figure(figure, showlegend=False)


def create_allocation_chart(frame):
    figure = px.pie(frame, names="category", values="value", hole=.64, title="Allocation")
    figure.update_traces(marker=dict(line=dict(color="#FFFFFF", width=3)), textinfo="percent+label")
    return style_figure(figure, showlegend=False)


def create_current_vs_target_chart(frame):
    figure = px.bar(frame, x="category", y="Weight %", color="Allocation", barmode="group", title="Current vs target",
                    color_discrete_map={"current_weight": DESIGN_TOKENS["primary"], "target_weight": "#A7B0BA"})
    return style_figure(figure)


def create_winners_losers_chart(frame):
    figure = go.Figure(go.Bar(x=frame.get("instrument", []), y=frame.get("daily_gain_eur", []),
                              marker_color=[DESIGN_TOKENS["positive"] if value >= 0 else DESIGN_TOKENS["negative"]
                                            for value in frame.get("daily_gain_eur", [])]))
    figure.update_layout(title="Daily winners and losers")
    return style_figure(figure, showlegend=False)


def create_savings_plan_before_after_chart(frame):
    figure = px.bar(frame, x="Instrument", y="Amount", color="Plan", barmode="group", title="Savings plans before and after",
                    color_discrete_map={"Before": "#A7B0BA", "After": DESIGN_TOKENS["primary"]})
    return style_figure(figure)
