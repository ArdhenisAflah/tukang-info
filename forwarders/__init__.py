import os
from pathlib import Path

from .base import ForwardMessage, MessageForwarder


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_forwarder_from_env() -> MessageForwarder | None:
    if not _env_bool("WHATSAPP_ENABLED"):
        return None

    target = os.getenv("WHATSAPP_TARGET", "").strip()
    if not target:
        raise SystemExit("WHATSAPP_TARGET is required when WHATSAPP_ENABLED=true")

    from .whatsapp import WhatsAppWebForwarder

    profile_dir = Path(
        os.path.expanduser(
            os.getenv(
                "WHATSAPP_PROFILE_DIR",
                "~/.local/share/tukang-info/whatsapp-profile",
            )
        )
    )
    attach = os.getenv("WHATSAPP_ATTACH") or None
    timeout = int(os.getenv("WHATSAPP_TIMEOUT", "45"))

    return WhatsAppWebForwarder(
        target=target,
        profile_dir=profile_dir,
        headless=_env_bool("WHATSAPP_HEADLESS"),
        attach=attach,
        timeout=timeout,
        dry_run=_env_bool("WHATSAPP_DRY_RUN"),
    )


__all__ = ["ForwardMessage", "MessageForwarder", "build_forwarder_from_env"]
