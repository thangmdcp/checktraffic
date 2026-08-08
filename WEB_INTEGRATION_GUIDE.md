# Tích hợp CheckTraffic vào website bên ngoài

## Kiến trúc

- App CheckTraffic chạy trên máy local để cào dữ liệu.
- Kết quả thành công được ghi vào bảng `public.traffic_cache` trên Supabase.
- Website bên ngoài đọc trực tiếp Supabase bằng anon key.
- Website không gọi `localhost:8501` và không được dùng `service_role` key.

Website chỉ trả được dữ liệu mà app local đã check trước đó. Nếu domain chưa tồn tại
trong `traffic_cache`, website hiển thị thông báo yêu cầu quét bằng app local.

## Cấu hình public cho frontend

```js
const SUPABASE_URL = "https://kwwrzoouitcknzwlcttc.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3d3J6b291aXRja256d2xjdHRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI3NTI2MzAsImV4cCI6MjA5ODMyODYzMH0.N6O0_RcA_OzyPDQOOqmDRkm0nIRa_uwZK9L59mXswDw";
```

Anon key có thể đặt ở frontend vì RLS chỉ cho phép `SELECT`. Không được đưa
`SUPABASE_SERVICE_ROLE_KEY` vào HTML, JavaScript, GitHub hoặc biến môi trường có
tiền tố public.

## Hàm tra cứu hoàn chỉnh

Hàm dưới đây nhận `example.com`, `www.example.com` hoặc URL đầy đủ:

```js
const SUPABASE_URL = "https://kwwrzoouitcknzwlcttc.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt3d3J6b291aXRja256d2xjdHRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI3NTI2MzAsImV4cCI6MjA5ODMyODYzMH0.N6O0_RcA_OzyPDQOOqmDRkm0nIRa_uwZK9L59mXswDw";

function normalizeDomain(input) {
  const value = input.trim();
  if (!value) throw new Error("Vui lòng nhập website.");

  const url = new URL(
    /^https?:\/\//i.test(value) ? value : `https://${value}`
  );

  return url.hostname.toLowerCase().replace(/^www\./, "");
}

async function getTraffic(input) {
  const domain = normalizeDomain(input);
  const query = new URLSearchParams({
    domain: `eq.${domain}`,
    status: "eq.ok",
    select:
      "domain,monthly_visits,monthly_visits_raw,change,trend,pages_per_visit,avg_duration,bounce_rate,registration,top_regions,top_keywords,fetched_at",
    limit: "1",
  });

  const response = await fetch(
    `${SUPABASE_URL}/rest/v1/traffic_cache?${query.toString()}`,
    {
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
    }
  );

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`Không đọc được Supabase (${response.status}): ${message}`);
  }

  const rows = await response.json();
  return rows[0] ?? null;
}
```

## Ví dụ form HTML

```html
<form id="traffic-form">
  <input
    id="website-input"
    type="text"
    placeholder="Dán URL, ví dụ https://www.example.com/shop"
    required
  />
  <button type="submit">Kiểm tra traffic</button>
</form>

<pre id="traffic-result"></pre>

<script>
  const form = document.querySelector("#traffic-form");
  const input = document.querySelector("#website-input");
  const output = document.querySelector("#traffic-result");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    output.textContent = "Đang tra cứu...";

    try {
      const traffic = await getTraffic(input.value);

      if (!traffic) {
        output.textContent =
          "Website này chưa có dữ liệu. Hãy check bằng app local trước.";
        return;
      }

      output.textContent = JSON.stringify(traffic, null, 2);
    } catch (error) {
      output.textContent = error.message;
    }
  });
</script>
```

## Response mẫu

```json
{
  "domain": "example.com",
  "monthly_visits": 125000,
  "monthly_visits_raw": "125K",
  "change": "+4.2%",
  "trend": "Tăng",
  "pages_per_visit": "3.15",
  "avg_duration": "00:02:10",
  "bounce_rate": "48.7%",
  "registration": "1995-08-14",
  "top_regions": [],
  "top_keywords": [],
  "fetched_at": 1784960000
}
```

## Quy trình sử dụng

1. Chạy app local tại `http://localhost:8501`.
2. Check danh sách domain cần dùng.
3. App local tự ghi kết quả thành công vào Supabase.
4. Người dùng dán URL trên website ngoài.
5. Website chuẩn hóa URL thành domain và đọc `traffic_cache`.
6. Có record thì hiển thị; không có thì báo chưa được quét.

## Không được làm

- Không đưa `SUPABASE_SERVICE_ROLE_KEY` lên website.
- Không gọi `http://localhost:8501` từ website public.
- Không cho frontend `INSERT`, `UPDATE` hoặc `DELETE`.
- Không kỳ vọng URL mới tự được cào khi máy local đang tắt.
