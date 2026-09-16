import json
from datetime import datetime
from typing import Sequence

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.conversation_exchange import ConversationExchange
from modules.knowledge.service import save_knowledge

DISTILL_INSTRUCTION = """Bạn là chuyên gia đúc kết tri thức về Photoshop, thiết kế 2D và quản lý công việc.
Nhiệm vụ của bạn là đọc các đoạn chat và tìm ra các quy tắc, mẹo, nguyên nhân lỗi, hoặc cách khắc phục lỗi hiệu quả mà người dùng hoặc AI đã nêu ra.
Chỉ tóm tắt thành một hoặc vài câu ngắn gọn mang tính nguyên tắc hoặc hướng dẫn. Bỏ qua các câu chat không mang ý nghĩa tri thức (ví dụ: chào hỏi, kiểm tra số đơn, lệnh bot).
Trả về một JSON có định dạng: {"rules": ["Cách sửa lỗi A: làm B", "Mẹo C: dùng công cụ D"]}. Nếu không có gì đáng lưu, trả về {"rules": []}.
Đảm bảo rằng các câu rule là độc lập và dễ hiểu khi đọc tách rời."""

def distill_exchanges(
    session: Session,
    client: genai.Client,
    model: str,
    since: datetime,
) -> int:
    """Fetch recent exchanges and distill them into knowledge base."""
    statement = (
        select(ConversationExchange)
        .where(ConversationExchange.created_at >= since)
        .order_by(ConversationExchange.created_at.asc())
    )
    exchanges = list(session.scalars(statement))
    
    if not exchanges:
        return 0

    # Group into text block
    text_blocks = []
    for ex in exchanges:
        text_blocks.append(f"User: {ex.user_text}\nAI: {ex.assistant_text}")
    
    chat_content = "\n---\n".join(text_blocks)
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "rules": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            }
        },
        "required": ["rules"]
    }

    try:
        response = client.models.generate_content(
            model=model,
            contents=chat_content,
            config=types.GenerateContentConfig(
                system_instruction=DISTILL_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2,
            )
        )
        if not response.text:
            return 0
        data = json.loads(response.text)
        rules = data.get("rules", [])
    except Exception:
        return 0
        
    saved_count = 0
    for rule in rules:
        if not rule.strip():
            continue
        # Embed rule
        try:
            emb_resp = client.models.embed_content(
                model="text-embedding-004",
                contents=rule,
                config=types.EmbedContentConfig(output_dimensionality=768)
            )
            embedding = emb_resp.embeddings[0].values
            save_knowledge(session, rule, embedding)
            saved_count += 1
        except Exception:
            # Skip if embedding fails
            pass
            
    return saved_count
