from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .custom_qr_generator import CustomQrGenerator


BASE_SIZE = (532, 1950)
DEFAULT_SIZE_MM = (45.0, 165.0)


@dataclass(frozen=True)
class Clg2026Data:
    art: str
    color: str
    size: str
    code: str
    certilogo_code: str
    certilogo_url: str


class Clg2026Generator:
    def __init__(
        self,
        template_path: str | Path,
        arial_font_path: str | Path,
        arial_bold_font_path: str | Path,
        clg_font_path: str | Path,
        qr_template_path: str | Path,
        size_mm: tuple[float, float] = DEFAULT_SIZE_MM,
    ) -> None:
        self.template_path = Path(template_path)
        self.arial_font_path = Path(arial_font_path)
        self.arial_bold_font_path = Path(arial_bold_font_path)
        self.clg_font_path = Path(clg_font_path)
        self.qr_template_path = Path(qr_template_path)
        self.size_mm = size_mm

        for path in [
            self.template_path,
            self.arial_font_path,
            self.arial_bold_font_path,
            self.clg_font_path,
            self.qr_template_path,
        ]:
            if not path.exists():
                raise FileNotFoundError(f"Required asset not found: {path}")

        self.template = Image.open(self.template_path).convert("RGBA")
        self.qr_generator = CustomQrGenerator(self.qr_template_path)
        self.scale_x = self.template.width / BASE_SIZE[0]
        self.scale_y = self.template.height / BASE_SIZE[1]

    def _pos(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self.scale_x), round(y * self.scale_y)

    def _font(self, path: Path, size: int) -> ImageFont.FreeTypeFont:
        scaled_size = max(1, round(size * min(self.scale_x, self.scale_y)))
        return ImageFont.truetype(path, scaled_size)

    def _dpi(self) -> tuple[float, float]:
        width_mm, height_mm = self.size_mm
        return (
            self.template.width / (width_mm / 25.4),
            self.template.height / (height_mm / 25.4),
        )

    def _add_datamatrix(self, img: Image.Image, data: str, position: tuple[int, int], size: int) -> None:
        try:
            from pylibdmtx.pylibdmtx import encode
        except ImportError as error:
            raise RuntimeError("libdmtx is not installed on the server. Install libdmtx0b/libdmtx.") from error

        encoded = encode(data.encode("utf-8"))
        dm_img = Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels)
        bbox = dm_img.convert("L").point(lambda value: 255 if value < 128 else 0).getbbox()
        if bbox is not None:
            dm_img = dm_img.crop(bbox)
        size_px = round(size * min(self.scale_x, self.scale_y))
        dm_img = dm_img.resize((size_px, size_px), Image.Resampling.NEAREST).convert("RGBA")
        img.paste(dm_img, self._pos(*position), dm_img)

    def _add_qr(self, img: Image.Image, data: str, position: tuple[int, int], size: int) -> None:
        size_px = round(size * min(self.scale_x, self.scale_y))
        qr_img = self.qr_generator.generate_image(data, output_size=size_px)
        img.paste(qr_img, self._pos(*position), qr_img)

    def _draw_spaced_text(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        spacing: int,
        space_spacing: int,
    ) -> None:
        x, y = self._pos(*position)
        spacing_px = round(spacing * self.scale_x)
        space_spacing_px = round(space_spacing * self.scale_x)

        for char in text:
            if char == " ":
                x += space_spacing_px
                continue

            draw.text((x, y), char, font=font, fill="black")
            bbox = draw.textbbox((x, y), char, font=font)
            x += (bbox[2] - bbox[0]) + spacing_px

    def _format_certilogo_code(self, value: str) -> str:
        compact_code = value.replace(" ", "")
        return "  ".join([compact_code[i:i + 3] for i in range(0, len(compact_code), 3)])

    def render_image(self, data: Clg2026Data) -> Image.Image:
        img = self.template.copy()
        draw = ImageDraw.Draw(img)
        certilogo_code = self._format_certilogo_code(data.certilogo_code)

        arial = self._font(self.arial_font_path, 36)
        arial_bold = self._font(self.arial_bold_font_path, 46)
        clg_font = self._font(self.clg_font_path, 22)

        draw.text(self._pos(98, 164), data.art, font=arial, fill="black")
        draw.text(self._pos(101, 253), data.color, font=arial, fill="black")
        draw.text(self._pos(187, 350), data.size, font=arial_bold, fill="black")
        draw.text(self._pos(100, 414), data.code, font=arial, fill="black")

        datamatrix_certilogo_code = " ".join(certilogo_code.split())
        datamatrix_data = f"{data.art}-{data.color}-{data.size}-{data.code}-{datamatrix_certilogo_code}"
        self._add_datamatrix(img, datamatrix_data, (153, 570), 226)

        self._draw_spaced_text(
            draw,
            (185, 1436),
            certilogo_code,
            clg_font,
            spacing=2,
            space_spacing=6,
        )
        self._add_qr(img, data.certilogo_url, (153, 1536), 226)

        return img

    def render(self, data: Clg2026Data) -> BytesIO:
        output = BytesIO()
        self.render_image(data).save(output, format="PNG", dpi=self._dpi())
        output.seek(0)
        return output

    async def generate_label(
        self,
        art: str,
        color: str,
        size_tag: str,
        code: str,
        certilogo_code: str,
        certilogo_url: str,
    ) -> BytesIO:
        return self.render(
            Clg2026Data(
                art=art,
                color=color,
                size=size_tag,
                code=code,
                certilogo_code=certilogo_code,
                certilogo_url=certilogo_url,
            )
        )
