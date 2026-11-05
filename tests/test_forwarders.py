from datetime import datetime

import pytest

from forwarders import build_forwarder_from_env
from forwarders.base import ForwardMessage
from forwarders.whatsapp import format_message, xpath_literal


def test_format_message() -> None:
    message = ForwardMessage(
        source="Telegram",
        sender="@john",
        text="hello\nthere",
        timestamp=datetime(2026, 11, 5, 20, 41),
    )

    assert format_message(message) == "@john 20:41: hello there"


def test_xpath_literal_handles_quotes() -> None:
    assert xpath_literal("john") == "'john'"
    assert xpath_literal("o'connor") == '"o\'connor"'
    assert xpath_literal('a"b\'c') == "concat('a\"b', \"'\", 'c')"


def test_forwarder_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)

    assert build_forwarder_from_env() is None


def test_forwarder_requires_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.delenv("WHATSAPP_TARGET", raising=False)

    with pytest.raises(SystemExit):
        build_forwarder_from_env()
