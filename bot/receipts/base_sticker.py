"""Base product sticker: EAN + Data Matrix, 50 x 25 mm."""
from io import BytesIO
import json
from PIL import Image, PngImagePlugin
from .price_tag import WIDTH, HEIGHT, DPI, ean_image, fit_lines, font, text, number_font
from .renderer import FontStyle


def datamatrix_image(payload):
    from pylibdmtx.pylibdmtx import encode
    encoded = encode(payload.encode('ascii'))
    return Image.frombytes('RGB', (encoded.width, encoded.height), encoded.pixels)


def render_base_sticker(item):
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    text(image, item.sticker_serial, 36, 30, FontStyle(number_font(50), 1.0))
    matrix = datamatrix_image(item.sticker_datamatrix)
    image.paste(matrix.resize((300, 300), Image.Resampling.NEAREST), (23, 76))
    chosen, lines = fit_lines(item.sticker_datamatrix, 410, 50, 43, True, numeric=True)
    for index, line in enumerate(lines):
        text(image, line, 27, 395 + index * (chosen.font.size + 3), chosen)
    image.paste(ean_image(item.product_barcode), (404, 45))
    details = ' '.join(value for value in (item.article, item.color, item.size) if value != '-')
    for value, y, height, size in ((details, 312, 66, 47),
                                   (item.name_it, 385, 66, 46),
                                   (item.sticker_code, 460, 36, 32)):
        chosen, lines = fit_lines(value, 492, height, size, True, numeric=(value == item.sticker_code))
        for index, line in enumerate(lines):
            text(image, line, 475, y + index * (chosen.font.size + 3), chosen)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('product', json.dumps(item.to_dict(), ensure_ascii=False))
    metadata.add_text('datamatrix_payload', item.sticker_datamatrix)
    metadata.add_text('service_fields', 'Synthetic serial, suffix and three-digit code; manufacturer meanings unknown.')
    output = BytesIO()
    image.save(output, format='PNG', dpi=(DPI, DPI), pnginfo=metadata)
    return output.getvalue()


def render_base_stickers(receipt):
    return [render_base_sticker(item) for item in receipt.items]
