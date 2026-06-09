import argparse
import asyncio
from pathlib import Path

from bot.config import ASSETS_DIR, DATA_DIR
from bot.services.clg2026_generator import Clg2026Generator
from bot.services.label_generator import LabelGenerator


def _format_code(value: str) -> str:
    compact_code = value.replace(" ", "")
    return "  ".join([compact_code[i:i + 3] for i in range(0, len(compact_code), 3)])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a label locally without starting the Telegram bot.",
    )
    parser.add_argument("--type", choices=["main", "clg2026"], default="main")
    parser.add_argument("--art", required=True, help="Article, for example 761530404")
    parser.add_argument("--color", required=True, help="Color, for example V0158")
    parser.add_argument("--size", required=True, help="Size, for example 30")
    parser.add_argument("--code", required=True, help="Product code, for example TOM068804")
    parser.add_argument("--certilogo-code", required=True, help="Certilogo code, for example CLG047604293519")
    parser.add_argument("--certilogo-url", required=True, help="QR content or URL")
    parser.add_argument("--output", help="Output PNG path. Defaults to data/local_label.png")
    return parser


async def _generate(args: argparse.Namespace) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else DATA_DIR / "local_label.png"

    if args.type == "clg2026":
        generator = Clg2026Generator(
            ASSETS_DIR / "clg2026" / "template.png",
            ASSETS_DIR / "clg2026" / "arial.ttf",
            ASSETS_DIR / "clg2026" / "arialbd.ttf",
            ASSETS_DIR / "num.ttf",
            ASSETS_DIR / "maket.jpg",
        )
        image = await generator.generate_label(
            art=args.art,
            color=args.color,
            size_tag=args.size,
            code=args.code,
            certilogo_code=_format_code(args.certilogo_code),
            certilogo_url=args.certilogo_url,
        )
    else:
        generator = LabelGenerator(
            ASSETS_DIR / "back.png",
            ASSETS_DIR / "font.ttf",
            ASSETS_DIR / "num.ttf",
            ASSETS_DIR / "maket.jpg",
        )
        image = await generator.generate_label(
            art=args.art,
            color=args.color,
            size_tag=args.size,
            code=args.code,
            certilogo_code=_format_code(args.certilogo_code),
            certilogo_url=args.certilogo_url,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image.getvalue())
    return output_path


def main() -> None:
    args = _build_parser().parse_args()
    output_path = asyncio.run(_generate(args))
    print(f"Generated: {output_path.resolve()}")


if __name__ == "__main__":
    main()
