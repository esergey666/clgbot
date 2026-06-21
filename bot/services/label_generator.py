from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .custom_qr_generator import CustomQrGenerator


class LabelGenerator:
    def __init__(
        self,
        template_path: str | Path,
        font_path: str | Path,
        numFont_path: str | Path,
        qr_template_path: str | Path,
        dpi: int = 300,
        scale: int = 1,
    ):
        self.scale = scale
        self.template = Image.open(template_path).convert("RGBA")
        if scale != 1:
            self.template = self.template.resize(
                (self.template.width * scale, self.template.height * scale),
                resample=Image.Resampling.LANCZOS,
            )
        self.font_path = font_path
        self.numFont_path = numFont_path
        self.dpi = dpi
        self.qr_generator = CustomQrGenerator(qr_template_path, dpi=dpi)
        self.draw = ImageDraw.Draw(self.template)

    def _fit(self, value: int) -> int:
        return max(1, round(value * self.scale / 2))

    def _fit_pos(self, pos: tuple[int, int]) -> tuple[int, int]:
        return (self._fit(pos[0]), self._fit(pos[1]))

    async def scale_pos(self, pos):
        return self._fit_pos(pos)

    async def save(self, filename):
        self.template.save(filename, dpi=(self.dpi, self.dpi))

    async def draw_text(
        self,
        position,
        text,
        font,
        fill="black",
        inner_stroke=False,
        inner_stroke_width=1,
        stroke_color="white",
    ):
        x, y = position

        # Внутренняя обводка
        if inner_stroke:
            offsets = []

            for i in range(1, inner_stroke_width + 1):
                offsets.extend([
                    (-i, 0),
                    (i, 0),
                    (0, -i),
                    (0, i),
                    (-i, -i),
                    (-i, i),
                    (i, -i),
                    (i, i),
                ])

            for dx, dy in offsets:
                self.draw.text(
                    (x + dx, y + dy),
                    text,
                    font=font,
                    fill=stroke_color
                )

        # Основной текст поверх
        self.draw.text(
            (x, y),
            text,
            font=font,
            fill=fill
        )

    async def draw_spaced_text(
            self,
            position,
            text,
            font,
            spacing=0,
            fill="black",
            inner_stroke=False,
            inner_stroke_width=1,
            stroke_color="white"
    ):
        x, y = position

        offsets = []

        if inner_stroke:
            for i in range(1, inner_stroke_width + 1):
                offsets.extend([
                    (-i, 0),
                    (i, 0),
                    (0, -i),
                    (0, i),
                ])

        for char in text:

            # внутренняя обводка
            if inner_stroke:
                for dx, dy in offsets:
                    self.draw.text(
                        (x + dx, y + dy),
                        char,
                        font=font,
                        fill=stroke_color
                    )

            # основной символ
            self.draw.text(
                (x, y),
                char,
                font=font,
                fill=fill
            )

            # ширина символа + spacing
            char_width = font.getbbox(char)[2]
            x += char_width + spacing
    async def add_qr(self, data, position, size=150):
        # Генерируем QR строго по рабочему алгоритму: сначала 1200x1200,
        # затем масштабируем под место на этикетке.
        qr_img = self.qr_generator.generate_image(data)
        qr_img = qr_img.resize((size, size), Image.Resampling.LANCZOS)
        self.template.paste(qr_img, position, qr_img)

    async def add_datemark(self, data, position, size=150):
        try:
            from pylibdmtx.pylibdmtx import encode
        except ImportError as error:
            raise RuntimeError("libdmtx is not installed on the server. Install libdmtx0b/libdmtx.") from error

        encode_data = encode(data.encode("utf-8"))
        img = Image.frombytes("RGB", (encode_data.width, encode_data.height), encode_data.pixels)
        img = img.resize((size, size))
        self.template.paste(img, position, img.convert("RGBA"))

    async def generate_label(self, art, color, size_tag, code, certilogo_code, certilogo_url):
        datamatrix_certilogo_code = " ".join(certilogo_code.split())
        certilogo_datemark: str = f"{art}-{color}-{size_tag}-{code}-{datamatrix_certilogo_code}"

        await self.draw_text(self._fit_pos((504, 1015)), art, ImageFont.truetype(self.font_path, self._fit(210)))
        await self.draw_text(self._fit_pos((504, 1364)), color, ImageFont.truetype(self.font_path, self._fit(310)))
        await self.draw_text(
            self._fit_pos((960, 2000)),
            size_tag,
            ImageFont.truetype(self.font_path, self._fit(290)),
            fill="black",
            inner_stroke=True,
            inner_stroke_width=self._fit(2),
            stroke_color="black"
        )
        await self.draw_text(self._fit_pos((510, 2600)), code, ImageFont.truetype(self.font_path, self._fit(200)))

        await self.add_datemark(certilogo_datemark, self._fit_pos((600, 3000)), self._fit(1200))

        await self.draw_spaced_text(
            self._fit_pos((719, 7387)),
            certilogo_code,
            ImageFont.truetype(self.numFont_path, self._fit(127)),
            spacing=self._fit(6),
            fill="black",
            inner_stroke=True,
            inner_stroke_width=self._fit(2),
            stroke_color="white"
        )
        await self.add_qr(certilogo_url, self._fit_pos((650, 7950)), self._fit(1100))

        output = BytesIO()
        self.template.save(output, format="PNG", dpi=(self.dpi, self.dpi))
        output.seek(0)
        return output
