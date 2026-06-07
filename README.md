# Check Traffic hàng loạt (traffic.cv)

Web app dán một **danh sách website** → tự động lấy **lượt truy cập/tháng** (và một
số chỉ số khác) từ [traffic.cv](https://traffic.cv) → tải về **file Excel**.

App dùng trang **bulk** của traffic.cv (`/bulk?domains=...`), trả tối đa **10 web mỗi
lần** và **không bị Cloudflare Turnstile**. Vì vậy app:

- ✅ Chạy **tự động hoàn toàn** (không cần tick xác minh, không thao tác tay).
- ✅ Chạy **headless** → vừa chạy local, vừa **deploy online** được.
- ✅ Tự **chia lô 10**, nghỉ ngẫu nhiên giữa các lô (lịch sự, tránh bị coi spam).
- ✅ **Cache** kết quả vào `cache.db` để không check lại web đã có gần đây.

## Cài đặt (chạy local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # tải trình duyệt cho Playwright
```

## Chạy

```bash
streamlit run app.py
```

1. Mở http://localhost:8501.
2. Dán danh sách website (mỗi dòng một web, hoặc cách nhau bởi dấu phẩy).
3. Bấm **🚀 Bắt đầu check** → app quét theo lô 10, hiện tiến trình + bảng kết quả.
4. Bấm **⬇️ Tải file Excel**.

### Thiết lập (thanh bên)
- **Tốc độ quét**: thời gian nghỉ giữa các lô 10 web (chậm hơn = lịch sự hơn).
- **Cache**: web đã check gần đây lấy lại từ `cache.db`, không gọi lại traffic.cv.
- **Hiện cửa sổ trình duyệt**: chỉ để debug; mặc định chạy ẩn.

## Chạy nền cho list LỚN (10k+) — khuyến nghị

Với danh sách rất lớn, dùng lệnh CLI (không cần mở Streamlit, chạy nhiều giờ vẫn ổn):

```bash
python -m trafficcv.cli list.txt -o ket_qua.xlsx            # hoặc .csv
python -m trafficcv.cli list.txt -o ket_qua.xlsx --speed safe
```
- `list.txt`: mỗi dòng một web (hoặc cách nhau bởi dấu phẩy).
- Hiện **tiến trình + ước tính thời gian còn lại (ETA)**.
- Lưu cache sau **mỗi lô** → **Ctrl+C** để dừng an toàn; chạy lại sẽ **tự tiếp tục** phần còn lại.
- Ước tính 10k web mới: ~2,5h (fast) → ~4h (safe).

## Proxy (tùy chọn — giảm rủi ro bị chặn khi chạy 10k)

Tạo file `proxies.txt` (xem `proxies.txt.example`), mỗi dòng một proxy. App/CLI sẽ
**xoay vòng** (mỗi lô 10 web đi một IP) và tự đổi proxy + nghỉ dài khi nghi bị chặn.
Không có file này thì dùng IP mạng nhà.

## Nhập website HOẶC tên brand (tự nhận diện)

Ô danh sách nhận **cả domain lẫn tên brand**, mỗi dòng 1 mục — app **tự nhận diện**:
- Dòng là **domain/URL** (vd `atoms.com`, `https://glossier.com/`) → check thẳng;
  cột **Tên Brand** = chính domain đó.
- Dòng là **tên brand** (vd `Nike`, `Atoms shoes`) → dùng **Serper.dev** tìm **website chính thức**
  (bỏ social/marketplace/review/streaming, lấy root domain) rồi check traffic; cột **Tên Brand** = tên brand.

Bảng kết quả luôn có cột **Tên Brand** + **Website** + các chỉ số traffic.

- **Serper API key**: điền vào `serper_keys.txt` (mỗi dòng 1 key — lấy free tại https://serper.dev)
  hoặc dán thẳng vào ô **"Serper API key"** ở sidebar. App tự xoay vòng key khi 1 key hết lượt.
  (Chỉ cần key khi trong danh sách có **tên brand**; danh sách toàn domain thì không cần.)
- Brand/website đã tra được **cache 90 ngày** (mặc định) → khỏi tốn lượt & nhanh hơn lần sau.
- Brand không tìm thấy web → giữ dòng, trạng thái `no_website`; bật **"Bỏ brand không tìm thấy web"**
  trong mục Lọc để ẩn chúng.

## Lọc kết quả theo traffic (tùy chọn)

> ⚠️ Lọc chỉ gọn **đầu ra**, KHÔNG làm quét nhanh hơn — vì phải check mới biết số liệu
> (traffic.cv trả 10 web/lần bất kể to nhỏ). Lọc lại trên dữ liệu đã cache thì tức thì.

- **App**: bật "Lọc theo traffic" ở thanh bên, nhập ngưỡng (vd `5k`, `1M`), chọn giữ/bỏ web không có dữ liệu.
- **CLI**:
  ```bash
  python -m trafficcv.cli list.txt -o ket_qua.xlsx --min-visits 5k --drop-unknown
  python -m trafficcv.cli list.txt -o ket_qua.xlsx --min-visits 5k --max-visits 1M
  ```

## Thử nhanh một vài web

```bash
python -m trafficcv.scraper google.com youtube.com vnexpress.net
```

## Deploy online

Dùng `Dockerfile` (đã kèm sẵn Chromium qua ảnh Playwright chính thức):

```bash
docker build -t check-traffic .
docker run -p 8501:8501 check-traffic
```

Đẩy ảnh này lên **Render / Railway / Fly.io / Hugging Face Spaces (Docker)** là có
link chia sẻ. (Streamlit Community Cloud không cài được Chromium nên dùng Docker.)

### Deploy tại `https://vibevic.com/checktraffic`

Trên VPS đang phục vụ `vibevic.com`, cài Docker rồi chạy:

```bash
docker compose up -d --build
```

File `compose.yaml` chỉ mở app tại `127.0.0.1:8501`, cấu hình Streamlit chạy dưới
subpath `/checktraffic`, và lưu cache trong Docker volume. Sau đó chép nội dung
`deploy/nginx-checktraffic.conf` vào block `server { ... }` HTTPS của
`vibevic.com`, kiểm tra và reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Không commit hoặc đóng `serper_keys.txt`, `proxies.txt`, `.env`, `cache.db` vào
Docker image. `.dockerignore` đã loại các file này; Compose mount Serper key vào
container ở chế độ chỉ đọc.

## Cấu trúc

```
app.py                 # Giao diện Streamlit
trafficcv/
  browser.py           # Phiên Chromium headless + mở /bulk?domains=
  scraper.py           # parse_bulk + get_traffic_bulk + chuẩn hóa domain
  runner.py            # Quét cả lô: chia 10, cache, nghỉ giữa lô, tiến trình
  cache.py             # SQLite cache (cache.db) có TTL
  excel.py             # Xuất .xlsx
Dockerfile             # Deploy online
```

## Lưu ý về parser

Số liệu được render trong các "card" của trang bulk. `scraper.py` bóc theo **nhãn
tiếng Anh** ("Total Visits", "Pages per Visit", "Bounce Rate", "Avg. Duration") nên
ổn định hơn class CSS. Nếu một ngày traffic.cv đổi nhãn khiến cột trống (status
`not_found` cho mọi web), cập nhật các nhãn này trong `scraper.py` (`parse_bulk`).

## Khắc phục sự cố
- **Nhiều web `not_found`**: traffic.cv có thể không có dữ liệu cho web đó, hoặc đã
  đổi giao diện (xem mục trên).
- **Bị chặn theo IP**: đặt biến môi trường `TRAFFICCV_PROXY` (xem `.env.example`).
