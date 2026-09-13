import hashlib
from google import genai
from google.genai import types

from core.gemini_router import RouterError


class GeminiQAClient:
    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 20.0) -> None:
        self._client = genai.Client(api_key=api_key, http_options={'timeout': timeout_seconds})
        self._model = model

    def answer(self, question: str, *, telegram_user_id: int) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=question,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "Trả lời ngắn gọn bằng tiếng Việt cho designer 2D. "
                        "Nếu câu hỏi cần dữ liệu thời sự mà bạn không có, hãy nói rõ giới hạn."
                    ),
                    max_output_tokens=800,
                )
            )
            if not response.text:
                raise RouterError("Gemini QA response contained no output text")
            return response.text.strip()
        except Exception as exc:
            if isinstance(exc, RouterError):
                raise
            raise RouterError("Gemini QA returned an invalid response") from exc
