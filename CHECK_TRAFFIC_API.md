# ⚡ CheckTraffic REST API Documentation

- **Base URL:** `https://checktraffic.vibevic.com`
- **Swagger UI:** `https://checktraffic.vibevic.com/api/docs`

---

## 🟢 1. Endpoint: `POST /api/check`

Lấy số liệu traffic hàng tháng và các chỉ số chi tiết cho danh sách website hoặc tên brand.

### Request Body (JSON)
```json
{
  "inputs": ["shygems.com", "Nike", "google.com"],
  "use_cache": true,
  "force_refresh": false,
  "concurrency": 3,
  "speed": "Vừa"
}
```

| Tham số | Kiểu | Mặc định | Mô tả |
| :--- | :--- | :--- | :--- |
| `inputs` | `Array<string>` | **Bắt buộc** | Danh sách tên miền hoặc tên Brand (ví dụ: `["google.com", "Nike"]`) |
| `use_cache` | `boolean` | `true` | Ưu tiên lấy từ Supabase/Cache nếu có (< 0.05s) |
| `force_refresh` | `boolean` | `false` | Bắt buộc quét mới 100% và ghi đè dữ liệu mới lên Supabase |
| `concurrency` | `integer` | `3` | Số luồng quét song song (tối đa 5) |

---

### Response Body (JSON 200 OK)
```json
{
  "status": "success",
  "total_inputs": 1,
  "data": [
    {
      "input": "shygems.com",
      "brand_name": "shygems.com",
      "domain": "shygems.com",
      "total_visits": "11.44K",
      "monthly_visits_raw": "11.44K",
      "change": "+24.82%",
      "trend": "Tăng",
      "pages_per_visit": "3.15",
      "avg_duration": "00:01:23",
      "bounce_rate": "50.78%",
      "top_regions": [{"country": "United States", "share": "45.2%"}],
      "top_keywords": [{"keyword": "shygems", "traffic": "2.1K"}],
      "status": "ok",
      "cache_hit": true
    }
  ]
}
```

---

## 💻 2. Ví dụ cURL

```bash
curl -X POST "https://checktraffic.vibevic.com/api/check" \
  -H "Content-Type: application/json" \
  -d '{"inputs": ["shygems.com"], "use_cache": true}'
```
