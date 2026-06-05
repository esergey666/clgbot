"""Compatibility entry point.

Можно запускать по-старому:
python bot/bot.py
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.main import main  # noqa: E402


if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
