# 🚀 CheckTraffic API — AI Integration Specs

> **Hướng dẫn cho AI / Dev:** Sử dụng API này để lấy lượt truy cập hàng tháng và các chỉ số traffic của bất kỳ website/brand nào, sau đó lưu vào Supabase.

---

## 📌 1. API Specs

- **Base URL:** `https://checktraffic.vibevic.com`
- **Swagger Docs:** `https://checktraffic.vibevic.com/api/docs`
- **CORS:** Allowed `*` (Gọi được cả từ Browser lẫn Server).

---

## ⚡ 2. Endpoints

### 🟢 `POST /api/check` — Check Traffic theo danh sách

- **Request Body (JSON):**
  ```json
  {
    "inputs": ["google.com", "vnexpress.net", "Nike"],
    "use_cache": true,
    "speed": "Vừa"
  }
  ```

- **Response Body (JSON - 200 OK):**
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
        "change": "-1.2%",
        "trend": "Giảm",
        "pages_per_visit": "2.8",
        "bounce_rate": "28.5%",
        "avg_duration": "10:30",
        "status": "ok",
        "cache_hit": true
      },
      {
        "input": "Nike",
        "brand_name": "Nike",
        "domain": "nike.com",
        "total_visits": "142.5M",
        "change": "+3.5%",
        "trend": "Tăng",
        "pages_per_visit": "3.5",
        "bounce_rate": "42.1%",
        "avg_duration": "03:15",
        "status": "ok",
        "cache_hit": false
      }
    ]
  }
  ```

---

### 🔍 `GET /api/cache?domain=google.com` — Tra cứu nhanh từ Cache (< 0.1s)

- **Response (200 OK):**
  ```json
  {
    "status": "success",
    "domain": "google.com",
    "data": {
      "domain": "google.com",
      "total_visits": "85.4B",
      "change": "-1.2%",
      "trend": "Giảm",
      "pages_per_visit": "2.8",
      "avg_duration": "10:30",
      "bounce_rate": "28.5%",
      "status": "ok",
      "cache_hit": true
    }
  }
  ```

---

## 🤖 3. Prompt Mẫu Cho AI Code (Dán câu lệnh này cho AI)

```text
Hãy viết giúp tôi hàm TypeScript/JavaScript bằng Next.js / Node.js để:
1. Nhận một domain hoặc tên brand từ input của user.
2. Gọi POST API https://checktraffic.vibevic.com/api/check với body: {"inputs": [domain], "use_cache": true}.
3. Lấy dữ liệu trả về (total_visits, change, trend, pages_per_visit, avg_duration, bounce_rate).
4. Lưu dữ liệu này vào bảng Supabase 'website_traffic' bằng @supabase/supabase-js.
```

---

## 💻 4. Code Snippet Chuẩn (Next.js / Node.js + Supabase)

```typescript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export async function fetchAndSaveTraffic(targetInput: string) {
  // 1. Gọi CheckTraffic API
  const res = await fetch('https://checktraffic.vibevic.com/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      inputs: [targetInput],
      use_cache: true
    })
  })

  const json = await res.json()
  if (!json.data || json.data.length === 0) throw new Error('No data found')

  const item = json.data[0]

  // 2. Lưu vào Supabase Database
  const { data, error } = await supabase
    .from('website_traffic')
    .insert([{
      domain: item.domain,
      brand_name: item.brand_name,
      total_visits: item.total_visits,
      change: item.change,
      trend: item.trend,
      pages_per_visit: item.pages_per_visit,
      avg_duration: item.avg_duration,
      bounce_rate: item.bounce_rate,
      status: item.status,
      checked_at: new Date().toISOString()
    }])

  if (error) throw error
  return item
}
```
