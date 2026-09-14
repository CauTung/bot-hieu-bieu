import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.gemini_router import RouterError
from core.intent_schema import Intent, IntentDecision, IntentParams
from core.telegram_client import TelegramAPIError
from models.product import Product
from modules.order.service import add_order, delete_order, list_orders, total_orders, update_order
from modules.reminder.service import cancel_reminder, create_reminder, list_pending_reminders
from modules.sku.image_service import find_sku_by_image, fingerprint_image, save_image_mapping
from modules.sku.service import create_product, delete_product, find_products, update_product
from services.confirmation_service import consume_pending_action, create_pending_action
from services.conversation_history_service import (
    history_context,
    recent_exchanges,
    record_exchange,
)
from services.conversation_service import (
    clear_conversation_state,
    get_conversation_state,
    save_conversation_state,
)
from services.date_ranges import parse_order_period
from services.reminder_presenter import format_confirmation, format_created, format_list
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

    def download_file(self, file_id: str, *, max_bytes: int = 10_000_000) -> bytes: ...


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
        history_retention_days: int,
        history_max_exchanges: int,
        max_message_length: int,
    ) -> None:
        self.session = session
        self.telegram = telegram
        self.router = router
        self.timezone_name = timezone_name
        self.confidence_threshold = confidence_threshold
        self.action_ttl_minutes = action_ttl_minutes
        self.conversation_ttl_minutes = conversation_ttl_minutes
        self.history_retention_days = history_retention_days
        self.history_max_exchanges = history_max_exchanges
        self.max_message_length = max_message_length

    def process(self, context: UpdateContext) -> None:
        if context.callback_query_id:
            self._handle_callback(context)
        elif (
            context.photo_file_id
            and context.photo_file_unique_id
            and context.chat_id is not None
            and context.user_id is not None
        ):
            self._handle_photo(context)
        elif context.text and context.chat_id is not None and context.user_id is not None:
            self._handle_message(context)

    def _handle_photo(self, context: UpdateContext) -> None:
        assert context.chat_id is not None and context.user_id is not None
        assert context.photo_file_id is not None and context.photo_file_unique_id is not None
        self.telegram.send_chat_action(context.chat_id)
        now = datetime.now(timezone.utc)
        sku = self._extract_taught_sku(context.caption or "")
        conversation = get_conversation_state(
            self.session, user_id=context.user_id, chat_id=context.chat_id, now=now
        )
        if (
            sku is None
            and conversation is not None
            and conversation.intent == Intent.REGISTER_SKU_IMAGE.value
        ):
            raw_sku = conversation.params.get("sku")
            sku = str(raw_sku) if raw_sku else None
        try:
            image = self.telegram.download_file(context.photo_file_id)
            fingerprint = fingerprint_image(image)
        except (ValueError, TelegramAPIError) as exc:
            self.telegram.send_message(context.chat_id, str(exc))
            return
        if sku is not None:
            normalized = sku.strip().upper()
            if self.session.get(Product, normalized) is None:
                self.telegram.send_message(
                    context.chat_id, f"Không tìm thấy SKU {normalized}. Hãy tạo SKU trước."
                )
                return
            action = create_pending_action(
                self.session,
                user_id=context.user_id,
                chat_id=context.chat_id,
                action_type=Intent.REGISTER_SKU_IMAGE.value,
                payload={
                    "sku": normalized,
                    "telegram_file_unique_id": context.photo_file_unique_id,
                    "sha256": fingerprint.sha256,
                    "perceptual_hash": fingerprint.perceptual_hash,
                },
                ttl_minutes=self.action_ttl_minutes,
            )
            clear_conversation_state(
                self.session, user_id=context.user_id, chat_id=context.chat_id
            )
            keyboard = {
                "inline_keyboard": [[
                    {"text": "✅ Đúng", "callback_data": f"confirm:{action.id}"},
                    {"text": "❌ Không", "callback_data": f"cancel:{action.id}"},
                ]]
            }
            self.telegram.send_message(
                context.chat_id,
                f"Gắn ảnh này với SKU {normalized}?",
                reply_markup=keyboard,
            )
            return
        matched_sku, match_type = find_sku_by_image(
            self.session,
            telegram_file_unique_id=context.photo_file_unique_id,
            fingerprint=fingerprint,
        )
        if matched_sku:
            qualifier = "" if match_type == "exact" else " (ảnh tương tự)"
            self.telegram.send_message(context.chat_id, f"Đây là mã SKU {matched_sku}{qualifier}.")
        elif match_type == "ambiguous":
            self.telegram.send_message(
                context.chat_id,
                "Ảnh này giống nhiều SKU nên mình chưa thể xác định chính xác.",
            )
        else:
            self.telegram.send_message(
                context.chat_id,
                "Mình chưa nhận ra ảnh này. Hãy gửi ảnh kèm chú thích "
                "“đây là mã SKU VAY01” để dạy bot.",
            )

    def _handle_message(self, context: UpdateContext) -> None:
        assert context.text is not None and context.chat_id is not None
        assert context.user_id is not None
        if len(context.text) > self.max_message_length:
            self.telegram.send_message(context.chat_id, "Tin nhắn quá dài, vui lòng gửi ngắn hơn.")
            return
        if self._handle_static_command(context):
            clear_conversation_state(
                self.session, user_id=context.user_id, chat_id=context.chat_id
            )
            return
        self.telegram.send_chat_action(context.chat_id)
        now = datetime.now(timezone.utc)
        conversation = get_conversation_state(
            self.session, user_id=context.user_id, chat_id=context.chat_id, now=now
        )
        exchanges = recent_exchanges(
            self.session,
            user_id=context.user_id,
            chat_id=context.chat_id,
            limit=self.history_max_exchanges,
            now=now,
        )
        decision = self._classify_locally(context.text)
        if decision is not None and conversation is not None:
            clear_conversation_state(
                self.session, user_id=context.user_id, chat_id=context.chat_id
            )
            conversation = None
        if decision is None:
            try:
                conversation_context: dict[str, object] = {
                    "recent_history": history_context(exchanges)
                }
                if conversation is not None:
                    conversation_context["pending_request"] = {
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
            self._send_and_record(context, question, decision)
            return

        if decision.intent == Intent.REGISTER_SKU_IMAGE:
            waiting = decision.model_copy(
                update={"clarification_question": "Bạn gửi ảnh của SKU này nhé."}
            )
            save_conversation_state(
                self.session,
                user_id=context.user_id,
                chat_id=context.chat_id,
                decision=waiting,
                ttl_minutes=self.conversation_ttl_minutes,
                now=now,
            )
            self._send_and_record(context, "Bạn gửi ảnh của SKU này nhé.", waiting)
            return

        if decision.intent == Intent.CREATE_REMINDER:
            if decision.params.event_at:
                event_at = datetime.fromisoformat(decision.params.event_at)
                if event_at.astimezone(timezone.utc) <= now:
                    incomplete = decision.model_copy(deep=True)
                    incomplete.params.event_at = None
                    incomplete.clarification_question = (
                        "Thời gian sự kiện đó đã qua. Sự kiện diễn ra vào lúc nào?"
                    )
                    save_conversation_state(
                        self.session,
                        user_id=context.user_id,
                        chat_id=context.chat_id,
                        decision=incomplete,
                        ttl_minutes=self.conversation_ttl_minutes,
                        now=now,
                    )
                    self._send_and_record(context, incomplete.clarification_question, incomplete)
                    return
            decision = self._prepare_reminder_times(decision, now)
            assert decision.params.remind_at is not None
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
                self._send_and_record(context, incomplete.clarification_question, incomplete)
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
        self._send_and_record(context, summary, decision, reply_markup=keyboard)

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
            self._record_callback(context, "Đã hủy yêu cầu.", action.action_type, action.payload)
            return
        try:
            result = self._execute_action(
                action.action_type, action.payload, context.user_id, context.chat_id
            )
        except ValueError as exc:
            self.telegram.answer_callback_query(context.callback_query_id, "Không thực hiện được.")
            self.telegram.send_message(context.chat_id, str(exc))
            self._record_callback(context, str(exc), action.action_type, action.payload)
            return
        self.telegram.answer_callback_query(context.callback_query_id, "Đã xác nhận.")
        self.telegram.send_message(context.chat_id, result)
        self._record_callback(context, result, action.action_type, action.payload)

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
                event_at=(
                    datetime.fromisoformat(str(payload["event_at"]))
                    if payload.get("event_at")
                    else None
                ),
            )
            return format_created(reminder, self.timezone_name)
        if action_type == Intent.CANCEL_REMINDER.value:
            cancelled = cancel_reminder(
                self.session,
                reminder_id=uuid.UUID(str(payload["reminder_id"])),
                user_id=user_id,
            )
            return "Đã hủy nhắc việc." if cancelled else "Không tìm thấy nhắc việc có thể hủy."
        if action_type == Intent.REGISTER_SKU_IMAGE.value:
            mapping = save_image_mapping(
                self.session,
                sku=str(payload["sku"]),
                telegram_file_unique_id=str(payload["telegram_file_unique_id"]),
                sha256=str(payload["sha256"]),
                perceptual_hash=str(payload["perceptual_hash"]),
                user_id=user_id,
                chat_id=chat_id,
            )
            return f"Đã ghi nhớ ảnh cho SKU {mapping.sku}. Lần sau chỉ cần gửi ảnh để tra mã."
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
            self._send_and_record(context, text, decision)
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
            text = (
                f"Tổng số lượng từ {start:%d/%m/%Y} đến trước {end:%d/%m/%Y}: {total}."
                f"{suffix}"
            )
            self._send_and_record(context, text, decision)
        elif decision.intent == Intent.LIST_REMINDERS:
            reminders = list_pending_reminders(self.session, user_id=context.user_id)
            if not reminders:
                self._send_and_record(context, "Bạn không có nhắc việc đang chờ.", decision)
                return
            text = format_list(reminders, self.timezone_name)
            self._send_and_record(context, text, decision)
        elif decision.intent == Intent.QA and params.question:
            answer = decision.answer or "Mình chưa có câu trả lời."
            self._send_and_record(context, answer, decision)
        else:
            self._send_and_record(
                context, "Mình chưa hiểu yêu cầu, bạn nói rõ hơn nhé.", decision
            )

    def _send_and_record(
        self,
        context: UpdateContext,
        text: str,
        decision: IntentDecision | None = None,
        **extra: Any,
    ) -> None:
        assert context.chat_id is not None and context.user_id is not None
        self.telegram.send_message(context.chat_id, text, **extra)
        if context.text:
            record_exchange(
                self.session,
                user_id=context.user_id,
                chat_id=context.chat_id,
                user_text=context.text,
                assistant_text=text,
                retention_days=self.history_retention_days,
                intent=decision.intent.value if decision else None,
                details=(decision.params.model_dump(mode="json") if decision else None),
            )

    def _record_callback(
        self,
        context: UpdateContext,
        text: str,
        intent: str,
        details: dict[str, object],
    ) -> None:
        assert context.chat_id is not None and context.user_id is not None
        record_exchange(
            self.session,
            user_id=context.user_id,
            chat_id=context.chat_id,
            user_text="Xác nhận thao tác đang chờ",
            assistant_text=text,
            retention_days=self.history_retention_days,
            intent=intent,
            details=details,
        )

    def _handle_static_command(self, context: UpdateContext) -> bool:
        assert context.chat_id is not None and context.text is not None
        command = context.text.strip().split(maxsplit=1)[0].lower()
        if command not in {"/start", "/help"}:
            return False
        self._send_and_record(
            context,
            "Các lệnh nhanh:\n"
            "• /sku <mã hoặc tên> — tìm SKU\n"
            "• /orders [YYYY-MM hoặc YYYY-MM-DD] — xem tổng đơn\n"
            "• /reminders — xem nhắc việc đang chờ\n"
            "• Gửi ảnh kèm 'đây là mã SKU VAY01' — dạy bot nhận diện ảnh\n"
            "Bạn cũng có thể nhập yêu cầu tự nhiên để bot hỗ trợ.",
        )
        return True

    def _classify_locally(self, text: str) -> IntentDecision | None:
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
            event_at=None,
            reminder_id=None,
            question=None,
        )
        taught_sku = BotService._extract_taught_sku(stripped)
        if taught_sku:
            return IntentDecision(
                intent=Intent.REGISTER_SKU_IMAGE,
                params=empty.model_copy(update={"sku": taught_sku}),
                confidence=1,
                clarification_question=None,
            )
        event_reminder = self._parse_dated_event(stripped, empty)
        if event_reminder is not None:
            return event_reminder
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

    def _parse_dated_event(
        self, text: str, empty: IntentParams
    ) -> IntentDecision | None:
        match = re.fullmatch(
            r"(?:(?:hẹn|hen)\s+)?(\d{1,2})h(?:(\d{1,2}))?\s+(?:ngày|ngay)\s+"
            r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s+(.+)",
            text.strip(),
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        hour, minute, day, month, year, content = match.groups()
        now = datetime.now(ZoneInfo(self.timezone_name))
        target_year = int(year) if year else now.year
        try:
            event_at = datetime(
                target_year,
                int(month),
                int(day),
                int(hour),
                int(minute or 0),
                tzinfo=ZoneInfo(self.timezone_name),
            )
            if year is None and event_at <= now:
                event_at = event_at.replace(year=target_year + 1)
        except ValueError:
            return None
        return IntentDecision(
            intent=Intent.CREATE_REMINDER,
            params=empty.model_copy(
                update={"content": content.strip(), "event_at": event_at.isoformat()}
            ),
            confidence=1,
            clarification_question=None,
        )

    @staticmethod
    def _extract_taught_sku(text: str) -> str | None:
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFD", text.lower())
            if unicodedata.category(char) != "Mn"
        )
        match = re.search(
            r"(?:day\s+la|anh\s+(?:nay\s+)?la|ma)\s+(?:ma\s+)?sku\s*[:#-]?\s*([a-z0-9][a-z0-9._-]{0,99})\b",
            normalized,
        )
        return match.group(1).upper() if match else None

    def _confirmation_summary(self, decision: IntentDecision) -> str:
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
            assert params.content is not None and params.remind_at is not None
            return format_confirmation(
                content=params.content,
                remind_at=datetime.fromisoformat(params.remind_at),
                event_at=datetime.fromisoformat(params.event_at) if params.event_at else None,
                timezone_name=self.timezone_name,
            )
        if decision.intent == Intent.CANCEL_REMINDER:
            return f"Hủy nhắc việc {params.reminder_id}?"
        raise ValueError("Intent không cần xác nhận")

    @staticmethod
    def _prepare_reminder_times(decision: IntentDecision, now: datetime) -> IntentDecision:
        prepared = decision.model_copy(deep=True)
        if prepared.params.event_at and not prepared.params.remind_at:
            event_at = datetime.fromisoformat(prepared.params.event_at)
            default_remind_at = event_at - timedelta(hours=2)
            if default_remind_at.astimezone(timezone.utc) <= now:
                default_remind_at = now + timedelta(minutes=1)
            prepared.params.remind_at = default_remind_at.isoformat()
        return prepared
