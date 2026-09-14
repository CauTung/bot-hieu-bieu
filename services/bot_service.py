import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.gemini_router import RouterError
from core.intent_schema import Intent, IntentDecision, IntentParams
from modules.order.service import add_order, delete_order, list_orders, total_orders, update_order
from modules.reminder.service import cancel_reminder, create_reminder, list_pending_reminders
from modules.sku.service import create_product, delete_product, find_products, update_product
from services.confirmation_service import consume_pending_action, create_pending_action
from services.conversation_service import (
    clear_conversation_state,
    get_conversation_state,
    save_conversation_state,
)
from services.date_ranges import parse_order_period
from services.update_processor import UpdateContext


class RouterPort(Protocol):
    def classify(
        self,
        text: str,
        *,
        now: datetime,
        timezone_name: str,
        telegram_user_id: int,
        conversation_context: dict[str, object] | None = None,
    ) -> IntentDecision: ...


class TelegramPort(Protocol):
    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]: ...

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None: ...

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None: ...

    def edit_message_reply_markup(self, chat_id: int, message_id: int) -> None: ...


class BotService:
    def __init__(
        self,
        *,
        session: Session,
        telegram: TelegramPort,
        router: RouterPort,
        timezone_name: str,
        confidence_threshold: float,
        action_ttl_minutes: int,
        conversation_ttl_minutes: int,
        max_message_length: int,
    ) -> None:
        self.session = session
        self.telegram = telegram
        self.router = router
        self.timezone_name = timezone_name
        self.confidence_threshold = confidence_threshold
        self.action_ttl_minutes = action_ttl_minutes
        self.conversation_ttl_minutes = conversation_ttl_minutes
        self.max_message_length = max_message_length

    def process(self, context: UpdateContext) -> None:
        if context.callback_query_id:
            self._handle_callback(context)
        elif context.text and context.chat_id is not None and context.user_id is not None:
            self._handle_message(context)

    def _handle_message(self, context: UpdateContext) -> None:
        assert context.text is not None and context.chat_id is not None
        assert context.user_id is not None
        if len(context.text) > self.max_message_length:
            self.telegram.send_message(context.chat_id, "Tin nhắn quá dài, vui lòng gửi ngắn hơn.")
            return
        if self._handle_static_command(context.chat_id, context.text):
            clear_conversation_state(
                self.session, user_id=context.user_id, chat_id=context.chat_id
            )
            return
        self.telegram.send_chat_action(context.chat_id)
        now = datetime.now(timezone.utc)
        conversation = get_conversation_state(
            self.session, user_id=context.user_id, chat_id=context.chat_id, now=now
        )
        decision = self._classify_locally(context.text)
        if decision is not None and conversation is not None:
            clear_conversation_state(
                self.session, user_id=context.user_id, chat_id=context.chat_id
            )
            conversation = None
        if decision is None:
            try:
                conversation_context: dict[str, object] | None = None
                if conversation is not None:
                    conversation_context = {
                        "intent": conversation.intent,
                        "params": conversation.params,
                        "clarification_question": conversation.clarification_question,
                    }
                decision = self.router.classify(
                    context.text,
                    now=now.astimezone(ZoneInfo(self.timezone_name)),
                    timezone_name=self.timezone_name,
                    telegram_user_id=context.user_id,
                    conversation_context=conversation_context,
                )
            except RouterError:
                self.telegram.send_message(
                    context.chat_id,
                    "Mình đang gặp sự cố với dịch vụ AI. Bạn thử lại sau ít phút nhé.",
                )
                return
        if decision.clarification_question or decision.confidence < self.confidence_threshold:
            question = decision.clarification_question or "Bạn có thể nói rõ yêu cầu hơn không?"
            if decision.intent != Intent.UNKNOWN:
                save_conversation_state(
                    self.session,
                    user_id=context.user_id,
                    chat_id=context.chat_id,
                    decision=decision,
                    ttl_minutes=self.conversation_ttl_minutes,
                    now=now,
                )
            self.telegram.send_message(context.chat_id, question)
            return

        if decision.intent == Intent.CREATE_REMINDER and decision.params.remind_at:
            remind_at = datetime.fromisoformat(decision.params.remind_at)
            if remind_at.astimezone(timezone.utc) <= now:
                incomplete = decision.model_copy(deep=True)
                incomplete.params.remind_at = None
                incomplete.clarification_question = (
                    "Thời gian đó đã qua. Bạn muốn được nhắc vào ngày và giờ nào?"
                )
                save_conversation_state(
                    self.session,
                    user_id=context.user_id,
                    chat_id=context.chat_id,
                    decision=incomplete,
                    ttl_minutes=self.conversation_ttl_minutes,
                    now=now,
                )
                self.telegram.send_message(
                    context.chat_id,
                    incomplete.clarification_question,
                )
                return

        clear_conversation_state(
            self.session, user_id=context.user_id, chat_id=context.chat_id
        )

        if decision.intent in {
            Intent.CREATE_SKU,
            Intent.EDIT_SKU,
            Intent.DELETE_SKU,
            Intent.ADD_ORDER,
            Intent.EDIT_ORDER,
            Intent.DELETE_ORDER,
            Intent.CREATE_REMINDER,
            Intent.CANCEL_REMINDER,
        }:
            self._request_confirmation(context, decision)
            return
        self._handle_read(context, decision, now)

    def _request_confirmation(self, context: UpdateContext, decision: IntentDecision) -> None:
        assert context.user_id is not None and context.chat_id is not None
        action = create_pending_action(
            self.session,
            user_id=context.user_id,
            chat_id=context.chat_id,
            action_type=decision.intent.value,
            payload=decision.params.model_dump(mode="json"),
            ttl_minutes=self.action_ttl_minutes,
        )
        summary = self._confirmation_summary(decision)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Đúng", "callback_data": f"confirm:{action.id}"},
                    {"text": "❌ Không", "callback_data": f"cancel:{action.id}"},
                ]
            ]
        }
        self.telegram.send_message(context.chat_id, summary, reply_markup=keyboard)

    def _handle_callback(self, context: UpdateContext) -> None:
        assert context.callback_query_id is not None
        if context.user_id is None or context.chat_id is None or not context.callback_data:
            self.telegram.answer_callback_query(context.callback_query_id, "Callback không hợp lệ.")
            return
        verb, separator, raw_id = context.callback_data.partition(":")
        if not separator or verb not in {"confirm", "cancel"}:
            self.telegram.answer_callback_query(context.callback_query_id, "Callback không hợp lệ.")
            return
        try:
            action_id = uuid.UUID(raw_id)
        except ValueError:
            self.telegram.answer_callback_query(context.callback_query_id, "Callback không hợp lệ.")
            return
        action = consume_pending_action(
            self.session,
            action_id=action_id,
            user_id=context.user_id,
            chat_id=context.chat_id,
            confirm=verb == "confirm",
        )
        if action is None:
            self.telegram.answer_callback_query(
                context.callback_query_id, "Yêu cầu đã hết hạn hoặc đã được xử lý."
            )
            return
        if context.message_id is not None:
            self.telegram.edit_message_reply_markup(context.chat_id, context.message_id)
        if verb == "cancel":
            self.telegram.answer_callback_query(context.callback_query_id, "Đã hủy.")
            self.telegram.send_message(context.chat_id, "Đã hủy yêu cầu.")
            return
        try:
            result = self._execute_action(
                action.action_type, action.payload, context.user_id, context.chat_id
            )
        except ValueError as exc:
            self.telegram.answer_callback_query(context.callback_query_id, "Không thực hiện được.")
            self.telegram.send_message(context.chat_id, str(exc))
            return
        self.telegram.answer_callback_query(context.callback_query_id, "Đã xác nhận.")
        self.telegram.send_message(context.chat_id, result)

    def _execute_action(
        self, action_type: str, payload: dict[str, object], user_id: int, chat_id: int
    ) -> str:
        if action_type == Intent.CREATE_SKU.value:
            raw_tags = payload.get("tags")
            tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else None
            raw_notes = payload.get("notes")
            notes = raw_notes if isinstance(raw_notes, str) else None
            product, created = create_product(
                self.session,
                sku=str(payload["sku"]),
                name=str(payload["name"]),
                tags=tags,
                notes=notes,
            )
            return (
                f"Đã lưu SKU {product.sku} cho mẫu '{product.name}'."
                if created
                else f"SKU {product.sku} đã tồn tại cho mẫu '{product.name}'."
            )
        if action_type == Intent.EDIT_SKU.value:
            raw_tags = payload.get("tags")
            tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else None
            product = update_product(
                self.session,
                sku=str(payload["sku"]),
                new_sku=(
                    str(payload["new_sku"])
                    if payload.get("new_sku") is not None
                    else None
                ),
                name=str(payload["name"]) if payload.get("name") is not None else None,
                tags=tags,
                notes=str(payload["notes"]) if payload.get("notes") is not None else None,
            )
            return f"Đã cập nhật SKU {product.sku}: {product.name}."
        if action_type == Intent.DELETE_SKU.value:
            sku = str(payload["sku"])
            return (
                f"Đã xóa SKU {sku.upper()}."
                if delete_product(self.session, sku=sku)
                else f"Không tìm thấy SKU {sku.upper()}."
            )
        if action_type == Intent.ADD_ORDER.value:
            raw_source = payload.get("source")
            source = raw_source if isinstance(raw_source, str) else None
            order = add_order(
                self.session,
                sku=str(payload["sku"]),
                quantity=int(str(payload["quantity"])),
                order_date=date.fromisoformat(str(payload["order_date"])),
                telegram_user_id=user_id,
                source=source,
            )
            return (
                f"Đã ghi nhận {order.quantity} sản phẩm SKU {order.sku} "
                f"ngày {order.order_date:%d/%m/%Y}."
            )
        if action_type == Intent.EDIT_ORDER.value:
            raw_date = payload.get("order_date")
            order = update_order(
                self.session,
                order_id=uuid.UUID(str(payload["order_id"])),
                telegram_user_id=user_id,
                sku=str(payload["new_sku"]) if payload.get("new_sku") else None,
                quantity=int(str(payload["quantity"])) if payload.get("quantity") else None,
                order_date=date.fromisoformat(str(raw_date)) if raw_date else None,
                source=str(payload["source"]) if payload.get("source") is not None else None,
            )
            return (
                f"Đã cập nhật order {order.id}: {order.quantity} sản phẩm SKU {order.sku}, "
                f"ngày {order.order_date:%d/%m/%Y}."
            )
        if action_type == Intent.DELETE_ORDER.value:
            order_id = uuid.UUID(str(payload["order_id"]))
            return (
                f"Đã xóa order {order_id}."
                if delete_order(
                    self.session, order_id=order_id, telegram_user_id=user_id
                )
                else "Không tìm thấy order hoặc order không thuộc tài khoản của bạn."
            )
        if action_type == Intent.CREATE_REMINDER.value:
            reminder = create_reminder(
                self.session,
                user_id=user_id,
                chat_id=chat_id,
                content=str(payload["content"]),
                remind_at=datetime.fromisoformat(str(payload["remind_at"])),
            )
            local_time = reminder.remind_at.astimezone(ZoneInfo(self.timezone_name))
            return f"Đã đặt nhắc lúc {local_time:%H:%M %d/%m/%Y}: {reminder.content}"
        if action_type == Intent.CANCEL_REMINDER.value:
            cancelled = cancel_reminder(
                self.session,
                reminder_id=uuid.UUID(str(payload["reminder_id"])),
                user_id=user_id,
            )
            return "Đã hủy nhắc việc." if cancelled else "Không tìm thấy nhắc việc có thể hủy."
        raise ValueError("Loại hành động không được hỗ trợ")

    def _handle_read(self, context: UpdateContext, decision: IntentDecision, now: datetime) -> None:
        assert context.user_id is not None and context.chat_id is not None
        params = decision.params
        if decision.intent == Intent.LOOKUP_SKU:
            query = params.sku or params.name or ""
            products = find_products(self.session, query)
            text = "Không tìm thấy SKU phù hợp."
            if products:
                text = "\n".join(f"• {item.sku} — {item.name}" for item in products)
            self.telegram.send_message(context.chat_id, text)
        elif decision.intent == Intent.QUERY_ORDERS:
            start, end = parse_order_period(
                params.period, now=now, timezone_name=self.timezone_name
            )
            total = total_orders(
                self.session, telegram_user_id=context.user_id, start_date=start, end_date=end
            )
            orders = list_orders(
                self.session,
                telegram_user_id=context.user_id,
                start_date=start,
                end_date=end,
            )
            details = "\n".join(
                f"• {item.id} — {item.order_date:%d/%m/%Y} — {item.sku} × {item.quantity}"
                for item in orders
            )
            suffix = f"\nCác order gần nhất:\n{details}" if details else ""
            self.telegram.send_message(
                context.chat_id,
                f"Tổng số lượng từ {start:%d/%m/%Y} đến trước {end:%d/%m/%Y}: {total}."
                f"{suffix}",
            )
        elif decision.intent == Intent.LIST_REMINDERS:
            reminders = list_pending_reminders(self.session, user_id=context.user_id)
            if not reminders:
                self.telegram.send_message(context.chat_id, "Bạn không có nhắc việc đang chờ.")
                return
            zone = ZoneInfo(self.timezone_name)
            text = "\n".join(
                f"• {item.id} — {item.remind_at.astimezone(zone):%H:%M %d/%m/%Y}: {item.content}"
                for item in reminders
            )
            self.telegram.send_message(context.chat_id, text)
        elif decision.intent == Intent.QA and params.question:
            answer = decision.answer or "Mình chưa có câu trả lời."
            self.telegram.send_message(context.chat_id, answer)
        else:
            self.telegram.send_message(
                context.chat_id, "Mình chưa hiểu yêu cầu, bạn nói rõ hơn nhé."
            )

    def _handle_static_command(self, chat_id: int, text: str) -> bool:
        command = text.strip().split(maxsplit=1)[0].lower()
        if command not in {"/start", "/help"}:
            return False
        self.telegram.send_message(
            chat_id,
            "Các lệnh nhanh:\n"
            "• /sku <mã hoặc tên> — tìm SKU\n"
            "• /orders [YYYY-MM hoặc YYYY-MM-DD] — xem tổng đơn\n"
            "• /reminders — xem nhắc việc đang chờ\n"
            "Bạn cũng có thể nhập yêu cầu tự nhiên để bot hỗ trợ.",
        )
        return True

    @staticmethod
    def _classify_locally(text: str) -> IntentDecision | None:
        stripped = text.strip()
        command, _, argument = stripped.partition(" ")
        command = command.lower()
        empty = IntentParams(
            sku=None,
            new_sku=None,
            order_id=None,
            name=None,
            tags=None,
            notes=None,
            quantity=None,
            order_date=None,
            source=None,
            period=None,
            content=None,
            remind_at=None,
            reminder_id=None,
            question=None,
        )
        if command == "/sku":
            query = argument.strip()
            if not query:
                return IntentDecision(
                    intent=Intent.LOOKUP_SKU,
                    params=empty,
                    confidence=1,
                    clarification_question="Bạn muốn tìm mã SKU hoặc tên mẫu nào?",
                )
            return IntentDecision(
                intent=Intent.LOOKUP_SKU,
                params=empty.model_copy(update={"sku": query}),
                confidence=1,
                clarification_question=None,
            )
        if command == "/orders":
            return IntentDecision(
                intent=Intent.QUERY_ORDERS,
                params=empty.model_copy(update={"period": argument.strip() or None}),
                confidence=1,
                clarification_question=None,
            )
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFD", stripped.lower())
            if unicodedata.category(char) != "Mn"
        )
        if command == "/reminders" or normalized in {
            "danh sach nhac viec",
            "xem nhac viec",
        }:
            return IntentDecision(
                intent=Intent.LIST_REMINDERS,
                params=empty,
                confidence=1,
                clarification_question=None,
            )
        return None

    @staticmethod
    def _confirmation_summary(decision: IntentDecision) -> str:
        params = decision.params
        if decision.intent == Intent.CREATE_SKU:
            return f"Tạo SKU {params.sku} cho mẫu '{params.name}'?"
        if decision.intent == Intent.EDIT_SKU:
            changes = ", ".join(
                f"{label}: {value}"
                for label, value in (
                    ("mã mới", params.new_sku),
                    ("tên", params.name),
                    ("tags", params.tags),
                    ("ghi chú", params.notes),
                )
                if value is not None
            )
            return f"Cập nhật SKU {params.sku} — {changes}?"
        if decision.intent == Intent.DELETE_SKU:
            return f"Xóa SKU {params.sku}? Thao tác này không thể hoàn tác."
        if decision.intent == Intent.ADD_ORDER:
            return f"Ghi {params.quantity} sản phẩm SKU {params.sku} ngày {params.order_date}?"
        if decision.intent == Intent.EDIT_ORDER:
            return f"Cập nhật order {params.order_id} theo thông tin vừa nhập?"
        if decision.intent == Intent.DELETE_ORDER:
            return f"Xóa order {params.order_id}? Thao tác này không thể hoàn tác."
        if decision.intent == Intent.CREATE_REMINDER:
            return f"Đặt nhắc lúc {params.remind_at}: {params.content}?"
        if decision.intent == Intent.CANCEL_REMINDER:
            return f"Hủy nhắc việc {params.reminder_id}?"
        raise ValueError("Intent không cần xác nhận")
