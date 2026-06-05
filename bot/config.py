from dataclasses import dataclass
from os import getenv
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: list[int]
    template_path: Path
    font_path: Path
    number_font_path: Path
    qr_template_path: Path
    price_tag_template_path: Path
    receipt_template_path: Path
    clg2026_template_path: Path
    clg2026_arial_font_path: Path
    clg2026_arial_bold_font_path: Path
    access_users_path: Path


def _parse_admin_ids(value: str | None) -> list[int]:
    return [int(item.strip()) for item in (value or "").split(",") if item.strip()]


def _get_env_value(*names: str) -> str | None:
    for name in names:
        value = getenv(name)
        if value and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def load_config() -> BotConfig:
    load_dotenv(BASE_DIR / ".env")
    token = _get_env_value("BOT_TOKEN", "bot", "TOKEN")
    if not token:
        raise RuntimeError("Telegram bot token is missing. Set BOT_TOKEN in environment variables.")

    return BotConfig(
        token=token,
        admin_ids=_parse_admin_ids(_get_env_value("ADMIN_IDS", "admins")),
        template_path=ASSETS_DIR / "back.png",
        font_path=ASSETS_DIR / "font.ttf",
        number_font_path=ASSETS_DIR / "num.ttf",
        qr_template_path=ASSETS_DIR / "maket.jpg",
        price_tag_template_path=ASSETS_DIR / "price_tag_template.png",
        receipt_template_path=ASSETS_DIR / "receipt_template.png",
        clg2026_template_path=ASSETS_DIR / "clg2026" / "template.png",
        clg2026_arial_font_path=ASSETS_DIR / "clg2026" / "arial.ttf",
        clg2026_arial_bold_font_path=ASSETS_DIR / "clg2026" / "arialbd.ttf",
        access_users_path=DATA_DIR / "users.json",
    )
