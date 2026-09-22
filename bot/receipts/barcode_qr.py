import json
from PIL import Image, ImageDraw
import qrcode
from reportlab.graphics.barcode.code39 import Standard39
import re


def qr_payload(receipt):
    return json.dumps({'receipt_id': receipt.receipt_id,
                       'date': receipt.purchase_date.strftime('%d/%m/%y'),
                       'time': receipt.purchase_time.isoformat(),
                       'total': str(receipt.total_ttc), 'currency': receipt.currency},
                      ensure_ascii=False, separators=(',', ':'))


def qr_image(receipt):
    qr = qrcode.QRCode(box_size=4, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(qr_payload(receipt)); qr.make(fit=True)
    return qr.make_image(fill_color='black', back_color='white').convert('RGB')


def barcode_image(value):
    if not re.fullmatch(r'01B\d{10}', value):
        raise ValueError('Receipt barcode must contain 01B followed by ten digits.')
    class RasterCode39(Standard39):
        def rect(self, x, y, w, h):
            self.raster.rectangle((round(x), 0, round(x + w) - 1, round(h) - 1), fill='black')
    barcode = RasterCode39(value, barWidth=4, ratio=2.2, gap=4,
                           barHeight=80, humanReadable=False, checksum=False, quiet=False)
    image = Image.new('RGB', (round(barcode.width), 80), 'white')
    barcode.raster = ImageDraw.Draw(image)
    barcode.draw()
    return image
