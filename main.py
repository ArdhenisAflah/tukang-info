import asyncio
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

from forwarders import ForwardMessage, build_forwarder_from_env

load_dotenv()

SESSION = "tukang-info"
TARGETS_FILE = Path("targets.txt")


def get_credentials() -> tuple[int, str]:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
    return int(api_id), api_hash


def normalize_phone(value: str) -> str | None:
    value = value.strip()
    digits = re.sub(r"\D", "", value)
    if value.startswith("+") and digits:
        return f"+{digits}"
    return None


def ask_phone() -> str:
    while True:
        value = input(
            "Phone number in international format (example: +6281234567890): "
        )
        phone = normalize_phone(value)
        if phone:
            return phone
        print("Use +<country code><number>, without the leading 0.")


def load_targets(path: Path = TARGETS_FILE) -> list[str]:
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Copy targets.example.txt to targets.txt and add targets."
        )

    targets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        value = value.lstrip("@")
        # Numeric IDs are kept as-is; usernames are case-insensitive.
        targets.append(value if value.isdigit() else value.lower())

    return list(dict.fromkeys(targets))


def target_label(entity) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    first_name = getattr(entity, "first_name", None)
    if first_name:
        return first_name
    return "Unknown"


async def resolve_targets(
    client: TelegramClient, targets: list[str]
) -> dict[int, str]:
    dialogs: dict[int, object] = {}
    async for dialog in client.iter_dialogs():
        if dialog.entity is not None:
            dialogs[dialog.entity.id] = dialog.entity

    resolved: dict[int, str] = {}
    for target in targets:
        entity = None
        if target.isdigit():
            entity = dialogs.get(int(target))
            if entity is None:
                try:
                    entity = await client.get_entity(int(target))
                except Exception as exc:  # noqa: BLE001
                    print(f"Skipping id:{target}: {exc}")
                    continue
        else:
            # Prefer the already-loaded dialog entity when the username matches.
            entity = next(
                (
                    item
                    for item in dialogs.values()
                    if (getattr(item, "username", None) or "").lower() == target
                ),
                None,
            )
            if entity is None:
                try:
                    entity = await client.get_entity(target)
                except Exception as exc:  # noqa: BLE001
                    print(f"Skipping @{target}: {exc}")
                    continue

        resolved[entity.id] = target_label(entity)
    return resolved


async def main() -> None:
    api_id, api_hash = get_credentials()
    targets = load_targets()
    if not targets:
        raise SystemExit("No targets configured. Add targets to targets.txt.")

    client = TelegramClient(SESSION, api_id, api_hash)
    await client.start(phone=ask_phone)

    resolved = await resolve_targets(client, targets)
    if not resolved:
        await client.disconnect()
        raise SystemExit("None of the targets in targets.txt could be resolved.")

    forwarder = None
    forward_lock = asyncio.Lock()
    try:
        forwarder = build_forwarder_from_env()
    except Exception:
        await client.disconnect()
        raise

    @client.on(events.NewMessage(incoming=True))
    async def handler(event) -> None:
        # Private DMs only. Remove this check to also catch group messages.
        if not event.is_private:
            return

        sender = await event.get_sender()
        if sender is None or sender.id not in resolved:
            return

        text = (event.raw_text or "").strip()
        print(f"[{event.date}] {resolved[sender.id]}: {text}")

        if forwarder is None or not text:
            return

        message = ForwardMessage(
            source="Telegram",
            sender=resolved[sender.id],
            text=text,
            timestamp=event.date,
        )
        try:
            async with forward_lock:
                await asyncio.to_thread(forwarder.send, message)
        except Exception as exc:  # noqa: BLE001
            print(f"WhatsApp forward failed: {exc}")

    print(
        f"Listening for DMs from {len(resolved)} target(s): "
        f"{', '.join(sorted(resolved.values()))}"
    )
    if forwarder is not None:
        print("WhatsApp forwarding is enabled.")
    try:
        await client.run_until_disconnected()
    finally:
        if forwarder is not None:
            forwarder.close()


if __name__ == "__main__":
    asyncio.run(main())
