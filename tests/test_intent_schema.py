import pytest
from pydantic import ValidationError

from core.intent_schema import Intent, IntentDecision, IntentParams, intent_json_schema


def empty_params(**overrides: object) -> IntentParams:
    values: dict[str, object] = {
        "sku": None,
        "new_sku": None,
        "order_id": None,
        "name": None,
        "tags": None,
        "notes": None,
        "quantity": None,
        "order_date": None,
        "source": None,
        "period": None,
        "content": None,
        "remind_at": None,
        "reminder_id": None,
        "question": None,
    }
    values.update(overrides)
    return IntentParams.model_validate(values)


def test_create_sku_requires_sku_and_name() -> None:
    decision = IntentDecision(
        intent=Intent.CREATE_SKU,
        params=empty_params(sku="VAY01", name="Váy xếp ly"),
        confidence=0.98,
        clarification_question=None,
    )
    assert decision.params.sku == "VAY01"


def test_missing_parameter_requires_clarification() -> None:
    with pytest.raises(ValidationError, match="clarification_question"):
        IntentDecision(
            intent=Intent.ADD_ORDER,
            params=empty_params(sku="VAY01", quantity=5),
            confidence=0.7,
            clarification_question=None,
        )


def test_quantity_must_be_positive() -> None:
    decision = IntentDecision(
        intent=Intent.ADD_ORDER,
        params=empty_params(sku="VAY01", quantity=0, order_date="2026-09-13"),
        confidence=0.9,
        clarification_question=None,
    )
    assert decision.params.quantity is None
    assert decision.clarification_question is not None


def test_invalid_reminder_datetime_becomes_clarification() -> None:
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=empty_params(content="Gửi mẫu", remind_at="15:00"),
        confidence=0.9,
        clarification_question=None,
    )
    assert decision.params.remind_at is None
    assert "ngày và giờ" in str(decision.clarification_question)


def test_json_schema_is_strict() -> None:
    schema = intent_json_schema()
    assert schema["additionalProperties"] is False
    params_schema = schema["$defs"]["IntentParams"]  # type: ignore[index]
    assert params_schema["additionalProperties"] is False  # type: ignore[index]


def test_edit_sku_requires_a_changed_field() -> None:
    with pytest.raises(ValidationError, match="changed field"):
        IntentDecision(
            intent=Intent.EDIT_SKU,
            params=empty_params(sku="VAY01"),
            confidence=1,
            clarification_question=None,
        )


def test_delete_order_requires_valid_uuid() -> None:
    decision = IntentDecision(
        intent=Intent.DELETE_ORDER,
        params=empty_params(order_id="not-a-uuid"),
        confidence=1,
        clarification_question=None,
    )
    assert decision.params.order_id is None
    assert decision.clarification_question is not None
