from dotenv import load_dotenv

from forwarders import build_forwarder_from_env

load_dotenv()


def main() -> None:
    forwarder = build_forwarder_from_env()
    if forwarder is None:
        raise SystemExit(
            "WhatsApp forwarding is disabled. Set WHATSAPP_ENABLED=true "
            "and WHATSAPP_TARGET in .env."
        )

    print("WhatsApp login and target chat are OK.")
    forwarder.close()


if __name__ == "__main__":
    main()
