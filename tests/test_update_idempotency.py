from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from models.processed_update import ProcessedUpdate
from services.update_processor import claim_update, complete_update


def test_claim_update_adds_processing_record() -> None:
    session = MagicMock()
    assert claim_update(session, 123) is True
    record = session.add.call_args.args[0]
    assert isinstance(record, ProcessedUpdate)
    assert record.update_id == 123
    assert record.status == "processing"
    session.flush.assert_called_once()


def test_duplicate_update_is_not_claimed() -> None:
    session = MagicMock()
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    assert claim_update(session, 123) is False
    session.rollback.assert_called_once()


def test_complete_update_marks_record() -> None:
    record = ProcessedUpdate(update_id=123, status="processing")
    session = MagicMock()
    session.get.return_value = record
    complete_update(session, 123)
    assert record.status == "completed"
    assert record.processed_at is not None
