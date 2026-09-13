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
