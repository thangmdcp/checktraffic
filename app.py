"""CheckTraffic Pro — bulk traffic workspace with resumable scans."""

from __future__ import annotations

import base64
import json
import queue
import threading
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode

from trafficcv.scraper import (parse_brand_list, looks_like_domain,
                               filter_results, parse_number)
from trafficcv.runner import RunSettings, run_auto_batch, load_proxies
from trafficcv.browser import parse_proxy_list
from trafficcv.brand import load_serper_keys
from trafficcv.cache import Cache
from trafficcv.excel import results_to_dataframe, results_to_xlsx_bytes, results_to_csv_bytes

APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
LOGO_MARK_FILE = ASSETS_DIR / "checktraffic-mark.svg"
FAVICON_FILE = ASSETS_DIR / "checktraffic-favicon.png"

st.set_page_config(
    page_title="CheckTraffic Pro — Data Intelligence",
    page_icon=str(FAVICON_FILE) if FAVICON_FILE.exists() else "📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---- Cấu hình lưu trữ cài đặt (settings.json) & logo ----
SETTINGS_FILE = APP_DIR / "settings.json"
LOGO_MARK_B64 = (
    base64.b64encode(LOGO_MARK_FILE.read_bytes()).decode("ascii")
    if LOGO_MARK_FILE.exists() else ""
)


def load_saved_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        SETTINGS_FILE.chmod(0o600)
    except Exception:
        pass


saved_conf = load_saved_settings()

if "scan_running" not in st.session_state:
    st.session_state["scan_running"] = False
if "scan_stopping" not in st.session_state:
    st.session_state["scan_stopping"] = False
if "scan_stop_event" not in st.session_state:
    st.session_state["scan_stop_event"] = None
if "scan_worker_thread" not in st.session_state:
    st.session_state["scan_worker_thread"] = None

active_scan_thread = st.session_state.get("scan_worker_thread")
if (st.session_state.get("scan_running") and active_scan_thread is not None
        and not active_scan_thread.is_alive()):
    st.session_state["scan_running"] = False
    st.session_state["scan_stopping"] = False
    st.session_state["scan_worker_thread"] = None
    st.session_state["scan_stop_event"] = None

# ---- UI-UX Pro Max Design Tokens (Glassmorphism & SaaS Dashboard) ----
PRIMARY = "#1E40AF"      # Deep Royal Blue
ACCENT = "#8B5CF6"       # Electric Violet
SECONDARY = "#3B82F6"    # Slate Blue
CYAN = "#06B6D4"
SUCCESS, DANGER, WARNING = "#10B981", "#EF4444", "#D97706"
MAX_TABLE_ROWS = 1000
ALL_PROJECTS_LABEL = "Tất cả website"

THEMES = {
    "Sáng": dict(
        bg="#F8FAFC", panel="rgba(255, 255, 255, 0.88)", border="rgba(226, 232, 240, 0.9)", text="#0F172A",
        muted="#475569", grid="rgba(241, 245, 249, 0.6)", inputbg="rgba(255, 255, 255, 0.95)",
        sidebar="#FFFFFF", hover="rgba(241, 245, 249, 0.7)", headbg="rgba(248, 250, 252, 0.8)",
        tablebg="rgba(255, 255, 255, 0.95)", tableodd="rgba(248, 250, 252, 0.7)", tablehover="#EEF2FF", tableborder="#E2E8F0",
        dlbg="#EEF2FF",
        herobg="rgba(255, 255, 255, 0.85)", heroborder="#E2E8F0", herotitle="#0F172A", herodesc="#475569",
        herobadgebgb="rgba(30, 64, 175, 0.06)", herobadgebord="rgba(30, 64, 175, 0.20)", herobadgetxt="#1E40AF"
    ),
    "Tối": dict(
        bg="#0B0F17", panel="rgba(15, 23, 42, 0.80)", border="rgba(255, 255, 255, 0.12)",
        text="#F8FAFC", muted="#94A3B8", grid="rgba(255, 255, 255, 0.05)",
        inputbg="rgba(15, 23, 42, 0.75)", sidebar="#070A10",
        hover="rgba(255, 255, 255, 0.04)", headbg="rgba(17, 24, 39, 0.8)",
        tablebg="rgba(15, 23, 42, 0.9)", tableodd="rgba(17, 24, 39, 0.8)", tablehover="#1E293B", tableborder="rgba(255,255,255,0.08)",
        dlbg="rgba(99, 102, 241, 0.12)",
        herobg="rgba(15, 23, 42, 0.85)", heroborder="rgba(255, 255, 255, 0.12)", herotitle="#FFFFFF", herodesc="#94A3B8",
        herobadgebgb="rgba(255, 255, 255, 0.08)", herobadgebord="rgba(255, 255, 255, 0.18)", herobadgetxt="#E2E8F0"
    ),
}

theme_name = saved_conf.get("theme", "Sáng")
T = THEMES[theme_name]

# ============================ CSS (Glassmorphism & Typewriter Animation) ============================
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Fira+Code:wght@500;600&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0');
    
    .mi {{ font-family:'Material Symbols Rounded'; font-weight:normal; font-style:normal; font-size:18px;
        line-height:1; vertical-align:-3px; margin-right:4px; letter-spacing:normal; text-transform:none;
        white-space:nowrap; -webkit-font-smoothing:antialiased; }}
        
    :root {{ 
        --primary:{PRIMARY}; --accent:{ACCENT}; --cyan:{CYAN};
        --text:{T['text']}; --muted:{T['muted']};
        --panel:{T['panel']}; --border:{T['border']}; 
    }}
    
    html, body, .stApp {{ font-family:'Plus Jakarta Sans', sans-serif; }}
    .stApp {{ background:{T['bg']} !important; }}
    
    /* Ẩn hoàn toàn Sidebar */
    [data-testid="stSidebar"], [data-testid="stSidebarNav"], [data-testid="stExpandSidebarButton"] {{
        display: none !important;
    }}
    
    /* Ẩn chrome cũ Streamlit */
    #MainMenu, footer, [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stDecoration"], [data-testid="stHeaderActionElements"],
    [data-testid="stStatusWidget"], [data-testid="stElementToolbar"] {{ display:none !important; }}
    header[data-testid="stHeader"] {{ background:transparent; }}
    
    .block-container {{ padding-top:1.2rem; max-width:1320px; }}
    
    /* Typography */
    .stApp, .stMarkdown, .stMarkdown p, p, label, span {{ color:{T['text']}; }}
    h1, h2, h3, h4, h5, h6,
    [data-testid="stWidgetLabel"] *, [data-testid="stWidgetLabel"] p {{ 
        color:{T['text']} !important; font-weight:600; letter-spacing: -0.2px; 
    }}
    
    /* Inputs & Textarea Rộng & Đẹp */
    .stTextArea textarea, .stTextInput input, .stNumberInput input,
    [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="base-input"],
    [data-baseweb="select"]>div {{ 
        background:{T['inputbg']} !important; 
        color:{T['text']} !important;
        border-radius:14px !important; 
        transition: all 0.2s ease;
    }}
    [data-baseweb="textarea"], [data-baseweb="input"] {{ 
        border:1.5px solid {T['border']} !important; 
    }}
    .stTextArea textarea {{ 
        font-family:'Fira Code', monospace; 
        font-size:13.5px; 
        line-height: 1.6;
        padding: 16px 18px;
    }}
    [data-baseweb="textarea"]:focus-within, [data-baseweb="input"]:focus-within {{ 
        border-color:{PRIMARY} !important; 
        box-shadow: 0 0 0 4px rgba(30, 64, 175, 0.15) !important; 
    }}

    /* Stat Cards */
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom: 18px; }}
    .stat {{ 
        background:{T['panel']}; 
        border:1px solid {T['border']}; 
        border-radius:16px; 
        padding:14px 18px;
        backdrop-filter: blur(20px);
        box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .stat:hover {{
        transform: translateY(-2px);
        box-shadow: 0 14px 35px -5px rgba(0, 0, 0, 0.1);
    }}
    .stat .row {{ display:flex; align-items:center; gap:8px; }}
    .stat .dot {{ width:8px; height:8px; border-radius:50%; box-shadow:0 0 10px currentColor; }}
    .stat .lbl {{ font-size:11.5px; color:{T['muted']} !important; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; }}
    .stat .val {{ font-size:28px; font-weight:800; color:{T['text']} !important; margin-top:4px; letter-spacing: -0.5px; font-family:'Fira Code', monospace; }}
    
    /* Container Panels Glassmorphism */
    [data-testid="stVerticalBlockBorderWrapper"] {{ 
        background:{T['panel']} !important; 
        border:1.5px solid rgba(79, 70, 229, 0.2) !important;
        border-radius:20px !important; 
        backdrop-filter: blur(24px) !important;
        box-shadow: 0 14px 45px -10px rgba(30, 64, 175, 0.08) !important;
    }}
    .panel-title {{ 
        display:inline-flex; align-items:center; font-size:12.5px; font-weight:700;
        color:{T['text']} !important; text-transform:uppercase; letter-spacing:.5px; margin:2px 0 12px;
        padding:5px 12px; border-radius:6px; background:{T['headbg']}; border-left:3px solid {PRIMARY}; 
    }}
    .table-title {{ 
        display:inline-flex; align-items:center; gap:8px; color:#fff !important;
        font-size:14px; font-weight:800; letter-spacing:.3px; padding:8px 18px; border-radius:10px;
        background:linear-gradient(135deg, {PRIMARY}, {SECONDARY});
        box-shadow:0 8px 20px -6px rgba(30, 64, 175, 0.5); margin:6px 0 14px; 
    }}

    /* Popover Icon-Only Button — Sửa lỗi click & Căn phải lề */
    div[data-testid="stPopover"] {{
        width: 100% !important;
        display: flex !important;
        justify-content: flex-end !important;
    }}
    div[data-testid="stPopover"] > button {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        width: 40px !important;
        height: 40px !important;
        min-height: 40px !important;
        border-radius: 10px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
    }}
    div[data-testid="stPopover"] > button:hover {{
        background: rgba(30, 64, 175, 0.12) !important;
    }}
    div[data-testid="stPopover"] > button svg {{
        display: none !important; /* Ẩn mũi tên ∨ */
    }}
    div[data-testid="stPopover"] > button p {{
        font-size: 22px !important;
        line-height: 1 !important;
        margin: 0 !important;
    }}

    /* Popover menu popup styling */
    div[data-testid="stPopoverBody"] {{
        border-radius: 16px !important;
        border: 1px solid {T['border']} !important;
        background: {T['panel']} !important;
        box-shadow: 0 20px 50px -10px rgba(0, 0, 0, 0.2) !important;
        backdrop-filter: blur(24px) !important;
        min-width: 360px !important;
    }}

    /* Buttons */
    .stButton>button, .stDownloadButton>button {{ 
        border-radius:12px; font-weight:700; font-size:14.5px;
        min-height:46px; padding:.55rem 1.4rem; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); 
    }}
    [data-testid="stBaseButton-primary"] {{ 
        background:linear-gradient(135deg, {PRIMARY}, {SECONDARY}) !important;
        border:none !important; 
        box-shadow:0 8px 22px -6px rgba(30, 64, 175, 0.6) !important;
    }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] * {{ color:#fff !important; }}
    .stButton>button:hover {{ 
        transform:translateY(-2px);
        box-shadow:0 14px 28px -8px rgba(30, 64, 175, 0.5) !important; 
    }}

    /* Chips */
    .chips {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; height:100%; }}
    .chip {{ border:1px solid {T['border']}; border-radius:999px; padding:4px 12px; font-size:12px;
        font-weight:600; color:{T['muted']}; background:{T['panel']}; }}
    .chip b {{ color:{T['text']}; }}
    .chip.accent {{ background:rgba(30, 64, 175, 0.12); border-color:rgba(30, 64, 175, 0.3); color:{PRIMARY}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# 2026 workspace refresh: giảm nhiễu thị giác, tăng hierarchy và khả năng đọc.
st.markdown(
    f"""
    <style>
    .stApp {{
        background:
            radial-gradient(circle at 8% 0%, rgba(59,130,246,.12), transparent 28%),
            radial-gradient(circle at 92% 8%, rgba(139,92,246,.10), transparent 26%),
            linear-gradient(180deg, {T['bg']} 0%, {T['bg']} 72%, {T['hover']} 100%) !important;
    }}
    .block-container {{ max-width:1440px; padding:1rem 2rem 2.5rem; }}

    .app-topbar {{
        display:flex; align-items:center; gap:13px; padding:8px 0 14px;
    }}
    .app-logo {{
        width:46px; height:46px; border-radius:14px; object-fit:cover;
        box-shadow:0 10px 28px rgba(37,99,235,.25);
    }}
    .brand-line {{ display:flex; align-items:center; gap:9px; flex-wrap:wrap; }}
    .brand-name {{ color:{T['text']} !important; font-size:21px; font-weight:800; letter-spacing:-.7px; }}
    .brand-name em {{ color:{SECONDARY}; font-style:normal; }}
    .health-badge {{
        display:inline-flex; align-items:center; gap:6px; padding:4px 9px;
        border:1px solid rgba(16,185,129,.22); border-radius:999px;
        background:rgba(16,185,129,.08); color:{SUCCESS} !important;
        font-size:10px; font-weight:800; letter-spacing:.04em;
    }}
    .health-badge::before {{ content:""; width:6px; height:6px; border-radius:50%; background:{SUCCESS}; }}

    .workspace-intro {{ margin:12px 0 14px; max-width:850px; }}
    .workspace-title {{
        margin:0; color:{T['text']} !important; font-size:clamp(24px,2.4vw,32px);
        line-height:1.15; font-weight:800; letter-spacing:-1px;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] {{
        background:{T['panel']} !important; border:1px solid {T['border']} !important;
        border-radius:18px !important; backdrop-filter:blur(18px) !important;
        box-shadow:0 18px 50px rgba(15,23,42,.07) !important;
    }}
    [data-testid="stVerticalBlockBorderWrapper"] > div {{ padding:1.15rem 1.2rem !important; }}
    .scan-label {{
        display:flex; align-items:center; justify-content:space-between; gap:12px;
        margin-bottom:10px;
    }}
    .scan-label strong {{ color:{T['text']} !important; font-size:14px; }}
    .scan-label span {{ color:{T['muted']} !important; font-size:11px; }}
    textarea[aria-label="Danh sách website hoặc tên brand"] {{ min-height:220px !important; font-size:13px; }}

    .run-readiness {{ min-height:270px; display:flex; flex-direction:column; }}
    .ready-kicker {{
        color:{T['muted']} !important; font-size:10px; font-weight:800;
        letter-spacing:.12em; text-transform:uppercase;
    }}
    .ready-state {{
        display:flex; align-items:center; gap:9px; margin:8px 0 18px;
        color:{T['text']} !important; font-size:18px; font-weight:800;
    }}
    .ready-state .pulse {{
        width:9px; height:9px; border-radius:50%; background:var(--state-color);
        box-shadow:0 0 0 5px color-mix(in srgb, var(--state-color) 14%, transparent);
    }}
    .ready-row {{
        display:flex; align-items:center; justify-content:space-between; gap:12px;
        padding:11px 0; border-top:1px solid {T['border']};
    }}
    .ready-row span {{ color:{T['muted']} !important; font-size:12px; }}
    .ready-row b {{ color:{T['text']} !important; font-size:12px; text-align:right; }}

    .chips {{ height:auto; min-height:38px; }}
    .chip {{ background:{T['hover']}; border-color:{T['border']}; padding:6px 10px; }}
    .chip.accent {{ color:{SECONDARY}; background:rgba(59,130,246,.10); border-color:rgba(59,130,246,.24); }}

    .stats {{ gap:12px; margin:22px 0 16px; }}
    .stat {{
        position:relative; overflow:hidden; padding:16px 17px; border-radius:16px;
        box-shadow:0 12px 34px rgba(15,23,42,.05);
    }}
    .stat:hover {{ transform:none; box-shadow:0 14px 38px rgba(15,23,42,.08); }}
    .stat-top {{ display:flex; align-items:center; justify-content:space-between; gap:10px; }}
    .stat-icon {{
        width:32px; height:32px; border-radius:10px; display:grid; place-items:center;
        background:color-mix(in srgb, var(--card-color) 12%, transparent);
        color:var(--card-color) !important;
    }}
    .stat .lbl {{ text-transform:none; letter-spacing:0; font-size:11px; }}
    .stat .val {{ font-size:25px; margin-top:10px; }}

    .panel-title {{
        padding:0; border:0; background:transparent; text-transform:none;
        letter-spacing:-.1px; font-size:13px; margin:2px 0 10px;
    }}
    /* Unified controls */
    [data-testid="stWidgetLabel"] p {{
        color:{T['text']} !important; font-size:12px !important; font-weight:700 !important;
        letter-spacing:-.05px !important;
    }}
    .stButton>button, .stDownloadButton>button,
    div[data-testid="stPopover"] > button {{
        min-height:42px !important; border:1px solid {T['border']} !important;
        border-radius:10px !important; background:{T['inputbg']} !important;
        color:{T['text']} !important; box-shadow:0 1px 2px rgba(15,23,42,.04) !important;
        font-size:13px !important; font-weight:700 !important; letter-spacing:-.05px !important;
        transition:border-color .16s ease, background .16s ease, box-shadow .16s ease !important;
    }}
    .stButton>button *, .stDownloadButton>button *,
    div[data-testid="stPopover"] > button * {{ color:inherit !important; }}
    .stButton>button:hover, .stDownloadButton>button:hover,
    div[data-testid="stPopover"] > button:hover {{
        transform:none !important; background:{T['hover']} !important;
        border-color:rgba(59,130,246,.45) !important; box-shadow:0 3px 10px rgba(15,23,42,.07) !important;
    }}
    .stButton>button:focus-visible, .stDownloadButton>button:focus-visible,
    div[data-testid="stPopover"] > button:focus-visible,
    [data-baseweb="select"]>div:focus-within,
    [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within {{
        outline:none !important; border-color:{SECONDARY} !important;
        box-shadow:0 0 0 3px rgba(59,130,246,.16) !important;
    }}
    .stButton>button:disabled, .stDownloadButton>button:disabled {{
        opacity:.42 !important; cursor:not-allowed !important; box-shadow:none !important;
    }}
    [data-testid="stBaseButton-primary"] {{
        background:{SECONDARY} !important; border-color:{SECONDARY} !important;
        color:#fff !important; box-shadow:0 5px 14px rgba(37,99,235,.22) !important;
    }}
    [data-testid="stBaseButton-primary"]:hover {{
        background:#2563EB !important; border-color:#2563EB !important;
        box-shadow:0 7px 18px rgba(37,99,235,.28) !important;
    }}
    [data-testid="stBaseButton-tertiary"] {{
        background:rgba(239,68,68,.07) !important; border-color:rgba(239,68,68,.18) !important;
        color:{DANGER} !important;
    }}
    [data-testid="stBaseButton-tertiary"]:hover {{
        background:rgba(239,68,68,.12) !important; border-color:rgba(239,68,68,.35) !important;
    }}

    /* Inputs and dropdowns */
    [data-baseweb="input"], [data-baseweb="textarea"],
    [data-baseweb="select"]>div {{
        min-height:42px !important; border:1px solid {T['border']} !important;
        border-radius:10px !important; background:{T['inputbg']} !important;
        box-shadow:0 1px 2px rgba(15,23,42,.03) !important;
    }}
    [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
    [data-baseweb="select"] * {{ color:{T['text']} !important; font-size:13px !important; }}
    [data-baseweb="input"] input::placeholder, [data-baseweb="textarea"] textarea::placeholder {{
        color:{T['muted']} !important; opacity:.72 !important;
    }}
    [data-baseweb="select"]>div:hover {{ border-color:rgba(59,130,246,.42) !important; }}
    [data-baseweb="popover"] ul[role="listbox"] {{
        padding:5px !important; border:1px solid {T['border']} !important;
        border-radius:11px !important; background:{T['sidebar']} !important;
        box-shadow:0 16px 40px rgba(15,23,42,.14) !important;
    }}
    [data-baseweb="popover"] li[role="option"] {{
        min-height:38px !important; margin:2px 0 !important; border-radius:8px !important;
        color:{T['text']} !important; font-size:13px !important;
    }}
    [data-baseweb="popover"] li[role="option"]:hover {{ background:{T['hover']} !important; }}
    [data-baseweb="popover"] li[role="option"][aria-selected="true"] {{
        background:rgba(59,130,246,.12) !important; color:{SECONDARY} !important;
    }}

    /* Tabs as a compact segmented nav */
    div[data-baseweb="tab-list"] {{
        gap:4px !important; padding:4px !important; border-radius:11px !important;
        background:{T['hover']} !important;
    }}
    button[data-baseweb="tab"] {{
        height:38px !important; padding:0 14px !important; border-radius:8px !important;
        color:{T['muted']} !important; font-size:12px !important; font-weight:700 !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        background:{T['inputbg']} !important; color:{T['text']} !important;
        box-shadow:0 2px 8px rgba(15,23,42,.08) !important;
    }}
    div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{ display:none !important; }}

    /* Segmented controls: chỉ tạo pill quanh nhóm nút, không bọc cả label. */
    div[data-testid="stButtonGroup"] {{
        width:auto !important; padding:0 !important; border:0 !important;
        border-radius:0 !important; background:transparent !important;
        box-shadow:none !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"] {{
        display:inline-flex !important; width:auto !important; max-width:100% !important;
        align-self:flex-start !important; gap:5px !important; padding:0 !important;
        border:0 !important; border-radius:0 !important;
        background:transparent !important; box-shadow:none !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"]::after {{
        content:none !important; display:none !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"] button {{
        flex:0 0 auto !important; width:auto !important; min-width:72px !important; min-height:34px !important;
        padding:0 13px !important; border:1px solid transparent !important; border-radius:9px !important;
        background:transparent !important; color:{T['muted']} !important; box-shadow:none !important;
        font-size:12px !important; font-weight:700 !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"] button:hover {{
        background:rgba(59,130,246,.08) !important; color:{T['text']} !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"] button[aria-checked="true"] {{
        background:rgba(59,130,246,.12) !important; color:{SECONDARY} !important;
        border-color:rgba(59,130,246,.24) !important; box-shadow:none !important;
    }}
    div[data-testid="stButtonGroup"] > div[data-baseweb="button-group"] button[aria-checked="true"] * {{
        color:{SECONDARY} !important;
    }}
    button[role="switch"] {{
        width:38px !important; min-width:38px !important; height:22px !important;
        padding:2px !important; border:0 !important; background:#94A3B8 !important;
    }}
    button[role="switch"][aria-checked="true"] {{ background:{SECONDARY} !important; }}

    /* Popovers */
    div[data-testid="stPopover"] > button {{
        width:42px !important; height:42px !important; min-width:42px !important; padding:0 !important;
    }}
    div[data-testid="stPopover"] > button svg {{ display:none !important; }}
    div[data-testid="stPopover"] > button p {{ margin:0 !important; font-size:0 !important; }}
    div[data-testid="stPopover"] > button p span {{ font-size:20px !important; }}
    div[data-testid="stPopoverBody"] {{
        width:min(460px, calc(100vw - 32px)) !important; min-width:0 !important; max-width:460px !important;
        max-height:min(760px, calc(100vh - 40px)) !important; overflow:auto !important;
        padding:14px !important; border:1px solid {T['border']} !important;
        border-radius:16px !important; background:{T['sidebar']} !important;
        box-shadow:0 24px 70px rgba(15,23,42,.18) !important; backdrop-filter:blur(20px) !important;
    }}
    div[data-testid="stPopoverBody"] h3 {{ font-size:18px !important; margin:0 0 4px !important; }}
    div[data-testid="stPopoverBody"] h5 {{ font-size:14px !important; margin:0 !important; }}
    div[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{ gap:.72rem !important; }}
    .app-footer {{
        display:flex; align-items:center; justify-content:center; gap:10px; margin-top:42px;
        padding:18px 0 4px; border-top:1px solid {T['border']}; color:{T['muted']} !important;
        font-size:11px;
    }}
    .app-footer b {{ color:{T['text']} !important; }}
    .app-footer a {{ color:{SECONDARY} !important; text-decoration:none; font-weight:700; }}

    @media (max-width:900px) {{
        .block-container {{ padding:1rem 1rem 2rem; }}
        .stats {{ grid-template-columns:repeat(2,1fr); }}
        .workspace-title {{ font-size:28px; }}
    }}
    @media (max-width:540px) {{
        .stats {{ grid-template-columns:1fr; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================ Top Header Bar ============================
c_head1, c_head2 = st.columns([5.5, 0.5], vertical_alignment="center")

with c_head1:
    logo_img_html = f'<img class="app-logo" src="data:image/svg+xml;base64,{LOGO_MARK_B64}" alt="CheckTraffic Pro" />' if LOGO_MARK_B64 else '<span class="mi app-logo" style="display:grid;place-items:center;font-size:28px;color:#2563EB;">query_stats</span>'
    st.markdown(
        f"""
        <div class="app-topbar">
            {logo_img_html}
            <div>
                <div class="brand-line">
                    <span class="brand-name">CheckTraffic <em>Pro</em></span>
                    <span class="health-badge">TỰ LƯU</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c_head2:
    with st.popover(":material/tune:", help="Cài đặt", width="stretch"):
        st.markdown("### Cài đặt")
        
        tab1, tab2, tab3 = st.tabs(["Cấu hình", "Bộ lọc", "API"])
        
        with tab1:
            p_theme = st.segmented_control(
                "Giao diện",
                ["Sáng", "Tối"],
                default=saved_conf.get("theme", "Sáng"),
                key="theme_input",
                width="content",
            ) or saved_conf.get("theme", "Sáng")
            
            p_speed_val = saved_conf.get("speed", "Vừa")
            p_speed = st.segmented_control(
                "Tốc độ quét",
                ["An toàn", "Vừa", "Nhanh"],
                default=p_speed_val,
                key="speed_input",
                width="content",
            ) or p_speed_val
            
            p_force_refresh_val = saved_conf.get("force_refresh", False)
            p_force_refresh = st.toggle("Bỏ cache khi quét", value=p_force_refresh_val, help="Lấy lại dữ liệu live và ghi đè kết quả cũ.", key="force_toggle")
            use_cache = not p_force_refresh
            
            p_use_parallel = st.toggle("Quét song song", value=saved_conf.get("use_parallel", True), key="parallel_toggle")
            current_concurrency = max(1, min(5, int(saved_conf.get("concurrency", 3))))
            p_concurrency = st.selectbox(
                "Số worker",
                list(range(1, 6)),
                index=current_concurrency - 1,
                disabled=not p_use_parallel,
                key="concurrency_input",
            ) if p_use_parallel else 1

            p_proxy_text = st.text_area(
                "Danh sách proxy (mỗi dòng một proxy)",
                value=saved_conf.get("proxy_input", ""),
                height=120,
                key="proxy_input",
                placeholder=("host:port\nhost:port:user:password\n"
                             "http://user:password@host:port\nsocks5://host:port"),
                help=("Hỗ trợ HTTP, HTTPS và SOCKS5. Mỗi worker chỉ dùng một proxy; "
                      "proxy có tài khoản dùng dạng user:password@host:port."),
            )
            parsed_proxy_preview, proxy_preview_errors = parse_proxy_list(p_proxy_text)
            if parsed_proxy_preview:
                st.success(f"Đã nhận {len(parsed_proxy_preview)} proxy hợp lệ.", icon="✅")
            if proxy_preview_errors:
                error_lines = ", ".join(
                    f"dòng {line_no}: {message}" for line_no, message in proxy_preview_errors[:5]
                )
                st.warning(f"Bỏ qua proxy sai — {error_lines}")

        with tab2:
            p_filter_on = st.toggle("Bật bộ lọc traffic", value=saved_conf.get("filter_on", False), key="filter_toggle")
            p_min_txt = st.text_input("Traffic tối thiểu", value=saved_conf.get("min_txt", "5k"), disabled=not p_filter_on, key="min_input")
            p_max_txt = st.text_input("Traffic tối đa", value=saved_conf.get("max_txt", ""), disabled=not p_filter_on, key="max_input")
            p_keep_unknown = st.toggle("Giữ web không có dữ liệu", value=saved_conf.get("keep_unknown", False), disabled=not p_filter_on, key="keep_unk_toggle")
            p_drop_no_site = st.toggle("Bỏ brand không thấy web", value=saved_conf.get("drop_no_site", False), disabled=not p_filter_on, key="drop_no_site_toggle")

        with tab3:
            st.markdown("**Base URL:** `https://checktraffic.vibevic.com`  \n"
                        "**POST Check:** `/api/check`  \n"
                        "**GET Cache:** `/api/cache`  \n"
                        "**Swagger UI:** [/api/docs](/api/docs)")
            st.code("""curl -X POST "https://checktraffic.vibevic.com/api/check" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": ["shygems.com"], "use_cache": true}'""", language="bash")
            guide_file = Path(__file__).parent / "CHECK_TRAFFIC_API.md"
            if guide_file.exists():
                st.download_button(
                    label=":material/download: Tải hướng dẫn",
                    data=guide_file.read_bytes(),
                    file_name="CHECK_TRAFFIC_API.md",
                    mime="text/markdown",
                    width="stretch"
                )

        current_conf = {
            "theme": p_theme,
            "speed": p_speed,
            "use_cache": use_cache,
            "force_refresh": p_force_refresh,
            "ttl_days": 3650,
            "use_parallel": p_use_parallel,
            "concurrency": int(p_concurrency),
            "proxy_input": p_proxy_text,
            "serper_input": "",
            "filter_on": p_filter_on,
            "min_txt": p_min_txt,
            "max_txt": p_max_txt,
            "keep_unknown": p_keep_unknown,
            "drop_no_site": p_drop_no_site,
        }
        if current_conf != saved_conf:
            theme_changed = current_conf["theme"] != saved_conf.get("theme", "Sáng")
            save_settings(current_conf)
            if theme_changed:
                st.rerun()

active_conf = current_conf

# Bind active variables
speed = active_conf.get("speed", "Vừa")
min_delay, max_delay = {"An toàn": (6.0, 12.0), "Vừa": (3.0, 8.0), "Nhanh": (1.5, 4.0)}[speed]
use_cache = active_conf.get("use_cache", True)
force_refresh = active_conf.get("force_refresh", False)
if force_refresh:
    use_cache = False
ttl_days = active_conf.get("ttl_days", 90)
use_parallel = active_conf.get("use_parallel", True)
concurrency = active_conf.get("concurrency", 3) if use_parallel else 1

server_proxies = load_proxies()
proxy_text = active_conf.get("proxy_input", "")
has_custom_proxy_text = any(
    line.strip() and not line.strip().startswith("#") for line in proxy_text.splitlines()
)
custom_proxies, custom_proxy_errors = parse_proxy_list(proxy_text)
proxies_list = custom_proxies if has_custom_proxy_text else server_proxies
use_proxy = bool(proxies_list)
proxy_config_invalid = has_custom_proxy_text and not custom_proxies

serper_keys = load_serper_keys()

filter_on = active_conf.get("filter_on", False)
min_txt = active_conf.get("min_txt", "5k")
max_txt = active_conf.get("max_txt", "")
keep_unknown = active_conf.get("keep_unknown", False)
drop_no_site = active_conf.get("drop_no_site", False)


# =========================== Project Management & Auto-Load ===========================
cache_mgr = Cache()
saved_projects = cache_mgr.get_projects()
project_names = [p["name"] for p in saved_projects]
all_proj_options = [ALL_PROJECTS_LABEL] + project_names

# Khôi phục bảng từ cache cả khi lần quét trước dừng/lỗi và để lại results=[].
if not st.session_state.get("results") and not st.session_state.get("scan_running", False):
    initial_doms = cache_mgr.get_all_saved_domains()
    st.session_state["last_sel_project"] = ALL_PROJECTS_LABEL
    if initial_doms:
        initial_map = cache_mgr.get_many(initial_doms)
        st.session_state["results"] = list(initial_map.values())
    else:
        st.session_state["results"] = []
cache_mgr.close()


# =========================== Input Section ===========================
st.markdown(
    """
    <div class="workspace-intro">
        <div class="workspace-title">Quét website hàng loạt</div>
    </div>
    """,
    unsafe_allow_html=True,
)

scan_col, readiness_col = st.columns([4.2, 1.45], gap="large")
with scan_col:
    with st.container(border=True):
        st.markdown(
            '<div class="scan-label"><strong>Danh sách website / brand</strong>'
            '<span>Mỗi dòng một mục</span></div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            "Danh sách website hoặc tên brand",
            key="domains_input",
            height=190,
            label_visibility="collapsed",
            placeholder="Dán danh sách vào đây…",
        )

        st.text_input(
            "Tên dự án / lô quét (tùy chọn)",
            key="project_name_input",
            placeholder="🏷️ Đặt tên lô quét trước khi quét (ví dụ: Goaffpro US 12k, Brand Q3...)",
            help="Nếu nhập tên dự án tại đây, lô quét sẽ tự động lưu thành Dự án trong Supabase ngay khi bắt đầu!",
        )

        preview = parse_brand_list(st.session_state.get("domains_input", ""))
        ttl_seconds = 3650 * 24 * 3600  # Chỉ làm mới khi bật Quét mới & Ghi đè.
        n_domain = sum(1 for x in preview if looks_like_domain(x))
        n_brand = len(preview) - n_domain

        col_a, col_stop, col_b = st.columns([1.25, 1.05, 2.7], vertical_alignment="center")
        with col_a:
            start = st.button(
                ":material/play_arrow: Bắt đầu",
                type="primary",
                width="stretch",
                disabled=st.session_state.get("scan_running", False) or proxy_config_invalid,
            )
            if start:
                scan_stop_event = threading.Event()
                st.session_state["scan_stop_event"] = scan_stop_event
                st.session_state["scan_running"] = True
                st.session_state["scan_stopping"] = False
        with col_stop:
            stop_scan = st.button(
                ":material/stop: Dừng an toàn",
                type="secondary",
                width="stretch",
                disabled=not st.session_state.get("scan_running", False),
                help="Dừng sau lô hiện tại; kết quả thành công đã được checkpoint vào SQLite/Supabase.",
            )
            if stop_scan:
                active_stop_event = st.session_state.get("scan_stop_event")
                if active_stop_event is not None:
                    active_stop_event.set()
                st.session_state["scan_stopping"] = True
        with col_b:
            if preview:
                chips = [f'<span class="chip accent"><b>{len(preview):,}</b> mục</span>']
                if n_domain:
                    chips.append(f'<span class="chip">🌐 <b>{n_domain:,}</b> web</span>')
                if n_brand:
                    chips.append(f'<span class="chip">🏷️ <b>{n_brand:,}</b> brand</span>')
                st.markdown(f'<div class="chips">{"".join(chips)}</div>', unsafe_allow_html=True)

        if proxy_config_invalid:
            st.error("Danh sách proxy chưa có dòng hợp lệ. Sửa proxy trong ⚙️ trước khi bắt đầu.")
        elif st.session_state.get("scan_stopping"):
            st.info("Đang dừng an toàn sau lô hiện tại… các kết quả đã quét vẫn được giữ lại.")

with readiness_col:
    effective_workers = min(concurrency, len(proxies_list)) if proxies_list else concurrency
    checkpoint_count = len(st.session_state.get("results") or [])
    if st.session_state.get("scan_stopping"):
        run_state_label, state_color = "Đang dừng an toàn", WARNING
    elif st.session_state.get("scan_running"):
        run_state_label, state_color = "Đang quét", SECONDARY
    elif proxy_config_invalid:
        run_state_label, state_color = "Cần sửa proxy", DANGER
    else:
        run_state_label, state_color = "Sẵn sàng", SUCCESS
    proxy_mode = f"{len(proxies_list)} proxy" if proxies_list else "Kết nối trực tiếp"
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="run-readiness">
                <div class="ready-kicker">Trạng thái tác vụ</div>
                <div class="ready-state" style="--state-color:{state_color}">
                    <span class="pulse"></span>{run_state_label}
                </div>
                <div class="ready-row"><span>Kết nối</span><b>{proxy_mode}</b></div>
                <div class="ready-row"><span>Worker</span><b>{effective_workers}</b></div>
                <div class="ready-row"><span>Tốc độ</span><b>{speed}</b></div>
                <div class="ready-row"><span>Đã lưu</span><b>{checkpoint_count:,}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================ Helpers: Bảng & Biểu đồ ============================
def _table_html(df: pd.DataFrame) -> str:
    show = df.head(MAX_TABLE_ROWS)

    def trend(v):
        return f"color:{SUCCESS};font-weight:600" if v == "Tăng" else (
            f"color:{DANGER};font-weight:600" if v == "Giảm" else "")

    def change(v):
        if isinstance(v, str) and v.startswith("+"):
            return f"color:{SUCCESS};font-weight:600"
        if isinstance(v, str) and v.startswith("-"):
            return f"color:{DANGER};font-weight:600"
        return ""

    rows = []
    for i, r in show.iterrows():
        bg = T['tableodd'] if i % 2 == 1 else T['tablebg']
        st_color = SUCCESS if r["Trạng thái"] == "ok" else (WARNING if r["Trạng thái"] == "no_website" else DANGER)

        rows.append(f"""
        <tr style="background:{bg}; border-bottom:1px solid {T['tableborder']}">
            <td style="padding:8px 12px; font-family:'Fira Code',monospace; font-weight:700">{r['Website']}</td>
            <td style="padding:8px 12px; font-weight:700; font-family:'Fira Code',monospace">{r['Lượt truy cập/tháng']}</td>
            <td style="padding:8px 12px; {trend(r['Xu hướng'])}">{r['Xu hướng']}</td>
            <td style="padding:8px 12px; {change(r['Thay đổi'])}">{r['Thay đổi']}</td>
            <td style="padding:8px 12px">{r['Trang/lượt']}</td>
            <td style="padding:8px 12px">{r['Thời lượng TB']}</td>
            <td style="padding:8px 12px">{r['Tỷ lệ thoát']}</td>
            <td style="padding:8px 12px">{r['Ngày đăng ký']}</td>
            <td style="padding:8px 12px"><span style="color:{st_color}; font-weight:600">{r['Trạng thái']}</span></td>
        </tr>
        """)

    return f"""
    <div style="overflow-x:auto; border-radius:12px; border:1px solid {T['tableborder']}; margin-top:6px">
    <table style="width:100%; border-collapse:collapse; text-align:left; font-size:12.5px">
        <thead>
            <tr style="background:{T['headbg']}; color:{T['text']}; border-bottom:1.5px solid {T['tableborder']}">
                <th style="padding:10px 12px">Website</th>
                <th style="padding:10px 12px">Lượt truy cập</th>
                <th style="padding:10px 12px">Xu hướng</th>
                <th style="padding:10px 12px">Thay đổi</th>
                <th style="padding:10px 12px">Trang/lượt</th>
                <th style="padding:10px 12px">Thời lượng</th>
                <th style="padding:10px 12px">Tỷ lệ thoát</th>
                <th style="padding:10px 12px">Ngày tạo</th>
                <th style="padding:10px 12px">Trạng thái</th>
            </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
    </table>
    </div>
    """


def _render_grid(df: pd.DataFrame, key: str = "grid"):
    df_clean = df.fillna("")
    st.dataframe(
        df_clean,
        width="stretch",
        height=520,
        hide_index=True,
        column_config={
            "Website": st.column_config.TextColumn("Website", width="medium"),
            "Lượt truy cập/tháng": st.column_config.TextColumn("Lượt truy cập/tháng", width="small"),
            "Xu hướng": st.column_config.TextColumn("Xu hướng", width="small"),
            "Thay đổi": st.column_config.TextColumn("Thay đổi", width="small"),
            "Trang/lượt": st.column_config.TextColumn("Trang/lượt", width="small"),
            "Thời lượng TB": st.column_config.TextColumn("Thời lượng TB", width="small"),
            "Tỷ lệ thoát": st.column_config.TextColumn("Tỷ lệ thoát", width="small"),
            "Ngày đăng ký": st.column_config.TextColumn("Ngày đăng ký", width="small"),
            "Trạng thái": st.column_config.TextColumn("Trạng thái", width="small"),
        }
    )


def _dark(chart):
    return (chart.properties(background="transparent").configure_view(strokeWidth=0)
            .configure_axis(labelColor=T['muted'], titleColor=T['muted'],
                            gridColor=T['grid'], domainColor=T['border'])
            .configure_legend(labelColor=T['text'], titleColor=T['muted']))


def _chart_top(results):
    rows = [{"Website": r.domain, "Visits": r.monthly_visits, "Xu hướng": r.trend or "—"}
            for r in results if r.status == "ok" and r.monthly_visits]
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("Visits", ascending=False).head(12)
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height=16).encode(
        x=alt.X("Visits:Q", title="Lượt truy cập/tháng", axis=alt.Axis(format="~s")),
        y=alt.Y("Website:N", sort="-x", title=None),
        color=alt.Color("Xu hướng:N",
                        scale=alt.Scale(domain=["Tăng", "Giảm", "—"], range=[SUCCESS, DANGER, T['muted']]),
                        legend=None),
        tooltip=["Website", alt.Tooltip("Visits:Q", format=",")],
    ).properties(height=300)
    return _dark(chart)


def _chart_trend(results):
    up = sum(1 for r in results if r.trend == "Tăng")
    down = sum(1 for r in results if r.trend == "Giảm")
    if up + down == 0:
        return None
    df = pd.DataFrame({"Xu hướng": ["Tăng", "Giảm"], "Số web": [up, down]})
    chart = alt.Chart(df).mark_arc(innerRadius=55, cornerRadius=3).encode(
        theta="Số web:Q",
        color=alt.Color("Xu hướng:N", scale=alt.Scale(domain=["Tăng", "Giảm"], range=[SUCCESS, DANGER]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Xu hướng", "Số web"],
    ).properties(height=300)
    return _dark(chart)


def _stats(results):
    ok = sum(1 for r in results if r.status == "ok")
    nf = sum(1 for r in results if r.status in ("not_found", "no_website"))
    err = sum(1 for r in results if r.status in ("error", "blocked"))
    cards = [
        ("Tổng kết quả", len(results), ACCENT, "database"),
        ("Lấy được traffic", ok, SUCCESS, "task_alt"),
        ("Không có dữ liệu", nf, WARNING, "remove_circle"),
        ("Lỗi / bị chặn", err, DANGER, "error"),
    ]
    html = '<div class="stats">' + "".join(
        f'<div class="stat" style="--card-color:{c}"><div class="stat-top">'
        f'<span class="lbl">{l}</span><span class="stat-icon mi">{icon}</span></div>'
        f'<div class="val">{v:,}</div></div>' for l, v, c, icon in cards
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _run_and_stream(items, settings, stop_event, serper_keys=None):
    q: "queue.Queue" = queue.Queue()
    callback_lock = threading.Lock()
    last_event = {"resolve": (0.0, 0), "progress": (0.0, 0)}

    def queue_throttled(kind, done, total, *extra):
        now = time.monotonic()
        with callback_lock:
            last_time, last_done = last_event[kind]
            if done < total and now - last_time < 0.35 and done - last_done < 250:
                return
            last_event[kind] = (now, done)
        q.put((kind, done, total, *extra))

    def worker():
        try:
            outcome = run_auto_batch(
                items, serper_keys or [], settings,
                resolve_cb=lambda d, t, b, dom: queue_throttled("resolve", d, t, b, dom),
                cache_progress_cb=lambda d, t: q.put(("cache", d, t)),
                resume_cb=lambda cached, pending: q.put(("resume", cached, pending)),
                run_state_cb=lambda phase, worker_no, seconds: q.put(
                    ("run_state", phase, worker_no, seconds)
                ),
                progress_cb=lambda d, t, r: queue_throttled("progress", d, t),
                batch_cb=lambda bi, bt, br: q.put(("batch", br)),
                should_stop=stop_event.is_set)
            q.put(("done", outcome))
        except Exception as e:  # noqa: BLE001
            q.put(("error", e))

    scan_worker = threading.Thread(target=worker, daemon=True, name="checktraffic-scan")
    st.session_state["scan_worker_thread"] = scan_worker
    scan_worker.start()
    prog_box = st.empty()
    status = st.empty()
    table_area = st.empty()
    results = []
    started = time.time()
    last_table_render = 0.0
    try:
        while True:
            kind, *rest = q.get()
            if kind == "resolve":
                done, total, brand, dom = rest
                prog_box.progress(done / total if total else 1.0)
                status.markdown(f":material/search: Đang nhận diện website/brand... **{done}/{total}**")
            elif kind == "cache":
                done, total = rest
                prog_box.progress(done / total if total else 1.0)
                status.markdown(f":material/cloud_sync: Đang đối chiếu dữ liệu Supabase... **{done}/{total} lô**")
            elif kind == "resume":
                cached, pending = rest
                total = cached + pending
                prog_box.progress(cached / total if total else 1.0)
                status.markdown(
                    f":material/check_circle: Tiếp tục từ checkpoint: **{cached} đã có** · "
                    f"**{pending} cần check**"
                )
            elif kind == "run_state":
                phase, worker_no, seconds = rest
                if phase == "cooldown":
                    status.warning(
                        f"Worker {worker_no} đang nghỉ {int(seconds)} giây vì traffic.cv trả lỗi/chặn. "
                        "Có thể bấm Dừng an toàn."
                    )
                else:
                    status.info(
                        f"Worker {worker_no} gặp lỗi tạm thời, tự thử lại sau {int(seconds)} giây…"
                    )
            elif kind == "progress":
                done, total = rest[:2]
                prog_box.progress(done / total if total else 1.0)
                elapsed = time.time() - started
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                status.markdown(f":material/monitoring: Check traffic **{done}/{total}** · "
                                f"còn ~**{int(eta // 60)}m{int(eta % 60):02d}s**")
            elif kind == "batch":
                results.extend(rest[0])
                # Giữ ngay kết quả từng lô trong session để bảng không mất nếu
                # worker lỗi hoặc người dùng dừng giữa chừng.
                st.session_state["results"] = results
                now = time.monotonic()
                if now - last_table_render >= 1.5:
                    latest = results[-200:]
                    table_area.dataframe(
                        results_to_dataframe(latest),
                        width="stretch",
                        height=350,
                    )
                    last_table_render = now
            elif kind == "done":
                prog_box.empty()
                status.empty()
                table_area.empty()
                return rest[0]
            else:
                raise rest[0]
    finally:
        stop_event.set()


# ================================ Run ================================
if start:
    st.session_state["results"] = []
    if not preview:
        st.session_state["scan_running"] = False
        st.session_state["scan_stop_event"] = None
        st.warning("Chưa có dữ liệu hợp lệ — hãy dán danh sách vào ô trên.")
    else:
        proj_name = st.session_state.get("project_name_input", "").strip()
        if proj_name:
            c_m = Cache()
            doms_preview = list({d.lower().strip() for d in preview if d})
            if doms_preview:
                c_m.save_project(proj_name, doms_preview)
            c_m.close()
            st.session_state["last_sel_project"] = proj_name
            st.toast(f"Đã gán lô quét vào dự án '{proj_name}'!", icon="📁")

        settings = RunSettings(min_delay=min_delay, max_delay=max_delay, use_cache=use_cache,
                               ttl=ttl_seconds, headless=True,
                               proxies=proxies_list if use_proxy else None,
                               concurrency=concurrency)
        try:
            outcome = _run_and_stream(
                preview,
                settings,
                st.session_state["scan_stop_event"],
                serper_keys=serper_keys,
            )
            st.session_state["results"] = outcome.results
            if proj_name and outcome.results:
                doms_done = list({r.domain.lower().strip() for r in outcome.results if r.domain})
                if doms_done:
                    c_m = Cache()
                    c_m.save_project(proj_name, doms_done)
                    c_m.close()
            st.session_state["scan_running"] = False
            st.session_state["scan_stopping"] = False
            st.session_state["scan_worker_thread"] = None
            st.session_state["scan_stop_event"] = None
            if outcome.cancelled:
                st.warning("Đã dừng an toàn. Mọi kết quả thành công đến lô cuối đã được checkpoint.")
            elif outcome.aborted_reason:
                st.error(outcome.aborted_reason)
            else:
                has_exhausted_brand = any(r.status == "no_website" and "Serper" in (r.error or "") for r in outcome.results)
                if has_exhausted_brand:
                    st.toast("Đã quét xong các website! (Một số tên brand hết lượt API Serper)", icon="⚠️")
                else:
                    st.toast("Hoàn tất quét toàn bộ danh sách!", icon="✅")
        except Exception as e:  # noqa: BLE001
            st.session_state["scan_running"] = False
            st.session_state["scan_stopping"] = False
            st.session_state["scan_worker_thread"] = None
            st.session_state["scan_stop_event"] = None
            st.error(f"Lỗi: {type(e).__name__}: {e}")

# ============================ Kết quả ============================
if st.session_state.get("results"):
    all_results = st.session_state["results"]
    results = all_results
    if filter_on:
        results = filter_results(
            results,
            min_visits=parse_number(min_txt) if min_txt.strip() else None,
            max_visits=parse_number(max_txt) if max_txt.strip() else None,
            keep_unknown=keep_unknown,
            require_website=drop_no_site,
        )

    st.markdown("####  ")
    _stats(results)
    if filter_on:
        st.caption(f"Hiển thị {len(results)}/{len(all_results)} web sau khi lọc.")

    st.markdown("####  ")
    c1, c2 = st.columns([2, 1])
    with c1:
        with st.container(border=True):
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:15px">bar_chart</span>'
                        'Top website theo lượt truy cập</div>', unsafe_allow_html=True)
            ch = _chart_top(results)
            if ch is not None:
                st.altair_chart(ch, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu để vẽ.")
    with c2:
        with st.container(border=True):
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:15px">donut_small</span>'
                        'Tỷ lệ tăng / giảm</div>', unsafe_allow_html=True)
            ch2 = _chart_trend(results)
            if ch2 is not None:
                st.altair_chart(ch2, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu xu hướng.")

    # Project selection logic
    c_mgr = Cache()
    saved_projects = c_mgr.get_projects()
    project_names = [p["name"] for p in saved_projects]
    all_proj_options = [ALL_PROJECTS_LABEL] + project_names
    c_mgr.close()

    # --- Unified Compact Header Bar Above Table ---
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    ch1, ch2, ch3, ch4, ch5, ch6, ch7 = st.columns([2.5, 0.7, 0.7, 0.7, 3.4, 1.0, 1.0], vertical_alignment="center")
    
    with ch1:
        sel_project = st.selectbox("Dự án", all_proj_options, key="project_select", label_visibility="collapsed")
    
    with ch2:
        btn_refresh_project = st.button(":material/refresh:", width="stretch", help="Quét lại dự án")
    
    with ch3:
        with st.popover(":material/folder_managed:", width="stretch", help="Quản lý dự án"):
            st.markdown("##### Quản lý dự án")
            default_name_val = "" if sel_project == ALL_PROJECTS_LABEL else sel_project
            save_name_input = st.text_input("Tên dự án", value=default_name_val, placeholder="Ví dụ: Brand Q3", key="proj_name_edit_input")
            
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                btn_save_new = st.button(":material/save: Lưu", type="primary", width="stretch")
            with b_col2:
                btn_rename = st.button(":material/edit: Đổi tên", width="stretch", disabled=sel_project == ALL_PROJECTS_LABEL)
            
            if sel_project != ALL_PROJECTS_LABEL:
                st.markdown("---")
                btn_del_proj = st.button(":material/delete: Xóa dự án", type="tertiary", width="stretch")
                if btn_del_proj:
                    c_m = Cache()
                    c_m.delete_project(sel_project)
                    c_m.close()
                    st.toast(f"Đã xóa dự án '{sel_project}'!", icon="🗑️")
                    st.session_state["last_sel_project"] = ALL_PROJECTS_LABEL
                    st.rerun()

            if btn_save_new and save_name_input.strip():
                current_res = st.session_state.get("results") or []
                doms_to_save = list({r.domain.lower().strip() for r in current_res if r.domain})
                if not doms_to_save and preview:
                    doms_to_save = list({d.lower().strip() for d in preview if d})
                if doms_to_save:
                    c_m = Cache()
                    c_m.save_project(save_name_input.strip(), doms_to_save)
                    c_m.close()
                    st.toast(f"Đã lưu dự án '{save_name_input.strip()}'!", icon="💾")
                    st.session_state["last_sel_project"] = save_name_input.strip()
                    st.rerun()
            elif btn_rename and save_name_input.strip() and sel_project != ALL_PROJECTS_LABEL:
                c_m = Cache()
                c_m.rename_project(sel_project, save_name_input.strip())
                c_m.close()
                st.toast(f"Đã đổi tên thành '{save_name_input.strip()}'!", icon="✏️")
                st.session_state["last_sel_project"] = save_name_input.strip()
                st.rerun()

    with ch4:
        with st.popover(":material/filter_alt:", width="stretch", help="Lọc kết quả"):
            st.markdown("##### Lọc kết quả")
            flt_on = st.toggle("Bật bộ lọc traffic", value=st.session_state.get("row_flt_on", False), key="row_flt_toggle")
            st.session_state["row_flt_on"] = flt_on
            flt_min = st.text_input("Traffic tối thiểu", value=st.session_state.get("row_flt_min", "5k"), disabled=not flt_on, key="row_flt_min_input")
            st.session_state["row_flt_min"] = flt_min
            flt_max = st.text_input("Traffic tối đa", value=st.session_state.get("row_flt_max", ""), disabled=not flt_on, key="row_flt_max_input")
            st.session_state["row_flt_max"] = flt_max
            flt_keep_unk = st.toggle("Giữ web không có dữ liệu", value=st.session_state.get("row_flt_keep", False), disabled=not flt_on, key="row_flt_keep_toggle")
            st.session_state["row_flt_keep"] = flt_keep_unk
            flt_drop_no_site = st.toggle("Bỏ brand không thấy web", value=st.session_state.get("row_flt_drop", False), disabled=not flt_on, key="row_flt_drop_toggle")
            st.session_state["row_flt_drop"] = flt_drop_no_site
            
            st.markdown("---")
            btn_del_flt_pop = st.button(":material/delete: Xóa kết quả đang lọc", type="tertiary", width="stretch", help="Xóa vĩnh viễn các website đang khớp bộ lọc")
            if btn_del_flt_pop:
                st.session_state["do_delete_filtered"] = True

    with ch5:
        search_kw = st.text_input("Tìm kiếm", placeholder="Tìm website hoặc brand", key="table_search_input", label_visibility="collapsed")

    # Handle project selection or refresh click
    if btn_refresh_project:
        c_m = Cache()
        if sel_project == ALL_PROJECTS_LABEL:
            target_domains = c_m.get_all_saved_domains()
        else:
            target_domains = c_m.get_project_domains(sel_project)
        c_m.close()
        if target_domains:
            settings = RunSettings(min_delay=min_delay, max_delay=max_delay, use_cache=False, headless=True, proxies=proxies_list if use_proxy else None, concurrency=concurrency)
            st.toast(f"Đang quét lại {len(target_domains)} website...", icon="🔄")
            refresh_stop_event = threading.Event()
            st.session_state["scan_stop_event"] = refresh_stop_event
            st.session_state["scan_running"] = True
            st.session_state["scan_stopping"] = False
            try:
                outcome = _run_and_stream(
                    target_domains,
                    settings,
                    refresh_stop_event,
                    serper_keys=serper_keys,
                )
                st.session_state["results"] = outcome.results
            finally:
                st.session_state["scan_running"] = False
                st.session_state["scan_stopping"] = False
                st.session_state["scan_worker_thread"] = None
                st.session_state["scan_stop_event"] = None
            c_m = Cache()
            if sel_project != ALL_PROJECTS_LABEL:
                c_m.save_project(sel_project, target_domains)
            c_m.close()
            st.rerun()
    elif sel_project != st.session_state.get("last_sel_project"):
        st.session_state["last_sel_project"] = sel_project
        c_m = Cache()
        if sel_project == ALL_PROJECTS_LABEL:
            target_domains = c_m.get_all_saved_domains()
        else:
            target_domains = c_m.get_project_domains(sel_project)
        if target_domains:
            res_map = c_m.get_many(target_domains)
            st.session_state["results"] = list(res_map.values())
        c_m.close()
        st.rerun()

    # Apply Traffic Filters if enabled from popover
    filtered_results = results
    if st.session_state.get("row_flt_on"):
        filtered_results = filter_results(
            filtered_results,
            min_visits=parse_number(st.session_state.get("row_flt_min", "")) if st.session_state.get("row_flt_min", "").strip() else None,
            max_visits=parse_number(st.session_state.get("row_flt_max", "")) if st.session_state.get("row_flt_max", "").strip() else None,
            keep_unknown=st.session_state.get("row_flt_keep", False),
            require_website=st.session_state.get("row_flt_drop", False),
        )

    # Apply Instant Search Filter
    if search_kw.strip():
        q = search_kw.strip().lower()
        filtered_results = [
            r for r in filtered_results
            if q in (r.domain or "").lower()
            or q in (r.brand or "").lower()
            or q in (r.monthly_visits_raw or "").lower()
            or q in (r.status or "").lower()
        ]

    is_filtered = len(filtered_results) < len(results) or search_kw.strip() or st.session_state.get("row_flt_on")
    if is_filtered:
        cap_col1, cap_col2 = st.columns([3.5, 1.2], vertical_alignment="center")
        with cap_col1:
            st.caption(f"🔍 Đang lọc hiển thị **{len(filtered_results)}** / {len(results)} website.")
        with cap_col2:
            if st.button(f":material/delete: Xóa {len(filtered_results)} website", key="btn_del_filtered_cap", type="tertiary", width="stretch"):
                st.session_state["do_delete_filtered"] = True

    if st.session_state.get("do_delete_filtered"):
        st.session_state["do_delete_filtered"] = False
        del_doms = [r.domain for r in filtered_results if r.domain]
        if del_doms:
            c_m = Cache()
            delete_fn = getattr(c_m, "delete_domains", None)
            if delete_fn is None:
                import importlib, trafficcv.cache
                importlib.reload(trafficcv.cache)
                c_m = trafficcv.cache.Cache()
                delete_fn = getattr(c_m, "delete_domains")
            n_del = delete_fn(del_doms)
            c_m.close()
            del_set = {d.lower().strip() for d in del_doms}
            st.session_state["results"] = [r for r in st.session_state["results"] if r.domain and r.domain.lower().strip() not in del_set]
            st.toast(f"Đã xóa vĩnh viễn {n_del} website khỏi Supabase!", icon="🗑️")
            st.rerun()

    # Render tối đa 1.000 dòng trước. Việc tạo Excel cho hơn 100k kết quả khá
    # nặng và không được phép chặn bảng dữ liệu xuất hiện.
    visible_results = filtered_results[:MAX_TABLE_ROWS]
    _render_grid(results_to_dataframe(visible_results), key=f"grid_{theme_name}")
    if len(filtered_results) > MAX_TABLE_ROWS:
        st.caption(f"Hiển thị {MAX_TABLE_ROWS}/{len(filtered_results)} dòng — tải file để xem đầy đủ.")

    # Không tạo sẵn file cho hơn 100k dòng ở mọi lần rerun. Chuẩn bị theo yêu
    # cầu rồi giữ bytes trong session; nhờ vậy bảng luôn hiện ngay.
    export_signature = (
        id(all_results),
        len(filtered_results),
        sel_project,
        search_kw.strip(),
        bool(filter_on), min_txt, max_txt, bool(keep_unknown), bool(drop_no_site),
        bool(st.session_state.get("row_flt_on")),
        st.session_state.get("row_flt_min", ""),
        st.session_state.get("row_flt_max", ""),
        bool(st.session_state.get("row_flt_keep")),
        bool(st.session_state.get("row_flt_drop")),
    )

    with ch6:
        xlsx_export = st.session_state.get("xlsx_export")
        if xlsx_export and xlsx_export.get("signature") == export_signature:
            st.download_button(
                ":material/download: Tải Excel",
                data=xlsx_export["data"],
                file_name="traffic_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        elif st.button(
            ":material/download: Excel",
            key="prepare_xlsx_export",
            width="stretch",
            help="Chuẩn bị file Excel đầy đủ",
        ):
            with st.spinner("Đang tạo Excel…"):
                st.session_state["xlsx_export"] = {
                    "signature": export_signature,
                    "data": results_to_xlsx_bytes(filtered_results),
                }
            st.rerun()

    with ch7:
        csv_export = st.session_state.get("csv_export")
        if csv_export and csv_export.get("signature") == export_signature:
            st.download_button(
                ":material/download: Tải CSV",
                data=csv_export["data"],
                file_name="traffic_results.csv",
                mime="text/csv",
                width="stretch",
            )
        elif st.button(
            ":material/download: CSV",
            key="prepare_csv_export",
            width="stretch",
            help="Chuẩn bị file CSV đầy đủ",
        ):
            with st.spinner("Đang tạo CSV…"):
                st.session_state["csv_export"] = {
                    "signature": export_signature,
                    "data": results_to_csv_bytes(filtered_results),
                }
            st.rerun()


# ============================ Footer ============================
st.markdown(
    f"""
    <div class="app-footer">
        <b>CheckTraffic Pro</b><span>·</span>
        <a href="/api/docs" target="_blank">API Docs</a><span>·</span>
        <span>v1.2.0</span>
    </div>
    """,
    unsafe_allow_html=True,
)
