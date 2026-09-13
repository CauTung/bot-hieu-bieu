# Bot Hiếu Biểu

Telegram bot serverless cho quản lý SKU, số lượng đơn, reminder và hỏi đáp.

Database production đã chọn: **Supabase Postgres**.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Cập nhật `.env`, sau đó chạy migration và test:

```powershell
python -m alembic upgrade head
python -m pytest
python -m ruff check .
python -m mypy
```

Với Supabase, dùng connection string dành cho server/transaction pooler nếu môi trường
Vercel không kết nối được trực tiếp bằng IPv6. Giữ query parameter SSL do Supabase cung cấp.

## Luồng phát triển hiện tại

- Webhook đã có secret validation, allowlist và deduplicate `update_id`.
- Intent router dùng OpenAI Responses API Structured Outputs.
- SKU, order, pending confirmation và reminder worker đã có service layer.
- `/api/check-reminders` yêu cầu `Authorization: Bearer <REMINDER_CRON_SECRET>`.
- Chưa được production-verified cho đến khi có Supabase URL, Telegram token và OpenAI key thật.

## Đăng ký webhook

Sau khi deploy lên URL production ổn định:

```powershell
python scripts/set_webhook.py https://your-project.vercel.app
```

Không commit `.env` hoặc token/secret thật.

Cron ngoài gọi `GET https://<production-domain>/api/check-reminders` mỗi 1–5 phút và
gửi header `Authorization: Bearer <REMINDER_CRON_SECRET>`.
