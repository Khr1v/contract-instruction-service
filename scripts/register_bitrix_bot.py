from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.integrations.bitrix_chat_adapter import BitrixChatAdapter  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    event_url = settings.bitrix_bot_event_url
    if not event_url:
        if not settings.public_base_url:
            raise RuntimeError("Set PUBLIC_BASE_URL or BITRIX_BOT_EVENT_URL")
        event_url = f"{settings.public_base_url.rstrip('/')}/api/bitrix/bot/events"

    result = await BitrixChatAdapter(settings).register_bot(event_url)
    payload = result.get("result")
    if isinstance(payload, dict):
        bot_id = payload.get("ID") or payload.get("id") or payload.get("BOT_ID")
    else:
        bot_id = payload
    print("Bitrix bot registered.")
    print(f"Event URL: {event_url}")
    if bot_id:
        print(f"BITRIX_BOT_ID={bot_id}")
        print("Put this value into .env on the server.")
    else:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
