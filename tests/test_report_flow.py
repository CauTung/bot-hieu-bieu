import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import services.bot_service as bot_module
import services.report_flow as flow_module
from core.gemini_router import RouterError
from core.intent_schema import Intent, IntentDecision
from core.report_schema import ReportDraft, ReportExtraction, ReportRow
from services.report_flow import REPORT_ACTION, ReportFlow
from services.update_processor import UpdateContext
from tests.test_bot_service import make_service, params
from tests.test_sku_image_service import make_image


@pytest.fixture
def flow(monkeypatch):
    session = MagicMock()
    session.get.return_value = None
    telegram = MagicMock()
    router = MagicMock()
    report = ReportFlow(session, telegram, router, "Asia/Ho_Chi_Minh", 15, 30)
    monkeypatch.setattr(flow_module, "snapshot", lambda *args: ({"hiếu": None}, []))
    create = MagicMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(flow_module, "create_pending_action", create)
    report.create_mock = create
    return report


def example_draft():
    return ReportDraft(
        rows=[ReportRow(name="Hiếu", count=90, uncertain=False)],
        report_date=date(2026, 9, 16), date_proposed=True, source="image-1",
    )


def pending_state(flow, monkeypatch, draft=None):
    state = SimpleNamespace(intent=REPORT_ACTION, params=(draft or example_draft()).model_dump(
        mode="json",
    ))
    flow.session.get.return_value = state
    monkeypatch.setattr(flow_module, "get_conversation_state", lambda *args, **kwargs: state)
    return state


def test_missing_date_requires_button_and_fixes_date_in_payload(flow):
    flow.preview(example_draft(), 1, 2)
    message = flow.telegram.send_message.call_args
    assert "hôm nay, ngày 16/09/2026, đúng không?" in message.args[1]
    assert "Hiếu: 90" in message.args[1]
    assert "reply_markup" in message.kwargs
    payload = flow.create_mock.call_args.kwargs["payload"]
    assert payload["draft"]["report_date"] == "2026-09-16"
    # This path only creates a pending action and conversation state, never business rows.
    assert all(type(call.args[0]).__name__ != "PersonReport"
               for call in flow.session.add.call_args_list)


@pytest.mark.parametrize("field,value", [("report_date", None), ("rows", [
    ReportRow(name="?", count=None, uncertain=True),
])])
def test_incomplete_report_has_no_confirm_button(flow, field, value):
    draft = example_draft()
    setattr(draft, field, value)
    flow.preview(draft, 1, 2)
    flow.create_mock.assert_not_called()
    assert "reply_markup" not in flow.telegram.send_message.call_args.kwargs


def test_reject_preserves_rows_for_date_correction(flow, monkeypatch):
    report = example_draft()
    flow.reject({"draft": report.model_dump(mode="json")}, 1, 2)
    state = pending_state(flow, monkeypatch, report)
    assert flow.message("/ngay 15/09/2026", 1, 2)
    assert state.params["rows"][0]["count"] == 90
    assert state.params["report_date"] == "2026-09-15"
    assert state.params["date_proposed"] is False
    assert flow.create_mock.call_args.kwargs["payload"]["draft"]["report_date"] == "2026-09-15"
    # Old pending report buttons are explicitly invalidated on each edit/preview.
    statements = [str(call.args[0]) for call in flow.session.execute.call_args_list]
    assert any("UPDATE pending_actions" in sql for sql in statements)


def test_fix_uncertain_row_then_preview(flow, monkeypatch):
    report = example_draft()
    report.rows[0].uncertain = True
    pending_state(flow, monkeypatch, report)
    flow.message("/sua 1 Hiếu: 0", 1, 2)
    saved = flow.create_mock.call_args.kwargs["payload"]["draft"]
    assert saved["rows"] == [{"name": "Hiếu", "count": 0, "uncertain": False}]


def test_invalid_edit_and_expired_state_never_create_action(flow, monkeypatch):
    pending_state(flow, monkeypatch)
    flow.message("/ngay 31/02/2026", 1, 2)
    flow.message("/sua 99 Hiếu: 10", 1, 2)
    flow.message("/sua 1 Hiếu: -1", 1, 2)
    flow.create_mock.assert_not_called()
    monkeypatch.setattr(flow_module, "get_conversation_state", lambda *args, **kwargs: None)
    flow.message("/xacnhan", 1, 2)
    assert "Không có báo cáo đang chờ" in flow.telegram.send_message.call_args.args[1]


def test_replacement_preview_shows_old_and_new(flow, monkeypatch):
    monkeypatch.setattr(flow_module, "snapshot", lambda *args: ({"hiếu": 1}, ["• Hiếu: 87 → 90"]))
    flow.preview(example_draft(), 1, 2)
    text = flow.telegram.send_message.call_args.args[1]
    assert "THAY THẾ" in text and "87 → 90" in text
    assert flow.create_mock.call_args.kwargs["payload"]["expected"] == {"hiếu": 1}


def test_unknown_photo_or_ai_failure_creates_no_action(flow):
    flow.router.extract_report.return_value = ReportExtraction(
        kind="unknown", rows=[], date_text=None, date_uncertain=False,
    )
    flow.photo(b"photo", "", "unique", 1, 2)
    assert "tra SKU hay nhập số đơn" in flow.telegram.send_message.call_args.args[1]
    flow.router.extract_report.side_effect = RouterError("failure")
    flow.photo(b"photo", "", "unique", 1, 2)
    flow.create_mock.assert_not_called()


def test_split_preview_attaches_button_only_to_last_message(flow, monkeypatch):
    report = example_draft()
    report.rows = [ReportRow(name=f"{i} " + "Tên dài " * 9, count=i, uncertain=False)
                   for i in range(30)]
    monkeypatch.setattr(flow_module, "snapshot", lambda *args: (
        {}, [f"• {row.name}: 100 → {row.count}" for row in report.rows],
    ))
    flow.preview(report, 1, 2)
    calls = flow.telegram.send_message.call_args_list
    assert len(calls) > 1
    assert all(len(call.args[1]) < 4096 for call in calls)
    assert "reply_markup" in calls[-1].kwargs
    assert all("reply_markup" not in call.kwargs for call in calls[:-1])


def test_report_confirm_and_cancel_use_existing_guarded_callback(monkeypatch):
    decision = IntentDecision(intent=Intent.UNKNOWN, params=params(), confidence=1,
                              clarification_question=None)
    service, telegram = make_service(decision)
    action_id = uuid.uuid4()
    action = SimpleNamespace(action_type=REPORT_ACTION,
                             payload={"draft": example_draft().model_dump(mode="json")})
    consume = MagicMock(return_value=action)
    monkeypatch.setattr(bot_module, "consume_pending_action", consume)
    save = MagicMock(return_value="Đã lưu báo cáo.")
    monkeypatch.setattr(bot_module, "save_report", save)
    context = UpdateContext(1, 123, 456, None, "cb", f"confirm:{action_id}", 99)
    service.process(context)
    save.assert_called_once_with(service.session, action.payload, 123, 456)
    assert consume.call_args.kwargs["user_id"] == 123
    assert consume.call_args.kwargs["chat_id"] == 456
    consume.return_value = None  # consumed/expired/wrong scope is rejected by the DB guard
    service.process(context)
    assert save.call_count == 1
    assert "hết hạn" in telegram.answers[-1][1]
    consume.return_value = action
    service.process(UpdateContext(2, 123, 456, None, "cb2", f"cancel:{action_id}", 99))
    assert save.call_count == 1
    assert "Chưa lưu" in telegram.messages[-1][1]


def test_callback_payload_date_is_not_recomputed_at_midnight(monkeypatch):
    service, _ = make_service(IntentDecision(
        intent=Intent.UNKNOWN, params=params(), confidence=1, clarification_question=None,
    ))
    save = MagicMock(return_value="Đã lưu")
    monkeypatch.setattr(bot_module, "save_report", save)
    payload = {"draft": example_draft().model_dump(mode="json")}
    service._execute_action(REPORT_ACTION, payload, 1, 2)
    assert save.call_args.args[1]["draft"]["report_date"] == "2026-09-16"


def test_natural_query_routes_to_reports(monkeypatch):
    service, _ = make_service(IntentDecision(
        intent=Intent.QUERY_REPORTS, params=params(period="2026-09"), confidence=1,
        clarification_question=None,
    ))
    query = MagicMock()
    monkeypatch.setattr(service.reports, "query", query)
    service._handle_read(
        UpdateContext(1, 123, 456, "ai nhiều đơn nhất tháng này", None, None, 10),
        service.router.decision, datetime.now(timezone.utc),
    )
    query.assert_called_once_with("2026-09", 123, 456)


@pytest.mark.parametrize("caption,match,expected_vision", [
    ("", ("VAY01", "exact"), False),
    ("báo cáo số đơn", ("VAY01", "exact"), True),
    ("", (None, "none"), True),
])
def test_photo_dispatch_preserves_sku_lookup(monkeypatch, caption, match, expected_vision):
    service, telegram = make_service(IntentDecision(
        intent=Intent.UNKNOWN, params=params(), confidence=1, clarification_question=None,
    ))
    telegram.download_file = lambda *args: make_image()
    monkeypatch.setattr(bot_module, "find_sku_by_image", lambda *args, **kwargs: match)
    photo = MagicMock()
    monkeypatch.setattr(service.reports, "photo", photo)
    service.process(UpdateContext(1, 123, 456, None, None, None, 10, "file", "unique", caption))
    assert photo.called is expected_vision
    if not expected_vision:
        assert "VAY01" in telegram.messages[-1][1]
