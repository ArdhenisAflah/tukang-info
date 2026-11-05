# tukang-info

Forward incoming Telegram direct messages to a WhatsApp chat.

The Telegram side uses the **user API** through Telethon, so it can read DMs sent
to your own account. The WhatsApp side uses WhatsApp Web through Selenium, so no
paid WhatsApp Business API is required.

## Features

- Watch incoming Telegram DMs from a local target list
- Support Telegram usernames, `@username`, and numeric user IDs
- Ignore messages that you send yourself
- Forward to a WhatsApp contact or group by chat name
- Dry-run mode that types into WhatsApp but never presses Enter
- Persistent Telegram and WhatsApp sessions
- Screenshot and page-source evidence when WhatsApp automation fails

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Chromium and matching chromedriver
- A Telegram account
- A WhatsApp account with WhatsApp Web access

## Installation

```bash
git clone <repository-url> tukang-info
cd tukang-info
uv sync
```

## Configuration

Create the local environment file:

```bash
cp .env.example .env
```

Fill in your Telegram API credentials from <https://my.telegram.org>:

```env
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=your-api-hash
```

Create the local target list:

```bash
cp targets.example.txt targets.txt
```

Add one target per line. Use a public username or a numeric user ID:

```text
john
@jane_doe
1234567890
```

Usernames are case-insensitive. If a profile has no public username, use its
numeric ID. In Telegram Web the ID is the number after `#`, for example:

```text
https://web.telegram.org/k/#1234567890  ->  1234567890
```

## Usage

Start the listener:

```bash
uv run main.py
```

The first Telegram run asks for your phone number, login code, and 2FA password
if enabled. Enter the phone number in international format:

```text
081234567890  ->  +6281234567890
```

Telethon stores the login in `tukang-info.session` and reuses it on later runs.

Only incoming private DMs are handled by default. Messages you send are ignored.
Targets are resolved at startup, so restart the listener after changing
`targets.txt` or a username.

## WhatsApp setup

WhatsApp forwarding is disabled until you configure it:

```env
WHATSAPP_ENABLED=true
WHATSAPP_TARGET=Exact WhatsApp chat or group name
```

The first login needs a visible browser so you can scan the WhatsApp QR code:

```bash
WHATSAPP_HEADLESS=false uv run main.py
```

The session is stored in a persistent Chromium profile at:

```text
~/.local/share/tukang-info/whatsapp-profile
```

After the QR login, unattended runs can use:

```env
WHATSAPP_HEADLESS=true
```

Verify login and the target chat without sending anything:

```bash
uv run python check_whatsapp.py
```

## Dry run

To test the complete forwarding path without sending:

```env
WHATSAPP_DRY_RUN=true
```

```bash
uv run main.py
```

Dry-run mode opens the target chat, types the message, verifies the text, clears
the message box, and prints what it would have sent. Enter is never pressed.

Go live by setting:

```env
WHATSAPP_DRY_RUN=false
```

## Message format

Forwarded messages use this format:

```text
<username> <HH:MM>: <message>
```

Example:

```text
@jane_doe 20:41: hello
```

No numeric IDs are included in the forwarded text.

## Attach to an existing Chromium

If you prefer to keep a manually logged-in browser open:

```bash
chromium --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.local/share/tukang-info/whatsapp-chrome"
```

Log in to WhatsApp Web there, then set:

```env
WHATSAPP_ATTACH=127.0.0.1:9222
```

## Architecture

```text
main.py                    Telegram listener + forwarding loop
check_whatsapp.py          Login/target verification without sending
forwarders/base.py         ForwardMessage + MessageForwarder ABC
forwarders/whatsapp.py     WhatsApp Web Selenium implementation
forwarders/__init__.py     Environment-based forwarder factory
```

To add another chat system, subclass `MessageForwarder`, implement `send()`, and
register it in the factory.

## Files

| Path | Purpose |
| --- | --- |
| `targets.txt` | Local target list, gitignored |
| `targets.example.txt` | Committed target template |
| `.env` | Local credentials, gitignored |
| `tukang-info.session` | Telegram login session, gitignored |
| `logs/whatsapp-failed/` | Failure screenshots and HTML, gitignored |

Never commit `.env`, `targets.txt`, `*.session`, or the WhatsApp profile.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `PhoneNumberInvalidError` | Use `+<country><number>`, without the leading `0` |
| WhatsApp asks for QR again | Use `WHATSAPP_HEADLESS=false` and scan it |
| Target chat is not found | Copy the exact chat/group name from WhatsApp Web |
| Selectors stopped working | Inspect `logs/whatsapp-failed/*.html` and update `forwarders/whatsapp.py` |
| Chromium/session error | Close other Selenium/WhatsApp sessions using the same profile |

## Development

```bash
uv run pytest
uv run ruff check .
```
