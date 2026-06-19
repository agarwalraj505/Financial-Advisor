"""Premium visual design tokens and Streamlit CSS for Financial Hub."""

from __future__ import annotations

import streamlit as st


DESIGN_TOKENS = {
    "canvas": "#F5F7FA",
    "surface": "rgba(255,255,255,.88)",
    "surface_strong": "#FFFFFF",
    "ink": "#18202A",
    "muted": "#667085",
    "line": "rgba(15,23,42,.08)",
    "primary": "#176B87",
    "primary_dark": "#0C4A60",
    "positive": "#16865A",
    "negative": "#C74747",
    "warning": "#B7791F",
}


PREMIUM_CSS = r"""
<style>
:root {
  --fh-canvas: #F5F7FA;
  --fh-surface: rgba(255,255,255,.88);
  --fh-ink: #18202A;
  --fh-muted: #667085;
  --fh-line: rgba(15,23,42,.08);
  --fh-primary: #176B87;
  --fh-primary-dark: #0C4A60;
  --fh-positive: #16865A;
  --fh-negative: #C74747;
  --fh-warning: #B7791F;
  --fh-radius-xl: 26px;
  --fh-radius-lg: 20px;
  --fh-shadow: 0 16px 48px rgba(15,23,42,.07), 0 2px 8px rgba(15,23,42,.035);
}

html, body, [class*="css"] { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.stApp {
  color: var(--fh-ink);
  background:
    radial-gradient(circle at 15% -10%, rgba(23,107,135,.10), transparent 32rem),
    radial-gradient(circle at 95% 10%, rgba(22,134,90,.06), transparent 30rem),
    linear-gradient(180deg, #FBFCFD 0%, var(--fh-canvas) 60%, #F1F4F7 100%);
}
.block-container { max-width: 1480px; padding: 2rem 2.35rem 4.5rem; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

/* Premium sidebar */
[data-testid="stSidebar"] {
  background: rgba(247,249,251,.91);
  border-right: 1px solid var(--fh-line);
  backdrop-filter: blur(24px) saturate(150%);
}
[data-testid="stSidebar"] > div:first-child { padding: 1.4rem 1.05rem; }
[data-testid="stSidebar"] [role="radiogroup"] { gap: .32rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  min-height: 45px; padding: .62rem .72rem; border-radius: 14px;
  transition: background .18s ease, transform .18s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(23,107,135,.07); transform: translateX(2px); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  color: var(--fh-primary-dark); background: rgba(23,107,135,.11); font-weight: 650;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] { display: none; }

/* Layout primitives */
.app-shell { width: 100%; }
.page-header { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:.15rem 0 1.25rem; }
.page-eyebrow { color:var(--fh-primary); font-size:.76rem; font-weight:750; letter-spacing:.09em; text-transform:uppercase; margin-bottom:.35rem; }
.page-title { margin:0; font-size:clamp(2rem,4vw,3.15rem); line-height:1.04; letter-spacing:-.045em; font-weight:760; color:var(--fh-ink); }
.page-subtitle { margin:.55rem 0 0; max-width:760px; color:var(--fh-muted); font-size:1rem; line-height:1.55; }
.hero-card, .glass-card, .section-card, .strategy-card, .rebalance-action-card {
  border: 1px solid rgba(255,255,255,.8); background: var(--fh-surface);
  box-shadow: var(--fh-shadow); backdrop-filter: blur(22px) saturate(140%);
  border-radius: var(--fh-radius-xl);
}
.hero-card { padding:clamp(1.3rem,3vw,2.2rem); margin:.6rem 0 1.2rem; overflow:hidden; position:relative; }
.hero-card::after { content:""; position:absolute; width:240px; height:240px; border-radius:50%; right:-110px; top:-130px; background:rgba(23,107,135,.1); filter:blur(2px); }
.hero-label { color:var(--fh-muted); font-size:.82rem; font-weight:650; letter-spacing:.04em; text-transform:uppercase; }
.hero-title { margin:.35rem 0 .1rem; font-size:1.05rem; font-weight:680; }
.hero-value { margin:.15rem 0; font-size:clamp(2.2rem,5vw,4.1rem); line-height:1; letter-spacing:-.055em; font-weight:760; }
.hero-caption { color:var(--fh-muted); margin-top:.55rem; font-size:.91rem; }
.hero-delta { display:inline-flex; align-items:center; margin-top:.65rem; padding:.35rem .62rem; border-radius:999px; font-size:.82rem; font-weight:700; }
.metric-card { min-height:122px; padding:1.05rem 1.1rem; border:1px solid var(--fh-line); background:rgba(255,255,255,.72); border-radius:20px; box-shadow:0 7px 22px rgba(15,23,42,.045); }
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
.flow-step-card { padding:.9rem; border:1px solid var(--fh-line); background:rgba(255,255,255,.72); border-radius:17px; min-height:95px; }
.flow-number { color:var(--fh-muted); font-size:.7rem; font-weight:750; text-transform:uppercase; }
.flow-name { margin:.25rem 0 .45rem; font-size:.87rem; font-weight:690; }
.insight-card, .news-card { border:1px solid var(--fh-line); background:rgba(255,255,255,.74); border-radius:19px; padding:1rem 1.05rem; margin:.55rem 0; }
.news-card a { color:var(--fh-ink); text-decoration:none; font-size:1rem; font-weight:680; line-height:1.35; }
.news-card a:hover { color:var(--fh-primary); }
.news-meta { display:flex; flex-wrap:wrap; gap:.45rem; align-items:center; color:var(--fh-muted); font-size:.75rem; margin-top:.5rem; }
.recommendation-card { border:1px solid var(--fh-line); border-left:4px solid var(--fh-primary); background:rgba(255,255,255,.78); border-radius:18px; padding:1rem 1.05rem; margin:.62rem 0; }
.recommendation-head { display:flex; justify-content:space-between; align-items:center; gap:1rem; }
.recommendation-instrument { font-weight:720; letter-spacing:-.015em; }
.recommendation-reason { color:var(--fh-muted); font-size:.87rem; line-height:1.48; margin-top:.55rem; }
.empty-state { text-align:center; padding:2.2rem 1rem; border:1px dashed rgba(15,23,42,.14); border-radius:20px; background:rgba(255,255,255,.42); }
.empty-state-title { font-weight:720; margin-bottom:.3rem; }.empty-state-message { color:var(--fh-muted); }
.sidebar-brand { padding:.2rem .35rem 1rem; }
.sidebar-title { font-size:1.28rem; font-weight:760; letter-spacing:-.035em; }
.sidebar-subtitle { color:var(--fh-muted); font-size:.75rem; margin-top:.1rem; }
.sidebar-status { margin-top:1rem; padding:.75rem; border-top:1px solid var(--fh-line); }
.sidebar-status-row { display:flex; align-items:center; justify-content:space-between; color:var(--fh-muted); font-size:.72rem; margin:.36rem 0; }
.privacy-footer { margin:2.5rem 0 0; padding-top:1rem; border-top:1px solid var(--fh-line); color:var(--fh-muted); text-align:center; font-size:.76rem; }

/* Streamlit controls */
.stButton > button, .stDownloadButton > button { border-radius:999px !important; min-height:42px; padding:.5rem 1rem; font-weight:680; border:1px solid rgba(23,107,135,.18); transition:all .18s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { transform:translateY(-1px); box-shadow:0 8px 18px rgba(15,23,42,.08); }
.stButton > button[kind="primary"] { background:linear-gradient(135deg,var(--fh-primary),var(--fh-primary-dark)); color:white; border:0; box-shadow:0 10px 24px rgba(23,107,135,.22); }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:1px solid var(--fh-line); border-radius:18px; overflow:hidden; box-shadow:0 8px 28px rgba(15,23,42,.04); }
[data-baseweb="tab-list"] { gap:.3rem; background:rgba(255,255,255,.58); border:1px solid var(--fh-line); border-radius:16px; padding:.28rem; }
[data-baseweb="tab"] { border-radius:12px; padding:.55rem .78rem; }
[data-baseweb="tab"][aria-selected="true"] { background:white; box-shadow:0 3px 10px rgba(15,23,42,.07); }
[data-testid="stFileUploader"] { border-radius:18px; }
div[data-testid="stExpander"] { border:1px solid var(--fh-line); border-radius:18px; background:rgba(255,255,255,.58); overflow:hidden; }

@media (max-width: 760px) {
  .block-container { padding:1.25rem .85rem 3.5rem; }
  .page-header { align-items:flex-start; flex-direction:column; }
  .hero-card { border-radius:21px; }
  .metric-card { min-height:104px; }
  [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
  [data-testid="column"] { min-width:min(100%, 240px) !important; flex:1 1 240px !important; }
  .flow-grid { grid-template-columns:1fr 1fr; }
}
@media (prefers-color-scheme: dark) {
  :root { --fh-surface:rgba(23,29,38,.88); --fh-ink:#F1F5F9; --fh-muted:#A8B1BD; --fh-line:rgba(255,255,255,.09); }
  .stApp { background:radial-gradient(circle at 10% 0%,rgba(23,107,135,.2),transparent 35rem),#10141A; }
  [data-testid="stSidebar"] { background:rgba(17,22,29,.92); }
  .metric-card,.flow-step-card,.insight-card,.news-card,.recommendation-card { background:rgba(27,34,44,.8); }
}
</style>
"""


def inject_premium_css() -> None:
    """Apply the design system once per Streamlit rerun."""
    st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

