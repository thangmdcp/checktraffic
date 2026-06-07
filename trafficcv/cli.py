"""Chạy nền quét traffic cho list lớn (10k+) ngay trong Terminal.

Ví dụ:
    python -m trafficcv.cli danh_sach.txt -o ket_qua.xlsx
    python -m trafficcv.cli danh_sach.txt -o ket_qua.csv --speed safe
    python -m trafficcv.cli danh_sach.txt --proxies proxies.txt

- Đọc domain từ file (mỗi dòng một web, hoặc cách nhau bởi dấu phẩy).
- In tiến trình + ước tính thời gian còn lại (ETA).
- Lưu cache sau mỗi lô → Ctrl+C để dừng an toàn, chạy lại sẽ tiếp tục phần còn lại.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from .runner import RunSettings, run_batch, load_proxies, SPEED_PRESETS, count_pending
from .scraper import normalize_list, filter_results, parse_number
from .excel import save_results


def _fmt_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check traffic hàng loạt từ traffic.cv (chạy nền).")
    ap.add_argument("input", help="File chứa danh sách website")
    ap.add_argument("-o", "--output", default="ket_qua.xlsx",
                    help="File kết quả (.xlsx hoặc .csv). Mặc định: ket_qua.xlsx")
    ap.add_argument("--speed", choices=list(SPEED_PRESETS), default="normal",
                    help="safe | normal | fast (mặc định: normal)")
    ap.add_argument("--proxies", default=None,
                    help="File proxy (mỗi dòng một proxy). Mặc định tự tìm proxies.txt / TRAFFICCV_PROXY")
    ap.add_argument("--no-cache", action="store_true", help="Bỏ qua cache, check lại tất cả")
    ap.add_argument("--ttl-days", type=int, default=7, help="Cache còn hạn (ngày)")
    ap.add_argument("--show-browser", action="store_true", help="Hiện cửa sổ trình duyệt (debug)")
    ap.add_argument("--min-visits", default=None,
                    help="Chỉ giữ web có lượt truy cập >= ngưỡng (vd 5k, 1M). Lọc đầu ra.")
    ap.add_argument("--max-visits", default=None, help="Chỉ giữ web có lượt truy cập <= ngưỡng.")
    ap.add_argument("--drop-unknown", action="store_true",
                    help="Bỏ web không có dữ liệu (not_found/lỗi) khỏi file kết quả.")
    args = ap.parse_args(argv)

    # đọc input
    try:
        text = open(args.input, encoding="utf-8").read()
    except OSError as e:
        print(f"❌ Không đọc được file input: {e}", file=sys.stderr)
        return 1
    domains = normalize_list(text)
    if not domains:
        print("❌ Không tìm thấy website hợp lệ trong file.", file=sys.stderr)
        return 1

    ttl = args.ttl_days * 24 * 3600
    proxies = load_proxies(args.proxies) if args.proxies else load_proxies()
    min_d, max_d = SPEED_PRESETS[args.speed]

    cached, pending = count_pending(domains, ttl) if not args.no_cache else (0, len(domains))
    print(f"Tổng: {len(domains)} web | đã có cache: {cached} | cần check: {pending}")
    if proxies:
        print(f"Dùng {len(proxies)} proxy (xoay vòng).")
    else:
        print("Không dùng proxy (IP mạng nhà).")
    print(f"Tốc độ: {args.speed}. Ctrl+C để dừng an toàn (chạy lại sẽ tiếp tục).\n")

    settings = RunSettings(
        min_delay=min_d, max_delay=max_d, use_cache=not args.no_cache,
        ttl=ttl, headless=not args.show_browser, proxies=proxies,
    )

    stop = {"flag": False}

    def _sigint(_sig, _frm):
        if not stop["flag"]:
            print("\n⏹  Đang dừng an toàn sau lô hiện tại...")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _sigint)

    start = time.time()
    state = {"last": start}

    def progress(done, total, res):
        # cập nhật ETA mỗi ~2 giây để khỏi spam dòng
        now = time.time()
        if now - state["last"] < 2 and done < total:
            return
        state["last"] = now
        elapsed = now - start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        pct = done * 100 // total
        print(f"\r[{done}/{total}] {pct}%  ETA ~{_fmt_eta(eta)}  | mới nhất: "
              f"{res.domain} = {res.monthly_visits_raw or res.status}      ", end="", flush=True)

    outcome = run_batch(domains, settings, progress_cb=progress,
                        should_stop=lambda: stop["flag"])
    print()  # xuống dòng sau thanh tiến trình

    # lọc đầu ra (nếu có)
    results = outcome.results
    if args.min_visits or args.max_visits or args.drop_unknown:
        before = len(results)
        results = filter_results(
            results,
            min_visits=parse_number(args.min_visits) if args.min_visits else None,
            max_visits=parse_number(args.max_visits) if args.max_visits else None,
            keep_unknown=not args.drop_unknown,
        )
        print(f"🔎 Lọc: giữ {len(results)}/{before} web.")

    # ghi kết quả
    try:
        save_results(results, args.output)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Lỗi khi ghi {args.output}: {e}", file=sys.stderr)
        return 1

    ok = sum(1 for r in outcome.results if r.status == "ok")
    nf = sum(1 for r in outcome.results if r.status == "not_found")
    err = sum(1 for r in outcome.results if r.status in ("error", "blocked"))
    print(f"\n✅ Xong{' (đã dừng giữa chừng)' if outcome.cancelled else ''}. "
          f"OK: {ok} | không có dữ liệu: {nf} | lỗi/bị chặn: {err}")
    if outcome.blocked_batches:
        print(f"⚠️  Có {outcome.blocked_batches} lô nghi bị chặn (đã tự nghỉ/đổi proxy).")
    print(f"📄 Đã lưu: {args.output}  (thời gian: {_fmt_eta(time.time() - start)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
