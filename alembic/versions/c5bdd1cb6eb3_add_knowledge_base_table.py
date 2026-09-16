"""Add knowledge_base table

Revision ID: c5bdd1cb6eb3
Revises: 20260916_0006
Create Date: 2026-09-17 00:08:35.506169
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision: str = 'c5bdd1cb6eb3'
down_revision: Union[str, None] = '20260916_0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the vector extension (must be superuser, Supabase allows this)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        'knowledge_base',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(768), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Use hnsw index for vector cosine similarity
    op.execute('CREATE INDEX idx_knowledge_base_embedding ON knowledge_base USING hnsw (embedding vector_cosine_ops)')


def downgrade() -> None:
    op.drop_table('knowledge_base')

