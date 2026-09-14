import hashlib
import json
from datetime import datetime

from google import genai
from google.genai import types
from pydantic import ValidationError

from core.intent_schema import IntentDecision


class RouterError(RuntimeError):
    pass


ROUTER_INSTRUCTIONS = """Bạn phân loại tin nhắn tiếng Việt cho bot quản lý công việc.
Chỉ trích xuất dữ liệu người dùng đã nói. Không tự bịa SKU, số lượng hoặc thời gian.
Ngày giờ phải dùng ISO 8601. Nếu ngày/giờ mơ hồ, để giá trị null và đặt câu hỏi làm rõ.
Các trường params không dùng cho intent phải là null. Confidence nằm trong khoảng 0 đến 1.
Nếu intent là qa, hãy đồng thời trả lời câu hỏi ngắn gọn bằng tiếng Việt trong trường answer.
Với intent khác qa, answer phải là null.
Khi sửa SKU, sku là mã hiện tại và new_sku là mã mới nếu đổi mã.
Khi sửa order, order_id là UUID bản ghi; new_sku là SKU mới nếu đổi sản phẩm.
Không được suy đoán order_id. Sửa và xóa là thao tác riêng, không phân loại thành tạo mới.
Nếu có TRẠNG THÁI HỘI THOẠI, tin nhắn hiện tại là câu trả lời cho câu hỏi làm rõ trước đó.
Hãy giữ lại các params đã biết, bổ sung thông tin mới và tiếp tục đúng intent đang chờ.
Chỉ bỏ trạng thái cũ khi người dùng thể hiện rõ họ muốn chuyển sang một yêu cầu khác.
"""


class GeminiIntentRouter:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        fallback_models: tuple[str, ...] = (),
        timeout_seconds: float = 12.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key, http_options={"timeout": int(timeout_seconds)})
        self._models = tuple(dict.fromkeys((model, *fallback_models)))

    def classify(
        self,
        text: str,
        *,
        now: datetime,
        timezone_name: str,
        telegram_user_id: int,
        conversation_context: dict[str, object] | None = None,
    ) -> IntentDecision:
        if not text.strip():
            raise ValueError("Message text must not be empty")

        context_text = ""
        if conversation_context:
            context_text = (
                "TRẠNG THÁI HỘI THOẠI:\n"
                f"{json.dumps(conversation_context, ensure_ascii=False, default=str)}\n"
            )
        input_text = (
            f"Thời gian hiện tại: {now.isoformat()} ({timezone_name})\n"
            f"{context_text}Tin nhắn hiện tại: {text}"
        )

        try:
            intent_schema = {
                "type": "OBJECT",
                "properties": {
                    "intent": {
                        "type": "STRING",
                        "enum": [
                            "create_sku",
                            "edit_sku",
                            "delete_sku",
                            "lookup_sku",
                            "add_order",
                            "edit_order",
                            "delete_order",
                            "query_orders",
                            "create_reminder",
                            "list_reminders",
                            "cancel_reminder",
                            "qa",
                            "unknown",
                        ]
                    },
                    "params": {
                        "type": "OBJECT",
                        "properties": {
                            "sku": {"type": "STRING", "nullable": True},
                            "new_sku": {"type": "STRING", "nullable": True},
                            "order_id": {"type": "STRING", "nullable": True},
                            "name": {"type": "STRING", "nullable": True},
                            "tags": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                                "nullable": True,
                            },
                            "notes": {"type": "STRING", "nullable": True},
                            "quantity": {"type": "INTEGER", "nullable": True},
                            "order_date": {"type": "STRING", "nullable": True},
                            "source": {"type": "STRING", "nullable": True},
                            "period": {"type": "STRING", "nullable": True},
                            "content": {"type": "STRING", "nullable": True},
                            "remind_at": {"type": "STRING", "nullable": True},
                            "reminder_id": {"type": "STRING", "nullable": True},
                            "question": {"type": "STRING", "nullable": True},
                        },
                        "required": [
                            "sku",
                            "new_sku",
                            "order_id",
                            "name",
                            "tags",
                            "notes",
                            "quantity",
                            "order_date",
                            "source",
                            "period",
                            "content",
                            "remind_at",
                            "reminder_id",
                            "question",
                        ],
                    },
                    "confidence": {"type": "NUMBER"},
                    "clarification_question": {"type": "STRING", "nullable": True},
                    "answer": {"type": "STRING", "nullable": True},
                },
                "required": ["intent", "params", "confidence", "clarification_question", "answer"]
            }
            last_error: Exception | None = None
            for model in self._models:
                try:
                    response = self._client.models.generate_content(
                        model=model,
                        contents=input_text,
                        config=types.GenerateContentConfig(
                            system_instruction=ROUTER_INSTRUCTIONS,
                            response_mime_type="application/json",
                            response_schema=intent_schema,
                            max_output_tokens=900,
                            temperature=0.0,
                        )
                    )
                    if not response.text:
                        raise RouterError("Gemini response contained no output text")
                    return IntentDecision.model_validate_json(response.text)
                except (ValidationError, ValueError) as exc:
                    last_error = RouterError("Gemini returned an invalid structured response")
                    last_error.__cause__ = exc
                except Exception as exc:
                    last_error = exc
            if isinstance(last_error, RouterError):
                raise last_error
            raise RouterError(f"All Gemini models failed: {last_error}") from last_error
        except RouterError:
            raise

    @staticmethod
    def _safety_identifier(telegram_user_id: int) -> str:
        return hashlib.sha256(f"telegram:{telegram_user_id}".encode()).hexdigest()
