from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from models.conversation_exchange import ConversationExchange
from models.knowledge import KnowledgeBase
from modules.knowledge.distill import distill_exchanges


def test_distill_exchanges_empty() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    
    client = MagicMock()
    count = distill_exchanges(session, client, "model", datetime.now(timezone.utc))
    assert count == 0
    client.models.generate_content.assert_not_called()


def test_distill_exchanges_with_data() -> None:
    now = datetime.now(timezone.utc)
    ex1 = ConversationExchange(
        telegram_user_id=1,
        chat_id=1,
        user_text="abc",
        assistant_text="def",
        expires_at=now + timedelta(days=1),
        created_at=now - timedelta(hours=1),
    )
    
    session = MagicMock()
    session.scalars.return_value = [ex1]

    client = MagicMock()
    # Mock generation
    mock_response = MagicMock()
    mock_response.text = '{"rules": ["Rule 1", "Rule 2"]}'
    client.models.generate_content.return_value = mock_response
    
    # Mock embedding
    mock_emb_response = MagicMock()
    mock_emb = MagicMock()
    mock_emb.values = [0.1, 0.2]
    mock_emb_response.embeddings = [mock_emb]
    client.models.embed_content.return_value = mock_emb_response

    count = distill_exchanges(session, client, "model", now - timedelta(days=1))
    
    assert count == 2
    client.models.generate_content.assert_called_once()
    assert client.models.embed_content.call_count == 2
    assert session.add.call_count == 2
