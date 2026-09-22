from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .barcode_qr import barcode_image, qr_image
from .calculations import fr_money

WIDTH, HEIGHT, DPI = 945, 2244, 300
ASSETS = Path(__file__).resolve().parents[2] / 'assets' / 'clg2026'


def wrap_text(text, font, max_width):
    """Wrap even long unbroken article/name tokens without clipping characters."""
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


def layout(receipt, store, font_size):
    font = ImageFont.truetype(str(ASSETS / 'arial.ttf'), font_size)
    bold = ImageFont.truetype(str(ASSETS / 'arialbd.ttf'), font_size)
    title = ImageFont.truetype(str(ASSETS / 'arialbd.ttf'), font_size + 10)
    commands = []
    margin, width, y = 48, WIDTH - 96, 48
    step = font_size + 10

    def text(value, center=False, strong=False):
        nonlocal y
        chosen = bold if strong else font
        for line in wrap_text(value, chosen, width):
            x = (WIDTH - chosen.getlength(line)) / 2 if center else margin
            commands.append(('text', (x, y), line, chosen)); y += step

    def pair(left, right, strong=False):
        nonlocal y
        chosen = bold if strong else font
        available = width - chosen.getlength(right) - 24
        for line in wrap_text(left, chosen, max(40, available))[:-1]:
            commands.append(('text', (margin, y), line, chosen)); y += step
        last = wrap_text(left, chosen, max(40, available))[-1]
        commands.append(('text', (margin, y), last, chosen))
        commands.append(('text', (WIDTH - margin - chosen.getlength(right), y), right, chosen))
        y += step

    def rule():
        nonlocal y
        y += 8; commands.append(('rule', y)); y += 12

    for line in wrap_text(store.name, title, width):
        commands.append(('text', ((WIDTH - title.getlength(line)) / 2, y), line, title)); y += font_size + 16
    for value in (store.address_1, store.address_2, store.phone, store.email, store.legal_name,
                  f'VAT N: {store.vat_number}' if store.vat_number else ''):
        if value:
            text(value, center=True)
    y += 12
    pair('Numero', receipt.receipt_number)
    pair(f'Etab: {receipt.establishment_id}', f'Caisse: {receipt.register_id}   Vd: {receipt.seller_number}')
    commands.append(('barcode', (margin, y), (width, 72))); y += 80
    text(receipt.receipt_id, center=True)
    rule(); pair('Articles', 'Montant TTC', strong=True); rule()
    items_start = y
    for item in receipt.items:
        pair(f'{item.quantity}x {item.name_it}', fr_money(item.line_total))
        text(f'    {item.size} / {item.color}   ART: {item.article}')
        if item.quantity > 1:
            text(f'    {fr_money(item.unit_price)} EUR x {item.quantity}')
        y += 6
    items_height = y - items_start
    rule(); pair('Total', f'{fr_money(receipt.total_ttc)} EUR', strong=True)
    text(f'{receipt.article_count} articles', center=True)
    rule(); text('Règlement', center=True, strong=True)
    pair('Espèces EUR', f'{fr_money(receipt.cash_paid)} EUR')
    pair('Espèces EUR', f'-{fr_money(receipt.change)} EUR')
    rule(); pair('Taxe / Taux', 'Montant / Base HT', strong=True)
    pair(f'TVA {fr_money(receipt.vat_rate * 100)}%', f'{fr_money(receipt.vat_amount)} / {fr_money(receipt.total_ht)}')
    rule(); text(f'Vous avez été conseillé par {receipt.consultant_name}', center=True)
    pair(f'Date: {receipt.purchase_date:%d/%m/%y}', f'Heure: {receipt.purchase_time:%H:%M:%S}')
    text(f'Opération: {receipt.sale_id}')
    text(f'Document: {receipt.document_id}')
    text(f'Contrôle: {receipt.control_code}')
    y += 8
    commands.append(('qr', ((WIDTH - 228) // 2, y), (228, 228))); y += 238
    text('Merci de votre visite', center=True)
    # Two short item blocks establish the 190 mm reference length.
    height = max(y + 48, HEIGHT + items_height - 2 * (2 * step + 6))
    return commands, height


def render(receipt, store):
    commands, height = layout(receipt, store, 36)
    image = Image.new('RGB', (WIDTH, height), 'white')
    draw = ImageDraw.Draw(image)
    for command in commands:
        if command[0] == 'text':
            _, position, text, font = command
            draw.text(position, text, font=font, fill=(28, 28, 28), anchor='lt')
        elif command[0] == 'rule':
            for x in range(48, WIDTH - 48, 16):
                draw.line((x, command[1], min(x + 9, WIDTH - 48), command[1]), fill=(100, 100, 100), width=2)
        else:
            _, position, size = command
            source = qr_image(receipt) if command[0] == 'qr' else barcode_image(receipt.receipt_id)
            image.paste(source.resize(size, Image.Resampling.NEAREST), position)
    png = BytesIO(); image.save(png, format='PNG', dpi=(DPI, DPI))
    return png.getvalue()
