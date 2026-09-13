import argparse

import httpx

from core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the Telegram production webhook")
    parser.add_argument("url", help="Stable HTTPS deployment URL, without a trailing slash")
    args = parser.parse_args()
    settings = get_settings()

    response = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook",
        json={
            "url": f"{args.url.rstrip('/')}/api/webhook",
            "secret_token": settings.telegram_webhook_secret,
            "allowed_updates": ["message", "callback_query"],
        },
        timeout=15.0,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("ok") is not True:
        raise RuntimeError(result.get("description", "Telegram rejected setWebhook"))
    print("Webhook registered successfully")


if __name__ == "__main__":
    main()
