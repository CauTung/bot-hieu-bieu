# Yêu cầu hệ thống: Telegram Bot hỗ trợ dev designer 2D

## 1. Mục tiêu và phạm vi

Xây một bot Telegram cá nhân cho dev designer 2D, hỗ trợ:

1. Tạo và tra cứu mã SKU của sản phẩm đã thiết kế.
2. Ghi nhận số lượng đơn theo SKU và tổng hợp theo ngày/tháng.
3. Đặt, xem và hủy nhắc việc theo thời gian người dùng chọn.
4. Trả lời câu hỏi tự do trong phạm vi công việc, ví dụ mạng xã hội và Photoshop.
5. Ghi nhớ ảnh mẫu theo SKU và tra mã SKU khi người dùng chỉ gửi ảnh.

Người dùng thao tác chủ yếu bằng **tin nhắn tự do**. Bot dùng LLM để phân tích ý định nhưng nghiệp vụ, phân quyền, kiểm tra dữ liệu và thao tác database phải do code quyết định.

### 1.1. Phạm vi MVP

- SKU: tạo, tra cứu, sửa và xóa. Đổi mã SKU phải chuyển các order liên quan; không cho xóa
  SKU còn order để tránh mất dữ liệu ngoài ý muốn.
- Đơn hàng: ghi nhận, sửa, xóa và tra cứu theo một SKU/ngày. Mỗi order có UUID để chọn đúng
  bản ghi; chỉ Telegram user đã tạo mới được sửa/xóa order đó.
- Nhắc việc: tạo, liệt kê reminder chưa gửi và hủy reminder.
- Hỏi đáp: trả lời trực tiếp, không tự động ghi dữ liệu.
- Chỉ các Telegram user ID trong allowlist được sử dụng bot.

## 2. Hạ tầng và mô hình chạy

- Deploy trên Vercel Hobby ở chế độ webhook; không dùng long-polling.
- Telegram gửi HTTPS POST tới `/api/webhook`.
- Dùng PostgreSQL có connection pooling phù hợp serverless; không dùng SQLite.
- Dịch vụ cron ngoài gọi `/api/check-reminders` mỗi 1–5 phút. Không dùng Vercel Cron Hobby cho reminder theo phút.
- Giới hạn function phụ thuộc runtime/Fluid Compute và cấu hình project; không giả định cố định là 10 giây.
- Mọi webhook và thao tác ghi phải idempotent vì Telegram hoặc HTTP client có thể retry.

## 3. Xử lý ý định và hội thoại

LLM router dùng Structured Outputs và trả về:

```json
{"intent": "...", "params": {}, "confidence": 0.0}
```

- Intent: `create_sku`, `edit_sku`, `delete_sku`, `lookup_sku`, `add_order`, `edit_order`,
  `delete_order`, `query_orders`, `create_reminder`, `list_reminders`, `cancel_reminder`, `qa`,
  `register_sku_image`, `unknown`.
- Schema phải khai báo chặt kiểu dữ liệu và trường bắt buộc theo từng intent.
- `confidence` chỉ là một tín hiệu. Code phải validate lại toàn bộ `params`.
- Nếu confidence dưới ngưỡng cấu hình hoặc thiếu/mơ hồ tham số, bot hỏi lại; không đoán bừa.
- Khi hỏi làm rõ, bot lưu intent và các params đã biết theo `telegram_user_id + chat_id`. Tin nhắn
  tiếp theo phải được ghép vào trạng thái này thay vì phân loại như một yêu cầu độc lập.
- Trạng thái làm rõ hết hạn sau thời gian cấu hình (mặc định 30 phút), được xóa khi yêu cầu hoàn
  chỉnh hoặc khi người dùng chuyển sang một lệnh rõ ràng khác.
- Lưu tối đa 30 ngày lịch sử trao đổi đã hoàn tất theo từng user/chat. Mỗi request chỉ gửi tối đa
  8 lượt gần nhất với độ dài bị giới hạn; không gửi toàn bộ lịch sử để kiểm soát token và quota.
- “Hôm nay”, “tháng này”, “thứ hai” được hiểu theo `Asia/Ho_Chi_Minh`.
- Nếu giờ không kèm ngày đã trôi qua, hỏi lại “hôm nay hay ngày mai”.
- Input ngày mơ hồ như `01/02` phải hỏi lại nếu không xác định chắc định dạng.

## 4. Xác nhận hành động ghi

Tạo/sửa/xóa SKU, ghi/sửa/xóa order, tạo hoặc hủy reminder đều phải được xác nhận bằng nút
`✅ Đúng` / `❌ Không`.

Luồng chuẩn:

1. Parse và validate yêu cầu.
2. Gửi bản tóm tắt cùng nút xác nhận.
3. Lưu payload trong `pending_actions`; `callback_data` chỉ chứa action ID ngắn.
4. Khi callback tới, kiểm tra đúng `telegram_user_id`, `chat_id`, trạng thái và thời hạn.
5. Consume action bằng atomic update để chỉ thực thi một lần.
6. Luôn gọi `answerCallbackQuery`, vô hiệu hóa keyboard cũ và thông báo kết quả.

Action mặc định hết hạn sau 15 phút. Callback hết hạn, bấm lại hoặc từ người khác không được ghi dữ liệu.

Sau khi ghi thành công, bot luôn gửi thông báo rõ ràng. Hành động chỉ đọc trả lời trực tiếp, không thêm câu “đã xử lý xong”.

## 5. Quy tắc nghiệp vụ

### 5.1. SKU

- Trim và chuẩn hóa SKU thành uppercase trước khi lưu/tra cứu.
- SKU unique không phân biệt hoa thường.
- Tạo SKU đã tồn tại phải trả bản ghi hiện có và không tạo trùng.
- Có thể tìm theo SKU chính xác, tên mẫu hoặc tags. Gợi ý gần đúng chỉ để người dùng chọn.

### 5.2. Đơn hàng

- `quantity` là số lượng sản phẩm, phải là số nguyên dương.
- Mỗi bản ghi thuộc một SKU và một ngày nghiệp vụ.
- Không ghi đơn cho SKU chưa tồn tại; bot hỏi có muốn tạo SKU trước không.
- Tra cứu không nêu phạm vi mặc định lấy tháng hiện tại theo UTC+7.
- Query theo ngày/tháng dùng boundary `Asia/Ho_Chi_Minh`.

### 5.3. Nhận diện SKU bằng ảnh

- Người dùng có thể gửi ảnh kèm `đây là mã SKU <mã>` hoặc gửi câu đó rồi gửi ảnh trong thời hạn
  hội thoại 30 phút.
- SKU phải tồn tại và việc gắn/gắn lại ảnh phải qua nút xác nhận.
- Ánh xạ ảnh lưu lâu dài trong PostgreSQL, dùng chung cho catalog; thông tin người tạo/chat được
  lưu để audit nhưng không giới hạn quyền tra cứu.
- Tra ảnh ưu tiên `file_unique_id` và SHA-256, sau đó mới dùng perceptual hash cho ảnh bị resize
  hoặc nén nhẹ. Không trả SKU nếu độ tương đồng thấp hoặc nhiều SKU đồng hạng.
- Xóa SKU xóa ánh xạ ảnh; đổi mã SKU chuyển ánh xạ sang mã mới.

### 5.4. Nhắc việc

- Thời điểm nhắc phải ở tương lai sau khi xác nhận.
- Tách `event_at` (giờ diễn ra) khỏi `remind_at` (giờ gửi thông báo). Nếu chỉ nêu giờ diễn ra,
  mặc định `remind_at = event_at - 2 giờ`; nếu người dùng nói rõ lúc cần nhắc hoặc khoảng tương
  đối như “2 tiếng nữa nhắc tôi”, dùng đúng thời điểm đó và không trừ thêm.
- Màn hình xác nhận và danh sách reminder phải hiển thị rõ cả hai mốc khi có `event_at`.
- Có thể liệt kê và hủy reminder chưa gửi.
- SLA MVP: gửi đúng hạn hoặc trễ không quá 5 phút, phụ thuộc cron ngoài.
- Gửi phải retry được; không đánh dấu `sent` trước khi Telegram xác nhận thành công.

### 5.5. Hỏi đáp

- Trả lời ngắn gọn và nêu rõ khi không chắc hoặc thiếu dữ liệu thời sự.
- Không đưa nội dung QA vào mutation nếu chưa phân loại lại và xác nhận.
- Giới hạn độ dài input/output và timeout để kiểm soát chi phí.

## 6. Data model tối thiểu

```text
products
- sku TEXT PK (normalized uppercase)
- name TEXT NOT NULL
- tags JSONB/TEXT[]
- notes TEXT
- created_at TIMESTAMPTZ NOT NULL
- updated_at TIMESTAMPTZ NOT NULL

orders
- id UUID PK
- sku TEXT FK -> products.sku
- quantity INTEGER NOT NULL CHECK (quantity > 0)
- order_date DATE NOT NULL
- source TEXT
- telegram_user_id BIGINT NOT NULL
- created_at TIMESTAMPTZ NOT NULL

reminders
- id UUID PK
- telegram_user_id BIGINT NOT NULL
- chat_id BIGINT NOT NULL
- content TEXT NOT NULL
- remind_at TIMESTAMPTZ NOT NULL
- event_at TIMESTAMPTZ NULL
- status TEXT NOT NULL  # pending, processing, sent, cancelled, failed
- attempt_count INTEGER NOT NULL DEFAULT 0
- locked_at TIMESTAMPTZ NULL
- next_retry_at TIMESTAMPTZ NULL
- sent_at TIMESTAMPTZ NULL
- last_error TEXT NULL
- created_at TIMESTAMPTZ NOT NULL
- updated_at TIMESTAMPTZ NOT NULL

pending_actions
- id UUID PK
- telegram_user_id BIGINT NOT NULL
- chat_id BIGINT NOT NULL
- action_type TEXT NOT NULL
- payload JSONB NOT NULL
- status TEXT NOT NULL  # pending, confirmed, cancelled, expired
- expires_at TIMESTAMPTZ NOT NULL
- created_at TIMESTAMPTZ NOT NULL
- confirmed_at TIMESTAMPTZ NULL

conversation_states
- telegram_user_id BIGINT PK
- chat_id BIGINT PK
- intent TEXT NOT NULL
- params JSONB NOT NULL
- clarification_question TEXT NOT NULL
- expires_at TIMESTAMPTZ NOT NULL

conversation_exchanges
- id UUID PK
- telegram_user_id BIGINT NOT NULL
- chat_id BIGINT NOT NULL
- user_text TEXT NOT NULL
- assistant_text TEXT NOT NULL
- intent TEXT NULL
- details JSONB NULL
- created_at TIMESTAMPTZ NOT NULL
- expires_at TIMESTAMPTZ NOT NULL

sku_image_fingerprints
- id UUID PK
- sku TEXT FK -> products.sku ON DELETE CASCADE
- telegram_file_unique_id TEXT UNIQUE NOT NULL
- sha256 TEXT NOT NULL
- perceptual_hash TEXT NOT NULL
- created_by_user_id BIGINT NOT NULL
- created_in_chat_id BIGINT NOT NULL
- created_at TIMESTAMPTZ NOT NULL

processed_updates
- update_id BIGINT PK
- status TEXT NOT NULL
- received_at TIMESTAMPTZ NOT NULL
- processed_at TIMESTAMPTZ NULL
- last_error TEXT NULL
```

Schema được quản lý bằng Alembic; không tự tạo bảng trong mỗi serverless invocation.

## 7. Bảo mật và độ tin cậy

- Secrets chỉ nằm trong Vercel Environment Variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `REMINDER_CRON_SECRET`, `OPENAI_API_KEY`, `DATABASE_URL`, `TELEGRAM_ALLOWED_USER_IDS`.
- `/api/webhook` chỉ nhận POST, validate body và `X-Telegram-Bot-Api-Secret-Token` bằng so sánh constant-time.
- `/api/check-reminders` yêu cầu secret riêng trong Authorization header; không để secret trong query string.
- Kiểm tra allowlist trước khi gọi LLM hoặc nghiệp vụ.
- Deduplicate theo `update_id`; một update không được tạo dữ liệu hai lần.
- Timeout hữu hạn và retry có exponential backoff cho Telegram/OpenAI/DB; chỉ retry operation an toàn hoặc idempotent.
- Log structured với `update_id`, intent, duration và trạng thái; redact token, Authorization và dữ liệu nhạy cảm.
- Giới hạn request size, độ dài tin nhắn và số lần gọi LLM.

## 8. Gửi reminder an toàn

Cron worker claim reminder đến hạn bằng transaction/row locking để hai request đồng thời không cùng gửi.

```text
pending -> processing -> sent
                    \-> pending (retry có next_retry_at)
                    \-> failed (vượt quá số lần retry)
```

- Chỉ chuyển `sent` sau khi Telegram API trả thành công.
- Nếu worker chết khi đang `processing`, reminder có `locked_at` quá hạn được trả về `pending`.
- Chấp nhận at-least-once delivery: sự cố hiếm giữa lúc Telegram nhận tin và DB cập nhật có thể gây gửi trùng; không tuyên bố exactly-once.

## 9. Stack

- Python serverless functions trong `/api`.
- SQLAlchemy + Alembic + Supabase PostgreSQL qua connection pooler cho serverless.
- `httpx` với timeout rõ ràng cho Telegram và OpenAI API.
- OpenAI API Structured Outputs cho router; lời gọi riêng cho QA.
- `pytest` cho unit/integration tests.
- Cron ngoài có khả năng gửi Authorization header và chạy mỗi 1–5 phút.

## 10. Tiêu chí nghiệm thu tổng thể

- Webhook/cron sai secret trả 401/403; user ngoài allowlist không kích hoạt LLM hay ghi dữ liệu.
- Cùng `update_id` gửi lại nhiều lần chỉ tạo đúng một dữ liệu nghiệp vụ.
- Hai callback đồng thời chỉ thực thi action một lần.
- Callback sai user/chat hoặc hết hạn không ghi dữ liệu.
- Hai cron request đồng thời chỉ claim một reminder.
- Telegram gửi lỗi thì reminder được retry, không bị đánh dấu `sent` giả.
- Query ngày/tháng đúng ở biên ngày UTC+7.
- Các luồng create/query/cancel chạy thành công trên deployment Vercel thật.
