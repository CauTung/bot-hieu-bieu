# Bot Hiếu Biểu

Telegram bot serverless cho quản lý SKU, số lượng đơn, reminder và hỏi đáp.

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

## Đăng ký webhook

Sau khi deploy lên URL production ổn định:

```powershell
python scripts/set_webhook.py https://your-project.vercel.app
```

Không commit `.env` hoặc token/secret thật.
