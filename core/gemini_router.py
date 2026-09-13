import hashlib
from datetime import datetime

from pydantic import ValidationError
from google import genai
from google.genai import types

from core.intent_schema import IntentDecision


class RouterError(RuntimeError):
    pass


ROUTER_INSTRUCTIONS = """Bạn phân loại tin nhắn tiếng Việt cho bot quản lý công việc.
Chỉ trích xuất dữ liệu người dùng đã nói. Không tự bịa SKU, số lượng hoặc thời gian.
Ngày giờ phải dùng ISO 8601. Nếu ngày/giờ mơ hồ, để giá trị null và đặt câu hỏi làm rõ.
Các trường params không dùng cho intent phải là null. Confidence nằm trong khoảng 0 đến 1.
"""


class GeminiIntentRouter:
    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 12.0) -> None:
        self._client = genai.Client(api_key=api_key, http_options={'timeout': timeout_seconds})
        self._model = model

    def classify(
        self,
        text: str,
        *,
        now: datetime,
        timezone_name: str,
        telegram_user_id: int,
    ) -> IntentDecision:
        if not text.strip():
            raise ValueError("Message text must not be empty")

        input_text = f"Thời gian hiện tại: {now.isoformat()} ({timezone_name})\nTin nhắn: {text}"

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=input_text,
                config=types.GenerateContentConfig(
                    system_instruction=ROUTER_INSTRUCTIONS,
                    response_mime_type="application/json",
                    response_schema=IntentDecision,
                    max_output_tokens=500,
                    temperature=0.0,
                )
            )
            
            if not response.text:
                raise RouterError("Gemini response contained no output text")
                
            return IntentDecision.model_validate_json(response.text)
        except ValidationError as exc:
            raise RouterError("Gemini returned an invalid structured response") from exc
        except Exception as exc:
            if isinstance(exc, RouterError):
                raise
            raise RouterError("Gemini request failed") from exc

    @staticmethod
    def _safety_identifier(telegram_user_id: int) -> str:
        return hashlib.sha256(f"telegram:{telegram_user_id}".encode()).hexdigest()
