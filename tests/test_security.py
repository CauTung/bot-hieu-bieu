import logging

import core.logging  # noqa: F401
from core.security import is_allowed_user, secrets_match


def test_secret_must_be_present_and_equal() -> None:
    assert secrets_match("correct-secret", "correct-secret")
    assert not secrets_match(None, "correct-secret")
    assert not secrets_match("wrong-secret", "correct-secret")


def test_allowlist_rejects_missing_and_unknown_users() -> None:
    allowed = frozenset({123})
    assert is_allowed_user(123, allowed)
    assert not is_allowed_user(456, allowed)
    assert not is_allowed_user(None, allowed)


def test_http_client_info_logs_are_disabled_to_protect_tokens() -> None:
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
