import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def parse_order_period(
    period: str | None, *, now: datetime, timezone_name: str
) -> tuple[date, date]:
    local_now = now.astimezone(ZoneInfo(timezone_name))
    if not period:
        first = date(local_now.year, local_now.month, 1)
        return first, _next_month(first)
    try:
        if len(period) == 7:
            first = datetime.strptime(period, "%Y-%m").date().replace(day=1)
            return first, _next_month(first)
        selected = date.fromisoformat(period)
        return selected, selected + timedelta(days=1)
    except ValueError as exc:
        raise ValueError("Khoảng ngày phải có dạng YYYY-MM hoặc YYYY-MM-DD") from exc


def _next_month(value: date) -> date:
    days = calendar.monthrange(value.year, value.month)[1]
    return value + timedelta(days=days)
