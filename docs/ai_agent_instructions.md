# Hướng dẫn dành cho AI Agent: Cấu hình, Vá lỗi và Deploy Messenger-Bridge-Telegram

File này dùng để gửi cho các AI Agent (như Antigravity, Cursor, Claude...) trong các cuộc trò chuyện tương lai để họ tự động thiết lập, vá lỗi biên dịch và deploy dự án này lên Cloud.

---

## Yêu Cầu Nhiệm Vụ (Task Prompt)

Hãy copy nội dung dưới đây gửi cho AI Agent mới:

```markdown
Chào bạn, tôi muốn bạn giúp tôi thiết lập, vá lỗi biên dịch và cấu hình deploy dự án "Messenger-Bridge-Telegram" lên dịch vụ cloud (Render/Koyeb). Hãy thực hiện theo các chỉ dẫn kỹ thuật chi tiết dưới đây:

### 1. Khởi tạo môi trường ảo Python
- Tạo môi trường ảo `.venv` và cài đặt dependencies từ `requirements.txt`.
- Cài đặt gói `fbchat-v2` từ PyPI (nếu bị lỗi cài trực tiếp từ git).
- Tạo file cấu hình `.env` từ file `.env.example`.

### 2. Thiết lập biên dịch E2EE Go Binary (Do thư viện fbchat-v2 yêu cầu)
- Kiểm tra sự tồn tại của Go compiler trên máy của tôi (Ví dụ: `C:\Program Files\Go\bin\go.exe`).
- Clone mã nguồn `fbchat-v2` về thư mục cục bộ của dự án:
  `git clone https://github.com/MinhHuyDev/fbchat-v2.git`
- Sao chép thư mục `fbchat-v2/bridge-e2ee` ra thư mục gốc của dự án chính để quản lý (loại bỏ thư mục `meta` rác bên trong).
- Clone mã nguồn `meta` vào trong `bridge-e2ee/meta`:
  `git clone https://github.com/mautrix/meta.git ./bridge-e2ee/meta`

### 3. Vá lỗi biên dịch thư viện Whatsmeow (Go Compiler Error)
Thư viện `whatsmeow` phiên bản mới yêu cầu interface `PrivacyTokenStore` phải có thêm phương thức `DeleteExpiredPrivacyTokens`. Bạn cần tìm file `bridge-e2ee/bridge/store.go` và bổ sung phương thức stub (chữa cháy) này dưới phương thức `GetPrivacyToken`:

```go
func (ds *DeviceStore) DeleteExpiredPrivacyTokens(ctx context.Context, cutoff time.Time) (int64, error) {
	return 0, nil
}
```

- Sau đó, tiến hành biên dịch lại file binary trên Windows cục bộ bằng lệnh:
  `go build -ldflags="-s -w" -o ../fbchat-v2/build/fbchat-bridge-e2ee.exe .` (trong thư mục `bridge-e2ee`).
- Cấu hình file `.env` trỏ đúng vào file `.exe` vừa biên dịch:
  `FBCHAT_E2EE_BIN=./fbchat-v2/build/fbchat-bridge-e2ee.exe`
  `FBCHAT_ENABLE_E2EE=1`

### 4. Tích hợp máy chủ Health Check (Giữ app chạy 24/7 trên Cloud)
- Trong file `src/main.py`, hãy viết thêm một máy chủ HTTP mini chạy ngầm bằng thư viện `http.server` và `threading` để lắng nghe cổng `PORT` (mặc định là 8080) và trả về "OK" cho các request GET.
- Gọi hàm khởi chạy server này ngay trong hàm `main()` trước khi chạy bot.

### 5. Tạo Dockerfile cho Cloud Deployment
Tạo file `Dockerfile` ở gốc dự án với cấu trúc Multi-stage:
- **Stage 1 (golang:alpine):** Copy thư mục `bridge-e2ee`, clone `meta` và build binary `fbchat-bridge-e2ee` chạy trên hệ điều hành Linux.
- **Stage 2 (python:3.12-slim):** Cài đặt pip, copy mã nguồn `src/` và copy file binary đã build ở Stage 1 sang để khởi chạy.

### 6. Git Push lên Github cá nhân
- Thêm `fbchat-v2/` vào file `.gitignore` để tránh đẩy mã nguồn thừa lên Github.
- Thực hiện commit các thay đổi và sử dụng công cụ `gh` CLI (nếu đã đăng nhập tài khoản của tôi `hainam603`) để tạo repo và push code lên.
```

---

## Chỉ dẫn kỹ thuật bổ sung cho Agent:

1. **Lỗi `charmap` codec error trên Windows:**
   Khi in tên tài khoản Facebook chứa ký tự tiếng Việt ra console bằng hàm `print`, tiến trình Python trên Windows sẽ bị crash do encoding mặc định của terminal. Agent phải chạy ứng dụng bằng cách thiết lập biến môi trường encoding UTF-8:
   * PowerShell: `$env:PYTHONIOENCODING="utf-8"; python src/main.py`

2. **Cấu hình Port trên Render:**
   Render sử dụng biến môi trường `PORT` động (thường là `10000`), do đó code Python bắt buộc phải lấy cổng thông qua `os.environ.get("PORT", "8080")` chứ không được fix cứng cổng `8080`.
