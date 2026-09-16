from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from models.knowledge import KnowledgeBase


def save_knowledge(session: Session, content: str, embedding: list[float]) -> KnowledgeBase:
    """Save a new distilled knowledge rule to the database."""
    kb = KnowledgeBase(content=content, embedding=embedding)
    session.add(kb)
    session.flush()
    return kb


def search_knowledge(
    session: Session, query_embedding: list[float], limit: int = 3, similarity_threshold: float = 0.7
) -> list[KnowledgeBase]:
    """Search for relevant knowledge using cosine distance.
    Distance < 0.3 means similarity > 0.7.
    Returns the top matching knowledge pieces.
    """
    # vector_cosine_ops calculates distance, smaller is better (0 is identical)
    # Cosine distance = 1 - Cosine similarity.
    # So similarity > 0.7 means distance < 0.3
    distance_threshold = 1.0 - similarity_threshold

    statement = (
        select(KnowledgeBase)
        .where(KnowledgeBase.embedding.cosine_distance(query_embedding) < distance_threshold)
        .order_by(KnowledgeBase.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    results = list(session.scalars(statement))
    
    # Update usage counts
    if results:
        now = datetime.now(timezone.utc)
        ids = [kb.id for kb in results]
        session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id.in_(ids))
            .values(use_count=KnowledgeBase.use_count + 1, last_used_at=now)
        )
        session.flush()

    return results
