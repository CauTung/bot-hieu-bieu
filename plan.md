# Kế hoạch triển khai Telegram Bot cho 2D Designer

Kế hoạch này triển khai `requirements.md` theo hướng an toàn cho webhook/serverless: bảo mật từ đầu, chống xử lý trùng và có retry đáng tin cậy.

## Trạng thái triển khai

- Đã code: schema/migration, webhook security, allowlist, deduplicate update, Gemini router,
  confirmation state, SKU, order, reminder worker, QA và test tự động.
- Production đang chạy trên Vercel với Supabase, Telegram và Gemini API.
- Allowlist Telegram đang tạm tắt theo cấu hình `TELEGRAM_ENFORCE_ALLOWLIST=false`; bot hiện cho
  phép mọi Telegram user gửi yêu cầu và cần bật lại sau giai đoạn thử nghiệm.
- Đã smoke-test webhook thật. Gemini Free Tier từng trả `429`; bot hiện trả lỗi thân thiện,
  không tạo vòng retry Telegram và có model fallback giới hạn.
- Các giai đoạn bên dưới chỉ được đánh dấu hoàn tất sau khi tiêu chí production tương ứng pass.

## 1. Quyết định phải chốt trước khi code

1. PostgreSQL provider đã chọn: **Supabase**; dùng connection pooling cho serverless.
2. Chốt `TELEGRAM_ALLOWED_USER_IDS` và các chat được phép sử dụng.
3. Chọn cron ngoài có thể chạy mỗi 1–5 phút và gửi Authorization header.
4. Chọn Gemini primary/fallback theo structured output, latency và quota; model ID nằm trong
   environment variable, không hardcode trong luồng nghiệp vụ.
5. Chốt retention cho `processed_updates`, `pending_actions` và logs.

## 2. Roadmap

### Giai đoạn 1: Foundation, database và webhook an toàn

**Mục tiêu:** Deployment Vercel nhận Telegram webhook an toàn, kết nối DB và xử lý update idempotent.

**Công việc:**

- Khởi tạo Python project, lint/typecheck/test và Vercel Functions.
- Tạo `core/config.py` validate biến môi trường.
- Setup SQLAlchemy session ngắn theo request và Alembic migrations.
- Tạo Telegram client dùng `httpx`, timeout hữu hạn và phân loại lỗi retryable.
- Implement `/api/webhook`:
  - Chỉ nhận POST; validate JSON và body size.
  - Verify `X-Telegram-Bot-Api-Secret-Token`.
  - Kiểm tra allowlist trước khi gọi LLM.
  - Hỗ trợ `message`, `callback_query`; bỏ qua an toàn update khác.
  - Deduplicate bằng unique `processed_updates.update_id`.
- Viết script `setWebhook` với `secret_token` và `allowed_updates`.
- Structured logging theo `update_id`, không log secrets.

**Tiêu chí hoàn thành:**

- Webhook Vercel thật nhận message và callback.
- Secret sai trả 401/403; user ngoài allowlist bị chặn trước OpenAI.
- Cùng một `update_id` gửi ba lần nhưng nghiệp vụ chỉ chạy một lần.
- Migration chạy được trên database mới.

### Giai đoạn 2: LLM router và conversational state

**Mục tiêu:** Phân loại intent và hỏi lại khi thiếu hoặc mơ hồ dữ liệu.

**Công việc:**

- Định nghĩa strict schema cho toàn bộ intent trong requirements.
- Parse các lệnh chắc chắn (`/help`, `/sku`, `/orders`, `/reminders`) bằng code trước để không
  tiêu quota LLM.
- Cung cấp giờ hiện tại theo `Asia/Ho_Chi_Minh` cho router.
- Validate code-side SKU, quantity, ngày/giờ và độ dài nội dung.
- Confidence threshold là config, không phải cơ chế an toàn duy nhất.
- Lưu `conversation_states` theo user/chat trong 30 phút để ghép các câu trả lời làm rõ; xóa state
  sau khi yêu cầu hoàn chỉnh, hết hạn hoặc người dùng chuyển sang lệnh khác.
- Lưu `conversation_exchanges` trong 30 ngày; chỉ đưa tối đa 8 lượt gần nhất đã cắt độ dài vào
  prompt để hiểu tham chiếu như “cái vừa rồi” mà không tăng token theo toàn bộ tuổi hội thoại.
- Implement `pending_actions`: gắn user/chat, TTL 15 phút, atomic consume.
- Xử lý nút Đồng ý/Không, gọi `answerCallbackQuery` và vô hiệu hóa keyboard.
- Tạo fixture tiếng Việt cho câu rõ ràng, sai chính tả, thiếu tham số và thời gian mơ hồ.

**Tiêu chí hoàn thành:**

- Router luôn trả đúng schema.
- Chuỗi nhiều lượt như “Lịch đi nhậu” → “16h ngày 19/9/2026” giữ lại nội dung và tạo đúng một
  yêu cầu nhắc việc hoàn chỉnh.
- Lịch sử của mỗi user/chat được cô lập; bản ghi hết hạn được dọn khi đọc và không xuất hiện trong
  prompt Gemini.
- Không ghi dữ liệu khi thiếu tham số, confidence thấp hoặc ngày giờ mơ hồ.
- Callback sai user/chat, hết hạn hoặc bấm hai lần không ghi dữ liệu.

### Giai đoạn 3: SKU và đơn hàng

**Mục tiêu:** Hoàn thiện CRUD SKU và CRUD/tra cứu số lượng đơn.

**Công việc:**

- Normalize SKU uppercase/trim và bảo đảm unique không phân biệt hoa thường.
- Tạo SKU qua confirmation; tra chính xác, theo tên/tags và gợi ý gần đúng.
- Sửa/xóa SKU qua confirmation; đổi mã chuyển toàn bộ order liên quan, xóa bị chặn khi SKU
  vẫn còn order.
- Order chỉ nhận quantity nguyên dương và SKU tồn tại.
- `/orders` hiển thị UUID các bản ghi gần nhất; sửa/xóa order qua confirmation và giới hạn theo
  Telegram user đã tạo.
- Tổng hợp theo ngày hoặc tháng; mặc định tháng hiện tại.
- Tính boundary theo `Asia/Ho_Chi_Minh`, không dựa vào timezone Vercel.
- Transaction bảo đảm callback retry không gây double write.

**Tiêu chí hoàn thành:**

- Tạo/sửa/xóa SKU và order chỉ sau khi xác nhận.
- `vay01` và `VAY01` không thành hai SKU.
- Cùng update/callback bị retry vẫn chỉ tạo một order.
- Query đúng tại biên ngày, tháng và năm theo UTC+7.

### Giai đoạn 4: Reminder delivery

**Mục tiêu:** Tạo, liệt kê, hủy và gửi reminder có retry, không mất reminder khi worker lỗi.

**Công việc:**

- Implement create/list/cancel qua confirmation flow.
- Implement `/api/check-reminders`:
  - Yêu cầu Authorization secret riêng.
  - Claim batch bằng transaction và row locking/`SKIP LOCKED`.
  - Chuyển `pending -> processing`, lưu `locked_at`.
  - Gửi Telegram rồi mới chuyển `sent`.
  - Lỗi retryable: tăng attempt, đặt `next_retry_at` với exponential backoff.
  - Vượt max attempts: chuyển `failed` và log/alert.
  - Reclaim lock quá hạn nếu worker chết.
- Giới hạn batch size và duration.
- Cấu hình cron ngoài gọi mỗi 1–5 phút.

**Tiêu chí hoàn thành:**

- Hai cron request đồng thời không cùng claim một reminder.
- Telegram lỗi không làm reminder thành `sent`; cron sau retry được.
- Worker chết ở `processing` thì reminder được reclaim.
- Reminder hợp lệ được gửi trễ không quá 5 phút; reminder hủy không được gửi.

### Giai đoạn 5: Hỏi đáp tự do và tối ưu quota

**Mục tiêu:** Trả lời câu hỏi công việc với chi phí và hành vi có kiểm soát.

**Công việc:**

- Gộp phân loại intent và câu trả lời QA trong cùng một Gemini structured-output request.
- Chỉ gọi Gemini khi lệnh không thể xử lý chắc chắn bằng code.
- Thử primary model rồi các model fallback duy nhất trong `GEMINI_FALLBACK_MODELS`; khi tất cả
  thất bại, gửi thông báo thân thiện và hoàn tất update để Telegram không retry vô hạn.
- Giới hạn input/output tokens, timeout và retry.
- Nêu rõ khi không chắc hoặc thiếu dữ liệu thời sự.
- QA không được gọi mutation ngoài confirmation flow.
- Test prompt injection cơ bản và input quá dài.

**Tiêu chí hoàn thành:**

- Câu hỏi Photoshop/mạng xã hội phổ biến được trả lời rõ ràng.
- Không biến dữ kiện không chắc thành kết luận chắc chắn.
- Nội dung QA không ghi SKU/order/reminder trực tiếp.

### Giai đoạn 6: Hardening và production validation

**Mục tiêu:** Xác minh hệ thống thật, không kết luận chỉ từ build hoặc unit test.

**Công việc:**

- Unit tests: parser, validation, timezone, state transitions.
- Integration tests PostgreSQL: migration, constraint, transaction, concurrent claim.
- Telegram contract tests cho message/callback/retry.
- Fault injection: Gemini timeout/429/5xx, Telegram 429/5xx, DB disconnect, worker chết sau claim.
- Rate limit, request size limit và log redaction.
- Kiểm tra Fluid Compute/function duration thật và cấu hình `maxDuration` phù hợp.
- Production smoke test trên URL Vercel ổn định với bot thật.
- Runbook: deploy, migrate, set webhook, rotate secret, kiểm tra failed reminder và rollback.

**Tiêu chí hoàn thành:**

- Lint/typecheck/unit/integration tests và build pass.
- Toàn bộ tiêu chí nghiệm thu trong `requirements.md` pass.
- Webhook, callback, cron và reminder được xác minh trên deployment thật.
- Không có secret trong git, logs hoặc tài liệu bàn giao.

## 3. Cấu trúc thư mục đề xuất

```text
/
├── api/
│   ├── webhook.py
│   └── check_reminders.py
├── core/
│   ├── config.py
│   ├── db.py
│   ├── llm_router.py
│   ├── logging.py
│   ├── security.py
│   └── telegram_client.py
├── models/
│   ├── base.py
│   ├── product.py
│   ├── order.py
│   ├── reminder.py
│   ├── pending_action.py
│   └── processed_update.py
├── modules/
│   ├── sku/handlers.py
│   ├── order/handlers.py
│   ├── reminder/handlers.py
│   └── qa/handlers.py
├── services/
│   ├── update_processor.py
│   ├── confirmation_service.py
│   └── reminder_worker.py
├── alembic/
├── scripts/set_webhook.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/telegram/
├── alembic.ini
├── requirements.txt
└── vercel.json
```

## 4. Quyết định kỹ thuật

### Database

- PostgreSQL bắt buộc cho production; Alembic quản lý schema.
- SQLAlchemy session ngắn theo request/transaction.
- Đặt function region gần database.

### Idempotency và transaction

- `processed_updates.update_id` chống Telegram retry ở đầu luồng.
- Unique constraint và atomic state transition bảo vệ tại database.
- Không retry mutation nếu chưa có idempotency tương ứng.

### Timezone

- Lưu timestamp bằng UTC `TIMESTAMPTZ`.
- `order_date` là ngày nghiệp vụ UTC+7.
- Parse, hiển thị và tính boundary theo `Asia/Ho_Chi_Minh`.

### HTTP và retry

- `httpx` có connect/read/write/pool timeout rõ ràng.
- Backoff và jitter cho 429/5xx/network error; tôn trọng Telegram `retry_after`.
- Không retry lỗi validation, auth hoặc request không idempotent.

### Reminder concurrency

- Không đánh dấu `sent` trước khi gửi.
- Claim bằng `processing`; chỉ ghi `sent_at` sau response thành công.
- Chấp nhận at-least-once delivery và reclaim stale lock.

## 5. Biến môi trường

```text
DATABASE_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOWED_USER_IDS=
REMINDER_CRON_SECRET=
OPENAI_API_KEY=
OPENAI_ROUTER_MODEL=
OPENAI_QA_MODEL=
APP_TIMEZONE=Asia/Ho_Chi_Minh
PENDING_ACTION_TTL_MINUTES=15
REMINDER_MAX_ATTEMPTS=5
REMINDER_LOCK_TIMEOUT_SECONDS=120
```

Không commit `.env`. `.env.example` chỉ chứa tên biến và giá trị mẫu không nhạy cảm.

## 6. Definition of Done

Một giai đoạn chỉ hoàn thành khi:

1. Code và migration tương ứng đã được review.
2. Test success, validation error, duplicate/retry và unauthorized đều pass.
3. Logs không lộ secret hoặc dữ liệu thừa.
4. Tài liệu vận hành liên quan đã cập nhật.
5. Chức năng phụ thuộc Vercel/Telegram thật đã smoke-test trên production hoặc ghi rõ là chưa xác minh.
