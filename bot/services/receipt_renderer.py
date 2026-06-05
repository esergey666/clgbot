from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from .price_tag_renderer import CODE128_PATTERNS
except ImportError:
    from price_tag_renderer import CODE128_PATTERNS


BASE_SIZE = (780, 2048)
DEFAULT_SIZE_MM = (80.0, 210.0)
DEFAULT_BARCODE = "1042010164784"


def generate_sale_number(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return str(rng.randint(10000, 99999))


def generate_receipt_datetime(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("%d/%m/%Y %I:%M %p")


def generate_receipt_barcode(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return "".join(rng.choices("0123456789", k=13))


@dataclass(frozen=True)
class ReceiptData:
    article: str
    color: str
    size: str
    item_name: str
    price: str | int | float
    sale_number: str = field(default_factory=generate_sale_number)
    date_time: str = field(default_factory=generate_receipt_datetime)
    barcode: str = field(default_factory=generate_receipt_barcode)


class ReceiptRenderer:
    def __init__(
        self,
        template_path: str | Path,
        font_path: str | Path,
        size_mm: tuple[float, float] = DEFAULT_SIZE_MM,
    ) -> None:
        self.template_path = Path(template_path)
        self.font_path = Path(font_path)
        self.size_mm = size_mm

        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        if not self.font_path.exists():
            raise FileNotFoundError(f"Font not found: {self.font_path}")

        self.template = Image.open(self.template_path).convert("RGBA")
        self.scale_x = self.template.width / BASE_SIZE[0]
        self.scale_y = self.template.height / BASE_SIZE[1]

    def _pos(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self.scale_x), round(y * self.scale_y)

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        scaled_size = max(1, round(size * min(self.scale_x, self.scale_y)))
        return ImageFont.truetype(self.font_path, scaled_size)

    def _text_width(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_right(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont) -> None:
        x, y = self._pos(*xy)
        draw.text((x - self._text_width(draw, text, font), y), text, font=font, fill="black")

    def _draw_center(self, draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont) -> None:
        x = (self.template.width - self._text_width(draw, text, font)) // 2
        draw.text((x, self._pos(0, y)[1]), text, font=font, fill="black")

    def _format_price(self, value: str | int | float) -> str:
        if isinstance(value, str):
            normalized = value.strip().replace(" ", "").replace(",", ".")
            number = float(normalized)
        else:
            number = float(value)
        return f"{number:.2f}".replace(".", ",")

    def _price_number(self, value: str | int | float) -> float:
        if isinstance(value, str):
            return float(value.strip().replace(" ", "").replace(",", "."))
        return float(value)

    def _format_tax_row_price(self, value: float) -> str:
        return f"Ç{value:.2f}".replace(".", ",")

    def _dpi(self) -> tuple[float, float]:
        width_mm, height_mm = self.size_mm
        return (
            self.template.width / (width_mm / 25.4),
            self.template.height / (height_mm / 25.4),
        )

    def _code128_values(self, text: str) -> list[int]:
        if any(ord(char) < 32 or ord(char) > 126 for char in text):
            raise ValueError("Code 128 renderer supports ASCII characters from 32 to 126.")

        values = [104]
        values.extend(ord(char) - 32 for char in text)
        checksum = values[0] + sum(value * index for index, value in enumerate(values[1:], start=1))
        values.append(checksum % 103)
        values.append(106)
        return values

    def _draw_code128(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        box: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = box
        left, top = self._pos(left, top)
        right, bottom = self._pos(right, bottom)
        values = self._code128_values(text)
        modules = sum(sum(int(width) for width in CODE128_PATTERNS[value]) for value in values)
        module_width = (right - left) / modules
        cursor = float(left)

        for value in values:
            for index, width_char in enumerate(CODE128_PATTERNS[value]):
                next_cursor = cursor + int(width_char) * module_width
                if index % 2 == 0:
                    draw.rectangle(
                        [round(cursor), top, max(round(next_cursor), round(cursor) + 1), bottom],
                        fill="black",
                    )
                cursor = next_cursor

    def render_image(self, data: ReceiptData) -> Image.Image:
        img = self.template.copy()
        draw = ImageDraw.Draw(img)

        regular = self._font(32)
        small = self._font(29)
        medium = self._font(37)
        total_label = self._font(51)
        total_value = self._font(55)
        tax_big = self._font(52)
        tax_label = self._font(36)
        tax_table = self._font(27)
        barcode_text_font = self._font(35)

        total = self._price_number(data.price)
        vat = round(total / 6, 2)
        ht = round(total - vat, 2)
        price_text = self._format_price(total)
        vat_text = self._format_price(vat)
        ht_table_text = self._format_tax_row_price(ht)
        vat_table_text = self._format_tax_row_price(vat)
        total_table_text = self._format_tax_row_price(total)
        item_code = f"{data.article.strip().upper()}.{data.color.strip().upper()}.{data.size.strip().upper()}"
        barcode = data.barcode.strip() or DEFAULT_BARCODE

        draw.rectangle([self._pos(250, 820), self._pos(560, 878)], fill="white")
        self._draw_center(draw, 836, f"VENTE N. {data.sale_number.strip()}", medium)
        self._draw_center(draw, 880, data.date_time.strip(), regular)

        draw.text(self._pos(36, 927), item_code, font=regular, fill="black")
        draw.text(self._pos(36, 969), f"1x{data.item_name.strip().upper()}", font=regular, fill="black")
        self._draw_right(draw, (690, 969), price_text, regular)
        self._draw_right(draw, (690, 1012), f"TVA 20,00% {vat_text}", small)

        self._draw_right(draw, (690, 1175), price_text, total_value)
        draw.text(self._pos(274, 1285), "Dont TVA 20% Euro :", font=tax_label, fill="black")
        self._draw_right(draw, (760, 1273), vat_text, tax_big)

        self._draw_right(draw, (720, 1400), price_text, regular)
        draw.text(self._pos(173, 1507), ht_table_text, font=tax_table, fill="black")
        draw.text(self._pos(283, 1507), vat_table_text, font=tax_table, fill="black")
        draw.text(self._pos(396, 1507), total_table_text, font=tax_table, fill="black")
        draw.text(self._pos(173, 1548), ht_table_text, font=tax_table, fill="black")
        draw.text(self._pos(283, 1548), vat_table_text, font=tax_table, fill="black")
        draw.text(self._pos(396, 1548), total_table_text, font=tax_table, fill="black")

        self._draw_code128(draw, barcode, (68, 1873, 720, 1960))
        spaced_barcode = " ".join(barcode)
        self._draw_center(draw, 1972, spaced_barcode, barcode_text_font)

        return img

    def render(self, data: ReceiptData) -> BytesIO:
        output = BytesIO()
        self.render_image(data).save(output, format="PNG", dpi=self._dpi())
        output.seek(0)
        return output

    def save(self, data: ReceiptData, output_path: str | Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.render_image(data).save(output_path, format="PNG", dpi=self._dpi())
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Stone Island receipt PNG.")
    parser.add_argument("--template", default="assets/receipt_template.png")
    parser.add_argument("--font", default="assets/font.ttf")
    parser.add_argument("--output", default="output/receipt.png")
    parser.add_argument("--sale-number", default=None)
    parser.add_argument("--date-time", default=None)
    parser.add_argument("--article", required=True)
    parser.add_argument("--color", required=True)
    parser.add_argument("--size", required=True)
    parser.add_argument("--item-name", required=True)
    parser.add_argument("--price", required=True)
    parser.add_argument("--barcode", default=None)
    args = parser.parse_args()

    renderer = ReceiptRenderer(args.template, args.font)
    renderer.save(
        ReceiptData(
            article=args.article,
            color=args.color,
            size=args.size,
            item_name=args.item_name,
            price=args.price,
            sale_number=args.sale_number or generate_sale_number(),
            date_time=args.date_time or generate_receipt_datetime(),
            barcode=args.barcode or generate_receipt_barcode(),
        ),
        args.output,
    )
    print(args.output)


if __name__ == "__main__":
    main()
