"""Web app check traffic hàng loạt — UI/UX Pro Max Glassmorphism (One-time Typewriter Title, Icon Popover Fix, Wider Input Frame)."""

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
from trafficcv.brand import load_serper_keys
from trafficcv.cache import Cache
from trafficcv.excel import results_to_dataframe, results_to_xlsx_bytes, results_to_csv_bytes

st.set_page_config(
    page_title="CheckTraffic Pro — Data Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---- Cấu hình lưu trữ cài đặt (settings.json) & Background ----
SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"
LOGO_FILE = Path(__file__).resolve().parent / "logo_b64.txt"
BG_LIGHT_FILE = Path(__file__).resolve().parent / "bg_light_b64.txt"
BG_DARK_FILE = Path(__file__).resolve().parent / "bg_dark_b64.txt"

LOGO_B64 = LOGO_FILE.read_text(encoding="utf-8").strip() if LOGO_FILE.exists() else ""
BG_LIGHT_B64 = BG_LIGHT_FILE.read_text(encoding="utf-8").strip() if BG_LIGHT_FILE.exists() else ""
BG_DARK_B64 = BG_DARK_FILE.read_text(encoding="utf-8").strip() if BG_DARK_FILE.exists() else ""


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
    except Exception:
        pass


saved_conf = load_saved_settings()

# ---- UI-UX Pro Max Design Tokens (Glassmorphism & SaaS Dashboard) ----
PRIMARY = "#1E40AF"      # Deep Royal Blue
ACCENT = "#8B5CF6"       # Electric Violet
SECONDARY = "#3B82F6"    # Slate Blue
CYAN = "#06B6D4"
SUCCESS, DANGER, WARNING = "#10B981", "#EF4444", "#D97706"
MAX_TABLE_ROWS = 1000

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

active_bg_b64 = BG_DARK_B64 if theme_name == "Tối" else BG_LIGHT_B64
bg_css_val = f"url('data:image/jpeg;base64,{active_bg_b64}') center/cover fixed !important;" if active_bg_b64 else f"{T['bg']} !important;"

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
    .stApp {{ background: {bg_css_val} }}
    
    /* Ẩn hoàn toàn Sidebar */
    [data-testid="stSidebar"], [data-testid="stSidebarNav"], [data-testid="stExpandSidebarButton"] {{
        display: none !important;
    }}
    
    /* Ẩn chrome cũ Streamlit */
    #MainMenu, footer, [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stDecoration"], [data-testid="stHeaderActionElements"] {{ display:none !important; }}
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

    /* Typewriter Title Animation — HIỆN 1 LẦN THÔI */
    .typewriter-box {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
    }}
    .typing-container {{
        display: inline-block;
        overflow: hidden;
    }}
    .typing-text {{
        display: inline-block;
        overflow: hidden;
        white-space: nowrap;
        border-right: 2.5px solid {PRIMARY};
        font-size: 14px;
        font-weight: 700;
        color: {T['text']};
        width: 0;
        animation: typing 2.5s steps(42, end) 0.5s 1 forwards, blink .75s step-end 4;
    }}
    @keyframes typing {{
        from {{ width: 0; }}
        to {{ width: 100%; }}
    }}
    @keyframes blink {{
        from, to {{ border-color: transparent; }}
        50% {{ border-color: {PRIMARY}; }}
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

# ============================ Top Header Bar ============================
c_head1, c_head2 = st.columns([5.5, 0.5], vertical_alignment="center")

with c_head1:
    logo_img_html = f'<img src="data:image/jpeg;base64,{LOGO_B64}" style="width:44px; height:44px; border-radius:12px; box-shadow:0 6px 18px rgba(30,64,175,0.25);" />' if LOGO_B64 else '<span class="mi" style="font-size:36px; color:#1E40AF;">show_chart</span>'
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:14px; margin-bottom: 2px;">
            {logo_img_html}
            <div>
                <div style="font-size: 24px; font-weight: 800; letter-spacing: -0.6px; color: {T['text']}; display:flex; align-items:center; gap:8px;">
                    CheckTraffic <span style="background: linear-gradient(135deg, #1E40AF, #3B82F6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Pro</span>
                    <span style="background: rgba(16, 185, 129, 0.1); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.25); padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px;">
                        <span style="width:6px; height:6px; border-radius:50%; background:#10B981;"></span> Hybrid Cloud
                    </span>
                </div>
                <div style="font-size: 13px; color: {T['muted']};">
                    Công cụ phân tích Lượt truy cập & Thương hiệu tự động
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c_head2:
    with st.popover("⚙️", help="Cài đặt & Tài liệu REST API", use_container_width=True):
        st.markdown("### ⚙️ Cài Đặt & REST API")
        
        tab1, tab2, tab3 = st.tabs(["⚙️ Cấu hình", "⚡ Bộ lọc", "🔌 REST API"])
        
        with tab1:
            p_theme = st.radio("Giao diện", ["Sáng", "Tối"], index=0 if saved_conf.get("theme") == "Sáng" else 1, horizontal=True, key="theme_input")
            
            p_speed_val = saved_conf.get("speed", "Vừa")
            p_speed = st.select_slider("Tốc độ quét", ["An toàn", "Vừa", "Nhanh"], value=p_speed_val, key="speed_input")
            
            p_force_refresh_val = saved_conf.get("force_refresh", False)
            p_force_refresh = st.toggle("⚡ Quét mới & Ghi đè Supabase", value=p_force_refresh_val, help="Bỏ qua dữ liệu cũ trong Supabase, cào mới 100% từ live web và ghi đè dữ liệu mới vào Supabase.", key="force_toggle")
            use_cache = not p_force_refresh
            
            p_use_parallel = st.toggle("Quét song song", value=saved_conf.get("use_parallel", True), key="parallel_toggle")
            p_concurrency = st.slider("Số luồng Chromium", 1, 5, int(saved_conf.get("concurrency", 3)), disabled=not p_use_parallel, key="concurrency_input") if p_use_parallel else 1

            p_proxy_text = st.text_area("Proxy riêng (tùy chọn)", value=saved_conf.get("proxy_input", ""), height=65, key="proxy_input", placeholder="http://host:port")

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
                    label="⬇️ Tải HD Tích Hợp AI (.md)",
                    data=guide_file.read_bytes(),
                    file_name="CHECK_TRAFFIC_API.md",
                    mime="text/markdown",
                    use_container_width=True
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
            save_settings(current_conf)

# Bind active variables
speed = saved_conf.get("speed", "Vừa")
min_delay, max_delay = {"An toàn": (6.0, 12.0), "Vừa": (3.0, 8.0), "Nhanh": (1.5, 4.0)}[speed]
use_cache = saved_conf.get("use_cache", True)
force_refresh = saved_conf.get("force_refresh", False)
if force_refresh:
    use_cache = False
ttl_days = saved_conf.get("ttl_days", 90)
use_parallel = saved_conf.get("use_parallel", True)
concurrency = saved_conf.get("concurrency", 3) if use_parallel else 1

server_proxies = load_proxies()
proxy_text = saved_conf.get("proxy_input", "")
custom_proxies = [ln.strip() for ln in proxy_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
proxies_list = custom_proxies or server_proxies
use_proxy = bool(proxies_list)

serper_keys = load_serper_keys()

filter_on = saved_conf.get("filter_on", False)
min_txt = saved_conf.get("min_txt", "5k")
max_txt = saved_conf.get("max_txt", "")
keep_unknown = saved_conf.get("keep_unknown", False)
drop_no_site = saved_conf.get("drop_no_site", False)


# =========================== Project Management & Auto-Load ===========================
cache_mgr = Cache()
saved_projects = cache_mgr.get_projects()
project_names = [p["name"] for p in saved_projects]
all_proj_options = ["🌐 Tất cả web tích lũy trong Supabase"] + project_names

# Auto-load initial results from Supabase if session_state["results"] is empty
if "results" not in st.session_state or st.session_state["results"] is None:
    initial_doms = cache_mgr.get_all_saved_domains()
    st.session_state["last_sel_project"] = "🌐 Tất cả web tích lũy trong Supabase"
    if initial_doms:
        initial_map = cache_mgr.get_many(initial_doms)
        st.session_state["results"] = list(initial_map.values())
cache_mgr.close()


# =========================== Input Section ===========================
st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(
        f"""
        <div class="typewriter-box">
            <span class="mi" style="font-size:18px; color:{PRIMARY};">edit_note</span>
            <div class="typing-container">
                <span class="typing-text">Nhập danh sách website hoặc brand tại đây...</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    st.text_area(
        "Danh sách website hoặc tên brand",
        key="domains_input",
        height=180,
        label_visibility="collapsed",
        placeholder="Mỗi dòng 1 mục. Ví dụ:\ngoogle.com\nNike\nshygems.com",
    )

    preview = parse_brand_list(st.session_state.get("domains_input", ""))
    ttl_seconds = 3650 * 24 * 3600  # Vô thời hạn (chỉ làm mới khi bật nút Quét mới & Ghi đè)
    n_domain = sum(1 for x in preview if looks_like_domain(x))
    n_brand = len(preview) - n_domain

    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
    col_a, col_b = st.columns([1.3, 3.7], vertical_alignment="center")
    with col_a:
        start = st.button(":material/play_circle: Bắt đầu check", type="primary", use_container_width=True)
    with col_b:
        if preview:
            chips = [f'<span class="chip accent"><b>{len(preview)}</b> mục tổng</span>']
            if n_domain:
                chips.append(f'<span class="chip">🌐 <b>{n_domain}</b> website</span>')
            if n_brand:
                chips.append(f'<span class="chip">🏷️ <b>{n_brand}</b> tên brand</span>')
            st.markdown(f'<div class="chips">{"".join(chips)}</div>', unsafe_allow_html=True)


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
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, filter=True, resizable=True)

    def col(field, name, width=None, flex=None, cell_style=None, pinned=None):
        kw = {"headerName": name}
        if width: kw["width"] = width
        if flex: kw["flex"] = flex
        if cell_style: kw["cellStyle"] = cell_style
        if pinned: kw["pinned"] = pinned
        gb.configure_column(field, **kw)

    col("Website", "Website", flex=1.2, pinned="left")
    col("Lượt truy cập/tháng", "Lượt truy cập/tháng", width=140)
    col("Xu hướng", "Xu hướng", width=110,
        cell_style=JsCode(f"params => params.value === 'Tăng' ? {{'color': '{SUCCESS}', 'fontWeight': '700'}} : (params.value === 'Giảm' ? {{'color': '{DANGER}', 'fontWeight': '700'}} : null)"))
    col("Thay đổi", "Thay đổi", width=110,
        cell_style=JsCode(f"params => typeof params.value === 'string' && params.value.startsWith('+') ? {{'color': '{SUCCESS}', 'fontWeight': '700'}} : (typeof params.value === 'string' && params.value.startsWith('-') ? {{'color': '{DANGER}', 'fontWeight': '700'}} : null)"))
    col("Trang/lượt", "Trang/lượt", width=105)
    col("Thời lượng TB", "Thời lượng TB", width=110)
    col("Tỷ lệ thoát", "Tỷ lệ thoát", width=110)
    col("Ngày đăng ký", "Ngày đăng ký", width=120)
    col("Trạng thái", "Trạng thái", width=110,
        cell_style=JsCode(f"params => params.value === 'ok' ? {{'color': '{SUCCESS}', 'fontWeight': '700'}} : {{'color': '{DANGER}', 'fontWeight': '700'}}"))

    bgf = T['tablebg']
    css = {
        ".ag-root-wrapper": {"border-radius": "12px", "border": f"1px solid {T['tableborder']}",
                             "background-color": bgf},
        ".ag-header": {"background-image": f"linear-gradient(120deg,{PRIMARY},{SECONDARY})",
                       "border-bottom": "none"},
        ".ag-header-cell-label": {"color": "#ffffff", "font-weight": "700", "font-size": "12.5px"},
        ".ag-header-cell-text": {"white-space": "nowrap", "overflow": "hidden", "text-overflow": "ellipsis"},
        ".ag-header-cell": {"border": "none"},
        ".ag-body-viewport, .ag-center-cols-viewport, .ag-center-cols-clipper, .ag-body, .ag-body-viewport-wrapper": {"background-color": bgf},
        ".ag-row": {"background-color": bgf, "border-color": f"{T['tableborder']} !important"},
        ".ag-row.ag-row-odd": {"background-color": f"{T['tableodd']} !important"},
        ".ag-row.ag-row-hover": {"background-color": f"{T['tablehover']} !important"},
        ".ag-cell, .ag-cell-value": {"color": T['text']},
        ".ag-theme-alpine": {
            "--ag-background-color": T['tablebg'],
            "--ag-odd-row-background-color": T['tableodd'],
            "--ag-foreground-color": T['text'],
            "--ag-data-color": T['text'],
            "--ag-secondary-foreground-color": T['muted'],
            "--ag-border-color": T['tableborder'],
            "--ag-row-hover-color": T['tablehover'],
            "--ag-font-family": "'Plus Jakarta Sans', sans-serif",
            "--ag-font-size": "12.5px",
            "--ag-header-height": "42px",
            "--ag-row-height": "40px",
        },
    }
    AgGrid(df, gridOptions=gb.build(), theme="alpine", custom_css=css,
           allow_unsafe_jscode=True, height=480, update_mode=GridUpdateMode.NO_UPDATE,
           key=key)


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
    cards = [("Tổng", len(results), ACCENT), ("Lấy được", ok, SUCCESS),
             ("Không có dữ liệu", nf, WARNING), ("Lỗi / bị chặn", err, DANGER)]
    html = '<div class="stats">' + "".join(
        f'<div class="stat"><div class="row"><span class="dot" style="color:{c};background:{c}"></span>'
        f'<span class="lbl">{l}</span></div><div class="val">{v}</div></div>' for l, v, c in cards
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _run_and_stream(items, settings, serper_keys=None):
    q: "queue.Queue" = queue.Queue()

    def worker():
        try:
            outcome = run_auto_batch(
                items, serper_keys or [], settings,
                resolve_cb=lambda d, t, b, dom: q.put(("resolve", d, t, b, dom)),
                progress_cb=lambda d, t, r: q.put(("progress", d, t)),
                batch_cb=lambda bi, bt, br: q.put(("batch", br)))
            q.put(("done", outcome))
        except Exception as e:  # noqa: BLE001
            q.put(("error", e))

    threading.Thread(target=worker, daemon=True).start()
    prog_box = st.empty()
    status = st.empty()
    table_area = st.empty()
    results = []
    started = time.time()
    while True:
        kind, *rest = q.get()
        if kind == "resolve":
            done, total, brand, dom = rest
            prog_box.progress(done / total if total else 1.0)
            status.markdown(f":material/search: Đang tìm website từ tên brand... **{done}/{total}**")
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
            table_area.dataframe(results_to_dataframe(results), use_container_width=True, height=350)
        elif kind == "done":
            prog_box.empty()
            status.empty()
            table_area.empty()
            return rest[0]
        else:
            raise rest[0]


# ================================ Run ================================
if start:
    st.session_state["results"] = None
    if not preview:
        st.warning("Chưa có dữ liệu hợp lệ — hãy dán danh sách vào ô trên.")
    else:
        settings = RunSettings(min_delay=min_delay, max_delay=max_delay, use_cache=use_cache,
                               ttl=ttl_seconds, headless=True,
                               proxies=proxies_list if use_proxy else None,
                               concurrency=concurrency)
        try:
            outcome = _run_and_stream(preview, settings, serper_keys=serper_keys)
            st.session_state["results"] = outcome.results
            if outcome.aborted_reason:
                st.error(outcome.aborted_reason)
            else:
                has_exhausted_brand = any(r.status == "no_website" and "Serper" in (r.error or "") for r in outcome.results)
                if has_exhausted_brand:
                    st.toast("Đã quét xong các website! (Một số tên brand hết lượt API Serper)", icon="⚠️")
                else:
                    st.toast("Hoàn tất quét toàn bộ danh sách!", icon="✅")
        except Exception as e:  # noqa: BLE001
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
    all_proj_options = project_names + ["🌐 Tất cả web tích lũy"] if project_names else ["🌐 Tất cả web tích lũy"]
    c_mgr.close()

    # --- Unified Compact Header Bar Above Table ---
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    ch1, ch2, ch3, ch4, ch5, ch6, ch7 = st.columns([1.8, 2.0, 1.1, 1.1, 1.8, 1.1, 1.1], vertical_alignment="center")
    
    with ch1:
        st.markdown(f'<div class="table-title" style="margin:0"><span class="mi" style="font-size:17px">table_rows</span> Kết quả</div>', unsafe_allow_html=True)
    with ch2:
        sel_project = st.selectbox("Dự án", all_proj_options, key="project_select", label_visibility="collapsed")
    with ch3:
        btn_refresh_project = st.button("🔄 Quét lại", use_container_width=True, help="Quét mới 100% từ live web cho tất cả website trong bảng này")
    with ch4:
        with st.popover("💾 Lưu", use_container_width=True):
            st.markdown("##### 💾 Lưu danh sách")
            save_name_input = st.text_input("Tên danh sách", placeholder="Ví dụ: Brand Q3", key="save_project_name")
            btn_save = st.button("Lưu ngay", type="primary", use_container_width=True)
            if btn_save and save_name_input.strip():
                current_res = st.session_state.get("results") or []
                doms_to_save = list({r.domain.lower().strip() for r in current_res if r.domain})
                if not doms_to_save and preview:
                    doms_to_save = list({d.lower().strip() for d in preview if d})
                if doms_to_save:
                    c_m = Cache()
                    c_m.save_project(save_name_input.strip(), doms_to_save)
                    c_m.close()
                    st.toast(f"Đã lưu '{save_name_input.strip()}'!", icon="💾")
                    st.session_state["last_sel_project"] = save_name_input.strip()
                    st.rerun()
                else:
                    st.warning("Chưa có tên miền nào để lưu.")
    with ch5:
        search_kw = st.text_input("Tìm kiếm", placeholder="🔍 Tìm nhanh...", key="table_search_input", label_visibility="collapsed")
    with ch6:
        st.download_button("📥 Excel", data=results_to_xlsx_bytes(results), file_name="traffic_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with ch7:
        st.download_button("📥 CSV", data=results_to_csv_bytes(results), file_name="traffic_results.csv", mime="text/csv", use_container_width=True)

    # Handle project selection or refresh click
    if btn_refresh_project:
        c_m = Cache()
        if sel_project.startswith("🌐"):
            target_domains = c_m.get_all_saved_domains()
        else:
            target_domains = c_m.get_project_domains(sel_project)
        c_m.close()
        if target_domains:
            settings = RunSettings(min_delay=min_delay, max_delay=max_delay, use_cache=False, headless=True, proxies=proxies_list if use_proxy else None, concurrency=concurrency)
            st.toast(f"Đang quét lại {len(target_domains)} website...", icon="🔄")
            outcome = _run_and_stream(target_domains, settings, serper_keys=serper_keys)
            st.session_state["results"] = outcome.results
            c_m = Cache()
            if not sel_project.startswith("🌐"):
                c_m.save_project(sel_project, target_domains)
            c_m.close()
            st.rerun()
    elif sel_project != st.session_state.get("last_sel_project"):
        st.session_state["last_sel_project"] = sel_project
        c_m = Cache()
        if sel_project.startswith("🌐"):
            target_domains = c_m.get_all_saved_domains()
        else:
            target_domains = c_m.get_project_domains(sel_project)
        if target_domains:
            res_map = c_m.get_many(target_domains)
            st.session_state["results"] = list(res_map.values())
        c_m.close()
        st.rerun()

    filtered_results = results
    if search_kw.strip():
        q = search_kw.strip().lower()
        filtered_results = [
            r for r in results
            if q in (r.domain or "").lower()
            or q in (r.brand_name or "").lower()
            or q in (r.monthly_visits_raw or "").lower()
            or q in (r.status or "").lower()
        ]
        st.caption(f"🔍 Tìm thấy **{len(filtered_results)}** / {len(results)} website trùng khớp với từ khóa **'{search_kw.strip()}'**.")

    _render_grid(results_to_dataframe(filtered_results).head(MAX_TABLE_ROWS), key=f"grid_{theme_name}_{hash(search_kw)}")
    if len(filtered_results) > MAX_TABLE_ROWS:
        st.caption(f"Hiển thị {MAX_TABLE_ROWS}/{len(filtered_results)} dòng — tải file để xem đầy đủ.")


# ============================ Footer ============================
st.markdown(
    f"""
    <div style="margin-top: 60px; padding: 24px 0 12px; border-top: 1px solid {T['border']}; font-size: 12.5px; color: {T['muted']}; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-weight: 700; color: {T['text']};">CheckTraffic Pro</span> © 2026 Vibevic Technology Inc. All rights reserved.
        </div>
        <div style="display: flex; gap: 14px; font-weight: 500;">
            <a href="/api/docs" target="_blank" style="color: {PRIMARY}; text-decoration: none; font-weight: 600;">Swagger API Docs</a>
            <span>·</span>
            <span>Version 1.2.0 Pro</span>
        </div>
        <div>
            Powered by <b style="color: {T['text']};">Playwright</b> & <b style="color: {PRIMARY};">Supabase Hybrid Cloud</b>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
