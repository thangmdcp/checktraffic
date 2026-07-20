# 📘 Hướng Dẫn Sử Dụng REST API CheckTraffic

Tài liệu hướng dẫn tích hợp **CheckTraffic REST API** vào các ứng dụng Web, App di động, Automation scripts hoặc các hệ thống khác.

---

## 🚀 1. Tổng quan & Base URL

- **Base URL:** `https://checktraffic.vibevic.com/api`
- **Tài liệu Swagger UI tương tác:** [https://checktraffic.vibevic.com/api/docs](https://checktraffic.vibevic.com/api/docs)
- **Định dạng dữ liệu:** JSON (`Content-Type: application/json`)
- **CORS:** Đã bật sẵn cho mọi nguồn (`Access-Control-Allow-Origin: *`), có thể gọi trực tiếp từ JavaScript trên trình duyệt (AJAX / Fetch).

---

## ⚡ 2. Các API Endpoint Chính

### 2.1 `POST /api/check` — Quét Traffic theo danh sách Website / Brand

Gửi một danh sách các domain hoặc tên thương hiệu để tự động lấy lượt truy cập/tháng và các chỉ số liên quan.

* **URL:** `/api/check`
* **Method:** `POST`
* **Header:** `Content-Type: application/json`

#### Request Body (JSON):
```json
{
  "inputs": [
    "google.com",
    "vnexpress.net",
    "Nike"
  ],
  "use_cache": true,
  "speed": "Vừa",
  "serper_api_keys": [
    "YOUR_SERPER_DEV_KEY_OPTIONAL"
  ]
}
```

| Tham số | Kiểu dữ liệu | Bắt buộc | Mặc định | Mô tả |
| :--- | :--- | :--- | :--- | :--- |
| `inputs` | `List[String]` | **Có** | — | Danh sách domain (vd: `atoms.com`) hoặc tên brand (vd: `Nike`). Tối đa 500 item/lần. |
| `use_cache` | `Boolean` | Không | `true` | Nếu `true`, lấy lại kết quả đã quét gần đây từ database cache. |
| `speed` | `String` | Không | `"Vừa"` | Tốc độ quét: `"An toàn"`, `"Vừa"`, hoặc `"Nhanh"`. |
| `serper_api_keys` | `List[String]` | Không | `null` | Danh sách Serper API key dùng để tìm website chính thức cho tên brand. |

#### Response thành công (200 OK):
```json
{
  "status": "success",
  "total_inputs": 3,
  "data": [
    {
      "input": "google.com",
      "brand_name": "google.com",
      "domain": "google.com",
      "total_visits": "85.4B",
      "monthly_visits_raw": "85.4B",
      "change": "-1.2%",
      "trend": "down",
      "pages_per_visit": "2.8",
      "avg_duration": "10:30",
      "bounce_rate": "28.5%",
      "status": "ok",
      "cache_hit": true
    },
    {
      "input": "Nike",
      "brand_name": "Nike",
      "domain": "nike.com",
      "total_visits": "142.5M",
      "monthly_visits_raw": "142.5M",
      "change": "+4.1%",
      "trend": "up",
      "pages_per_visit": "3.5",
      "avg_duration": "03:15",
      "bounce_rate": "42.1%",
      "status": "ok",
      "cache_hit": false
    }
  ]
}
```

---

### 2.2 `GET /api/cache` — Tra cứu tức thì từ Cache

Tra cứu kết quả đã được lưu sẵn trong SQLite cache cho 1 domain cụ thể (Tốc độ phản hồi < 0.1 giây).

* **URL:** `/api/cache?domain=google.com`
* **Method:** `GET`

#### Response (200 OK):
```json
{
  "status": "success",
  "domain": "google.com",
  "data": {
    "domain": "google.com",
    "total_visits": "85.4B",
    "change": "-1.2%",
    "trend": "down",
    "pages_per_visit": "2.8",
    "avg_duration": "10:30",
    "bounce_rate": "28.5%",
    "status": "ok",
    "cache_hit": true
  }
}
```

---

### 2.3 `GET /api/health` — Kiểm tra kết nối API

* **URL:** `/api/health`
* **Method:** `GET`
* **Response:** `{"status": "ok", "service": "CheckTraffic API", "version": "1.0.0"}`

---

## 💻 3. Ví Dụ Tích Hợp Code (Sample Code)

### 3.1 JavaScript / Node.js (Fetch API)

```javascript
async function checkTraffic(domainList) {
  const response = await fetch('https://checktraffic.vibevic.com/api/check', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      inputs: domainList,
      use_cache: true
    })
  });

  const result = await response.json();
  console.log('Kết quả Traffic:', result.data);
}

// Gọi thử:
checkTraffic(['google.com', 'vnexpress.net', 'Nike']);
```

### 3.2 Python (requests / httpx)

```python
import requests

url = "https://checktraffic.vibevic.com/api/check"
payload = {
    "inputs": ["google.com", "vnexpress.net", "Nike"],
    "use_cache": True,
    "speed": "Vừa"
}

response = requests.post(url, json=payload)
data = response.json()

for item in data.get("data", []):
    print(f"Brand: {item['brand_name']} | Domain: {item['domain']} | Visits: {item['total_visits']}")
```

### 3.3 cURL (Command Line)

```bash
curl -X POST "https://checktraffic.vibevic.com/api/check" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": ["google.com", "vnexpress.net"],
    "use_cache": true
  }'
```

### 3.4 PHP (cURL)

```php
<?php
$ch = curl_init('https://checktraffic.vibevic.com/api/check');
$payload = json_encode([
    'inputs' => ['google.com', 'vnexpress.net'],
    'use_cache' => true
]);

curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);

$response = curl_exec($ch);
curl_close($ch);

$data = json_decode($response, true);
print_r($data);
?>
```

---

## 🔴 4. Mã Lỗi Thường Gặp (Error Handling)

- **`400 Bad Request`**: Danh sách `inputs` trống hoặc quá 500 mục.
- **`404 Not Found`**: Không tìm thấy dữ liệu trong cache khi gọi `/api/cache`.
- **`500 Internal Server Error`**: Lỗi hệ thống server khi cào dữ liệu.

---
*Mọi thắc mắc hoặc yêu cầu đóng góp vui lòng cập nhật tại [GitHub Repository](https://github.com/thangmdcp/checktraffic).*
