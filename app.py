"""Web app check traffic hàng loạt từ traffic.cv — SaaS dashboard siêu sạch, hiện đại."""

from __future__ import annotations

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
from trafficcv.excel import results_to_dataframe, results_to_xlsx_bytes, results_to_csv_bytes

st.set_page_config(page_title="Check Traffic Hàng Loạt", page_icon="📈", layout="wide")

# ---- Cấu hình lưu trữ cài đặt (settings.json) ----
SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"


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

# ---- Tokens cố định (Design System 'Minimal Clean SaaS') ----
PRIMARY, ACCENT = "#4F46E5", "#8B5CF6"
CYAN = "#06B6D4"
SUCCESS, DANGER, WARNING = "#10B981", "#EF4444", "#F59E0B"
MAX_TABLE_ROWS = 1000

THEMES = {
    "Sáng": dict(
        bg="#F8FAFC", panel="#FFFFFF", border="#E2E8F0", text="#0F172A",
        muted="#64748B", grid="#F1F5F9", inputbg="#FFFFFF",
        sidebar="#FFFFFF", hover="#F1F5F9", headbg="#F8FAFC",
        tablebg="#FFFFFF", tableodd="#F8FAFC", tablehover="#EEF2FF", tableborder="#E2E8F0",
        dlbg="#EEF2FF",
        herobg="#FFFFFF", heroborder="#E2E8F0", herotitle="#0F172A", herodesc="#64748B",
        herobadgebgb="rgba(79, 70, 229, 0.06)", herobadgebord="rgba(99, 102, 241, 0.20)", herobadgetxt="#4F46E5"
    ),
    "Tối": dict(
        bg="#0B0F17", panel="rgba(17, 24, 39, 0.70)", border="rgba(255, 255, 255, 0.08)",
        text="#F8FAFC", muted="#94A3B8", grid="rgba(255, 255, 255, 0.05)",
        inputbg="rgba(15, 23, 42, 0.6)", sidebar="#070A10",
        hover="rgba(255, 255, 255, 0.04)", headbg="#111827",
        tablebg="#0F172A", tableodd="#111827", tablehover="#1E293B", tableborder="rgba(255,255,255,0.08)",
        dlbg="rgba(99, 102, 241, 0.12)",
        herobg="linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 27, 75, 0.90) 50%, rgba(15, 23, 42, 0.98) 100%)",
        heroborder="rgba(255, 255, 255, 0.12)", herotitle="#FFFFFF", herodesc="#94A3B8",
        herobadgebgb="rgba(255, 255, 255, 0.08)", herobadgebord="rgba(255, 255, 255, 0.18)", herobadgetxt="#E2E8F0"
    ),
}

# ================================ Sidebar ================================
with st.sidebar:
    st.markdown('<div style="font-size: 18px; font-weight: 800; color: #4F46E5; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;"><span class="mi">tune</span> Cấu Hình</div>', unsafe_allow_html=True)
    
    theme_index = 1 if saved_conf.get("theme") == "Tối" else 0
    theme_name = st.radio("Giao diện", ["Sáng", "Tối"], index=theme_index, horizontal=True, key="theme")

    speed_val = saved_conf.get("speed", "Vừa")
    speed = st.select_slider("Tốc độ quét", ["An toàn", "Vừa", "Nhanh"], value=speed_val)
    min_delay, max_delay = {"An toàn": (6.0, 12.0), "Vừa": (3.0, 8.0), "Nhanh": (1.5, 4.0)}[speed]

    use_cache_val = saved_conf.get("use_cache", True)
    use_cache = st.toggle("Dùng cache dữ liệu", value=use_cache_val)
    
    force_refresh_val = saved_conf.get("force_refresh", False)
    force_refresh = st.toggle("⚡ Ép quét mới & Ghi đè", value=force_refresh_val, help="Bỏ qua cache, bắt buộc quét mới 100% và ghi đè dữ liệu mới lên Supabase.")
    if force_refresh:
        use_cache = False

    ttl_days_val = int(saved_conf.get("ttl_days", 90))
    ttl_days = st.number_input("Thời hạn Cache (ngày)", 1, 365, ttl_days_val, disabled=not use_cache)
    
    use_parallel_val = saved_conf.get("use_parallel", True)
    use_parallel = st.toggle("Quét song song", value=use_parallel_val)
    concurrency_val = int(saved_conf.get("concurrency", 3))
    concurrency = st.slider("Số luồng Chromium", 1, 5, concurrency_val, disabled=not use_parallel) if use_parallel else 1

    if st.button("🗑️ Xóa Bộ Nhớ Cache", use_container_width=True):
        try:
            from trafficcv.cache import Cache
            c = Cache()
            c.conn.execute("DELETE FROM traffic")
            c.conn.commit()
            c.close()
            st.session_state["results"] = None
            st.toast("Đã xóa sạch bộ nhớ cache!", icon="🧹")
        except Exception:
            pass

    st.markdown('<div style="font-size: 13px; font-weight: 700; margin-top: 16px; margin-bottom: 8px; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px;">🌐 Proxy & Serper Key</div>', unsafe_allow_html=True)
    server_proxies = load_proxies()
    proxy_val = saved_conf.get("proxy_input", "")
    proxy_text = st.text_area("Proxy riêng (tùy chọn)", value=proxy_val, height=70, key="proxy_input", placeholder="http://host:port")
    custom_proxies = [ln.strip() for ln in proxy_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    proxies_list = custom_proxies or server_proxies
    use_proxy = st.toggle(f"Dùng proxy ({len(proxies_list)} IP)", value=bool(proxies_list), disabled=not proxies_list)

    server_serper_keys = load_serper_keys()
    serper_val = saved_conf.get("serper_input", "")
    serper_text = st.text_area("Serper API Key", value=serper_val, height=70, key="serper_input", placeholder="dán key serper.dev…")
    custom_serper_keys = [k.strip() for k in serper_text.splitlines() if k.strip() and not k.strip().startswith("#")]
    serper_keys = custom_serper_keys or server_serper_keys

    st.markdown('<div style="font-size: 13px; font-weight: 700; margin-top: 16px; margin-bottom: 8px; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px;">⚡ Bộ Lọc Dữ Liệu</div>', unsafe_allow_html=True)
    filter_on_val = saved_conf.get("filter_on", False)
    filter_on = st.toggle("Bật bộ lọc traffic", value=filter_on_val)
    
    min_txt_val = saved_conf.get("min_txt", "5k")
    min_txt = st.text_input("Traffic tối thiểu", value=min_txt_val, disabled=not filter_on, placeholder="vd 5k, 1M")
    
    max_txt_val = saved_conf.get("max_txt", "")
    max_txt = st.text_input("Traffic tối đa", value=max_txt_val, disabled=not filter_on, placeholder="không giới hạn")
    
    keep_unknown_val = saved_conf.get("keep_unknown", False)
    keep_unknown = st.toggle("Giữ web không có dữ liệu", value=keep_unknown_val, disabled=not filter_on)
    
    drop_no_site_val = saved_conf.get("drop_no_site", False)
    drop_no_site = st.toggle("Bỏ brand không thấy web", value=drop_no_site_val, disabled=not filter_on)

    current_conf = {
        "theme": theme_name,
        "speed": speed,
        "use_cache": use_cache,
        "force_refresh": force_refresh,
        "ttl_days": int(ttl_days),
        "use_parallel": use_parallel,
        "concurrency": int(concurrency),
        "proxy_input": proxy_text,
        "serper_input": serper_text,
        "filter_on": filter_on,
        "min_txt": min_txt,
        "max_txt": max_txt,
        "keep_unknown": keep_unknown,
        "drop_no_site": drop_no_site,
    }
    if current_conf != saved_conf:
        save_settings(current_conf)

T = THEMES[theme_name]

# ============================ CSS (Clean SaaS Design System) ============================
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0');
    
    .mi {{ font-family:'Material Symbols Rounded'; font-weight:normal; font-style:normal; font-size:18px;
        line-height:1; vertical-align:-3px; margin-right:4px; letter-spacing:normal; text-transform:none;
        white-space:nowrap; -webkit-font-smoothing:antialiased; }}
        
    :root {{ 
        --primary:{PRIMARY}; --accent:{ACCENT}; --cyan:{CYAN};
        --text:{T['text']}; --muted:{T['muted']};
        --panel:{T['panel']}; --border:{T['border']}; 
    }}
    
    html, body, .stApp, [class*="css"] {{ font-family:'Plus Jakarta Sans', sans-serif; }}
    .stApp {{ background:{T['bg']}; }}
    
    /* Ẩn chrome cũ Streamlit */
    #MainMenu, footer, [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stDecoration"], [data-testid="stHeaderActionElements"] {{ display:none !important; }}
    header[data-testid="stHeader"] {{ background:transparent; }}
    
    .block-container {{ padding-top:1rem; max-width:1320px; }}
    
    /* Typography */
    .stApp, .stMarkdown, .stMarkdown p, p, label, span {{ color:{T['text']}; }}
    h1, h2, h3, h4, h5, h6,
    [data-testid="stWidgetLabel"] *, [data-testid="stWidgetLabel"] p {{ 
        color:{T['text']} !important; font-weight:600; letter-spacing: -0.2px; 
    }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{ 
        background:{T['sidebar']}; 
        border-right:1px solid {T['border']}; 
    }}
    
    /* Inputs */
    .stTextArea textarea, .stTextInput input, .stNumberInput input,
    [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="base-input"],
    [data-baseweb="select"]>div {{ 
        background:{T['inputbg']} !important; 
        color:{T['text']} !important;
        border-radius:12px !important; 
        transition: all 0.2s ease;
    }}
    [data-baseweb="textarea"], [data-baseweb="input"] {{ 
        border:1px solid {T['border']} !important; 
    }}
    .stTextArea textarea {{ 
        font-family:'JetBrains Mono', monospace; 
        font-size:13.5px; 
        line-height: 1.6;
    }}
    [data-baseweb="textarea"]:focus-within, [data-baseweb="input"]:focus-within {{ 
        border-color:{PRIMARY} !important; 
        box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important; 
    }}

    /* Stat Cards */
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom: 18px; }}
    .stat {{ 
        background:{T['panel']}; 
        border:1px solid {T['border']}; 
        border-radius:16px; 
        padding:16px 18px;
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.03);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .stat:hover {{
        transform: translateY(-2px);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08);
    }}
    .stat .row {{ display:flex; align-items:center; gap:8px; }}
    .stat .dot {{ width:8px; height:8px; border-radius:50%; box-shadow:0 0 10px currentColor; }}
    .stat .lbl {{ font-size:12px; color:{T['muted']} !important; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; }}
    .stat .val {{ font-size:28px; font-weight:800; color:{T['text']} !important; margin-top:4px; letter-spacing: -0.5px; }}
    
    /* Container Panels */
    [data-testid="stVerticalBlockBorderWrapper"] {{ 
        background:{T['panel']}; 
        border:1px solid {T['border']} !important;
        border-radius:16px; 
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.03);
    }}
    .panel-title {{ 
        display:inline-flex; align-items:center; font-size:12.5px; font-weight:700;
        color:{T['text']} !important; text-transform:uppercase; letter-spacing:.5px; margin:2px 0 12px;
        padding:6px 12px; border-radius:8px; background:{T['headbg']}; border-left:3px solid {PRIMARY}; 
    }}
    .table-title {{ 
        display:inline-flex; align-items:center; gap:8px; color:#fff !important;
        font-size:14px; font-weight:800; letter-spacing:.3px; padding:8px 18px; border-radius:10px;
        background:linear-gradient(135deg, {PRIMARY}, {ACCENT});
        box-shadow:0 8px 20px -6px rgba(99, 102, 241, 0.5); margin:6px 0 14px; 
    }}

    /* Buttons */
    .stButton>button, .stDownloadButton>button {{ 
        border-radius:12px; font-weight:700; font-size:14.5px;
        min-height:46px; padding:.55rem 1.2rem; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); 
    }}
    [data-testid="stBaseButton-primary"] {{ 
        background:linear-gradient(135deg, {PRIMARY}, {ACCENT}) !important;
        border:none !important; 
        box-shadow:0 8px 22px -6px rgba(99,102,241,0.6) !important;
    }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] * {{ color:#fff !important; }}
    .stButton>button:hover {{ 
        transform:translateY(-2px);
        box-shadow:0 14px 28px -8px rgba(99,102,241,0.5) !important; 
    }}
    .stDownloadButton>button {{ background:{T['dlbg']} !important; border:1.5px solid {PRIMARY} !important; }}
    .stDownloadButton>button, .stDownloadButton>button * {{ color:{PRIMARY} !important; }}
    .stDownloadButton>button:hover {{ background:{PRIMARY} !important; }}
    .stDownloadButton>button:hover * {{ color:#fff !important; }}

    /* Chips */
    .chips {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; height:100%; }}
    .chip {{ border:1px solid {T['border']}; border-radius:999px; padding:5px 12px; font-size:12.5px;
        font-weight:600; color:{T['muted']}; background:{T['panel']}; }}
    .chip b {{ color:{T['text']}; }}
    .chip.accent {{ background:rgba(99,102,241,0.12); border-color:rgba(99,102,241,0.3); color:{PRIMARY}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================ Top Header Bar ============================
c_head1, c_head2 = st.columns([4, 1], vertical_alignment="center")

with c_head1:
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:10px; margin-bottom: 2px;">
            <div style="font-size: 24px; font-weight: 800; letter-spacing: -0.6px; color: {T['text']};">
                CheckTraffic <span style="background: linear-gradient(135deg, #4F46E5, #8B5CF6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Pro</span>
            </div>
            <span style="background: rgba(16, 185, 129, 0.1); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.25); padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px;">
                <span style="width:6px; height:6px; border-radius:50%; background:#10B981;"></span> Hybrid Cloud
            </span>
        </div>
        <div style="font-size: 13px; color: {T['muted']}; margin-bottom: 14px;">
            Phân tích Lượt truy cập & Thương hiệu tự động từ traffic.cv
        </div>
        """,
        unsafe_allow_html=True,
    )

with c_head2:
    with st.popover("⚡ REST API", help="Tài liệu & Tích hợp API cho Developer", use_container_width=True):
        st.markdown("### ⚡ CheckTraffic REST API")
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

# =========================== Input Section ===========================
st.text_area("Danh sách website hoặc tên brand", key="domains_input", height=150,
             placeholder="google.com\nNike\nshygems.com\nhttps://glossier.com/",
             help="Mỗi dòng 1 mục. App tự nhận diện Domain hoặc Tên Brand để cào số liệu.")

preview = parse_brand_list(st.session_state.get("domains_input", ""))
ttl_seconds = int(ttl_days) * 24 * 3600
n_domain = sum(1 for x in preview if looks_like_domain(x))
n_brand = len(preview) - n_domain

col_a, col_b = st.columns([1, 2.4])
with col_a:
    start = st.button(":material/play_circle: Bắt đầu check", type="primary", use_container_width=True)
with col_b:
    if preview:
        chips = [f'<span class="chip accent"><b>{len(preview)}</b> mục</span>']
        if n_domain:
            chips.append(f'<span class="chip">{n_domain} website</span>')
        if n_brand:
            chips.append(f'<span class="chip">{n_brand} tên brand</span>')
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
            <td style="padding:10px 14px; font-weight:600">{r['Brand']}</td>
            <td style="padding:10px 14px; font-family:'JetBrains Mono',monospace">{r['Website']}</td>
            <td style="padding:10px 14px; font-weight:700">{r['Lượt truy cập/tháng']}</td>
            <td style="padding:10px 14px; {trend(r['Xu hướng'])}">{r['Xu hướng']}</td>
            <td style="padding:10px 14px; {change(r['Thay đổi'])}">{r['Thay đổi']}</td>
            <td style="padding:10px 14px">{r['Trang/lượt']}</td>
            <td style="padding:10px 14px">{r['Thời lượng TB']}</td>
            <td style="padding:10px 14px">{r['Tỷ lệ thoát']}</td>
            <td style="padding:10px 14px">{r['Ngày đăng ký']}</td>
            <td style="padding:10px 14px"><span style="color:{st_color}; font-weight:600">{r['Trạng thái']}</span></td>
        </tr>
        """)

    return f"""
    <div style="overflow-x:auto; border-radius:14px; border:1px solid {T['tableborder']}; margin-top:8px">
    <table style="width:100%; border-collapse:collapse; text-align:left; font-size:13px">
        <thead>
            <tr style="background:{T['headbg']}; color:{T['text']}; border-bottom:1.5px solid {T['tableborder']}">
                <th style="padding:12px 14px">Brand</th>
                <th style="padding:12px 14px">Website</th>
                <th style="padding:12px 14px">Lượt truy cập</th>
                <th style="padding:12px 14px">Xu hướng</th>
                <th style="padding:12px 14px">Thay đổi</th>
                <th style="padding:12px 14px">Trang/lượt</th>
                <th style="padding:12px 14px">Thời lượng</th>
                <th style="padding:12px 14px">Tỷ lệ thoát</th>
                <th style="padding:12px 14px">Ngày tạo</th>
                <th style="padding:12px 14px">Trạng thái</th>
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

    col("Brand", "Brand", flex=1, pinned="left")
    col("Website", "Website", flex=1.2)
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
        ".ag-root-wrapper": {"border-radius": "14px", "border": f"1px solid {T['tableborder']}",
                             "background-color": bgf},
        ".ag-header": {"background-image": f"linear-gradient(120deg,{ACCENT},{PRIMARY})",
                       "border-bottom": "none"},
        ".ag-header-cell-label": {"color": "#ffffff", "font-weight": "700", "font-size": "13px"},
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
            "--ag-font-size": "13px",
            "--ag-header-height": "44px",
            "--ag-row-height": "42px",
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
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=5, height=18).encode(
        x=alt.X("Visits:Q", title="Lượt truy cập/tháng", axis=alt.Axis(format="~s")),
        y=alt.Y("Website:N", sort="-x", title=None),
        color=alt.Color("Xu hướng:N",
                        scale=alt.Scale(domain=["Tăng", "Giảm", "—"], range=[SUCCESS, DANGER, T['muted']]),
                        legend=None),
        tooltip=["Website", alt.Tooltip("Visits:Q", format=",")],
    ).properties(height=320)
    return _dark(chart)


def _chart_trend(results):
    up = sum(1 for r in results if r.trend == "Tăng")
    down = sum(1 for r in results if r.trend == "Giảm")
    if up + down == 0:
        return None
    df = pd.DataFrame({"Xu hướng": ["Tăng", "Giảm"], "Số web": [up, down]})
    chart = alt.Chart(df).mark_arc(innerRadius=60, cornerRadius=3).encode(
        theta="Số web:Q",
        color=alt.Color("Xu hướng:N", scale=alt.Scale(domain=["Tăng", "Giảm"], range=[SUCCESS, DANGER]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Xu hướng", "Số web"],
    ).properties(height=320)
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
            table_area.markdown(_table_html(results_to_dataframe(results)), unsafe_allow_html=True)
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
    elif n_brand and not serper_keys:
        st.warning(f"Có {n_brand} tên brand cần tìm web nhưng chưa có Serper API key.")
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
                st.toast("Hoàn tất!", icon="✅")
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
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:16px">bar_chart</span>'
                        'Top website theo lượt truy cập</div>', unsafe_allow_html=True)
            ch = _chart_top(results)
            if ch is not None:
                st.altair_chart(ch, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu để vẽ.")
    with c2:
        with st.container(border=True):
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:16px">donut_small</span>'
                        'Tỷ lệ tăng / giảm</div>', unsafe_allow_html=True)
            ch2 = _chart_trend(results)
            if ch2 is not None:
                st.altair_chart(ch2, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu xu hướng.")

    st.markdown('<div class="table-title"><span class="mi" style="font-size:18px">table_rows</span>'
                'Bảng kết quả</div>', unsafe_allow_html=True)
    _render_grid(results_to_dataframe(results).head(MAX_TABLE_ROWS), key=f"grid_{theme_name}")
    if len(results) > MAX_TABLE_ROWS:
        st.caption(f"Hiển thị {MAX_TABLE_ROWS}/{len(results)} dòng — tải file để xem đầy đủ.")

    st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)
    dl1, dl2 = st.columns(2)
    dl1.download_button(":material/download: Tải Excel (.xlsx)", data=results_to_xlsx_bytes(results),
                        file_name="traffic_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True)
    dl2.download_button(":material/download: Tải CSV", data=results_to_csv_bytes(results),
                        file_name="traffic_results.csv", mime="text/csv",
                        use_container_width=True)
