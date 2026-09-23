"""French outlet sticker: 50 x 25 mm, independently from the black hang tag."""
from io import BytesIO
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from reportlab.graphics.barcode.eanbc import Ean13BarcodeWidget
from reportlab.graphics.shapes import Rect, String
from .calculations import fr_money
from .product_codes import validate_barcode
from .renderer import FontStyle, wrap_text

WIDTH, HEIGHT, DPI = 1000, 500, 508
FONTS = Path(__file__).resolve().parents[2] / 'assets' / 'clg2026'


def font(size, bold=False):
    return FontStyle(ImageFont.truetype(str(FONTS / ('arialbd.ttf' if bold else 'arial.ttf')), size), 0.78)


def fit_lines(value, width, height, size, bold=False):
    for actual in range(size, 13, -1):
        chosen = font(actual, bold)
        lines = wrap_text(value, chosen, width)
        if len(lines) * (actual + 3) <= height:
            return chosen, lines
    raise ValueError('Название слишком длинное для ценника 50 × 25 мм.')


def text(image, value, x, y, style, right=False):
    if right:
        x -= style.getlength(value)
    layer = Image.new('RGBA', (math.ceil(style.font.getlength(value)) + 4, style.font.size * 2), (255, 255, 255, 0))
    ImageDraw.Draw(layer).text((1, 0), value, font=style.font, fill='black', anchor='lt')
    layer = layer.resize((max(1, round(layer.width * style.squeeze)), layer.height), Image.Resampling.LANCZOS)
    image.paste(layer, (round(x), round(y)), layer)


def ean_image(value):
    validate_barcode(value)
    # Integer module widths avoid resampling bars and preserve quiet zones.
    barcode = Ean13BarcodeWidget(value=value[:12], barWidth=5, barHeight=240,
                                  fontSize=40, humanReadable=True)
    group = barcode.draw()
    image = Image.new('RGB', (round(barcode.width), 240), 'white')
    draw = ImageDraw.Draw(image)
    number_font = ImageFont.truetype(str(FONTS / 'arial.ttf'), 40)
    for shape in group.contents:
        if isinstance(shape, Rect) and shape.fillColor is not None:
            draw.rectangle((round(shape.x), round(240 - shape.y - shape.height),
                            round(shape.x + shape.width) - 1, round(240 - shape.y) - 1), fill='black')
        elif isinstance(shape, String):
            x = shape.x
            if shape.textAnchor == 'middle':
                x -= number_font.getlength(shape.text) / 2
            draw.text((round(x), round(240 - shape.y)), shape.text, font=number_font, fill='black', anchor='ls')
    return image


def render_price_tag(item):
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    heading = '   '.join(value for value in (item.article, item.color) if value != '-')
    chosen, lines = fit_lines(heading, 950, 68, 54, True)
    for index, line in enumerate(lines):
        text(image, line, 22, 27 + index * (chosen.font.size + 3), chosen)
    chosen, lines = fit_lines(item.name_it, 585, 87, 48, True)
    for index, line in enumerate(lines):
        text(image, line, 22, 112 + index * (chosen.font.size + 3), chosen)
    image.paste(ean_image(item.product_barcode), (35, 203))
    for value, y, size, bold in (
        ('Retail Price', 142, 39, True),
        (fr_money(item.retail_price) + ' EUR', 210, 42, True),
        ('OUTLET PRICE', 275, 39, True),
        (fr_money(item.unit_price) + ' EUR', 342, 44, True),
        ('Sz. ' + item.size, 430, 40, True),
    ):
        chosen, lines = fit_lines(value, 350, 56, size, bold)
        for index, line in enumerate(lines):
            text(image, line, 955, y + index * (chosen.font.size + 3), chosen, right=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('product', json.dumps(item.to_dict(), ensure_ascii=False))
    output = BytesIO()
    image.save(output, format='PNG', dpi=(DPI, DPI), pnginfo=metadata)
    return output.getvalue()


def render_price_tags(receipt):
    return [render_price_tag(item) for item in receipt.items]
