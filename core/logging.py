import json
import logging
from typing import Any

logger = logging.getLogger("bot_hieu_bieu")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def log_event(event: str, **fields: Any) -> None:
    safe_fields = {key: value for key, value in fields.items() if key not in {"token", "secret"}}
    logger.info(json.dumps({"event": event, **safe_fields}, ensure_ascii=False, default=str))
