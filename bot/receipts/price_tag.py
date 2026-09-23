"""French outlet sticker: 50 x 25 mm, independently from the black hang tag."""
from io import BytesIO
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from reportlab.graphics.barcode.eanbc import Ean13BarcodeWidget
from reportlab.graphics.shapes import Rect
from .calculations import fr_money
from .product_codes import validate_barcode
from .pixel_digits import draw_digits
from .renderer import FontStyle, wrap_text

WIDTH, HEIGHT, DPI = 1000, 500, 508
ASSETS = Path(__file__).resolve().parents[2] / 'assets'
FONTS = ASSETS / 'sticker_fonts'


def font(size, bold=False):
    return FontStyle(ImageFont.truetype(str(FONTS / ('RobotoCondensed-Bold.ttf' if bold else 'RobotoCondensed-Regular.ttf')), size), 1.0)

def number_font(size, bold=False):
    return ImageFont.truetype(str(ASSETS / 'receipt_fr' / ('Inconsolata-Bold.ttf' if bold else 'Inconsolata-Regular.ttf')), size)


def text(image, value, x, y, style, right=False):
    if right:
        x -= style.getlength(value)
    layer = Image.new('RGBA', (math.ceil(style.font.getlength(value)) + 4, style.font.size * 2), (255, 255, 255, 0))
    ImageDraw.Draw(layer).text((1, 0), value, font=style.font, fill='black', anchor='lt')
    layer = layer.resize((max(1, round(layer.width * style.squeeze)), layer.height), Image.Resampling.LANCZOS)
    image.paste(layer, (round(x), round(y)), layer)


def ean_image(value, bar_height=190, guard_height=225, digit_y=203):
    validate_barcode(value)
    barcode = Ean13BarcodeWidget(value=value[:12], barWidth=5, barHeight=bar_height,
                                  humanReadable=False)
    image = Image.new('RGB', (585, max(guard_height, digit_y + 35)), 'white')
    draw = ImageDraw.Draw(image)
    # The bars begin at x=60; the extra left margin holds the first EAN digit.
    for shape in barcode.draw().contents:
        if isinstance(shape, Rect) and shape.fillColor is not None:
            module = round((shape.x - 45) / 5)
            height = guard_height if module < 3 or 45 <= module < 50 or module >= 92 else bar_height
            x = round(shape.x) + 15
            draw.rectangle((x, 0, x + round(shape.width) - 1, height - 1), fill='black')
    draw_digits(image, value[0], 13, digit_y)
    draw_digits(image, value[1:7], 106, digit_y)
    draw_digits(image, value[7:], 312, digit_y)
    return image


def fitted_style(sample, width, height, bold=True):
    """Calibrate ink dimensions, not font point size, against the scan."""
    face = font(80, bold).font
    bounds = face.getbbox(sample)
    face = font(round(80 * height / (bounds[3] - bounds[1])), bold).font
    return FontStyle(face, width / face.getlength(sample))


def block(image, value, x, y, width, height, style):
    # Keep calibrated short fields; shrink and wrap unusually long user input.
    while True:
        lines = [value] if style.getlength(value) <= width else wrap_text(value, style, width)
        line_height = max(style.font.getbbox(line)[3] - style.font.getbbox(line)[1] for line in lines) + 5
        if len(lines) * line_height <= height:
            break
        if style.font.size <= 14:
            raise ValueError('Текст не помещается на наклейке 50 × 25 мм.')
        style = FontStyle(style.font.font_variant(size=style.font.size - 1), style.squeeze)
    for index, line in enumerate(lines):
        text(image, line, x, y + index * line_height, style)


def render_price_tag(item):
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    heading = '   '.join(value for value in (item.article, item.color) if value != '-')
    block(image, heading, 8, 52, 965, 70,
          fitted_style('801563750   V0041', 450, 41))
    block(image, item.name_it, 7, 134, 590, 61, fitted_style('FELPA', 145, 46))
    image.paste(ean_image(item.product_barcode), (43, 200))
    for value, x, y, width, style in (
        ('Retail Price', 751, 141, 235, fitted_style('Retail Price', 184, 31, bold=False)),
        (fr_money(item.retail_price) + ' EUR', 759, 209, 225, fitted_style('255,00 EUR', 192, 31, bold=False)),
        ('OUTLET PRICE', 704, 273, 280, fitted_style('OUTLET PRICE', 238, 31, bold=False)),
        (fr_money(item.unit_price) + ' EUR', 759, 342, 225, fitted_style('170,50 EUR', 192, 31, bold=False)),
        ('Sz. ' + item.size, 704, 422, 280, fitted_style('Sz. XXL', 145, 33)),
    ):
        block(image, value, x, y, width, 55, style)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('product', json.dumps(item.to_dict(), ensure_ascii=False))
    output = BytesIO()
    image.save(output, format='PNG', dpi=(DPI, DPI), pnginfo=metadata)
    return output.getvalue()


def render_price_tags(receipt):
    return [render_price_tag(item) for item in receipt.items]
