import hmac


def secrets_match(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def is_allowed_user(user_id: int | None, allowed_user_ids: frozenset[int]) -> bool:
    return user_id is not None and user_id in allowed_user_ids
