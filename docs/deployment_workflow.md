# Quy trình Deploy ứng dụng Hybrid (Python + Go Subprocess) lên Cloud Miễn phí

Tài liệu này hướng dẫn chi tiết quy trình đóng gói và triển khai (deploy) các ứng dụng chạy ngầm liên tục (như Telegram/Messenger Bridge) sử dụng kiến trúc hỗn hợp **Python + Go Subprocess** lên các nền tảng đám mây hỗ trợ Docker miễn phí (như Render, Koyeb) và giữ chúng hoạt động 24/7.

---

## 1. Chuẩn bị mã nguồn dự án

### Bước 1.1: Tích hợp HTTP Health Server (Mục đích tránh ngủ đông)
Vì các nền tảng cloud miễn phí (Render, Koyeb) sẽ tự động tắt ứng dụng (ngủ đông) sau 15 phút nếu không nhận được traffic HTTP, bạn cần khởi chạy một server HTTP mini chạy song song trong code chính.

Thêm đoạn mã sau vào file entrypoint của Python (ví dụ: `src/main.py`):

```python
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format: str, *args: any) -> None:
        pass # Tắt log request để giữ console sạch sẽ

def start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
```
*Gọi hàm `start_health_server()` ngay trước khi khởi chạy logic chính của bot.*

### Bước 1.2: Đưa mã nguồn Go vào Repository
Nếu ứng dụng của bạn gọi các file thực thi Go (.exe hoặc binary) tự build:
* Hãy đặt thư mục mã nguồn Go (ví dụ: `bridge-e2ee/`) ngay trong thư mục dự án để Docker build có thể đọc được trực tiếp.
* **Lưu ý:** Đảm bảo thêm các thư mục build hoặc các thư viện ngoài tạm thời (như `meta/` của Go hoặc `.venv/` của Python) vào file `.gitignore` để tránh đẩy các file rác lên GitHub.

---

## 2. Thiết lập Dockerfile tối ưu (Multi-stage Build)

Tạo file mang tên `Dockerfile` ở thư mục gốc của dự án. File này sẽ biên dịch Go trong môi trường biệt lập trước, sau đó copy file binary sang môi trường Python nhẹ hơn để giảm dung lượng image tối đa:

```dockerfile
# --- Stage 1: Build the Go binary ---
FROM golang:alpine AS go-builder

RUN apk add --no-cache git

WORKDIR /app/bridge-e2ee
# Sao chép mã nguồn Go cục bộ vào
COPY bridge-e2ee/ .

# Clone các dependency bên ngoài nếu cần
RUN git clone https://github.com/mautrix/meta.git ./meta
# Biên dịch file binary hệ điều hành Linux
RUN go mod tidy
RUN go build -ldflags="-s -w" -o /app/fbchat-bridge-e2ee .

# --- Stage 2: Final lightweight runner ---
FROM python:3.12-slim

# Cài đặt git (nếu requirements.txt yêu cầu cài từ git+https)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài đặt thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy file binary đã build từ Stage 1 sang
COPY --from=go-builder /app/fbchat-bridge-e2ee /app/fbchat-bridge-e2ee

# Copy mã nguồn Python chính
COPY src/ ./src/

# Cấu hình biến môi trường mặc định trong container
ENV PYTHONIOENCODING=utf-8
ENV PORT=8080
ENV FBCHAT_E2EE_BIN=/app/fbchat-bridge-e2ee

EXPOSE 8080

CMD ["python", "src/main.py"]
```

---

## 3. Triển khai lên Cloud (Ví dụ: Render.com)

1. **GitHub:** Đẩy dự án đã có `Dockerfile` lên một kho lưu trữ GitHub cá nhân.
2. **Tạo dịch vụ:** Truy cập **Render Dashboard** -> Chọn **New +** -> **Web Service**.
3. **Kết nối Git:** Chọn Repo GitHub chứa code của bạn.
4. **Cấu hình Web Service:**
   * **Runtime:** Chọn **Docker** (Render sẽ tự động đọc Dockerfile).
   * **Instance Type:** Chọn **Free** (Miễn phí).
5. **Cấu hình Environment Variables (Biến môi trường):**
   Điền đầy đủ các token bảo mật và cookie lấy từ file cấu hình cục bộ `.env` của bạn lên Render (Ví dụ: `TG_TOKEN`, `TG_GROUP_ID`, `FACEBOOK_COOKIE`).
   > [!IMPORTANT]
   > Tuyệt đối không đẩy file cấu hình chứa token thực tế `.env` lên GitHub để tránh bị lộ thông tin bảo mật.

---

## 4. Cấu hình Ping Service để chạy 24/7 miễn phí

Sau khi Render deploy thành công, bạn sẽ nhận được một địa chỉ URL có dạng: `https://your-app.onrender.com`.

1. Truy cập trang web miễn phí [UptimeRobot.com](https://uptimerobot.com/) và tạo tài khoản.
2. Click **Add New Monitor**:
   * **Monitor Type:** Chọn `HTTP(s)`.
   * **Friendly Name:** Đặt tên gợi nhớ (ví dụ: `messenger-bot-ping`).
   * **URL (or IP):** Nhập địa chỉ URL của app Render của bạn.
   * **Monitoring Interval:** Đặt là **10 minutes** (10 phút ping 1 lần là tối ưu nhất).
3. Click **Create Monitor**.

> [!TIP]
> Mỗi lần UptimeRobot gửi lệnh ping đến URL của bạn, HTTP server trong Python sẽ trả về status `200 OK`. Điều này khiến Render hiểu rằng ứng dụng đang có người truy cập và sẽ **không bao giờ tắt** (keep-alive) dịch vụ miễn phí của bạn.
