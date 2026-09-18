import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.knowledge import KnowledgeBase
from modules.knowledge.service import save_knowledge, search_knowledge


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    # For SQLite, the pgvector Vector type will just be treated as a blob/string
    # We can create the table successfully
    KnowledgeBase.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_save_knowledge(session: Session) -> None:
    kb = save_knowledge(session, "Lỗi cọ: dùng F5", [0.1, 0.2, 0.3])
    assert kb.id is not None
    assert kb.content == "Lỗi cọ: dùng F5"
    assert kb.embedding == [0.1, 0.2, 0.3]
    assert kb.use_count == 0


def test_search_knowledge_mocked(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    # Since SQLite does not support cosine_distance, we must mock the search
    save_knowledge(session, "A", [0.1])
    save_knowledge(session, "B", [0.2])
    
    # We can mock the query execution directly on the session
    def mock_scalars(statement):
        # Return all for testing the use_count update logic
        return session.query(KnowledgeBase).all()

    monkeypatch.setattr(session, "scalars", mock_scalars)
    
    results = search_knowledge(session, [0.1], limit=10)
    assert len(results) == 2
    
    # Assert use_count was incremented
    session.refresh(results[0])
    assert results[0].use_count == 1
    assert results[0].last_used_at is not None
