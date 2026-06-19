"""Premium visual design tokens and Streamlit CSS for Financial Hub."""

from __future__ import annotations

import streamlit as st


DESIGN_TOKENS = {
    "canvas": "#F6F8FB",
    "surface": "#FFFFFF",
    "surface_strong": "#FFFFFF",
    "ink": "#111827",
    "muted": "#6B7280",
    "line": "#E5E7EB",
    "primary": "#0F766E",
    "primary_dark": "#115E59",
    "positive": "#16A34A",
    "negative": "#DC2626",
    "warning": "#D97706",
}


PREMIUM_CSS = r"""
<style>
:root {
  --fh-canvas: #F6F8FB;
  --fh-surface: #FFFFFF;
  --fh-ink: #111827;
  --fh-muted: #6B7280;
  --fh-line: #E5E7EB;
  --fh-primary: #0F766E;
  --fh-primary-dark: #115E59;
  --fh-positive: #16A34A;
  --fh-negative: #DC2626;
  --fh-warning: #D97706;
  --fh-radius-xl: 26px;
  --fh-radius-lg: 20px;
  --fh-shadow: 0 10px 28px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.04);
}

html, body, [class*="css"] { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size:14px; color:var(--fh-ink); }
.stApp {
  color: var(--fh-ink);
  background: linear-gradient(180deg, #FBFCFE 0%, var(--fh-canvas) 24rem, var(--fh-canvas) 100%);
}
.block-container { max-width: 1480px; padding: 2rem 2.35rem 4.5rem; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

/* Premium sidebar */
[data-testid="stSidebar"] {
  background: #FFFFFF;
  border-right: 1px solid var(--fh-line);
}
[data-testid="stSidebar"] > div:first-child { padding: 1.4rem 1.05rem; }
[data-testid="stSidebar"] [role="radiogroup"] { gap: .32rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  min-height: 46px; padding: .66rem .78rem; border-radius: 12px; color:#374151; font-size:1rem;
  transition: background .18s ease, transform .18s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #F0FDFA; color:var(--fh-primary-dark); transform: translateX(2px); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  color: var(--fh-primary-dark); background: #CCFBF1; font-weight: 700;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] { display: none; }

/* Layout primitives */
.app-shell { width: 100%; }
.page-header { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:.15rem 0 1.25rem; }
.page-eyebrow { color:var(--fh-primary); font-size:.76rem; font-weight:750; letter-spacing:.09em; text-transform:uppercase; margin-bottom:.35rem; }
.page-title { margin:0; font-size:clamp(2rem,4vw,3.15rem); line-height:1.04; letter-spacing:-.045em; font-weight:760; color:var(--fh-ink); }
.page-subtitle { margin:.55rem 0 0; max-width:760px; color:var(--fh-muted); font-size:1rem; line-height:1.55; }
.hero-card, .glass-card, .section-card, .strategy-card, .rebalance-action-card {
  border: 1px solid var(--fh-line); background: var(--fh-surface);
  box-shadow: var(--fh-shadow); border-radius: var(--fh-radius-xl);
}
.hero-card { padding:clamp(1.3rem,3vw,2.2rem); margin:.6rem 0 1.2rem; overflow:hidden; position:relative; }
.hero-card::after { content:""; position:absolute; width:240px; height:240px; border-radius:50%; right:-110px; top:-130px; background:rgba(20,184,166,.09); }
.hero-label { color:var(--fh-muted); font-size:.82rem; font-weight:650; letter-spacing:.04em; text-transform:uppercase; }
.hero-title { margin:.35rem 0 .1rem; font-size:1.05rem; font-weight:680; }
.hero-value { margin:.15rem 0; font-size:clamp(2.2rem,5vw,4.1rem); line-height:1; letter-spacing:-.055em; font-weight:760; }
.hero-caption { color:var(--fh-muted); margin-top:.55rem; font-size:.91rem; }
.hero-delta { display:inline-flex; align-items:center; margin-top:.65rem; padding:.35rem .62rem; border-radius:999px; font-size:.82rem; font-weight:700; }
.metric-card { min-height:118px; padding:1.05rem 1.1rem; border:1px solid var(--fh-line); background:#FFFFFF; border-radius:18px; box-shadow:0 5px 16px rgba(15,23,42,.04); }
.metric-label { color:var(--fh-muted); font-size:.78rem; font-weight:650; }
.metric-value { margin:.35rem 0 .25rem; font-size:1.55rem; font-weight:735; letter-spacing:-.035em; }
.metric-delta { font-size:.78rem; font-weight:680; }
.tone-positive { color:var(--fh-positive); } .tone-negative { color:var(--fh-negative); }
.tone-warning { color:var(--fh-warning); } .tone-neutral { color:var(--fh-muted); }
.tone-info { color:var(--fh-primary); }
.section-card { padding:1.2rem 1.25rem; margin:.75rem 0 1rem; }
.section-title { font-size:1.08rem; font-weight:720; letter-spacing:-.02em; margin-bottom:.35rem; }
.section-body { color:var(--fh-muted); line-height:1.55; }

/* Pills and alerts */
.status-pill { display:inline-flex; align-items:center; gap:.36rem; padding:.34rem .62rem; border-radius:999px; font-size:.74rem; font-weight:720; white-space:nowrap; border:1px solid transparent; }
.status-pill::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
.success-pill { color:#116B49; background:#EAF7F0; border-color:#CEEBDD; }
.warning-pill { color:#9A6417; background:#FFF7E8; border-color:#F6E4BD; }
.danger-pill { color:#AC3838; background:#FDF0F0; border-color:#F3D3D3; }
.info-pill { color:#135F79; background:#EAF5F8; border-color:#CDE7EE; }
.neutral-pill { color:#5F6976; background:#F1F3F5; border-color:#E2E6EA; }
.premium-alert { display:flex; gap:.7rem; padding:.85rem 1rem; margin:.55rem 0; border-radius:16px; border:1px solid; font-size:.9rem; line-height:1.48; }
.alert-info { color:#174D61; background:#EFF8FB; border-color:#D3EAF1; }
.alert-success { color:#155E43; background:#EFF9F4; border-color:#D4EDDF; }
.alert-warning { color:#815515; background:#FFF8EB; border-color:#F3E3BF; }
.alert-danger { color:#993A3A; background:#FEF2F2; border-color:#F3D0D0; }

/* Content cards */
.flow-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:.7rem; margin:.8rem 0; }
.flow-step-card { padding:.9rem; border:1px solid var(--fh-line); background:#FFFFFF; border-radius:17px; min-height:95px; }
.flow-number { color:var(--fh-muted); font-size:.7rem; font-weight:750; text-transform:uppercase; }
.flow-name { margin:.25rem 0 .45rem; font-size:.87rem; font-weight:690; }
.insight-card, .news-card { border:1px solid var(--fh-line); background:#FFFFFF; border-radius:18px; padding:1rem 1.05rem; margin:.55rem 0; }
.news-card a { color:var(--fh-ink); text-decoration:none; font-size:1rem; font-weight:680; line-height:1.35; }
.news-card a:hover { color:var(--fh-primary); }
.news-meta { display:flex; flex-wrap:wrap; gap:.45rem; align-items:center; color:var(--fh-muted); font-size:.75rem; margin-top:.5rem; }
.recommendation-card { border:1px solid var(--fh-line); border-left:4px solid var(--fh-primary); background:#FFFFFF; border-radius:18px; padding:1rem 1.05rem; margin:.62rem 0; }
.recommendation-head { display:flex; justify-content:space-between; align-items:center; gap:1rem; }
.recommendation-instrument { font-weight:720; letter-spacing:-.015em; }
.recommendation-reason { color:var(--fh-muted); font-size:.87rem; line-height:1.48; margin-top:.55rem; }
.empty-state { text-align:center; padding:2.2rem 1rem; border:1px dashed rgba(15,23,42,.14); border-radius:20px; background:rgba(255,255,255,.42); }
.empty-state-title { font-weight:720; margin-bottom:.3rem; }.empty-state-message { color:var(--fh-muted); }
.sidebar-brand { padding:.2rem .35rem 1rem; }
.sidebar-title { font-size:1.28rem; font-weight:760; letter-spacing:-.035em; }
.sidebar-subtitle { color:#4B5563; font-size:.82rem; margin-top:.16rem; }
.sidebar-status { margin-top:1rem; padding:.8rem; border:1px solid var(--fh-line); border-radius:14px; background:#F9FAFB; }
.sidebar-status-row { display:flex; align-items:center; justify-content:space-between; gap:.5rem; color:#4B5563; font-size:.78rem; margin:.46rem 0; }
.privacy-footer { margin:2.5rem 0 0; padding-top:1rem; border-top:1px solid var(--fh-line); color:#4B5563; text-align:center; font-size:.82rem; }

/* Streamlit controls */
.stButton > button, .stDownloadButton > button { border-radius:12px !important; min-height:44px; padding:.55rem 1rem; font-weight:700; color:var(--fh-primary-dark); background:#FFFFFF; border:1px solid #99D5CE; transition:all .18s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { transform:translateY(-1px); box-shadow:0 8px 18px rgba(15,23,42,.08); }
.stButton > button[kind="primary"] { background:var(--fh-primary); color:#FFFFFF; border:1px solid var(--fh-primary); box-shadow:0 8px 18px rgba(15,118,110,.20); }
.stButton > button[kind="primary"]:hover { background:var(--fh-primary-dark); color:#FFFFFF; }
.stButton > button:disabled, .stDownloadButton > button:disabled { opacity:1 !important; color:#6B7280 !important; background:#E5E7EB !important; border-color:#D1D5DB !important; box-shadow:none !important; cursor:not-allowed; }
[data-testid="stButton"] button p, [data-testid="stDownloadButton"] button p { color:inherit !important; font-size:.9rem; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:1px solid var(--fh-line); border-radius:18px; overflow:hidden; box-shadow:0 8px 28px rgba(15,23,42,.04); }
[data-baseweb="tab-list"] { gap:.3rem; background:#FFFFFF; border:1px solid var(--fh-line); border-radius:16px; padding:.28rem; flex-wrap:wrap; }
[data-baseweb="tab"] { border-radius:12px; padding:.55rem .78rem; }
[data-baseweb="tab"][aria-selected="true"] { background:white; box-shadow:0 3px 10px rgba(15,23,42,.07); }
[data-testid="stFileUploader"] { border-radius:18px; }
div[data-testid="stExpander"] { border:1px solid var(--fh-line); border-radius:16px; background:#FFFFFF; overflow:hidden; }

@media (max-width: 760px) {
  .block-container { padding:1.25rem .85rem 3.5rem; }
  .page-header { align-items:flex-start; flex-direction:column; }
  .hero-card { border-radius:21px; }
  .metric-card { min-height:104px; }
  [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
  [data-testid="column"] { min-width:min(100%, 240px) !important; flex:1 1 240px !important; }
  .flow-grid { grid-template-columns:1fr 1fr; }
}
</style>
"""


def inject_premium_css() -> None:
    """Apply the design system once per Streamlit rerun."""
    st.markdown(PREMIUM_CSS, unsafe_allow_html=True)
