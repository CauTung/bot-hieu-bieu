import unicodedata
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.report_schema import ReportDraft, ReportExtraction, ReportRow, person_key
from models.person_report import PersonReport
from modules.report.service import existing_rows, report_summary, save_report, snapshot
from services.date_ranges import parse_order_period
from services.report_flow import draft_from_image


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    PersonReport.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def draft(day="2026-09-16", **counts):
    return ReportDraft(
        rows=[ReportRow(name=name, count=count, uncertain=False) for name, count in counts.items()],
        report_date=day, source="telegram-image",
    )


def persist(session, report, user_id=1, chat_id=2):
    expected, _ = snapshot(session, report, user_id, chat_id)
    return save_report(
        session, {"draft": report.model_dump(mode="json"), "expected": expected}, user_id, chat_id,
    )


@pytest.mark.parametrize("caption,image_day,unclear,expected,proposed", [
    ("", None, False, "2026-09-16", True),
    ("báo cáo số đơn", None, False, "2026-09-16", True),
    ("hôm qua", None, False, "2026-09-15", False),
    ("số đơn ngày 14/09/2026", None, False, "2026-09-14", False),
    ("báo cáo 14-09-2026", None, False, "2026-09-14", False),
    ("báo cáo 14.09.2026", None, False, "2026-09-14", False),
    ("", "ngày 14/09/2026", False, "2026-09-14", False),
    ("", "13/09/2026", False, "2026-09-13", False),
    ("", "01/02", False, None, False),
    ("ngày 01/02", None, False, None, False),
    ("ngày 31/02/2026", None, False, None, False),
    ("ngày thứ ba", None, False, None, False),
    ("16/09/2026", "15/09/2026", False, None, False),
    ("16/09/2026 và 15/09/2026", None, False, None, False),
    ("", None, True, None, False),
    ("", "5:24 PM", False, None, False),
])
def test_date_evidence(caption, image_day, unclear, expected, proposed):
    extracted = ReportExtraction(
        kind="report", rows=[ReportRow(name="Hiếu", count=90, uncertain=False)],
        date_text=image_day, date_uncertain=unclear,
    )
    result = draft_from_image(extracted, caption, "image-1", date(2026, 9, 16))
    assert result.report_date == (date.fromisoformat(expected) if expected else None)
    assert result.date_proposed is proposed


@pytest.mark.parametrize("count", [-1, 1.5, True, "97", 2_147_483_648])
def test_reject_invalid_counts(count):
    with pytest.raises(ValidationError):
        ReportRow(name="Huyền", count=count, uncertain=False)


def test_duplicate_rows_cannot_be_saved(session):
    report = draft(Hiếu=90)
    report.rows.append(ReportRow(name="HIẾU", count=20, uncertain=False))
    with pytest.raises(ValueError, match="trùng"):
        persist(session, report)
    assert list(session.scalars(select(PersonReport))) == []


def test_names_keep_accents_and_do_not_fuzzy_merge():
    assert person_key("  HIẾU  ") == person_key(unicodedata.normalize("NFD", "Hiếu"))
    assert person_key("Hiếu") != person_key("Hieu")
    assert person_key("Hiếu") != person_key("Hiếu Bảnh")


def test_save_replace_and_stale_snapshot_are_atomic(session):
    initial = draft(Hiếu=90, Nhung=0)
    result = persist(session, initial)
    assert "90 đơn" in result
    replacement = draft(Hiếu=97, Nhung=1)
    expected, changes = snapshot(session, replacement, 1, 2)
    assert "• Hiếu: 90 → 97" in changes
    persist(session, draft(Nhung=3))
    with pytest.raises(ValueError, match="đã thay đổi"):
        save_report(session, {"draft": replacement.model_dump(mode="json"), "expected": expected},
                    1, 2)
    current = existing_rows(session, 1, 2, date(2026, 9, 16))
    assert current[person_key("Hiếu")].count == 90  # no partial update of earlier row
    assert current[person_key("Nhung")].count == 3
    persist(session, replacement)
    current = existing_rows(session, 1, 2, date(2026, 9, 16))
    assert current[person_key("Hiếu")].count == 97  # replacement, not 187
    assert len(current) == 2


def test_replaying_initial_snapshot_does_not_duplicate(session):
    report = draft(Hiếu=90)
    expected, _ = snapshot(session, report, 1, 2)
    payload = {"draft": report.model_dump(mode="json"), "expected": expected}
    save_report(session, payload, 1, 2)
    with pytest.raises(ValueError, match="đã thay đổi"):
        save_report(session, payload, 1, 2)
    assert len(list(session.scalars(select(PersonReport)))) == 1


def test_monthly_totals_ties_coverage_boundaries_and_scope(session):
    persist(session, draft("2026-09-01", Hiếu=90, Nhung=97, Huyền=0))
    persist(session, draft("2026-09-30", Hiếu=7, Nhung=0))
    persist(session, draft("2026-10-01", Hiếu=1000))
    persist(session, draft(Other=500), user_id=9)
    persist(session, draft(OtherChat=700), chat_id=9)
    start, end = parse_order_period(
        None, now=datetime(2026, 8, 31, 17, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
    )
    result = report_summary(session, 1, 2, start, end)
    assert "1. Hiếu: 97 đơn (2 ngày có dữ liệu" in result
    assert "1. Nhung: 97 đơn (2 ngày có dữ liệu" in result
    assert "3. Huyền: 0 đơn (1 ngày có dữ liệu" in result
    assert "Tổng: 194 đơn" in result
    assert "Other" not in result
    assert "1000" not in result
    assert "ngày chưa nhập không được coi là 0" in result
    daily = report_summary(session, 1, 2, date(2026, 9, 30), date(2026, 10, 1))
    assert "Tổng: 7 đơn" in daily
