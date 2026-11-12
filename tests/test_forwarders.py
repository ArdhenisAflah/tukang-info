from datetime import datetime
from pathlib import Path

import pytest

from forwarders import build_forwarder_from_env
from forwarders.base import ForwardMessage
from forwarders.whatsapp import (
    build_chrome_options,
    build_firefox_options,
    format_message,
    xpath_literal,
)


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


def test_chrome_headless_uses_desktop_user_agent(tmp_path: Path) -> None:
    options = build_chrome_options(tmp_path, headless=True)

    user_agent = next(
        argument for argument in options.arguments if argument.startswith("--user-agent=")
    )
    assert "HeadlessChrome" not in user_agent
    assert "--window-size=1400,900" in options.arguments
    assert "--headless=new" in options.arguments


def test_firefox_headless_options(tmp_path: Path) -> None:
    options = build_firefox_options(tmp_path, headless=True)

    assert "-headless" in options.arguments
    assert "general.useragent.override" in options.preferences


def test_forwarder_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)

    assert build_forwarder_from_env() is None


def test_forwarder_requires_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.delenv("WHATSAPP_TARGET", raising=False)

    with pytest.raises(SystemExit):
        build_forwarder_from_env()
