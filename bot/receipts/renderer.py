from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import json
import math
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from .barcode_qr import barcode_image, qr_payload
from .calculations import fr_money

WIDTH, HEIGHT, DPI = 945, 2244, 300
ASSETS = Path(__file__).resolve().parents[2] / 'assets' / 'clg2026'
FONTS = ASSETS.parent / 'receipt_fr'
RETURN_TEXT = (
    "Aucun remboursement. Nous échangerons ou\n"
    "émettrons un avoir en boutique dans les 20 jours\n"
    "suivant l'achat. Les produits doivent être non\n"
    "portés et en parfait état. Cela n'affecte pas vos\n"
    "droits statutaires."
)


@dataclass(frozen=True)
class FontStyle:
    font: ImageFont.FreeTypeFont
    squeeze: float = 0.80

    def getlength(self, text):
        return self.font.getlength(text) * self.squeeze


def font_style(size, bold=False, squeeze=0.80):
    return FontStyle(ImageFont.truetype(str(FONTS / ('ReceiptMono-Bold.ttf' if bold else 'ReceiptMono-Regular.ttf')), size), squeeze)


def wrap_text(text, font, max_width):
    lines, current = [], ''
    for word in text.split():
        candidate = f'{current} {word}'.strip()
        if font.getlength(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current); current = ''
        for char in word:
            if current and font.getlength(current + char) > max_width:
                lines.append(current); current = ''
            current += char
    if current:
        lines.append(current)
    return lines or ['']


def layout(receipt, store, font_size=50):
    regular = font_style(font_size)
    bold = font_style(font_size, True)
    small = font_style(38)
    foot = font_style(37, squeeze=0.82)
    title = font_style(90, False, 0.52)
    commands = []
    left, right = 22, 826

    def text(value, x, y, font=regular):
        commands.append(('text', (x, y), value, font))

    def center(value, y, font=regular, center_x=WIDTH / 2):
        text(value, center_x - font.getlength(value) / 2, y, font)

    def right_text(value, x, y, font=regular):
        text(value, x - font.getlength(value), y, font)

    def rule(y):
        commands.append(('rule', y))

    # Layout follows the supplied scan: generous top margin, narrow print,
    # four register columns, item articles on their own lines, four VAT columns.
    y = 188
    for line in wrap_text(store.name, title, WIDTH - 80):
        center(line, y, title); y += 82
    for value in (store.address_1, store.address_2, store.phone, store.email,
                  store.legal_name, f'VAT N: {store.vat_number}' if store.vat_number else ''):
        for line in wrap_text(value, regular, WIDTH - 60):
            center(line, y); y += 52
    y += 28
    for x, heading in zip((left, 204, 384, 606), ('Numero', 'Etab', 'Caisse', 'Vd')):
        text(heading, x, y)
    y += 50
    # Keep the full identifier in PNG metadata; shrink only unusually long numbers.
    number_font = regular if regular.getlength(receipt.receipt_number) <= 174 else font_style(29)
    text(receipt.receipt_number, left, y, number_font)
    text(receipt.establishment_id, 204, y)
    text(receipt.register_id, 384, y)
    text(receipt.seller_number, 606, y)
    y += 54
    commands.append(('barcode', (left, y), (730, 46))); y += 54
    center('  '.join('*' + receipt.barcode_data + '*'), y, font_style(32, squeeze=0.90), center_x=left + 365)
    y += 92
    rule(y); y += 28
    text('Articles', left, y, bold)
    right_text('Montant TTC', right, y, bold)
    y += 50; rule(y); y += 28
    items_start = y
    for item in receipt.items:
        amount = fr_money(item.line_total)
        description = ' '.join(value for value in (item.name_it, item.size, item.color) if value != '-')
        amount_width = regular.getlength(amount)
        lines = wrap_text(description, regular, right - 100 - amount_width - 24)
        text(f'{item.quantity}x', left, y)
        for index, line in enumerate(lines):
            text(line, 100, y)
            if index == 0:
                right_text(amount, right, y)
            y += 42
        for line in wrap_text(item.article, small, right - 100):
            text(line, 100, y, small); y += 36
        if item.quantity > 1:
            text(f'{fr_money(item.unit_price)} EUR x {item.quantity}', 100, y, small); y += 36
    items_height = y - items_start
    y += 24
    text('Total', left, y, bold)
    right_text(fr_money(receipt.total_ttc), 660, y, bold)
    right_text('EUR', right, y, bold)
    y += 50; center(f'{receipt.article_count} articles', y, bold, center_x=420)
    y += 62; rule(y); y += 28
    center('Règlement', y, bold, center_x=420)
    y += 50; rule(y); y += 27
    text('Espèces EUR', left, y); right_text(f'{fr_money(receipt.cash_paid)}EUR', right, y)
    y += 40
    text('Espèces EUR', left, y); right_text(f'-{fr_money(receipt.change)}EUR', right, y)
    y += 65; rule(y); y += 28
    text('Taxe', left, y, bold)
    right_text('Montant', 402, y, bold)
    right_text('Taux', 562, y, bold)
    right_text('Base HT', right, y, bold)
    y += 48; rule(y); y += 28
    text('TVA', left, y)
    # Smaller numbers keep very large totals within the same columns.
    for value, x, available in ((fr_money(receipt.vat_amount), 402, 240),
                                (fr_money(receipt.vat_rate * 100) + '%', 562, 145),
                                (fr_money(receipt.total_ht), right, 240)):
        chosen = regular
        if chosen.getlength(value) > available:
            chosen = font_style(max(20, int(font_size * available / chosen.getlength(value))))
        right_text(value, x, y, chosen)
    y += 64
    center('Vous avez été conseillé par', y, center_x=420)
    y += 54; center(receipt.display_cashier, y, bold, center_x=420)
    y += 76
    text('Date:', left, y, bold); text(receipt.purchase_date.strftime('%d/%m/%y'), 178, y)
    text('Heure:', 420, y, bold); text(receipt.purchase_time.strftime('%H:%M:%S'), 622, y)
    y += 69
    for line in RETURN_TEXT.splitlines():
        center(line, y, foot, center_x=(right + left) / 2); y += 31
    y += 78; center('A01', y, small, center_x=420)
    y += 66
    # Two service-code lines, generated once with the receipt, as in the scan.
    signature_font = font_style(36, squeeze=0.87)
    for offset in range(0, len(receipt.control_code), 48):
        text(receipt.control_code[offset:offset + 48], left, y, signature_font); y += 32
    height = max(HEIGHT + items_height - 156, y + 36)
    return commands, height


def render(receipt, store):
    commands, height = layout(receipt, store)
    image = Image.new('RGB', (WIDTH, height), 'white')
    draw = ImageDraw.Draw(image)
    for command in commands:
        if command[0] == 'text':
            _, (x, y), value, style = command
            layer = Image.new('RGBA', (math.ceil(style.font.getlength(value)) + 4, style.font.size * 2), (255, 255, 255, 0))
            ImageDraw.Draw(layer).text((1, 0), value, font=style.font, fill=(20, 20, 20), anchor='lt')
            layer = layer.resize((max(1, round(layer.width * style.squeeze)), layer.height), Image.Resampling.LANCZOS)
            image.paste(layer, (round(x), round(y)), layer)
        elif command[0] == 'rule':
            for x in range(22, 826, 20):
                draw.line((x, command[1], min(x + 13, 826), command[1]), fill=(70, 70, 70), width=2)
        else:
            _, position, size = command
            image.paste(barcode_image(receipt.barcode_data).resize(size, Image.Resampling.NEAREST), position)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('receipt', json.dumps(receipt.to_dict(), ensure_ascii=False))
    metadata.add_text('receipt_qr_payload', qr_payload(receipt))
    output = BytesIO()
    image.save(output, format='PNG', dpi=(DPI, DPI), pnginfo=metadata)
    return output.getvalue()
