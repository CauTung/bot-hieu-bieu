import json
from typing import Any

from fastapi import FastAPI, Request, Response, Header
from pydantic import ValidationError

from core.config import get_settings
from core.db import session_scope
from core.logging import log_event
from core.gemini_router import GeminiIntentRouter
from core.security import is_allowed_user, secrets_match
from core.telegram_client import TelegramClient
from services.bot_service import BotService
from services.update_processor import (
    claim_update,
    complete_update,
    parse_update,
)
from services.reminder_worker import (
    claim_due_reminders,
    mark_reminder_error,
    mark_reminder_sent,
)

app = FastAPI()

MAX_BODY_BYTES = 256_000

@app.post("/api/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)) -> Response:
    try:
        settings = get_settings()
    except ValidationError as exc:
        log_event("configuration_error", errors=exc.error_count())
        return Response(status_code=500, content=json.dumps({"ok": False, "error": "Server configuration error"}), media_type="application/json")

    if not secrets_match(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret):
        return Response(status_code=401, content=json.dumps({"ok": False, "error": "Unauthorized"}), media_type="application/json")

    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return Response(status_code=415, content=json.dumps({"ok": False, "error": "Expected application/json"}), media_type="application/json")

    try:
        content_length = int(request.headers.get("Content-Length", "0"))
    except ValueError:
        return Response(status_code=400, content=json.dumps({"ok": False, "error": "Invalid Content-Length"}), media_type="application/json")
        
    if content_length <= 0 or content_length > MAX_BODY_BYTES:
        return Response(status_code=413, content=json.dumps({"ok": False, "error": "Invalid request size"}), media_type="application/json")

    try:
        body = await request.body()
        payload: dict[str, Any] = json.loads(body)
        context = parse_update(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
        return Response(status_code=400, content=json.dumps({"ok": False, "error": "Invalid Telegram update"}), media_type="application/json")

    if settings.telegram_enforce_allowlist and not is_allowed_user(
        context.user_id, settings.telegram_allowed_user_ids
    ):
        if context.user_id is None:
            return Response(status_code=200, content=json.dumps({"ok": True, "ignored": True}), media_type="application/json")
        log_event("unauthorized_user", update_id=context.update_id, user_id=context.user_id)
        return Response(status_code=200, content=json.dumps({"ok": True, "ignored": True}), media_type="application/json")

    try:
        with session_scope() as session:
            if not claim_update(session, context.update_id):
                return Response(status_code=200, content=json.dumps({"ok": True, "duplicate": True}), media_type="application/json")
            telegram = TelegramClient(settings.telegram_bot_token)
            service = BotService(
                session=session,
                telegram=telegram,
                router=GeminiIntentRouter(
                    settings.gemini_api_key,
                    settings.gemini_router_model,
                    fallback_models=settings.gemini_fallback_models,
                ),
                timezone_name=settings.app_timezone,
                confidence_threshold=settings.intent_confidence_threshold,
                action_ttl_minutes=settings.pending_action_ttl_minutes,
                max_message_length=settings.max_message_length,
            )
            service.process(context)
            complete_update(session, context.update_id)
        log_event("update_completed", update_id=context.update_id)
        return Response(status_code=200, content=json.dumps({"ok": True}), media_type="application/json")
    except Exception as exc:
        import traceback
        err_msg = type(exc).__name__
        if str(exc):
            err_msg += f": {str(exc)}"
        log_event("update_failed", update_id=context.update_id, error=err_msg, traceback=traceback.format_exc())
        return Response(status_code=500, content=json.dumps({"ok": False, "error": "Temporary processing error"}), media_type="application/json")

@app.api_route("/api/check-reminders", methods=["GET", "POST"])
@app.api_route("/api/check_reminders", methods=["GET", "POST"])
async def check_reminders(request: Request, authorization: str = Header(None)) -> Response:
    try:
        settings = get_settings()
    except ValidationError as exc:
        log_event("configuration_error", errors=exc.error_count())
        return Response(status_code=500, content=json.dumps({"ok": False, "error": "Server configuration error"}), media_type="application/json")
        
    expected = f"Bearer {settings.reminder_cron_secret}"
    if not secrets_match(authorization, expected):
        return Response(status_code=401, content=json.dumps({"ok": False, "error": "Unauthorized"}), media_type="application/json")

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
            
    return Response(status_code=200, content=json.dumps({
        "ok": True,
        "claimed": len(reminders),
        "sent": sent,
        "retried": retried,
        "failed": failed,
    }), media_type="application/json")
