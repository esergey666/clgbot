import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bot.config import BASE_DIR, load_config


def _mask_token(token: str) -> str:
    if ":" not in token:
        return token[:8] + "..."

    bot_id, secret = token.split(":", 1)
    secret_start = secret[:4]
    secret_end = secret[-4:] if len(secret) >= 4 else secret
    return f"{bot_id}:{secret_start}...{secret_end}"


def main() -> None:
    config = load_config()
    env_path = BASE_DIR / ".env"
    print(f"Reading .env from: {env_path}")
    print(f".env exists: {env_path.exists()}")
    print(f"Token length: {len(config.token)}")
    print(f"Token preview: {_mask_token(config.token)}")

    url = f"https://api.telegram.org/bot{config.token}/getMe"

    try:
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        print(f"Token check failed: HTTP {error.code}")
        print(text)
        return
    except URLError as error:
        print(f"Token check failed: {error}")
        return

    if not payload.get("ok"):
        print("Token check failed:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    result = payload["result"]
    print("Token is valid.")
    print(f"Bot: @{result.get('username')} / id={result.get('id')}")


if __name__ == "__main__":
    main()
