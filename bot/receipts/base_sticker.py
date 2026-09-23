"""Base product sticker: EAN + Data Matrix, 50 x 25 mm."""
from io import BytesIO
import json
from PIL import Image, PngImagePlugin
from .price_tag import WIDTH, HEIGHT, DPI, ean_image, text, number_font, fitted_style, block
from .renderer import FontStyle


def datamatrix_image(payload):
    from pylibdmtx.pylibdmtx import encode
    encoded = encode(payload.encode('ascii'))
    return Image.frombytes('RGB', (encoded.width, encoded.height), encoded.pixels)


def render_base_sticker(item):
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    # The serial is monospaced, but the lower 25-digit line is tall and condensed.
    serial_face = number_font(58, bold=True)
    text(image, item.sticker_serial, 45, 39,
         FontStyle(serial_face, 324 / serial_face.getlength('598087478656')))
    matrix = datamatrix_image(item.sticker_datamatrix)
    # libdmtx includes its own white border. Position the *ink* at the measured box.
    from PIL import ImageChops
    ink = ImageChops.difference(matrix, Image.new('RGB', matrix.size, 'white')).getbbox()
    matrix = matrix.crop(ink).resize((280, 280), Image.Resampling.NEAREST)
    image.paste(matrix, (45, 94))
    block(image, item.sticker_datamatrix, 37, 395, 385, 53,
          fitted_style('8052572986499000010000036', 378, 39))
    image.paste(ean_image(item.product_barcode, bar_height=172, guard_height=195, digit_y=180), (415, 58))
    details = ' '.join(value for value in (item.article, item.color, item.size) if value != '-')
    block(image, details, 494, 305, 480, 60,
          fitted_style('801563750 V0041 XXL', 376, 39))
    block(image, item.name_it, 494, 371, 480, 45, fitted_style('FELPA', 128, 35))
    block(image, item.sticker_code, 494, 423, 150, 53, fitted_style('076', 62, 33))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('product', json.dumps(item.to_dict(), ensure_ascii=False))
    metadata.add_text('datamatrix_payload', item.sticker_datamatrix)
    metadata.add_text('service_fields', 'Synthetic serial, suffix and three-digit code; manufacturer meanings unknown.')
    output = BytesIO()
    image.save(output, format='PNG', dpi=(DPI, DPI), pnginfo=metadata)
    return output.getvalue()


def render_base_stickers(receipt):
    return [render_base_sticker(item) for item in receipt.items]
