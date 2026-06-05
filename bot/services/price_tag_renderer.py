from __future__ import annotations

import argparse
import random
import string
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_SIZE = (945, 472)
DEFAULT_SIZE_MM = (43.0, 25.0)
CODE128_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
    "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
    "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
    "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
    "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
    "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
    "211214", "211232", "2331112",
]


@dataclass(frozen=True)
class PriceTagData:
    model_code: str
    color_code: str
    title: str
    size: str
    price: str | int | float
    old_price: str | int | float | None = None
    top_code: str | None = None


def generate_top_code(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    first = rng.choice(string.ascii_uppercase) + "".join(rng.choices(string.digits, k=2))
    second = "".join(rng.choices(string.ascii_uppercase, k=3))
    third = "".join(rng.choices(string.ascii_uppercase, k=4))
    fourth = "".join(rng.choices(string.digits, k=12))
    return f"{first} {second} {third} {fourth}"


def normalize_model_code(value: str) -> str:
    code = value.strip().upper().replace(" ", "")
    if code.startswith("MO"):
        code = code[2:]
    if not code.isalnum() or len(code) != 9:
        raise ValueError("Article must contain exactly 9 digits or Latin letters, with or without MO prefix.")
    return f"MO{code}"


class PriceTagRenderer:
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

    def _fit_font(self, text: str, size: int, max_width: int, min_size: int = 10) -> ImageFont.FreeTypeFont:
        scaled_max_width = round(max_width * self.scale_x)

        while size >= min_size:
            font = self._font(size)
            bbox = font.getbbox(text)
            if bbox[2] - bbox[0] <= scaled_max_width:
                return font
            size -= 1

        return self._font(min_size)

    def _text_width(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_centered(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        box: tuple[int, int, int, int],
        font: ImageFont.FreeTypeFont,
        fill: str = "black",
    ) -> None:
        left, top, right, bottom = box
        left, top = self._pos(left, top)
        right, bottom = self._pos(right, bottom)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = left + ((right - left) - text_width) // 2
        y = top + ((bottom - top) - text_height) // 2 - bbox[1]
        draw.text((x, y), text, font=font, fill=fill)

    def _format_price(self, price: str | int | float) -> str:
        if isinstance(price, str):
            normalized = price.strip().replace(" ", "")
            if not normalized:
                return ""
            if "," in normalized:
                return normalized
            try:
                value = float(normalized)
            except ValueError:
                return normalized
        else:
            value = float(price)

        return f"{value:,.2f}".replace(",", " ").replace(".", ",")

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
        fill: str = "black",
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
                        fill=fill,
                    )
                cursor = next_cursor

    def _draw_top_code(self, draw: ImageDraw.ImageDraw, top_code: str) -> None:
        parts = top_code.split()
        barcode_text = parts[-1] if parts else top_code.replace(" ", "")
        self._draw_code128(draw, barcode_text, (108, 23, 785, 135))

        human_font = self._fit_font(top_code, size=44, max_width=810, min_size=30)
        if len(parts) == 4:
            for part, x in zip(parts, (54, 212, 368, 528), strict=True):
                draw.text(self._pos(x, 139), part, font=human_font, fill="black")
            return

        draw.text(self._pos(54, 139), top_code, font=human_font, fill="black")

    def render_image(self, data: PriceTagData) -> Image.Image:
        img = self.template.copy()
        draw = ImageDraw.Draw(img)
        top_code = data.top_code or generate_top_code()
        model_code = normalize_model_code(data.model_code)

        top_line_font = self._fit_font(
            f"{model_code}  {data.color_code}",
            size=45,
            max_width=630,
            min_size=28,
        )
        title_font = self._fit_font(data.title, size=47, max_width=620, min_size=28)
        size_font = self._fit_font(data.size, size=52, max_width=160, min_size=28)
        formatted_old_price = self._format_price(data.old_price if data.old_price is not None else data.price)
        formatted_price = self._format_price(data.price)
        price_font = self._fit_font(
            max(formatted_old_price, formatted_price, key=len),
            size=62,
            max_width=230,
            min_size=34,
        )

        self._draw_top_code(draw, top_code)
        draw.text(self._pos(52, 205), model_code, font=top_line_font, fill="black")
        draw.text(self._pos(386, 205), data.color_code, font=top_line_font, fill="black")
        draw.text(self._pos(44, 291), data.title, font=title_font, fill="black", stroke_width=1, stroke_fill="black")

        self._draw_centered(draw, data.size, (716, 189, 909, 282), size_font)

        euro_sign = "\u20ac"
        euro_font = price_font

        def draw_price_line(y: int, price_text: str, strikethrough: bool = False) -> None:
            euro_x, euro_y = self._pos(629, y)
            draw.text((euro_x, euro_y), euro_sign, font=euro_font, fill="black", stroke_width=1, stroke_fill="black")
            price_x = euro_x + self._text_width(draw, euro_sign, euro_font) + round(22 * self.scale_x)
            draw.text((price_x, euro_y), price_text, font=price_font, fill="black", stroke_width=1, stroke_fill="black")
            if strikethrough:
                text_bbox = draw.textbbox((euro_x, euro_y), f"{euro_sign} {price_text}", font=price_font)
                line_y = text_bbox[1] + ((text_bbox[3] - text_bbox[1]) // 2) - round(2 * self.scale_y)
                line_start = euro_x - round(38 * self.scale_x)
                line_end = price_x + self._text_width(draw, price_text, price_font) + round(12 * self.scale_x)
                line_width = max(1, round(5 * min(self.scale_x, self.scale_y)))
                draw.line((line_start, line_y, line_end, line_y), fill="black", width=line_width)

        draw_price_line(296, formatted_old_price, strikethrough=True)
        draw_price_line(371, formatted_price)

        return img

    def render(self, data: PriceTagData) -> BytesIO:
        output = BytesIO()
        self.render_image(data).save(output, format="PNG", dpi=self._dpi())
        output.seek(0)
        return output

    def save(self, data: PriceTagData, output_path: str | Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.render_image(data).save(output_path, format="PNG", dpi=self._dpi())
        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Stone Island price tag PNG.")
    parser.add_argument("--template", default="assets/price_tag_template.png")
    parser.add_argument("--font", default="assets/font.ttf")
    parser.add_argument("--output", default="output/price_tag.png")
    parser.add_argument("--model-code", required=True)
    parser.add_argument("--color-code", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--size", required=True)
    parser.add_argument("--price", required=True)
    parser.add_argument("--old-price", default=None)
    parser.add_argument("--top-code", default=None, help="Optional code for the barcode line. Random if omitted.")
    args = parser.parse_args()

    renderer = PriceTagRenderer(args.template, args.font)
    top_code = args.top_code or generate_top_code()
    renderer.save(
        PriceTagData(
            model_code=args.model_code,
            color_code=args.color_code,
            title=args.title,
            size=args.size,
            price=args.price,
            old_price=args.old_price,
            top_code=top_code,
        ),
        args.output,
    )
    print(f"{args.output} | {top_code}")


if __name__ == "__main__":
    main()
