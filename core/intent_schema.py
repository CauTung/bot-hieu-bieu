from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Intent(str, Enum):
    CREATE_SKU = "create_sku"
    LOOKUP_SKU = "lookup_sku"
    ADD_ORDER = "add_order"
    QUERY_ORDERS = "query_orders"
    CREATE_REMINDER = "create_reminder"
    LIST_REMINDERS = "list_reminders"
    CANCEL_REMINDER = "cancel_reminder"
    QA = "qa"
    UNKNOWN = "unknown"


class IntentParams(BaseModel):
    """Fixed shape keeps the Structured Output schema strict; unused values are null."""

    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(description="Mã SKU do người dùng nêu")
    name: str | None = Field(description="Tên mẫu hoặc từ khóa tìm mẫu")
    tags: list[str] | None = Field(description="Danh sách tag sản phẩm")
    notes: str | None = Field(description="Ghi chú sản phẩm")
    quantity: int | None = Field(description="Số lượng sản phẩm nguyên dương")
    order_date: str | None = Field(description="Ngày đơn hàng dạng YYYY-MM-DD")
    source: str | None = Field(description="Nguồn đơn hàng")
    period: str | None = Field(description="Ngày YYYY-MM-DD, tháng YYYY-MM, hoặc null")
    content: str | None = Field(description="Nội dung nhắc việc")
    remind_at: str | None = Field(description="Thời điểm ISO 8601 có timezone")
    reminder_id: str | None = Field(description="UUID của nhắc việc cần hủy")
    question: str | None = Field(description="Câu hỏi tự do nguyên văn")


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    params: IntentParams
    confidence: float = Field(ge=0, le=1)
    clarification_question: str | None
    answer: str | None = Field(
        default=None,
        description="Câu trả lời hoàn chỉnh khi intent là qa; null với intent khác",
    )

    @model_validator(mode="after")
    def validate_required_params(self) -> "IntentDecision":
        if self.params.quantity is not None and self.params.quantity <= 0:
            self.params.quantity = None
            self.clarification_question = (
                self.clarification_question or "Số lượng phải lớn hơn 0, bạn muốn ghi bao nhiêu?"
            )
        if self.params.order_date is not None:
            try:
                date.fromisoformat(self.params.order_date)
            except ValueError:
                self.params.order_date = None
                self.clarification_question = (
                    self.clarification_question or "Ngày đơn hàng là ngày nào?"
                )
        if self.params.remind_at is not None:
            try:
                parsed_reminder = datetime.fromisoformat(self.params.remind_at)
                if parsed_reminder.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError:
                self.params.remind_at = None
                self.clarification_question = (
                    self.clarification_question or "Bạn muốn được nhắc vào ngày và giờ nào?"
                )
        required: dict[Intent, tuple[str, ...]] = {
            Intent.CREATE_SKU: ("sku", "name"),
            Intent.LOOKUP_SKU: (),
            Intent.ADD_ORDER: ("sku", "quantity", "order_date"),
            Intent.QUERY_ORDERS: (),
            Intent.CREATE_REMINDER: ("content", "remind_at"),
            Intent.CANCEL_REMINDER: ("reminder_id",),
            Intent.QA: ("question",),
        }
        missing = [
            field for field in required.get(self.intent, ()) if getattr(self.params, field) is None
        ]
        if missing and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when intent parameters are missing: "
                + ", ".join(missing)
            )
        if (
            self.intent == Intent.QA
            and self.params.question
            and not self.clarification_question
            and not self.answer
        ):
            raise ValueError("answer is required for qa intent")
        if (
            self.intent == Intent.LOOKUP_SKU
            and not (self.params.sku or self.params.name)
            and not self.clarification_question
        ):
            raise ValueError("clarification_question is required when SKU search is empty")
        return self


def intent_json_schema() -> dict[str, object]:
    return IntentDecision.model_json_schema()
