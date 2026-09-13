import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from pydantic import ValidationError

from core.config import get_settings
from core.db import session_scope
from core.logging import log_event
from core.security import is_allowed_user, secrets_match
from core.telegram_client import TelegramClient
from services.update_processor import (
    claim_update,
    complete_update,
    parse_update,
    process_placeholder_update,
)

MAX_BODY_BYTES = 256_000


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            settings = get_settings()
        except ValidationError as exc:
            log_event("configuration_error", errors=exc.error_count())
            self._json_response(500, {"ok": False, "error": "Server configuration error"})
            return

        provided_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not secrets_match(provided_secret, settings.telegram_webhook_secret):
            self._json_response(401, {"ok": False, "error": "Unauthorized"})
            return

        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json_response(415, {"ok": False, "error": "Expected application/json"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response(400, {"ok": False, "error": "Invalid Content-Length"})
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self._json_response(413, {"ok": False, "error": "Invalid request size"})
            return

        try:
            payload: dict[str, Any] = json.loads(self.rfile.read(content_length))
            context = parse_update(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            self._json_response(400, {"ok": False, "error": "Invalid Telegram update"})
            return

        if not is_allowed_user(context.user_id, settings.telegram_allowed_user_ids):
            log_event("unauthorized_user", update_id=context.update_id, user_id=context.user_id)
            self._json_response(403, {"ok": False, "error": "Forbidden"})
            return

        try:
            with session_scope() as session:
                if not claim_update(session, context.update_id):
                    self._json_response(200, {"ok": True, "duplicate": True})
                    return
                telegram = TelegramClient(settings.telegram_bot_token)
                process_placeholder_update(context, telegram)
                complete_update(session, context.update_id)
            log_event("update_completed", update_id=context.update_id)
            self._json_response(200, {"ok": True})
        except Exception as exc:
            log_event("update_failed", update_id=context.update_id, error=type(exc).__name__)
            self._json_response(500, {"ok": False, "error": "Temporary processing error"})

    def do_GET(self) -> None:
        self._json_response(405, {"ok": False, "error": "Method not allowed"})

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
