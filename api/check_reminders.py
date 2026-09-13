import json
from http.server import BaseHTTPRequestHandler

from pydantic import ValidationError

from core.config import get_settings
from core.db import session_scope
from core.logging import log_event
from core.security import secrets_match
from core.telegram_client import TelegramClient
from services.reminder_worker import (
    claim_due_reminders,
    mark_reminder_error,
    mark_reminder_sent,
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._run()

    def do_POST(self) -> None:
        self._run()

    def _run(self) -> None:
        try:
            settings = get_settings()
        except ValidationError as exc:
            log_event("configuration_error", errors=exc.error_count())
            self._json_response(500, {"ok": False, "error": "Server configuration error"})
            return
        authorization = self.headers.get("Authorization")
        expected = f"Bearer {settings.reminder_cron_secret}"
        if not secrets_match(authorization, expected):
            self._json_response(401, {"ok": False, "error": "Unauthorized"})
            return

        with session_scope() as session:
            reminders = claim_due_reminders(
                session,
                batch_size=settings.reminder_batch_size,
                lock_timeout_seconds=settings.reminder_lock_timeout_seconds,
            )

        telegram = TelegramClient(settings.telegram_bot_token)
        sent = retried = failed = 0
        for reminder in reminders:
            try:
                telegram.send_message(reminder.chat_id, f"⏰ Nhắc việc: {reminder.content}")
                with session_scope() as session:
                    mark_reminder_sent(session, reminder)
                sent += 1
            except Exception as exc:
                with session_scope() as session:
                    outcome = mark_reminder_error(
                        session,
                        reminder,
                        exc,
                        max_attempts=settings.reminder_max_attempts,
                    )
                if outcome == "failed":
                    failed += 1
                elif outcome == "retried":
                    retried += 1
                log_event(
                    "reminder_delivery_failed",
                    reminder_id=reminder.id,
                    outcome=outcome,
                    error=type(exc).__name__,
                )
        self._json_response(
            200,
            {
                "ok": True,
                "claimed": len(reminders),
                "sent": sent,
                "retried": retried,
                "failed": failed,
            },
        )

    def _json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
