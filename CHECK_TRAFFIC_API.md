# ⚡ CheckTraffic REST API Documentation (Version 1.2.0 Pro)

- **Base URL:** `https://checktraffic.vibevic.com`
- **Swagger Interactive Docs:** `https://checktraffic.vibevic.com/api/docs`
- **Architecture:** Playwright Bulk Engine + Supabase Hybrid Cloud

---

## 🟢 1. Endpoint: `POST /api/check`

Lấy số liệu traffic hàng tháng và trọn bộ 7 chỉ số phân tích thương hiệu cho danh sách website hoặc tên brand.

### Request Body (JSON)
```json
{
  "inputs": ["shygems.com", "Nike", "google.com"],
  "use_cache": true,
  "force_refresh": false,
  "concurrency": 3
}
```

### Chi tiết các tham số Request
| Tham số | Kiểu dữ liệu | Mặc định | Mô tả chi tiết |
| :--- | :--- | :--- | :--- |
| `inputs` | `Array<string>` | **Bắt buộc** | Danh sách tên miền hoặc tên Brand (ví dụ: `["google.com", "Nike"]`) |
| `use_cache` | `boolean` | `true` | Tự động lấy dữ liệu đã lưu trong Supabase nếu có (< 0.05s) |
| `force_refresh` | `boolean` | `false` | Bắt buộc cào mới 100% từ live web và ghi đè dữ liệu mới lên Supabase |
| `concurrency` | `integer` | `3` | Số luồng quét Chromium song song (tối đa 5 luồng) |

---

### Response Body (JSON 200 OK)
```json
{
  "status": "success",
  "total_inputs": 3,
  "data": [
    {
      "input": "shygems.com",
      "brand_name": "shygems.com",
      "domain": "shygems.com",
      "monthly_visits_raw": "11.44K",
      "change": "+24.82%",
      "trend": "Tăng",
      "pages_per_visit": "3.15",
      "avg_duration": "00:01:23",
      "bounce_rate": "50.78%",
      "registration": "2018-05-12",
      "status": "ok",
      "cache_hit": true
    },
    {
      "input": "Nike",
      "brand_name": "Nike",
      "domain": "nike.com",
      "monthly_visits_raw": "142.8M",
      "change": "+3.15%",
      "trend": "Tăng",
      "pages_per_visit": "4.12",
      "avg_duration": "00:03:45",
      "bounce_rate": "42.10%",
      "registration": "1994-12-10",
      "status": "ok",
      "cache_hit": true
    }
  ]
}
```

---

## 💻 2. Ví dụ tích hợp Code

### 🔹 cURL (Terminal)
```bash
curl -X POST "https://checktraffic.vibevic.com/api/check" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": ["shygems.com", "Nike"],
    "use_cache": true,
    "force_refresh": false
  }'
```

### 🐍 Python (requests)
```python
import requests

url = "https://checktraffic.vibevic.com/api/check"
payload = {
    "inputs": ["shygems.com", "Nike", "google.com"],
    "use_cache": True,
    "force_refresh": False
}

response = requests.post(url, json=payload)
data = response.json()

for item in data.get("data", []):
    print(f"Website: {item['domain']} | Visits: {item['monthly_visits_raw']} | Trend: {item['trend']}")
```

### 🟨 JavaScript / Node.js (fetch)
```javascript
const response = await fetch("https://checktraffic.vibevic.com/api/check", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    inputs: ["shygems.com", "Nike"],
    use_cache: true,
    force_refresh: false
  })
});

const result = await response.json();
console.log(result.data);
```

### 🐘 PHP (cURL)
```php
<?php
$ch = curl_init("https://checktraffic.vibevic.com/api/check");
$payload = json_encode([
    "inputs" => ["shygems.com", "Nike"],
    "use_cache" => true,
    "force_refresh" => false
]);

curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);

$response = curl_exec($ch);
curl_close($ch);

$data = json_decode($response, true);
print_r($data['data']);
?>
```
