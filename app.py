"""Web app check traffic hàng loạt từ traffic.cv — SaaS dashboard, hỗ trợ theme Sáng/Tối."""

from __future__ import annotations

import queue
import threading
import time

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

# ---- Tokens cố định (theo design system 'Dashboard') ----
PRIMARY, ACCENT = "#0C5CAB", "#3B82F6"
SUCCESS, DANGER, WARNING = "#10b981", "#ef4444", "#f59e0b"
MAX_TABLE_ROWS = 1000  # giới hạn dòng hiển thị bảng (file tải về luôn đủ)

THEMES = {
    "Sáng": dict(bg="#EEF2F9", panel="#FFFFFF", border="rgba(15,23,42,.10)", text="#0F172A",
                 muted="#64748B", grid="rgba(15,23,42,.06)", inputbg="#FFFFFF",
                 sidebar="#FFFFFF", hover="#F1F5F9", headbg="#F8FAFC",
                 tablebg="#FFFFFF", tableodd="#F8FAFC", tablehover="#E8EEF8", tableborder="#E2E8F0",
                 dlbg="#E8F0FF"),
    "Tối": dict(bg="#09090B", panel="rgba(255,255,255,.03)", border="rgba(255,255,255,.09)",
                text="#FAFAFA", muted="#A1A1AA", grid="rgba(255,255,255,.06)",
                inputbg="rgba(255,255,255,.03)", sidebar="#0B0B0E",
                hover="rgba(255,255,255,.05)", headbg="#0F1117",
                tablebg="#101014", tableodd="#16161C", tablehover="#20202A", tableborder="#2A2A33",
                dlbg="#1A1A22"),
}

# ================================ Sidebar ================================
with st.sidebar:
    st.header(":material/tune: Thiết lập")
    theme_name = st.radio("Giao diện", ["Sáng", "Tối"], index=0, horizontal=True, key="theme")

    speed = st.select_slider("Tốc độ", ["An toàn", "Vừa", "Nhanh"], value="Vừa")
    min_delay, max_delay = {"An toàn": (6.0, 12.0), "Vừa": (3.0, 8.0), "Nhanh": (1.5, 4.0)}[speed]

    use_cache = st.toggle("Dùng cache", value=True)
    ttl_days = st.number_input("Cache (ngày)", 1, 365, 90, disabled=not use_cache)

    server_proxies = load_proxies()
    proxy_text = st.text_area("Proxy riêng (mỗi dòng 1 cái, tùy chọn)",
                              value="", height=78, key="proxy_input",
                              placeholder="http://host:port\nhttp://user:pass@host:port")
    custom_proxies = [ln.strip() for ln in proxy_text.splitlines()
                      if ln.strip() and not ln.strip().startswith("#")]
    proxies_list = custom_proxies or server_proxies
    use_proxy = st.toggle(f"Dùng proxy ({len(proxies_list)} IP)", value=bool(proxies_list),
                          disabled=not proxies_list)
    if server_proxies and not custom_proxies:
        st.caption(":material/lock: Đang dùng proxy đã cấu hình trên server")

    server_serper_keys = load_serper_keys()
    serper_text = st.text_area("Serper API key riêng (cho dòng là TÊN BRAND)",
                               value="", height=78, key="serper_input",
                               placeholder="dán API key serper.dev…")
    custom_serper_keys = [k.strip() for k in serper_text.splitlines()
                          if k.strip() and not k.strip().startswith("#")]
    serper_keys = custom_serper_keys or server_serper_keys
    st.caption(f":material/key: {len(serper_keys)} Serper key")
    if server_serper_keys and not custom_serper_keys:
        st.caption(":material/lock: Key được lưu trên server và không hiển thị")

    st.divider()
    st.subheader(":material/filter_alt: Lọc traffic")
    filter_on = st.toggle("Bật lọc", value=False)
    min_txt = st.text_input("Tối thiểu", value="5k", disabled=not filter_on, placeholder="vd 5k, 1M")
    max_txt = st.text_input("Tối đa", value="", disabled=not filter_on, placeholder="không giới hạn")
    keep_unknown = st.toggle("Giữ web không có dữ liệu", value=False, disabled=not filter_on)
    drop_no_site = st.toggle("Bỏ brand không tìm thấy web", value=False, disabled=not filter_on)

    st.divider()
    with st.expander(":material/api: REST API cho Dev", expanded=False):
        st.markdown("""
        **Tích hợp API vào Web App khác:**
        - 📄 **Swagger UI:** [/api/docs](/api/docs)
        - ⚡ **POST Check:** `/api/check`
        - 🔍 **GET Cache:** `/api/cache?domain=...`
        
        **Ví dụ cURL:**
        """)
        st.code("""curl -X POST "https://checktraffic.vibevic.com/api/check" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": ["google.com", "Nike"]}'""", language="bash")
        st.caption("📘 Chi tiết xem trong file `API_GUIDE.md` tại repo GitHub.")

T = THEMES[theme_name]

# ============================ CSS (theo theme) ============================
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0');
    .mi {{ font-family:'Material Symbols Rounded'; font-weight:normal; font-style:normal; font-size:20px;
        line-height:1; vertical-align:-5px; margin-right:8px; letter-spacing:normal; text-transform:none;
        white-space:nowrap; -webkit-font-smoothing:antialiased; }}
    :root {{ --primary:{PRIMARY}; --accent:{ACCENT}; --text:{T['text']}; --muted:{T['muted']};
             --panel:{T['panel']}; --border:{T['border']}; }}
    html, body, .stApp, [class*="css"] {{ font-family:'IBM Plex Sans',sans-serif; }}
    .stApp {{ background:{T['bg']}; }}
    /* Ẩn menu Deploy nhưng GIỮ header + nút bung/thu sidebar */
    #MainMenu, footer, [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"],
    [data-testid="stDecoration"], [data-testid="stHeaderActionElements"] {{ display:none !important; }}
    header[data-testid="stHeader"] {{ background:transparent; }}
    /* Nút BUNG sidebar (khi đã thu): nền xanh cho dễ thấy */
    [data-testid="stExpandSidebarButton"] button {{ background:{ACCENT} !important; color:#fff !important;
        border-radius:10px !important; box-shadow:0 6px 16px -6px rgba(59,130,246,.7); }}
    [data-testid="stExpandSidebarButton"] button svg {{ color:#fff !important; fill:#fff !important; }}
    /* Nút THU sidebar (trong sidebar) */
    [data-testid="stSidebarCollapseButton"] button {{ color:{T['text']} !important; }}
    .block-container {{ padding-top:1.2rem; max-width:1320px; }}
    /* Tương phản chữ: luôn nổi bật ở cả 2 theme */
    .stApp, .stMarkdown, .stMarkdown p, p, label, span {{ color:{T['text']}; }}
    h1, h2, h3, h4, h5, h6,
    [data-testid="stWidgetLabel"] *, [data-testid="stWidgetLabel"] p,
    section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown,
    .stRadio label, [data-baseweb="radio"] div {{ color:{T['text']} !important; font-weight:500; }}
    [data-testid="stCaptionContainer"], .stCaption, [data-testid="stCaptionContainer"] * {{ color:{T['muted']} !important; }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{ background:{T['sidebar']}; border-right:1px solid {T['border']}; }}

    /* Inputs */
    .stTextArea textarea, .stTextInput input, .stNumberInput input,
    [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="base-input"],
    [data-baseweb="select"]>div {{ background:{T['inputbg']} !important; color:{T['text']} !important;
        border-radius:12px; }}
    [data-baseweb="textarea"], [data-baseweb="input"] {{ border:1px solid {T['border']} !important; }}
    .stTextArea textarea {{ font-family:'IBM Plex Mono',monospace; font-size:13.5px; }}
    [data-baseweb="textarea"]:focus-within {{ border-color:{ACCENT} !important; box-shadow:0 0 0 3px rgba(59,130,246,.22); }}
    /* placeholder & input chữ luôn rõ theo theme */
    .stTextArea textarea::placeholder, input::placeholder {{ color:{T['muted']} !important; opacity:1 !important; }}
    input:disabled, textarea:disabled {{ -webkit-text-fill-color:{T['muted']} !important; opacity:1 !important; }}

    /* Hero */
    .hero {{ position:relative; overflow:hidden;
        background:linear-gradient(120deg, {PRIMARY} 0%, #0a4a8a 55%, #06294d 100%);
        border:1px solid rgba(255,255,255,.16); border-radius:20px; padding:24px 30px; margin-bottom:22px;
        box-shadow:0 20px 50px -24px rgba(12,92,171,.85), inset 0 1px 0 rgba(255,255,255,.18); }}
    .hero::after {{ content:""; position:absolute; inset:0;
        background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),
                         linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);
        background-size:34px 34px; opacity:.45; pointer-events:none; }}
    .hero h1 {{ font-size:31px; font-weight:700; margin:0 0 4px; color:#fff !important; letter-spacing:-.6px; }}
    .hero p {{ margin:0; font-size:14.5px; color:rgba(255,255,255,.85) !important; }}
    .hero-row {{ display:flex; align-items:center; gap:18px; position:relative; z-index:1; }}
    .hero .logo {{ width:62px; height:62px; min-width:62px; border-radius:16px; display:flex;
        align-items:center; justify-content:center; font-size:32px; background:rgba(255,255,255,.16);
        border:1px solid rgba(255,255,255,.32); box-shadow:inset 0 1px 0 rgba(255,255,255,.3); }}

    /* Stat cards & panels */
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }}
    .stat {{ background:{T['panel']}; border:1px solid {T['border']}; border-radius:16px; padding:16px 18px; }}
    .stat .row {{ display:flex; align-items:center; gap:8px; }}
    .stat .dot {{ width:9px; height:9px; border-radius:50%; box-shadow:0 0 12px currentColor; }}
    .stat .lbl {{ font-size:11.5px; color:{T['muted']} !important; text-transform:uppercase; letter-spacing:.7px; }}
    .stat .val {{ font-size:30px; font-weight:700; color:{T['text']} !important; margin-top:6px; }}
    [data-testid="stVerticalBlockBorderWrapper"] {{ background:{T['panel']}; border:1px solid {T['border']} !important;
        border-radius:16px; }}
    .panel-title {{ display:inline-flex; align-items:center; font-size:12.5px; font-weight:700;
        color:{T['text']} !important; text-transform:uppercase; letter-spacing:.5px; margin:2px 0 12px;
        padding:6px 12px; border-radius:8px; background:{T['headbg']}; border-left:3px solid {ACCENT}; }}
    /* Tiêu đề bảng kết quả: nổi bật, có nền gradient */
    .table-title {{ display:inline-flex; align-items:center; gap:8px; color:#fff !important;
        font-size:14.5px; font-weight:700; letter-spacing:.3px; padding:9px 20px; border-radius:10px;
        background:linear-gradient(120deg,{ACCENT},{PRIMARY});
        box-shadow:0 8px 20px -8px rgba(59,130,246,.65); margin:6px 0 14px; }}

    /* Buttons — dễ nhìn hơn ở cả 2 theme */
    .stButton>button, .stDownloadButton>button {{ border-radius:12px; font-weight:700; font-size:15px;
        min-height:48px; padding:.55rem 1.2rem; transition:transform .08s ease, box-shadow .2s ease; }}
    [data-testid="stBaseButton-primary"] {{ background:linear-gradient(120deg,{ACCENT},{PRIMARY});
        border:none !important; box-shadow:0 12px 28px -10px rgba(59,130,246,.8);
        text-shadow:0 1px 2px rgba(0,0,0,.25); }}
    [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] * {{ color:#fff !important; }}
    .stButton>button:hover, .stDownloadButton>button:hover {{ transform:translateY(-2px);
        box-shadow:0 16px 34px -10px rgba(59,130,246,.6); }}
    .stDownloadButton>button {{ background:{T['dlbg']} !important; border:1.5px solid {ACCENT} !important; }}
    .stDownloadButton>button, .stDownloadButton>button * {{ color:{ACCENT} !important; }}
    .stDownloadButton>button:hover {{ background:{ACCENT} !important; }}
    .stDownloadButton>button:hover * {{ color:#fff !important; }}
    *:focus-visible {{ outline:2px solid {ACCENT} !important; outline-offset:2px; }}

    /* Hero: chữ LUÔN trắng dù theme nào */
    .hero, .hero * {{ color:#fff !important; }}

    /* Chips */
    .chips {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; height:100%; }}
    .chip {{ border:1px solid {T['border']}; border-radius:999px; padding:6px 14px; font-size:13px;
        font-weight:500; color:{T['muted']}; background:{T['panel']}; }}
    .chip b {{ color:{T['text']}; }}
    .chip.accent {{ background:rgba(59,130,246,.14); border-color:rgba(59,130,246,.4); color:{ACCENT}; }}

    /* Bảng HTML */
    .ttable-wrap {{ max-height:560px; overflow:auto; border:1px solid {T['border']}; border-radius:14px; }}
    table.ttable {{ border-collapse:separate; border-spacing:0; width:100%; font-size:13px; color:{T['text']}; }}
    table.ttable th {{ position:sticky; top:0; background:{T['headbg']}; color:{T['muted']}; text-align:left;
        font-weight:600; padding:11px 14px; border-bottom:1px solid {T['border']}; white-space:nowrap; }}
    table.ttable td {{ padding:10px 14px; border-bottom:1px solid {T['border']}; white-space:nowrap; }}
    table.ttable tr:hover td {{ background:{T['hover']}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <div class="hero-row">
            <div class="logo"><span class="mi" style="font-size:34px;margin:0">query_stats</span></div>
            <div>
                <h1 style="color:#fff!important">Check Traffic Hàng Loạt</h1>
                <p style="color:rgba(255,255,255,.9)!important">Kiểm tra lượt truy cập website hàng loạt từ traffic.cv → trực quan hoá → xuất Excel/CSV.</p>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================== Input (tự nhận diện domain / tên brand) ===========================
st.text_area("Danh sách website hoặc tên brand", key="domains_input", height=200,
             placeholder="google.com\nNike\nAtoms shoes\nhttps://glossier.com/",
             help="Mỗi dòng 1 mục. App tự nhận biết: dòng là domain → check thẳng; "
                  "dòng là tên brand → tự tìm website rồi check.")

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


# ============================ Helpers: bảng & biểu đồ ============================
def _table_html(df: pd.DataFrame) -> str:
    show = df.head(MAX_TABLE_ROWS)

    def trend(v):
        return f"color:{SUCCESS};font-weight:600" if v == "Tăng" else (
            f"color:{DANGER};font-weight:600" if v == "Giảm" else "")

    def change(v):
        if isinstance(v, str) and v.startswith("+"):
            return f"color:{SUCCESS}"
        if isinstance(v, str) and v.startswith("-"):
            return f"color:{DANGER}"
        return ""

    sty = show.style
    if "Xu hướng" in show.columns:
        sty = sty.map(trend, subset=["Xu hướng"])
    if "Thay đổi" in show.columns:
        sty = sty.map(change, subset=["Thay đổi"])
    sty = sty.hide(axis="index").set_table_attributes('class="ttable"')
    return f'<div class="ttable-wrap">{sty.to_html()}</div>'


VN_LOCALE = {"noRowsToShow": "Không có dữ liệu", "loadingOoo": "Đang tải…"}


def _render_grid(df: pd.DataFrame, key: str):
    """Bảng AgGrid: click tiêu đề cột để sắp xếp lớn/nhỏ; tiêu đề 1 dòng; cho cuộn ngang."""
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, filter=False, resizable=True,
                                suppressMenu=True, width=150, minWidth=110)
    if "Website" in df.columns:
        gb.configure_column("Website", width=185, minWidth=150)
    trend_js = JsCode(f"""function(p){{
        if(p.value==='Tăng') return {{color:'{SUCCESS}', fontWeight:'700'}};
        if(p.value==='Giảm') return {{color:'{DANGER}', fontWeight:'700'}};
        return {{}};
    }}""")
    change_js = JsCode(f"""function(p){{
        if(p.value && p.value[0]==='+') return {{color:'{SUCCESS}'}};
        if(p.value && p.value[0]==='-') return {{color:'{DANGER}'}};
        return {{}};
    }}""")
    if "Xu hướng" in df.columns:
        gb.configure_column("Xu hướng", cellStyle=trend_js)
    if "Thay đổi" in df.columns:
        gb.configure_column("Thay đổi", cellStyle=change_js)
    # Sắp xếp theo SỐ (34.83K, 1.2M, 2.5B…) thay vì theo chữ
    visits_cmp = JsCode("""function(a,b){
        function n(v){ if(v==null) return 0; v=(''+v).replace(/,/g,'');
            var m=v.match(/([0-9.]+)\\s*([KMB]?)/i); if(!m) return parseFloat(v)||0;
            var x=parseFloat(m[1])||0, s=(m[2]||'').toUpperCase();
            if(s==='K')x*=1e3; else if(s==='M')x*=1e6; else if(s==='B')x*=1e9; return x; }
        return n(a)-n(b); }""")
    num_cmp = JsCode("function(a,b){return (parseFloat(a)||0)-(parseFloat(b)||0);}")
    if "Lượt truy cập/tháng" in df.columns:
        gb.configure_column("Lượt truy cập/tháng", comparator=visits_cmp)
    for c in ("Thay đổi", "Trang/lượt", "Tỷ lệ thoát"):
        if c in df.columns:
            gb.configure_column(c, comparator=num_cmp)
    gb.configure_grid_options(localeText=VN_LOCALE)
    bgf = f"{T['tablebg']} !important"
    css = {
        ".ag-root-wrapper": {"border": f"1px solid {T['tableborder']}", "border-radius": "14px",
                             "background-color": bgf},
        ".ag-header": {"background-image": f"linear-gradient(120deg,{ACCENT},{PRIMARY})",
                       "border-bottom": "none"},
        ".ag-header-cell-label": {"color": "#ffffff", "font-weight": "700", "font-size": "13px"},
        ".ag-header-cell-text": {"white-space": "nowrap", "overflow": "hidden",
                                 "text-overflow": "ellipsis"},
        ".ag-header-cell": {"border": "none"},
        # ép nền tối/sáng cho mọi lớp thân bảng (màu Tăng/Giảm là inline nên không bị ảnh hưởng)
        ".ag-body-viewport, .ag-center-cols-viewport, .ag-center-cols-clipper, "
        ".ag-body, .ag-body-viewport-wrapper": {"background-color": bgf},
        ".ag-row": {"background-color": bgf, "border-color": f"{T['tableborder']} !important"},
        ".ag-row.ag-row-odd": {"background-color": f"{T['tableodd']} !important"},
        ".ag-row.ag-row-hover": {"background-color": f"{T['tablehover']} !important"},
        # chữ ô: KHÔNG !important để cellStyle (Tăng/Giảm) inline vẫn thắng
        ".ag-cell, .ag-cell-value": {"color": T['text']},
        ".ag-theme-alpine": {
            "--ag-background-color": T['tablebg'],
            "--ag-odd-row-background-color": T['tableodd'],
            "--ag-foreground-color": T['text'],
            "--ag-data-color": T['text'],
            "--ag-secondary-foreground-color": T['muted'],
            "--ag-border-color": T['tableborder'],
            "--ag-row-hover-color": T['tablehover'],
            "--ag-font-family": "'IBM Plex Sans', sans-serif",
            "--ag-font-size": "13px",
            "--ag-header-height": "46px",
            "--ag-row-height": "44px",
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
    ).properties(height=330)
    return _dark(chart)


def _chart_trend(results):
    up = sum(1 for r in results if r.trend == "Tăng")
    down = sum(1 for r in results if r.trend == "Giảm")
    if up + down == 0:
        return None
    df = pd.DataFrame({"Xu hướng": ["Tăng", "Giảm"], "Số web": [up, down]})
    chart = alt.Chart(df).mark_arc(innerRadius=62, cornerRadius=3).encode(
        theta="Số web:Q",
        color=alt.Color("Xu hướng:N", scale=alt.Scale(domain=["Tăng", "Giảm"], range=[SUCCESS, DANGER]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Xu hướng", "Số web"],
    ).properties(height=330)
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
            mark = dom if dom else "✗ không thấy web"
            status.markdown(f":material/search: Tìm website **{done}/{total}** — {brand} → {mark}")
        elif kind == "progress":
            done, total = rest
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
            # xoá hẳn UI tạm (thanh tiến trình + bảng streaming) → chỉ còn bảng kết quả cuối
            prog_box.empty()
            status.empty()
            table_area.empty()
            return rest[0]
        else:
            raise rest[0]


# ================================ Run ================================
if start:
    if not preview:
        st.warning("Chưa có dữ liệu hợp lệ — hãy dán danh sách vào ô trên.")
    elif n_brand and not serper_keys:
        st.warning(f"Có {n_brand} tên brand cần tìm web nhưng chưa có Serper API key — "
                   "thêm key ở mục Thiết lập (sidebar).")
    else:
        settings = RunSettings(min_delay=min_delay, max_delay=max_delay, use_cache=use_cache,
                               ttl=ttl_seconds, headless=True,
                               proxies=proxies_list if use_proxy else None)
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
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:17px">bar_chart</span>'
                        'Top website theo lượt truy cập</div>', unsafe_allow_html=True)
            ch = _chart_top(results)
            if ch is not None:
                st.altair_chart(ch, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu để vẽ.")
    with c2:
        with st.container(border=True):
            st.markdown('<div class="panel-title"><span class="mi" style="font-size:17px">donut_small</span>'
                        'Tỷ lệ tăng / giảm</div>', unsafe_allow_html=True)
            ch2 = _chart_trend(results)
            if ch2 is not None:
                st.altair_chart(ch2, use_container_width=True)
            else:
                st.caption("Chưa có dữ liệu xu hướng.")

    st.markdown('<div class="table-title"><span class="mi" style="font-size:19px">table_rows</span>'
                'Bảng kết quả</div>', unsafe_allow_html=True)
    _render_grid(results_to_dataframe(results).head(MAX_TABLE_ROWS), key=f"grid_{theme_name}")
    if len(results) > MAX_TABLE_ROWS:
        st.caption(f"Hiển thị {MAX_TABLE_ROWS}/{len(results)} dòng — tải file để xem đầy đủ.")

    # khoảng cách giữa bảng và nút tải
    st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
    dl1, dl2 = st.columns(2)
    dl1.download_button(":material/download: Tải Excel (.xlsx)", data=results_to_xlsx_bytes(results),
                        file_name="traffic_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True)
    dl2.download_button(":material/download: Tải CSV", data=results_to_csv_bytes(results),
                        file_name="traffic_results.csv", mime="text/csv",
                        use_container_width=True)
