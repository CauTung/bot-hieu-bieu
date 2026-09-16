import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import unicodedata
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.gemini_router import RouterError
from core.report_schema import ReportDraft, ReportExtraction, ReportRow
from models.conversation_state import ConversationState
from models.pending_action import PendingAction
from modules.report.service import report_summary, save_report, scope_lock, snapshot
from services.confirmation_service import consume_pending_action, create_pending_action
from services.conversation_service import clear_conversation_state, get_conversation_state
from services.date_ranges import parse_order_period

REPORT_ACTION = "save_person_report"


class ReportRouter(Protocol):
    def extract_report(self, image: bytes, caption: str) -> ReportExtraction: ...


class ReportTelegram(Protocol):
    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]: ...


def explicit_date(text: str, today: date) -> date | None:
    """Accept a complete calendar date or an explicit relative day, never time-only."""
    stripped = text.strip().casefold()
    stripped = re.sub(r"^(?:(?:ngày|ngay)\s+)", "", stripped)
    if stripped in {"hôm nay", "hom nay"}:
        return today
    if stripped in {"hôm qua", "hom qua"}:
        return today - timedelta(days=1)
    for pattern, fmt, has_year in (
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d", True),
        (r"\d{1,2}/\d{1,2}/\d{4}", "%d/%m/%Y", True),
        (r"\d{1,2}-\d{1,2}-\d{4}", "%d-%m-%Y", True),
        (r"\d{1,2}\.\d{1,2}\.\d{4}", "%d.%m.%Y", True),
        (r"\d{1,2}/\d{1,2}", "%d/%m", False),
        (r"\d{1,2}-\d{1,2}", "%d-%m", False),
        (r"\d{1,2}\.\d{1,2}", "%d.%m", False),
    ):
        if re.fullmatch(pattern, stripped):
            try:
                parsed = datetime.strptime(stripped, fmt).date()
                if not has_year:
                    parsed = parsed.replace(year=today.year)
                return parsed
            except ValueError:
                return None
    return None


def caption_date(caption: str, today: date) -> tuple[date | None, bool]:
    candidates = re.findall(
        r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)(?!\d)"
        r"|hôm nay|hom nay|hôm qua|hom qua",
        caption.casefold(),
    )
    if not candidates:
        return None, bool(re.search(
            r"\b(?:ngày|ngay|hôm|hom|tháng|thang|tuần|tuan)\b", caption.casefold(),
        ))
    dates = {explicit_date(value, today) for value in candidates}
    if len(dates) != 1 or None in dates:
        return None, True
    return dates.pop(), False


def draft_from_image(
    extracted: ReportExtraction, caption: str, source: str, today: date,
) -> ReportDraft:
    image_date = explicit_date(extracted.date_text, today) if extracted.date_text else None
    supplied_date, caption_uncertain = caption_date(caption, today)
    unclear = (
        extracted.date_uncertain or caption_uncertain
        or bool(extracted.date_text and image_date is None)
        or bool(image_date and supplied_date and image_date != supplied_date)
    )
    proposed = not unclear and image_date is None and supplied_date is None
    return ReportDraft(
        rows=extracted.rows,
        report_date=None if unclear else (supplied_date or image_date or today),
        date_proposed=proposed, source=source,
    )


class ReportFlow:
    def __init__(
        self, session: Session, telegram: ReportTelegram, router: ReportRouter,
        timezone_name: str, action_ttl: int, conversation_ttl: int,
    ) -> None:
        self.session = session
        self.telegram = telegram
        self.router = router
        self.timezone_name = timezone_name
        self.action_ttl = action_ttl
        self.conversation_ttl = conversation_ttl

    def photo(self, image: bytes, caption: str, source: str, user_id: int, chat_id: int) -> None:
        try:
            extracted = self.router.extract_report(image, caption)
        except RouterError:
            self.telegram.send_message(chat_id, "Chưa đọc được ảnh. Bạn thử gửi lại sau nhé.")
            return
        if extracted.kind != "report" or not extracted.rows:
            self.telegram.send_message(
                chat_id,
                "Bạn muốn tra SKU hay nhập số đơn theo người? Nếu nhập số đơn, gửi ảnh rõ "
                "tối đa 30 dòng kèm chú thích ‘báo cáo số đơn’. "
                "Nếu dạy SKU, gửi ảnh kèm ‘đây là mã SKU VAY01’.",
            )
            return
        draft = draft_from_image(
            extracted, caption, source, datetime.now(ZoneInfo(self.timezone_name)).date(),
        )
        self.preview(draft, user_id, chat_id)

    def _invalidate(self, user_id: int, chat_id: int) -> None:
        self.session.execute(update(PendingAction).where(
            PendingAction.telegram_user_id == user_id,
            PendingAction.chat_id == chat_id,
            PendingAction.action_type == REPORT_ACTION,
            PendingAction.status == "pending",
        ).values(status="cancelled"))

    def abandon(self, user_id: int, chat_id: int) -> None:
        scope_lock(self.session, user_id, chat_id)
        self._invalidate(user_id, chat_id)
        clear_conversation_state(self.session, user_id=user_id, chat_id=chat_id)

    def remember(self, draft: ReportDraft, user_id: int, chat_id: int) -> None:
        state = self.session.get(ConversationState, (user_id, chat_id))
        if state is None:
            state = ConversationState(telegram_user_id=user_id, chat_id=chat_id)
            self.session.add(state)
        state.intent = REPORT_ACTION
        state.params = draft.model_dump(mode="json")
        state.clarification_question = "Sửa ngày/số liệu hoặc xác nhận bản xem trước."
        state.expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.conversation_ttl)
        self.session.flush()

    def preview(self, draft: ReportDraft, user_id: int, chat_id: int) -> None:
        scope_lock(self.session, user_id, chat_id)
        self._invalidate(user_id, chat_id)
        self.remember(draft, user_id, chat_id)
        lines = ["Mình đọc được số đơn:"]
        for index, row in enumerate(draft.rows, 1):
            flag = " (chưa rõ)" if row.uncertain else ""
            lines.append(
                f"{index}. {row.name or '?'}: {row.count if row.count is not None else '?'}{flag}"
            )
        if draft.report_date:
            if draft.date_proposed:
                lines.append(
                    f"Đây là số đơn hôm nay, ngày {draft.report_date:%d/%m/%Y}, đúng không?"
                )
            else:
                lines.append(f"Ngày báo cáo: {draft.report_date:%d/%m/%Y}.")
        problem = draft.problem()
        if problem:
            lines.append(problem)
            self.send_chunks(chat_id, "\n".join(lines))
            return
        expected, changes = snapshot(self.session, draft, user_id, chat_id)
        if changes:
            lines.append("Đã có dữ liệu. Xác nhận sẽ THAY THẾ số cũ → số mới, không cộng thêm:")
            lines.extend(changes)
        lines.append("Kiểm tra ngày, tên và số đơn. Chỉ lưu khi bấm ✅ Đúng.")
        lines.append("Sửa: /ngay DD/MM/YYYY hoặc /sua 2 Tên: số đơn. Hủy: /huy.")
        action = create_pending_action(
            self.session, user_id=user_id, chat_id=chat_id, action_type=REPORT_ACTION,
            payload={"draft": draft.model_dump(mode="json"), "expected": expected},
            ttl_minutes=self.action_ttl,
        )
        self.send_chunks(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": [[
            {"text": "✅ Đúng", "callback_data": f"confirm:{action.id}"},
            {"text": "❌ Không", "callback_data": f"cancel:{action.id}"},
        ]]})

    def reject(self, payload: dict[str, object], user_id: int, chat_id: int) -> None:
        self.remember(ReportDraft.model_validate(payload["draft"]), user_id, chat_id)
        self.telegram.send_message(
            chat_id, "Chưa lưu. Gửi /ngay DD/MM/YYYY để sửa ngày, /sua 2 Tên: số đơn "
            "để sửa dòng, /xoadong 2 để bỏ dòng, hoặc /huy để bỏ báo cáo.",
        )

    def message(self, text: str, user_id: int, chat_id: int) -> bool:
        command, _, argument = text.strip().partition(" ")
        command = command.casefold()
        if command in {"/reports", "/baocao"}:
            self.query(argument.strip() or None, user_id, chat_id)
            return True
        state = get_conversation_state(self.session, user_id=user_id, chat_id=chat_id)
        if state is None or state.intent != REPORT_ACTION:
            if command in {"/ngay", "/sua", "/xoadong", "/xacnhan", "/huy"}:
                self.telegram.send_message(chat_id, "Không có báo cáo đang chờ. Bạn gửi ảnh nhé.")
                return True
            return False
        if command.startswith("/") and command not in {
            "/ngay", "/sua", "/xoadong", "/xacnhan", "/huy",
        }:
            self.abandon(user_id, chat_id)
            return False

        normalized_text = "".join(
            char for char in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(char) != "Mn"
        )
        if re.search(r"^(huy|thoi|bo|huy bo)$", normalized_text.strip()):
            self.abandon(user_id, chat_id)
            self.telegram.send_message(chat_id, "Đã hủy báo cáo, chưa ghi số liệu.")
            return True

        if normalized_text.strip() == "khong":
            state = get_conversation_state(self.session, user_id=user_id, chat_id=chat_id)
            if state:
                self.reject(state.params, user_id, chat_id)
            return True

        if re.search(r"^(dung|dung roi|ok|oke|chuan|yes|xac nhan)$", normalized_text.strip()):
            action = self.session.scalar(select(PendingAction).where(
                PendingAction.telegram_user_id == user_id,
                PendingAction.chat_id == chat_id,
                PendingAction.action_type == REPORT_ACTION,
                PendingAction.status == "pending"
            ).order_by(PendingAction.created_at.desc()).limit(1))
            if action:
                scope_lock(self.session, user_id, chat_id)
                action = consume_pending_action(
                    self.session, action_id=action.id, user_id=user_id, chat_id=chat_id, confirm=True
                )
                if action:
                    try:
                        result = save_report(self.session, action.payload, user_id, chat_id)
                        clear_conversation_state(self.session, user_id=user_id, chat_id=chat_id)
                        self.telegram.send_message(chat_id, result)
                    except ValueError as exc:
                        self.telegram.send_message(chat_id, str(exc))
                else:
                    self.telegram.send_message(chat_id, "Yêu cầu đã hết hạn hoặc đã được xử lý.")
                return True

        scope_lock(self.session, user_id, chat_id)
        # Any edit invalidates old buttons, including an invalid edit awaiting clarification.
        self._invalidate(user_id, chat_id)
        if command == "/huy":
            clear_conversation_state(self.session, user_id=user_id, chat_id=chat_id)
            self.telegram.send_message(chat_id, "Đã hủy báo cáo, chưa ghi số liệu.")
            return True
        draft = ReportDraft.model_validate(state.params)
        today = datetime.now(ZoneInfo(self.timezone_name)).date()
        
        if command == "/ngay":
            selected = explicit_date(argument, today)
        else:
            selected, _ = caption_date(text, today)
            
        try:
            if selected:
                draft.report_date = selected
                draft.date_proposed = False
            elif command == "/sua":
                match = re.fullmatch(r"(\d+)\s+(.+?):\s*(\d+)", argument.strip())
                if not match:
                    raise ValueError("Gửi /sua 2 Huyền: 97 (số thứ tự dòng, tên, số đơn).")
                index = int(match[1]) - 1
                if not 0 <= index < len(draft.rows):
                    raise ValueError("Số thứ tự dòng không tồn tại.")
                draft.rows[index] = ReportRow(name=match[2], count=int(match[3]), uncertain=False)
            elif command == "/xoadong":
                if not argument.strip().isdigit() or not 1 <= int(argument) <= len(draft.rows):
                    raise ValueError("Gửi /xoadong kèm số thứ tự dòng đang hiển thị.")
                if len(draft.rows) == 1:
                    raise ValueError("Chỉ còn một dòng. Gửi /huy nếu muốn bỏ báo cáo.")
                del draft.rows[int(argument) - 1]
            elif command != "/xacnhan":
                raise ValueError(
                    "Chưa lưu. Gửi /ngay DD/MM/YYYY, /sua 2 Tên: số đơn, "
                    "/xacnhan để xem lại hoặc /huy."
                )
        except ValueError:
            self.telegram.send_message(
                chat_id, "Thông tin chưa hợp lệ. Dùng /ngay DD/MM/YYYY; "
                "/sua 2 Tên: số nguyên không âm; /xoadong 2; /xacnhan hoặc /huy.",
            )
            return True
        self.preview(draft, user_id, chat_id)
        return True

    def query(self, period: str | None, user_id: int, chat_id: int) -> None:
        try:
            start, end = parse_order_period(
                period, now=datetime.now(timezone.utc), timezone_name=self.timezone_name,
            )
            result = report_summary(self.session, user_id, chat_id, start, end)
        except ValueError as exc:
            self.telegram.send_message(chat_id, str(exc))
            return
        self.send_chunks(chat_id, result)

    def send_chunks(self, chat_id: int, text: str, **extra: Any) -> None:
        chunks: list[str] = []
        current = ""
        for line in text.splitlines():
            if len(current) + len(line) + 1 > 3500:
                chunks.append(current)
                current = ""
            current += ("\n" if current else "") + line
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks):
            self.telegram.send_message(
                chat_id, chunk, **(extra if index == len(chunks) - 1 else {}),
            )
