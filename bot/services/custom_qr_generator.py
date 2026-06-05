from io import BytesIO
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw


class CustomQrGenerator:
    """Кастомный QR-генератор на основе готового макета.

    Алгоритм повторяет рабочий Colab-вариант:
    - QR version=3, ERROR_CORRECT_L, border=0, mask_pattern=3
    - матрица накладывается на maket.jpg без промежутков между модулями
    - итоговый QR сохраняется как PNG 1200x1200, 300 DPI
    """

    def __init__(self, template_path: str | Path, output_size: int = 1200, dpi: int = 300) -> None:
        self.template_path = Path(template_path)
        self.output_size = output_size
        self.dpi = dpi

        if not self.template_path.exists():
            raise FileNotFoundError(f"Файл макета '{self.template_path}' не найден!")

        self.template = Image.open(self.template_path).convert("RGBA")

    def generate_image(self, data: str, output_size: int | None = None) -> Image.Image:
        qr = qrcode.QRCode(
            version=3,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=0,
            mask_pattern=3,
        )
        qr.add_data(data)
        qr.make(fit=True)

        qr_matrix = np.array(qr.get_matrix(), dtype=np.uint8)

        # Важно: qrcode может увеличить версию, если ссылка длиннее, чем помещается в version=3.
        # Поэтому нельзя жёстко брать 29 модулей — иначе QR обрезается и получается
        # слишком крупным, как на неверном примере.
        module_count = qr_matrix.shape[0]
        module_size = self.template.width // module_count
        qr_layer = Image.new("RGBA", (module_count * module_size, module_count * module_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(qr_layer)

        for y in range(module_count):
            for x in range(module_count):
                if qr_matrix[y, x] == 1:
                    left = x * module_size
                    top = y * module_size
                    right = left + module_size
                    bottom = top + module_size
                    draw.rectangle([left, top, right, bottom], fill=(0, 0, 0, 255))

        template_resized = self.template.resize(qr_layer.size, Image.Resampling.LANCZOS)
        final = Image.alpha_composite(template_resized, qr_layer)

        size = output_size or self.output_size
        final = final.resize((size, size), Image.Resampling.LANCZOS)
        return final

    def generate(self, data: str, output_size: int | None = None) -> BytesIO:
        final = self.generate_image(data, output_size)

        output_buffer = BytesIO()
        final.save(output_buffer, format="PNG", dpi=(self.dpi, self.dpi))
        output_buffer.seek(0)
        return output_buffer
